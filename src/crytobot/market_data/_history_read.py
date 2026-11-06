"""Geçmiş veri dosyasını okumak (spec 0025 R-3; plan Risk 4, 5).

Dosya spec 0023'ün yazdığı biçimdedir (`_history_file`). Dosya bütünüyle belleğe alınır (Risk 4).
Sonuç beş durumdan biridir:

- **yok**: yolda dosya yok.
- **okunamıyor**: dosya açılamıyor ya da UTF-8 değil.
- **bozuk**: başlık, satır biçimi, çift kümesi ya da sıra, sayım satırıyla uyum yanlış; ısınma
  başlangıcı ile bitiş arası dışında mum var; tamamlanma satırından sonra satır var.
- **tamamlanmamış**: tamamlanma satırı yok.
- **güvenilmeyen veri**: spec 0017'nin mum denetimlerinden (`parse_rows`) geçmeyen mum. Denetim
  kopyalanmaz; okuma ve indirme ile aynı fonksiyondur.

Önce dosyanın bütün yapısı denetlenir, sonra mumların değerleri. Boşluk güvenilmezlik değildir
(spec 0025 R-6). İstisna fırlatmaz; `BaseException` geçer.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Final

from crytobot.market_data._candles import parse_rows
from crytobot.market_data._history_file import FORMAT, VERSION
from crytobot.market_data._numbers import exact_decimal
from crytobot.market_data._types import CANDLE_INTERVALS, MarketCandle, MarketRules

_INTERVALS_BY_TEXT: Final = {text: interval for interval, text in CANDLE_INTERVALS.items()}
_CANDLE_COLUMNS: Final = 6


class HistoryReadProblem(Enum):
    """Okumanın adı konmuş sorunu; ham dosya metni taşımaz."""

    MISSING = "missing"
    UNREADABLE = "unreadable"
    CORRUPT = "corrupt"
    INCOMPLETE = "incomplete"
    UNTRUSTED = "untrusted"


@dataclass(frozen=True, slots=True)
class HistoryPair:
    """Bir çiftin dosyadaki kuralları, fiyat adımı ve mumları (açılış sırasıyla)."""

    pair: str
    tick: Decimal
    rules: MarketRules
    candles: tuple[MarketCandle, ...]


@dataclass(frozen=True, slots=True)
class HistoryData:
    """Veri dosyası: dönem (`start`..`end`, bitiş hariç), ısınma başlangıcı, indirme anı, çiftler
    başlıktaki sırayla."""

    exchange: str
    candle_interval: timedelta
    start: datetime
    end: datetime
    warmup_start: datetime
    downloaded_at: datetime
    pairs: tuple[HistoryPair, ...]


@dataclass(frozen=True, slots=True)
class HistoryRead:
    """`data` yalnız dosya geçerliyse doludur. `pair` ve `detail` güvenilmeyen veride sorunun
    çiftini ve 0017'nin neden adını (ör. `high_below_low`) taşır; bozukta `detail` neyin bozuk
    olduğunu söyler."""

    data: HistoryData | None
    problem: HistoryReadProblem | None
    pair: str | None = None
    detail: str | None = None


class _Refused(Exception):
    def __init__(self, problem: HistoryReadProblem, detail: str, pair: str | None = None) -> None:
        super().__init__(problem.value)
        self.problem = problem
        self.detail = detail
        self.pair = pair


def _corrupt(detail: str) -> _Refused:
    return _Refused(HistoryReadProblem.CORRUPT, detail)


@dataclass(frozen=True, slots=True)
class _Header:
    exchange: str
    interval: timedelta
    start: datetime
    end: datetime
    warmup_start: datetime
    downloaded_at: datetime
    pairs: tuple[tuple[str, Decimal, MarketRules], ...]


def _moment(value: object) -> datetime:
    if type(value) is not str:
        raise _corrupt("header")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise _corrupt("header") from None
    if moment.utcoffset() != timedelta(0):
        raise _corrupt("header")
    return moment.astimezone(UTC)


def _positive(value: object, *, zero: bool = False) -> Decimal:
    number = exact_decimal(value)
    if number is None or number < 0 or (number == 0 and not zero):
        raise _corrupt("header")
    return number


def _pair_header(item: object) -> tuple[str, Decimal, MarketRules]:
    if not isinstance(item, Mapping):
        raise _corrupt("header")
    pair = item.get("pair")
    if type(pair) is not str or not pair:
        raise _corrupt("header")
    rules = MarketRules(
        _positive(item.get("amount_step")),
        _positive(item.get("min_amount"), zero=True),
        _positive(item.get("min_notional"), zero=True),
    )
    return pair, _positive(item.get("tick")), rules


def _header(value: object) -> _Header:
    if not isinstance(value, Mapping):
        raise _corrupt("header")
    if value.get("format") != FORMAT or value.get("version") != VERSION:
        raise _corrupt("header")
    exchange = value.get("exchange")
    interval = _INTERVALS_BY_TEXT.get(value.get("candle_interval"))  # type: ignore[arg-type]
    if type(exchange) is not str or not exchange or interval is None:
        raise _corrupt("header")
    start, end = _moment(value.get("start")), _moment(value.get("end"))
    warmup_start = _moment(value.get("warmup_start"))
    downloaded_at = _moment(value.get("downloaded_at"))
    if not (warmup_start <= start < end <= downloaded_at):
        raise _corrupt("header")
    items = value.get("pairs")
    if not isinstance(items, list) or not items:
        raise _corrupt("header")
    pairs = tuple(_pair_header(item) for item in items)
    if len({pair for pair, _, _ in pairs}) != len(pairs):
        raise _corrupt("header")
    return _Header(exchange, interval, start, end, warmup_start, downloaded_at, pairs)


def _parse_line(text: str) -> object:
    try:
        return json.loads(text)
    except ValueError:  # JSON errors and the 4300-digit limit
        raise _corrupt("line") from None
    except RecursionError:
        raise _corrupt("line") from None


def _is_complete(value: object) -> bool:
    return isinstance(value, Mapping) and "complete" in value


def _check_complete(value: Mapping[object, object], rows: Mapping[str, list[list[object]]]) -> None:
    counts = value.get("counts")
    if value.get("complete") is not True or set(value) != {"complete", "counts"}:
        raise _corrupt("complete")
    if not isinstance(counts, Mapping) or set(counts) != set(rows):
        raise _corrupt("counts")
    for pair, found in rows.items():
        count = counts[pair]
        if type(count) is not int or count != len(found):
            raise _corrupt("counts")


def _candle_rows(lines: list[str], header: _Header) -> dict[str, list[list[object]]]:
    """Mum satırlarını çift başına toplar; biçim, çift ve sıra denetlenir, değerler denetlenmez."""
    order = [pair for pair, _, _ in header.pairs]
    rows: dict[str, list[list[object]]] = {pair: [] for pair in order}
    position = 0
    for index, text in enumerate(lines):
        value = _parse_line(text)
        if _is_complete(value):
            assert isinstance(value, Mapping)  # checked by _is_complete
            if index != len(lines) - 1:
                raise _corrupt("after_complete")
            _check_complete(value, rows)
            return rows
        if not (isinstance(value, list) and len(value) == _CANDLE_COLUMNS):
            raise _corrupt("candle_line")
        pair, open_ms = value[0], value[1]
        if type(pair) is not str or pair not in rows or type(open_ms) is not int:
            raise _corrupt("candle_line")
        current = order.index(pair)
        if current < position:  # pairs come in header order, each one block
            raise _corrupt("pair_order")
        position = current
        rows[pair].append(value[1:])
    raise _Refused(HistoryReadProblem.INCOMPLETE, "complete")


def _candles(pair: str, found: list[list[object]], header: _Header) -> tuple[MarketCandle, ...]:
    candles = parse_rows(found, header.interval)
    if not isinstance(candles, tuple):
        raise _Refused(HistoryReadProblem.UNTRUSTED, candles.value, pair)
    for candle in candles:
        if (
            candle.open_time < header.warmup_start
            or candle.open_time + header.interval > header.end
        ):
            raise _corrupt("outside_period")
    return candles


def _data(lines: list[str]) -> HistoryData:
    if not lines:
        raise _corrupt("header")
    header = _header(_parse_line(lines[0]))
    rows = _candle_rows(lines[1:], header)
    pairs = tuple(
        HistoryPair(pair, tick, rules, _candles(pair, rows[pair], header))
        for pair, tick, rules in header.pairs
    )
    return HistoryData(
        header.exchange,
        header.interval,
        header.start,
        header.end,
        header.warmup_start,
        header.downloaded_at,
        pairs,
    )


def read_history(path: str) -> HistoryRead:
    """Veri dosyasını okur ve denetler; dosyaya yazmaz. İstisna fırlatmaz."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return HistoryRead(None, HistoryReadProblem.MISSING)
    except (OSError, UnicodeError, ValueError):
        return HistoryRead(None, HistoryReadProblem.UNREADABLE)
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # the file ends with a newline
    try:
        return HistoryRead(_data(lines), None)
    except _Refused as refused:
        return HistoryRead(None, refused.problem, refused.pair, refused.detail)
