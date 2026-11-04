"""İndikatör hesapları (spec 0014, Formül uzlaşıları). Saf: yalnız girdiye bakar, onu değiştirmez.

Sıra her indikatörde aynıdır: önce parametre, sonra mum denetimi, en son hesap. Bu yüzden boş seri
ve geçersiz parametre hatadır, boş seri ve geçerli parametre boş sonuçtur (plan 0014, Risk 6).

Kayan toplam kullanılmaz: `1e300 + 1 - 1e300 = 0` hatası ve birikim yerine her pencere `math.fsum`
ile toplanır (plan 0014, Risk 7). Bedel O(n * periyot); çevrimdışı hesap için kabul.
"""

import math
from collections.abc import Sequence

from crytobot.analysis._candles import (
    Candle,
    NonFiniteResultError,
    check_period,
    checked_prices,
)

Series = tuple[float | None, ...]


def _finite(value: float, indicator: str, position: int) -> float:
    if not math.isfinite(value):
        raise NonFiniteResultError(indicator, position)
    return value


def _mean(values: Sequence[float], indicator: str, position: int) -> float:
    try:
        total = math.fsum(values)
    except OverflowError:
        raise NonFiniteResultError(indicator, position) from None
    return _finite(total / len(values), indicator, position)


def _padded(values: Sequence[float], length: int) -> Series:
    """Serinin sonuna hizalar: baştaki konumlar "değer yok"."""
    return (*([None] * (length - len(values))), *values)


def _sma_values(closes: Sequence[float], period: int, indicator: str) -> list[float]:
    """`period-1` konumundan başlayan değerler; seri kısaysa boş."""
    return [
        _mean(closes[end + 1 - period : end + 1], indicator, end)
        for end in range(period - 1, len(closes))
    ]


def _ema_values(
    values: Sequence[float], period: int, indicator: str, offset: int = 0
) -> list[float]:
    """`period-1` konumundan başlayan EMA; ilk değer ilk `period` değerin ortalaması.

    Ham `float` alır, fiyat denetiminden geçmez: MACD çizgisi sıfır ve negatif olabilir. `offset`,
    hata konumunu girdi serisine çevirir.
    """
    if len(values) < period:
        return []
    multiplier = 2 / (period + 1)
    current = _mean(values[:period], indicator, offset + period - 1)
    result = [current]
    for index in range(period, len(values)):
        current = _finite(
            current + multiplier * (values[index] - current), indicator, offset + index
        )
        result.append(current)
    return result


def sma(candles: Sequence[Candle], *, period: int) -> Series:
    """Son `period` kapanışın aritmetik ortalaması; ilk değer `period-1` konumunda."""
    check_period(period, "period")
    closes = checked_prices(candles).closes
    return _padded(_sma_values(closes, period, "sma"), len(closes))


def ema(candles: Sequence[Candle], *, period: int) -> Series:
    """Çarpan `2/(period+1)`; ilk değer `period-1` konumunda ilk `period` kapanışın SMA'sı."""
    check_period(period, "period")
    closes = checked_prices(candles).closes
    return _padded(_ema_values(closes, period, "ema"), len(closes))
