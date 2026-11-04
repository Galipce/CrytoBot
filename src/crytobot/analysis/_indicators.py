"""İndikatör hesapları (spec 0014, Formül uzlaşıları). Saf: yalnız girdiye bakar, onu değiştirmez.

Sıra her indikatörde aynıdır: önce parametre, sonra mum denetimi, en son hesap. Bu yüzden boş seri
ve geçersiz parametre hatadır, boş seri ve geçerli parametre boş sonuçtur (plan 0014, Risk 6).

Kayan toplam kullanılmaz: `1e300 + 1 - 1e300 = 0` hatası ve birikim yerine her pencere `math.fsum`
ile toplanır (plan 0014, Risk 7). Bedel O(n * periyot); çevrimdışı hesap için kabul.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from statistics import pstdev

from crytobot.analysis._candles import (
    Candle,
    InvalidParameterError,
    NonFiniteResultError,
    ParameterProblem,
    check_multiplier,
    check_period,
    checked_prices,
)

Series = tuple[float | None, ...]


@dataclass(frozen=True, slots=True)
class MacdSeries:
    """MACD üçlüsü; her alan girdiyle aynı uzunlukta."""

    macd: Series
    signal: Series
    histogram: Series


@dataclass(frozen=True, slots=True)
class BollingerSeries:
    """Bollinger bantları; her alan girdiyle aynı uzunlukta."""

    middle: Series
    upper: Series
    lower: Series


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


def _padded(values: Sequence[float | None], length: int) -> Series:
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


def _wilder_values(
    values: Sequence[float], period: int, indicator: str, offset: int
) -> list[float]:
    """Wilder yumuşatması: ilk değer ilk `period` değerin ortalaması, sonra `(önceki*(n-1)+yeni)/n`.

    Her adım denetlenir: RSI'da ortalama kazanç `inf` olup kayıp sonlu kalsa sonuç `100` çıkar,
    yalnız son değere bakmak taşmayı gizler (plan 0014, Risk 7).
    """
    if len(values) < period:
        return []
    current = _mean(values[:period], indicator, offset + period - 1)
    result = [current]
    for index in range(period, len(values)):
        current = _finite(
            (current * (period - 1) + values[index]) / period, indicator, offset + index
        )
        result.append(current)
    return result


def _rsi_value(gain: float, loss: float) -> float | None:
    """İki ortalamadan RSI. `gain / loss` sonsuza taşsa da sonuç doğru sınırdır: 100."""
    if loss == 0:
        return None if gain == 0 else 100.0
    return 100 - 100 / (1 + gain / loss)


def rsi(candles: Sequence[Candle], *, period: int) -> Series:
    """Wilder RSI; ilk değer `period` konumunda, her değer 0 ile 100 arasında.

    Hiç hareket yoksa "değer yok", yalnız kazanç varsa 100, yalnız kayıp varsa 0. Bu kural konuma
    göre işler: düz başlangıç penceresi `None` verir, ilk hareketle sayı başlar. Yani `None`
    `period` konumundan sonra da görünebilir; hareketten sonraki düz dönemde ortalamalar sıfıra
    inmez, değer sürer (plan 0014, Risk 9).
    """
    check_period(period, "period")
    closes = checked_prices(candles).closes
    changes = [after - before for before, after in pairwise(closes)]
    gains = _wilder_values([max(change, 0.0) for change in changes], period, "rsi", 1)
    losses = _wilder_values([max(-change, 0.0) for change in changes], period, "rsi", 1)
    values = [_rsi_value(gain, loss) for gain, loss in zip(gains, losses, strict=True)]
    return _padded(values, len(closes))


def _true_range(high: float, low: float, previous_close: float) -> float:
    return max(high - low, abs(high - previous_close), abs(low - previous_close))


def atr(candles: Sequence[Candle], *, period: int) -> Series:
    """Wilder ATR; ilk değer `period-1` konumunda ilk `period` gerçek aralığın ortalaması.

    İlk mumun gerçek aralığı `high - low` (Wilder'ın özgün tanımı); sonrakiler önceki kapanışı
    hesaba katar.
    """
    check_period(period, "period")
    prices = checked_prices(candles)
    ranges = [
        high - low if index == 0 else _true_range(high, low, prices.closes[index - 1])
        for index, (high, low) in enumerate(zip(prices.highs, prices.lows, strict=True))
    ]
    return _padded(_wilder_values(ranges, period, "atr", 0), len(ranges))


def macd(candles: Sequence[Candle], *, fast: int, slow: int, signal: int) -> MacdSeries:
    """Çizgi `slow-1`, sinyal ve histogram `slow+signal-2` konumunda başlar.

    Histogram = çizgi - sinyal. Hızlı ve yavaş EMA ayrı ayrı EMA tanımıyla hesaplanır (hızlı, yavaşa
    hizalanmaz). Sinyal, çizginin ilk `signal` değerinin ortalamasıyla başlayan EMA'sıdır.
    """
    check_period(fast, "fast")
    check_period(slow, "slow")
    check_period(signal, "signal")
    if fast >= slow:
        raise InvalidParameterError(ParameterProblem.FAST_NOT_BELOW_SLOW, "fast")
    closes = checked_prices(candles).closes
    length = len(closes)

    slow_values = _ema_values(closes, slow, "macd")
    fast_values = _ema_values(closes, fast, "macd")[slow - fast :]
    line = [
        _finite(quick - slower, "macd", slow - 1 + index)
        for index, (quick, slower) in enumerate(zip(fast_values, slow_values, strict=True))
    ]
    signal_values = _ema_values(line, signal, "macd", offset=slow - 1)
    histogram = [
        _finite(value - smooth, "macd", slow + signal - 2 + index)
        for index, (value, smooth) in enumerate(zip(line[signal - 1 :], signal_values, strict=True))
    ]
    return MacdSeries(
        macd=_padded(line, length),
        signal=_padded(signal_values, length),
        histogram=_padded(histogram, length),
    )


def bollinger(candles: Sequence[Candle], *, period: int, k: float) -> BollingerSeries:
    """Orta bant `period` kapanışın SMA'sı; bantlar `orta ± k * sigma`, sigma popülasyon sapması.

    `pstdev` tam aritmetik yapar: değişmeyen kapanışta sigma tam 0'dır, üç bant eşitlenir. Alt bant
    negatif olabilir, hata değildir: yalnız girdi fiyatları pozitif olmak zorundadır.
    """
    check_period(period, "period")
    width = check_multiplier(k, "k")
    closes = checked_prices(candles).closes
    length = len(closes)

    middle = _sma_values(closes, period, "bollinger")
    upper: list[float] = []
    lower: list[float] = []
    for index, center in enumerate(middle):
        end = period + index
        spread = _finite(width * pstdev(closes[end - period : end]), "bollinger", end - 1)
        upper.append(_finite(center + spread, "bollinger", end - 1))
        lower.append(_finite(center - spread, "bollinger", end - 1))
    return BollingerSeries(
        middle=_padded(middle, length),
        upper=_padded(upper, length),
        lower=_padded(lower, length),
    )
