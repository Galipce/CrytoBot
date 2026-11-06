"""Geçmiş veri indirme (spec 0023 R-1, R-3…R-8; plan Risk 3…9, 11).

Sıra: yol denetimi → `.part` → bağlantı ve piyasalar → her çiftin kuralları → başlık → çift başına
geriye doğru sayfalı mum okuması → tamamlanma satırı → son ad. Yalnız herkese açık iki uç kullanılır
(piyasalar, mumlar), anahtar yoktur. Her çağrı bir kez yapılır (`call_once`): ağ hatası, süre aşımı,
429 ve 418 indirmeyi durdurur, sonra istek atılmaz. Durdurma isteğine her çağrıdan önce bakılır.

İstisna fırlatmaz: sonuç ya tamamdır (çift özetleriyle) ya da adı konmuş bir durmadır. Yalnız
`BaseException` (`ForcedStop`) geçer; `.part` yine silinir. Beklenmeyen hata tip adıyla döner,
metni tutulmaz (R-8).

Sayfalama (plan Risk 4): istemcinin `klines(market_id, aralık, limit, end_ms)` ucu, `end_ms`'e
kadar olan son `limit` mumu verir. İlk sayfa bitişten 1 ms önce biter, sonraki sayfa önceki sayfanın
ilk mumundan 1 ms önce. Isınma başlangıcı geçilince ya da boş yanıtta durulur. Dosyaya giren mum:
açılış ≥ ısınma başlangıcı ve kapanış ≤ bitiş (Risk 5); bitiş indirme anından sonra olamadığından
hepsi kapanmıştır.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Final

from crytobot.market_data._calls import OnceFailed, call_once
from crytobot.market_data._candles import parse_rows
from crytobot.market_data._client import PublicExchange, connect_public
from crytobot.market_data._history_file import (
    FileHeader,
    HistoryFileError,
    HistoryFileExists,
    HistoryWriter,
    PairHeader,
    candle_line,
    complete_line,
    existing,
    header_line,
)
from crytobot.market_data._numbers import ms_from_utc, utc_from_ms
from crytobot.market_data._pairs import pair_spec
from crytobot.market_data._types import (
    CANDLE_INTERVALS,
    MAX_CANDLE_COUNT,
    IssueReason,
    MarketDataError,
    ReadSettings,
    pairs_problem,
    settings_problem,
)

_MILLISECOND: Final = timedelta(milliseconds=1)
_PRICE_COLUMNS: Final = slice(1, 5)
_UNAVAILABLE: Final = frozenset(
    {
        IssueReason.NOT_LISTED,
        IssueReason.NOT_USDT,
        IssueReason.NOT_SPOT,
        IssueReason.NOT_TRADING,
    }
)


class HistoryStopReason(Enum):
    """İndirmenin durma nedeni; ham yanıt ve istisna metni taşımaz (R-7, R-8)."""

    INPUT = "input"
    DATA_FILE_EXISTS = "data_file_exists"
    PART_FILE_EXISTS = "part_file_exists"
    WRITE_FAILED = "write_failed"
    NETWORK = "network"
    CALL_TIMED_OUT = "call_timed_out"
    RATE_LIMITED = "rate_limited"
    BANNED = "banned"
    EXCHANGE_ERROR = "exchange_error"
    PAIR_UNAVAILABLE = "pair_unavailable"
    MISSING_RULES = "missing_rules"
    UNTRUSTED_DATA = "untrusted_data"
    NO_CANDLES = "no_candles"
    STOP_REQUESTED = "stop_requested"
    UNEXPECTED = "unexpected"


# Untrusted, not a pair-level fact: a candle after the requested end belongs to no page (R-5)
OUTSIDE_REQUEST: Final = "outside_request"


@dataclass(frozen=True, slots=True)
class HistoryRequest:
    """İndirmenin girdisi; `app` denetler (R-2), indirme yine de kendi sınırını korur."""

    data_path: str
    pairs: tuple[str, ...]
    settings: ReadSettings
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class PairSummary:
    """İndirme özeti (R-3): dosyadaki ilk ve son mumun açılışı, mum sayısı (ısınma dahil) ve
    dönem içindeki boşluk sayısı (R-6)."""

    pair: str
    first_open: datetime
    last_open: datetime
    candles: int
    gaps: int


@dataclass(frozen=True, slots=True)
class HistoryStop:
    """`pair`: nedeni çifte ait ise; `detail`: okumanın neden adı (ör. `duplicate_time`);
    `ban_until`: yasağın bilinen bitişi; `error_type`: beklenmeyen hatanın tip adı."""

    reason: HistoryStopReason
    pair: str | None = None
    detail: str | None = None
    ban_until: datetime | None = None
    error_type: str | None = None


@dataclass(frozen=True, slots=True)
class HistoryResult:
    """Tamam: `stop` `None`, `summaries` beyaz liste sırasıyla. Durma: `summaries` boş."""

    summaries: tuple[PairSummary, ...]
    stop: HistoryStop | None
    downloaded_at: datetime | None


class _Stopped(MarketDataError):
    def __init__(self, stop: HistoryStop) -> None:
        super().__init__(stop.reason.value)
        self.stop = stop


@dataclass(frozen=True, slots=True)
class _Window:
    """Milisaniye sınırları: `warm` ısınma başlangıcı, `start` dönem başı, `end` hariç bitiş."""

    interval_ms: int
    warm: int
    start: int
    end: int

    @property
    def last_slot(self) -> int:
        """Bitişten önce kapanan son mumun açılışı."""
        return self.end // self.interval_ms * self.interval_ms - self.interval_ms


@dataclass(slots=True)
class _PairCandles:
    """Bir çiftin dosyaya girecek satırları, sayfa sayfa (yeniden eskiye)."""

    pages: list[list[str]]
    seen: int | None = None  # the oldest open received, kept or not: the next page ends before it
    first: int | None = None
    last: int | None = None
    count: int = 0
    in_period: int = 0
    gaps: int = 0


def _window(request: HistoryRequest) -> _Window:
    interval_ms = request.settings.candle_interval // _MILLISECOND
    start = ms_from_utc(request.start)
    # The first turn at `start` reads the last `candle_count` candles closed by then
    warm = start // interval_ms * interval_ms - request.settings.candle_count * interval_ms
    return _Window(interval_ms, max(warm, 0), start, ms_from_utc(request.end))


def _moment(value: int) -> datetime:
    moment = utc_from_ms(value)
    assert moment is not None  # every value here passed parse_rows or came from a datetime
    return moment


class _Download:
    def __init__(
        self,
        request: HistoryRequest,
        clock: Callable[[], datetime],
        stop_requested: Callable[[], bool],
        writer: HistoryWriter,
        connect: Callable[[], PublicExchange],
    ) -> None:
        self.request = request
        self.clock = clock
        self.stop_requested = stop_requested
        self.writer = writer
        self.connect = connect
        self.timeout = request.settings.call_timeout.total_seconds()
        self.window = _window(request)
        self.interval_text = CANDLE_INTERVALS[request.settings.candle_interval]

    # --- calls ------------------------------------------------------------------------------
    def call[T](self, request: Callable[[float], T]) -> T:
        if self.stop_requested():
            raise _Stopped(HistoryStop(HistoryStopReason.STOP_REQUESTED))
        try:
            return call_once(request, self.timeout)
        except OnceFailed as failed:
            raise _Stopped(self._failure(failed)) from None

    def _failure(self, failed: OnceFailed) -> HistoryStop:
        if failed.banned:
            return HistoryStop(HistoryStopReason.BANNED, ban_until=self._ban_until(failed))
        named = {
            IssueReason.NETWORK: HistoryStopReason.NETWORK,
            IssueReason.CALL_TIMED_OUT: HistoryStopReason.CALL_TIMED_OUT,
            IssueReason.RATE_LIMITED: HistoryStopReason.RATE_LIMITED,
        }.get(failed.reason)
        if named is not None:
            return HistoryStop(named)
        return HistoryStop(HistoryStopReason.EXCHANGE_ERROR, detail=failed.reason.value)

    def _ban_until(self, failed: OnceFailed) -> datetime | None:
        """Bitiş, yasağın görüldüğü andan `Retry-After` kadar sonradır; okunamayan saatte ya da
        takvimin sonunu aşan değerde bilinmez sayılır."""
        now = _read_clock(self.clock)
        if failed.retry_after is None or now is None:
            return None
        try:
            return now + timedelta(seconds=failed.retry_after)
        except OverflowError:
            return None

    # --- markets ----------------------------------------------------------------------------
    def pair_headers(self, markets: Mapping[str, object]) -> tuple[PairHeader, ...]:
        headers: list[PairHeader] = []
        for pair in self.request.pairs:
            spec = pair_spec(pair, markets)
            if isinstance(spec, IssueReason):
                reason = (
                    HistoryStopReason.PAIR_UNAVAILABLE
                    if spec in _UNAVAILABLE
                    else HistoryStopReason.UNTRUSTED_DATA
                )
                raise _Stopped(HistoryStop(reason, pair=pair, detail=spec.value))
            if spec.tick is None or spec.rules is None:
                detail = spec.issues[0].reason.value if spec.issues else None
                raise _Stopped(HistoryStop(HistoryStopReason.MISSING_RULES, pair, detail))
            headers.append(PairHeader(pair, spec.market_id, spec.tick, spec.rules))
        return tuple(headers)

    # --- candles ----------------------------------------------------------------------------
    def untrusted(self, pair: str, detail: str) -> _Stopped:
        return _Stopped(HistoryStop(HistoryStopReason.UNTRUSTED_DATA, pair, detail))

    def page(
        self, exchange: PublicExchange, pair: str, market_id: str, end_ms: int
    ) -> Sequence[object]:
        window = self.window
        slots = (end_ms - window.warm) // window.interval_ms + 1
        limit = min(MAX_CANDLE_COUNT, slots)
        text = self.interval_text
        response = self.call(lambda t: exchange.klines(market_id, text, limit, end_ms, t))
        if not isinstance(response, list | tuple):
            raise self.untrusted(pair, IssueReason.MALFORMED_RESPONSE.value)
        if len(response) > limit:
            raise self.untrusted(pair, IssueReason.TOO_MANY_CANDLES.value)
        return response

    def keep(self, pair: str, rows: Sequence[object], end_ms: int, into: _PairCandles) -> int:
        """Sayfanın denetimi ve dosyaya girecek satırları; sayfanın ilk açılışını döner (R-5)."""
        window = self.window
        candles = parse_rows(rows, self.request.settings.candle_interval)
        if isinstance(candles, IssueReason):
            raise self.untrusted(pair, candles.value)
        opens = [ms_from_utc(candle.open_time) for candle in candles]
        if into.seen is not None:
            # Pages go back in time: this page must end before the one after it begins
            if opens[-1] == into.seen:
                raise self.untrusted(pair, IssueReason.DUPLICATE_TIME.value)
            if opens[-1] > into.seen:
                raise self.untrusted(pair, IssueReason.TIME_OUT_OF_ORDER.value)
        if opens[-1] > end_ms:
            raise self.untrusted(pair, OUTSIDE_REQUEST)
        lines: list[str] = []
        later = into.first
        for open_ms, row in zip(reversed(opens), reversed(rows), strict=True):
            if not (window.warm <= open_ms and open_ms + window.interval_ms <= window.end):
                continue
            if later is None:
                into.last = open_ms
                if open_ms < window.last_slot:
                    into.gaps += 1  # the end of the period is missing
            elif later - open_ms > window.interval_ms and later > window.start:
                # the newest missing candle closes at `later`: inside the period (plan Risk 6, A-2)
                into.gaps += 1
            later = open_ms
            into.count += 1
            into.in_period += open_ms >= window.start
            assert isinstance(row, list | tuple)  # parse_rows passed it
            lines.append(candle_line(pair, open_ms, [str(text) for text in row[_PRICE_COLUMNS]]))
        lines.reverse()
        into.pages.append(lines)
        into.first = later
        into.seen = opens[0]
        return opens[0]

    def pair_candles(self, exchange: PublicExchange, header: PairHeader) -> _PairCandles:
        window = self.window
        collected = _PairCandles([])
        end_ms = window.end - 1
        while True:  # every page ends before the last one began; the warm-up start ends it
            rows = self.page(exchange, header.pair, header.market_id, end_ms)
            if not rows:
                break  # no older history: a pair listed inside the period (R-6)
            first = self.keep(header.pair, rows, end_ms, collected)
            if first <= window.warm:
                break
            end_ms = first - 1
        if collected.in_period == 0:
            raise _Stopped(HistoryStop(HistoryStopReason.NO_CANDLES, header.pair))
        return collected

    # --- the whole download -----------------------------------------------------------------
    def run(self, downloaded_at: datetime) -> tuple[PairSummary, ...]:
        exchange: PublicExchange = self.call(lambda _: self.connect())
        markets = self.call(exchange.markets)
        if not isinstance(markets, Mapping):
            raise _Stopped(
                HistoryStop(
                    HistoryStopReason.EXCHANGE_ERROR, detail=IssueReason.MALFORMED_RESPONSE.value
                )
            )
        headers = self.pair_headers(markets)
        self.writer.write(
            header_line(
                FileHeader(
                    self.request.settings.exchange,
                    self.interval_text,
                    self.request.start,
                    self.request.end,
                    _moment(self.window.warm),
                    downloaded_at,
                    headers,
                )
            )
        )
        summaries: list[PairSummary] = []
        for header in headers:
            collected = self.pair_candles(exchange, header)
            for page in reversed(collected.pages):
                for text in page:
                    self.writer.write(text)
            assert collected.first is not None and collected.last is not None
            summaries.append(
                PairSummary(
                    header.pair,
                    _moment(collected.first),
                    _moment(collected.last),
                    collected.count,
                    collected.gaps,
                )
            )
        self.writer.write(complete_line([(item.pair, item.candles) for item in summaries]))
        self.writer.finish()
        return tuple(summaries)


def _input_problem(request: object) -> bool:
    if not isinstance(request, HistoryRequest):
        return True
    if settings_problem(request.settings) is not None or pairs_problem(request.pairs) is not None:
        return True
    if not request.pairs or type(request.data_path) is not str or not request.data_path:
        return True
    moments = (request.start, request.end)
    if not all(
        isinstance(moment, datetime) and moment.utcoffset() is not None for moment in moments
    ):
        return True
    return not request.start < request.end


def _read_clock(clock: Callable[[], datetime]) -> datetime | None:
    try:
        value: object = clock()
    except Exception:
        return None
    if not (isinstance(value, datetime) and value.utcoffset() is not None):
        return None
    return value.astimezone(UTC)


def _stopped(stop: HistoryStop, downloaded_at: datetime | None = None) -> HistoryResult:
    return HistoryResult((), stop, downloaded_at)


def download_history(
    request: HistoryRequest,
    clock: Callable[[], datetime],
    stop_requested: Callable[[], bool],
    *,
    connect: Callable[[], PublicExchange] = connect_public,
) -> HistoryResult:
    """Beyaz liste çiftlerinin geçmiş kapanmış mumlarını veri dosyasına indirir (spec 0023).

    `clock` indirme anını verir (bir kez, başta); bitiş ondan sonra olamaz. `stop_requested` her
    çağrıdan önce sorulur. İstisna fırlatmaz; `BaseException` geçer, `.part` yine silinir.
    """
    if _input_problem(request):
        return _stopped(HistoryStop(HistoryStopReason.INPUT))
    downloaded_at = _read_clock(clock)
    if downloaded_at is None:
        return _stopped(HistoryStop(HistoryStopReason.INPUT, detail="clock"))
    if request.end > downloaded_at:
        return _stopped(HistoryStop(HistoryStopReason.INPUT, detail="end"), downloaded_at)
    path = Path(request.data_path)
    found = existing(path)
    if found is not None:
        return _stopped(_exists_stop(found), downloaded_at)
    writer = HistoryWriter(path)
    download = _Download(request, clock, stop_requested, writer, connect)
    try:
        writer.open()
        return HistoryResult(download.run(downloaded_at), None, downloaded_at)
    except _Stopped as stopped:
        return _stopped(stopped.stop, downloaded_at)
    except HistoryFileExists as found_late:
        return _stopped(_exists_stop(found_late), downloaded_at)
    except HistoryFileError:
        return _stopped(HistoryStop(HistoryStopReason.WRITE_FAILED), downloaded_at)
    except Exception as error:
        # The error's text may carry anything; only its type is named (R-8)
        stop = HistoryStop(HistoryStopReason.UNEXPECTED, error_type=type(error).__name__)
        return _stopped(stop, downloaded_at)
    finally:
        writer.close()


def _exists_stop(found: HistoryFileExists) -> HistoryStop:
    reason = (
        HistoryStopReason.PART_FILE_EXISTS if found.part else HistoryStopReason.DATA_FILE_EXISTS
    )
    return HistoryStop(reason)
