"""Olay fiyat verisinin indirme adımı (spec 0048 R-3, G-1, G-6, AC-9; plan Risk 7, 10).

Sıra: borsa bilgisi (depoda anlık görüntü yoksa bir istek; USDT çiftleri, kapanmış ya da kaldırılmış
olanlar dahil) → coin sırasıyla, coinin birleşik aralıklarından depoda olmayan parçalar. Her eksik
parça önce Binance'in genel piyasa verisinden (`klines`, 1000'lik sayfalar, bitişten geriye), o
parçada hiç mum gelmezse ya da sembol geçersizse (-1121) herkese açık geçmiş veri arşivinden (aylık
zip; 404 o ay yok) alınır. İkisi de mum vermezse parça "fiyat verisi yok" olarak kaydedilir. USDT
çifti olmayan coin için "fiyat verisi yok" yazılır ve adım sürer. Yalnız kapanmış mumlar alınır:
koşunun başındaki saatin tavanından sonrası istenmez.

Aynı anda tek istek; bir yanıtın bitişinden sonrakinin başlangıcına en az `gap_s` saniye, monoton
saatle; istek başına en çok `timeout_s` (30 s). Ağ hatası, HTTP hata cevabı, hız sınırı (429),
borsa yasağı (418) ya da beklenmeyen yanıt adım durur: hatanın adı yazılır, istek yinelenmez,
indirilmiş parçalar kalır, yeniden çalıştırma yalnız eksikleri ister. Durdurma isteğine her istekten
önce ve bekleme sırasında bakılır. API anahtarı ve kişisel bilgi taşınmaz. Toplam süre ve istek
sayısı koşu kaydına yazılır.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from itertools import pairwise
from typing import Final

from crytobot.market_data._calls import OnceFailed, call_once
from crytobot.market_data._client import PublicExchange, connect_public
from crytobot.market_data._numbers import exact_decimal, ms_from_utc, utc_from_ms
from crytobot.market_data._price_store import (
    SOURCE_API,
    SOURCE_NONE,
    SOURCE_VISION,
    DownloadRun,
    PairInfo,
    PriceStore,
    PriceStoreError,
    StoredCandle,
    StoredSpan,
)
from crytobot.market_data._types import IssueReason
from crytobot.market_data._vision import (
    VisionFetched,
    VisionFormatError,
    fetch_month,
    month_url,
    parse_month,
)

HOUR: Final = timedelta(hours=1)
HOUR_MS: Final = 3_600_000
PAGE: Final = 1000
QUOTE: Final = "USDT"
REQUEST_TIMEOUT_S: Final = 30.0
MIN_GAP_S: Final = 1.0
_REASONS: Final = {
    IssueReason.CALL_TIMED_OUT: "zaman aşımı",
    IssueReason.NETWORK: "ağ hatası ya da sunucu hatası",
    IssueReason.RATE_LIMITED: "hız sınırı (429)",
    IssueReason.EXCHANGE_ERROR: "HTTP hata cevabı",
    IssueReason.MALFORMED_RESPONSE: "beklenmeyen yanıt",
}


@dataclass(frozen=True)
class PriceNeed:
    """Bir coinin istenen aralığı `[start, end)`, saat başına hizalı."""

    coin: str
    start: datetime
    end: datetime


class DownloadOutcome(Enum):
    COMPLETE = "complete"  # exit 0
    FAILED = "failed"  # a source or store error: exit 1
    STOPPED = "stopped"  # a stop request: exit 4


def _real_vision(url: str, timeout: float, stopped: Callable[[], bool]) -> VisionFetched:
    return fetch_month(url, budget_s=timeout, stopped=stopped)


@dataclass(frozen=True)
class EventPriceParts:
    """Gerçek etkiler. `connect` ilk istekte bir kez çağrılır; `vision(url, süre, durdu_mu)`."""

    clock: Callable[[], datetime]
    monotonic: Callable[[], float]
    wait: Callable[[float], None]
    stopped: Callable[[], bool]
    say: Callable[[str], None]
    connect: Callable[[], PublicExchange] = connect_public
    vision: Callable[[str, float, Callable[[], bool]], VisionFetched] = _real_vision
    timeout_s: float = REQUEST_TIMEOUT_S


class _Stopped(Exception):
    pass


class _SourceError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


@dataclass
class _Gate:
    """Tek kapı: aralık bir yanıtın bitişinden sonrakinin başlangıcına (R-3)."""

    parts: EventPriceParts
    gap_s: float
    requests: int = 0
    last_end: float | None = None
    _exchange: PublicExchange | None = field(default=None, repr=False)

    def _ready(self) -> None:
        if self.parts.stopped():
            raise _Stopped
        if self.last_end is None:
            return
        while (left := self.last_end + self.gap_s - self.parts.monotonic()) > 0:
            self.parts.wait(left)
            if self.parts.stopped():
                raise _Stopped

    def exchange(self) -> PublicExchange:
        if self._exchange is None:
            self._exchange = self.parts.connect()
        return self._exchange

    def api(self, request: Callable[[PublicExchange, float], object]) -> object:
        self._ready()
        exchange = self.exchange()
        self.requests += 1
        try:
            return call_once(lambda timeout: request(exchange, timeout), self.parts.timeout_s)
        except OnceFailed as failed:
            if failed.banned:
                raise _SourceError("borsa yasağı (418)") from None
            if failed.reason is IssueReason.BAD_SYMBOL:
                raise
            raise _SourceError(_REASONS.get(failed.reason, "beklenmeyen hata")) from None
        except Exception:  # an unexpected library error: named by type only
            raise _SourceError("beklenmeyen hata") from None
        finally:
            self.last_end = self.parts.monotonic()

    def vision(self, url: str) -> VisionFetched:
        self._ready()
        self.requests += 1
        try:
            fetched = self.parts.vision(url, self.parts.timeout_s, self.parts.stopped)
        finally:
            self.last_end = self.parts.monotonic()
        if fetched.error == "stopped":
            raise _Stopped
        return fetched


def _pairs(markets: object) -> list[PairInfo]:
    if not isinstance(markets, dict) or not markets:
        raise _SourceError("beklenmeyen yanıt")
    found: dict[str, PairInfo] = {}
    for market in markets.values():
        info = market.get("info") if isinstance(market, dict) else None
        if not isinstance(info, dict):
            raise _SourceError("beklenmeyen yanıt")
        symbol, base, quote, status = (
            info.get(key) for key in ("symbol", "baseAsset", "quoteAsset", "status")
        )
        if not all(isinstance(value, str) and value for value in (symbol, base, quote, status)):
            raise _SourceError("beklenmeyen yanıt")
        assert isinstance(symbol, str) and isinstance(base, str) and isinstance(status, str)
        if quote == QUOTE:
            found[base] = PairInfo(base, symbol, status)
    return [found[base] for base in sorted(found)]


def _row(row: object) -> StoredCandle:
    if not isinstance(row, list) or len(row) < 6:
        raise _SourceError("beklenmeyen yanıt")
    stamp = row[0]
    if utc_from_ms(stamp) is None or not isinstance(stamp, int) or stamp % HOUR_MS:
        raise _SourceError("beklenmeyen yanıt")
    values = [exact_decimal(value) for value in row[1:5]]
    o, h, lo, c = values
    if o is None or h is None or lo is None or c is None or not (0 < lo <= min(o, c)):
        raise _SourceError("beklenmeyen yanıt")
    if max(o, c) > h:
        raise _SourceError("beklenmeyen yanıt")
    return StoredCandle(stamp, str(row[1]), str(row[2]), str(row[3]), str(row[4]))


def _api_span(gate: _Gate, symbol: str, start_ms: int, end_ms: int) -> list[StoredCandle] | None:
    """Parçanın mumları; sembol geçersizse `None` (-1121)."""
    found: dict[int, StoredCandle] = {}
    upper = end_ms - 1
    while upper >= start_ms:
        last = upper

        def page(exchange: PublicExchange, timeout: float, end: int = last) -> object:
            return exchange.klines(symbol, "1h", PAGE, end, timeout)

        try:
            rows = gate.api(page)
        except OnceFailed:  # BAD_SYMBOL only: the other failures are source errors
            return None
        if not isinstance(rows, list):
            raise _SourceError("beklenmeyen yanıt")
        candles = [_row(row) for row in rows]
        opens = [candle.open_ms for candle in candles]
        if any(b <= a for a, b in pairwise(opens)) or (opens and opens[-1] > last):
            raise _SourceError("beklenmeyen yanıt")
        for candle in candles:
            if start_ms <= candle.open_ms < end_ms:
                found[candle.open_ms] = candle
        if len(candles) < PAGE or not candles:
            break
        upper = opens[0] - 1
    return [found[key] for key in sorted(found)]


def _months(start: datetime, end: datetime) -> list[tuple[int, int]]:
    year, month = start.year, start.month
    last = end - timedelta(milliseconds=1)
    months: list[tuple[int, int]] = []
    while (year, month) <= (last.year, last.month):
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def _vision_error(name: str) -> str:
    if name == "http_429":
        return "hız sınırı (429)"
    if name.startswith("http_"):
        return f"HTTP hata cevabı ({name[5:]})"
    if name == "timeout":
        return "zaman aşımı"
    if name == "network_error":
        return "ağ hatası"
    return f"beklenmeyen yanıt ({name})"


def _vision_span(gate: _Gate, symbol: str, start: datetime, end: datetime) -> list[StoredCandle]:
    start_ms, end_ms = ms_from_utc(start), ms_from_utc(end)
    found: dict[int, StoredCandle] = {}
    for year, month in _months(start, end):
        fetched = gate.vision(month_url(symbol, year, month))
        if fetched.missing:
            continue
        if fetched.error is not None or fetched.body is None:
            raise _SourceError(_vision_error(fetched.error or "empty"))
        try:
            candles = parse_month(fetched.body)
        except VisionFormatError:
            raise _SourceError("beklenmeyen yanıt (arşiv biçimi)") from None
        for candle in candles:
            if start_ms <= candle.open_ms < end_ms:
                found[candle.open_ms] = candle
    return [found[key] for key in sorted(found)]


def missing_spans(
    wanted: Sequence[tuple[datetime, datetime]], stored: Sequence[StoredSpan]
) -> list[tuple[datetime, datetime]]:
    """İstenen aralıklardan depoda olmayan parçalar (aralık sırasıyla); üst üste binen istekler
    önce birleşir, böylece aynı parça bir kez istenir."""
    covered = sorted((span.start, span.end) for span in stored)
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(wanted):
        if start >= end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    missing: list[tuple[datetime, datetime]] = []
    for start, end in merged:
        cursor = start
        for low, high in covered:
            if high <= cursor or low >= end:
                continue
            if low > cursor:
                missing.append((cursor, low))
            cursor = max(cursor, high)
            if cursor >= end:
                break
        if cursor < end:
            missing.append((cursor, end))
    return missing


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%MZ")


def _ceiling(now: datetime) -> datetime:
    """Kapanmış son mumun kapanışı: saatin tavanı değil tabanı (açık mum alınmaz)."""
    return now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _coin(
    gate: _Gate,
    store: PriceStore,
    parts: EventPriceParts,
    pair: PairInfo,
    needs: Sequence[PriceNeed],
    ceiling: datetime,
) -> None:
    wanted = [(need.start, min(need.end, ceiling)) for need in needs if need.start < ceiling]
    for start, end in missing_spans(wanted, store.spans(pair.symbol)):
        candles = _api_span(gate, pair.symbol, ms_from_utc(start), ms_from_utc(end))
        source = SOURCE_API
        if not candles:
            candles = _vision_span(gate, pair.symbol, start, end)
            source = SOURCE_VISION if candles else SOURCE_NONE
        store.save_span(pair.symbol, start, end, candles, source, parts.clock())
        result = f"{len(candles)} mum ({source})" if candles else "fiyat verisi yok"
        parts.say(f"{pair.base}: {_stamp(start)} → {_stamp(end)} {result}")


def download_event_prices(
    needs: Sequence[PriceNeed], store: PriceStore, parts: EventPriceParts, gap_s: float
) -> DownloadOutcome:
    """İndirme adımı; sonuç satırları `parts.say`'e, koşu kaydı depoya."""
    started_at = parts.clock()
    begun = parts.monotonic()
    ceiling = _ceiling(started_at)
    gate = _Gate(parts, max(gap_s, MIN_GAP_S))
    outcome = DownloadOutcome.COMPLETE
    try:
        pairs = store.pairs()
        if pairs is None:
            listed = _pairs(gate.api(lambda ex, timeout: ex.markets(timeout)))
            store.save_pairs(listed, parts.clock())
            pairs = {pair.base: pair for pair in listed}
            parts.say(f"borsa bilgisi: {len(listed)} USDT çifti")
        by_coin: dict[str, list[PriceNeed]] = {}
        for need in needs:
            by_coin.setdefault(need.coin, []).append(need)
        for coin in sorted(by_coin):
            pair = pairs.get(coin)
            if pair is None:
                parts.say(f"{coin}: USDT spot çifti yok; fiyat verisi yok")
                continue
            _coin(gate, store, parts, pair, by_coin[coin], ceiling)
    except _Stopped:
        parts.say("durdu: durdurma isteği; indirilmiş olanlar kaldı")
        outcome = DownloadOutcome.STOPPED
    except _SourceError as error:
        parts.say(
            f"durdu: kaynak hatası: {error.name}; istek yinelenmedi, indirilmiş olanlar kaldı"
        )
        outcome = DownloadOutcome.FAILED
    except PriceStoreError as error:
        parts.say(f"durdu: {error}")
        return DownloadOutcome.FAILED
    seconds = parts.monotonic() - begun
    try:
        store.record_run(DownloadRun(started_at, parts.clock(), seconds, gate.requests, ceiling))
    except PriceStoreError as error:
        parts.say(f"durdu: {error}")
        return DownloadOutcome.FAILED
    parts.say(f"toplam süre: {seconds:.1f} s, istek: {gate.requests}")
    return outcome
