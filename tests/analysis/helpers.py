"""Spec 0014 testlerinin ortak parçaları: mum kurucuları, hypothesis stratejisi, indikatör tablosu.

AC-7…AC-11 testleri `INDICATORS` üzerinden koşar: tabloya giren indikatör bu kurallara kendiliğinden
girer.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from hypothesis import strategies as st

from crytobot.analysis import Candle, atr, ema, rsi, sma

Series = tuple[float | None, ...]
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def at(position: int) -> datetime:
    return T0 + timedelta(minutes=position)


def candle(position: int, open: Any, high: Any, low: Any, close: Any) -> Candle:
    return Candle(open_time=at(position), open=open, high=high, low=low, close=close)


def from_closes(closes: Iterable[float]) -> list[Candle]:
    """Yalnız kapanış taşıyan tablolar için: `open = high = low = close`."""
    return [candle(i, close, close, close, close) for i, close in enumerate(closes)]


def from_hlc(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]
) -> list[Candle]:
    """Açılış taşımayan tablolar için: `open = close`."""
    return [
        candle(i, close, high, low, close)
        for i, (high, low, close) in enumerate(zip(highs, lows, closes, strict=True))
    ]


@dataclass(frozen=True)
class Indicator:
    name: str
    compute: Callable[[Sequence[Candle]], tuple[Series, ...]]
    needs: int  # tablodaki parametrelerle ilk değeri üreten en kısa seri


INDICATORS = [
    Indicator("sma", lambda c: (sma(c, period=3),), 3),
    Indicator("ema", lambda c: (ema(c, period=3),), 3),
    Indicator("rsi", lambda c: (rsi(c, period=3),), 4),
    Indicator("atr", lambda c: (atr(c, period=3),), 3),
]
INDICATOR_IDS = [indicator.name for indicator in INDICATORS]


def valid_candles(from_prices: list[list[float]]) -> list[Candle]:
    """Dört fiyat sıralanır: en küçüğü `low`, en büyüğü `high`, ortadakiler açılış ve kapanış."""
    result = []
    for position, prices in enumerate(from_prices):
        low, first, second, high = sorted(prices)
        result.append(candle(position, first, high, low, second))
    return result


_price = st.floats(min_value=0.01, max_value=1_000_000.0, allow_nan=False, allow_infinity=False)


def candle_series(min_size: int = 0, max_size: int = 40) -> st.SearchStrategy[list[Candle]]:
    return st.lists(
        st.lists(_price, min_size=4, max_size=4), min_size=min_size, max_size=max_size
    ).map(valid_candles)
