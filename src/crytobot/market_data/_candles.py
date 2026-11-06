"""Yanıttan kapanmış mum serisi (spec 0017 R-5, R-6, R-13, R-16; plan Risk 5, 12).

Sıra: önce yanıtın tamamı denetlenir, bozuksa seri onarılmaz. Sonra kapanmamışlar çıkar, sonra son
boşluktan sonrası kalır. Saat istekten önce okunur: istek sırasında kapanan mum, açıkken gelmiş
olabilir ve kapanmış sayılmamalıdır (plan Risk 4).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from crytobot.market_data._numbers import exact_decimal, ms_from_utc, utc_from_ms
from crytobot.market_data._types import IssueReason, MarketCandle, MarketDataError

_MILLISECOND: Final = timedelta(milliseconds=1)
_ROW_COLUMNS: Final = 5


class _BadSeries(MarketDataError):
    def __init__(self, reason: IssueReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class CandleSeries:
    """`candles` `None` ise seri eksiktir; `issue` eksikliğin ya da boşluğun adıdır."""

    candles: tuple[MarketCandle, ...] | None
    issue: IssueReason | None


def request_end_ms(now: datetime, interval: timedelta) -> int:
    """Son kapanmış mumun son milisaniyesi: Binance istenen sayıya açık mumu da katar (Risk 5)."""
    interval_ms = interval // _MILLISECOND
    return ms_from_utc(now) // interval_ms * interval_ms - 1


def _price(text: object) -> Decimal:
    if isinstance(text, str) and text.startswith("-") and exact_decimal(text[1:]) is not None:
        raise _BadSeries(IssueReason.NOT_POSITIVE)
    value = exact_decimal(text)
    if value is None:
        raise _BadSeries(IssueReason.NOT_A_NUMBER)
    if value <= 0:
        raise _BadSeries(IssueReason.NOT_POSITIVE)
    return value


def _candle(row: object) -> MarketCandle:
    if not isinstance(row, list | tuple) or len(row) < _ROW_COLUMNS:
        raise _BadSeries(IssueReason.MALFORMED_RESPONSE)
    open_time = utc_from_ms(row[0])
    if open_time is None:
        raise _BadSeries(IssueReason.NOT_A_NUMBER)
    open_, high, low, close = (_price(text) for text in row[1:_ROW_COLUMNS])
    if high < low:
        raise _BadSeries(IssueReason.HIGH_BELOW_LOW)
    # analysis refuses these too; refused here the reason stays visible (plan Risk 12)
    if not (low <= open_ <= high and low <= close <= high):
        raise _BadSeries(IssueReason.PRICE_OUTSIDE_RANGE)
    return MarketCandle(open_time, open_, high, low, close)


def _check_times(candles: Sequence[MarketCandle], interval: timedelta) -> None:
    interval_ms = interval // _MILLISECOND
    previous: datetime | None = None
    for candle in candles:
        if ms_from_utc(candle.open_time) % interval_ms != 0:
            raise _BadSeries(IssueReason.TIME_OFF_INTERVAL)
        if previous is not None and candle.open_time == previous:
            raise _BadSeries(IssueReason.DUPLICATE_TIME)
        if previous is not None and candle.open_time < previous:
            raise _BadSeries(IssueReason.TIME_OUT_OF_ORDER)
        previous = candle.open_time


def parse_rows(
    rows: Sequence[object], interval: timedelta
) -> tuple[MarketCandle, ...] | IssueReason:
    """Satırların her biri ve zaman sırası denetlenir; ilk bozukluğun adı döner, seri onarılmaz.

    Okuma (0017) ve geçmiş indirme (0023) aynı denetimi kullanır: biri gevşerse ikisi gevşer.
    """
    try:
        candles = tuple(_candle(row) for row in rows)
        _check_times(candles, interval)
    except _BadSeries as bad:
        return bad.reason
    return candles


def _after_last_gap(
    candles: Sequence[MarketCandle], interval: timedelta
) -> tuple[tuple[MarketCandle, ...], bool]:
    start = 0
    for index in range(1, len(candles)):
        if candles[index].open_time - candles[index - 1].open_time != interval:
            start = index
    return tuple(candles[start:]), start > 0


def parse_series(
    response: object, interval: timedelta, requested: int, now: datetime
) -> CandleSeries:
    """Borsa yanıtından seri; `now`, istekten önce okunan saattir. İstisna fırlatmaz."""
    if not isinstance(response, list | tuple):
        return CandleSeries(None, IssueReason.MALFORMED_RESPONSE)
    if len(response) > requested:
        return CandleSeries(None, IssueReason.TOO_MANY_CANDLES)
    candles = parse_rows(response, interval)
    if isinstance(candles, IssueReason):
        return CandleSeries(None, candles)
    try:
        closed = [candle for candle in candles if candle.open_time + interval <= now]
    except OverflowError:  # a stamp at the end of the calendar
        return CandleSeries(None, IssueReason.NOT_A_NUMBER)
    if not closed:
        return CandleSeries(None, IssueReason.NO_CANDLES)
    kept, gapped = _after_last_gap(closed, interval)
    return CandleSeries(kept, IssueReason.CANDLE_GAP if gapped else None)
