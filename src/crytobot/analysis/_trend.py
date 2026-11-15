"""Stochastic, ADX/DI, Supertrend ve Donchian (spec 0045 R-1; plan Risk 7). Saf.

Sıra `_indicators` ile aynıdır: önce parametre, sonra mum denetimi, en son hesap. Sonuç
girdiyle aynı uzunluktadır; geçmişi yetmeyen konum `None` taşır. Yalnız sayı döner, "al/sat"
yorumu yoktur.

Tanımlar:

- **Stochastic** (hızlı): `%K = 100·(kapanış - en düşük_k)/(en yüksek_k - en düşük_k)`, pencere son
  `k` mum (o mum dahil); ilk değer `k-1` konumunda. Pencerede en yüksek = en düşükse `%K` yoktur.
  `%D` son `d` `%K`'nın aritmetik ortalaması; pencerede `%K` eksikse yoktur.
- **ADX/DI** (Wilder): gerçek aralık, `+DM`, `-DM` 1. konumdan; üçü Wilder yumuşatmasıyla
  (`_wilder_values`), ilk değer `n` konumunda. `+DI = 100·+DM_n/TR_n`; `TR_n = 0` ise iki DI de 0
  (aralık yoksa hareket de yoktur). `DX = 100·|+DI - -DI|/(+DI + -DI)`, toplam 0 ise 0. ADX, DX'in
  Wilder yumuşatmasıdır: ilk değer `2n-1` konumunda.
- **Supertrend**: `hl2 ± m·ATR(n)` (Wilder ATR); son bant kuralı: üst bant küçülürse ya da önceki
  kapanış önceki üst bandın üstündeyse yeni temel üst bant alınır, alt bant simetrik. Yön ilk ATR
  konumunda (`n-1`) aşağıdır; sonra önceki çizgi üst bantsa kapanış üst bandı aşınca yukarı, alt
  bantsa kapanış alt bandın altına inince aşağı döner.
- **Donchian**: konum `t`'de önceki `n` mumun (t hariç) en yükseği ve en düşüğü; ilk değer `n`
  konumunda.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from crytobot.analysis._candles import (
    Candle,
    check_multiplier,
    check_period,
    checked_prices,
)
from crytobot.analysis._indicators import Series, _finite, _padded, _wilder_values, atr


@dataclass(frozen=True, slots=True)
class StochasticSeries:
    """`k`: %K, `d`: %D; ikisi de girdiyle aynı uzunlukta."""

    k: Series
    d: Series


@dataclass(frozen=True, slots=True)
class AdxSeries:
    """`plus_di`, `minus_di`, `adx`; hepsi girdiyle aynı uzunlukta."""

    plus_di: Series
    minus_di: Series
    adx: Series


@dataclass(frozen=True, slots=True)
class SupertrendSeries:
    """`line`: geçerli bant (yukarı yönde alt, aşağı yönde üst); `up`: yön yukarı mı."""

    line: Series
    up: tuple[bool | None, ...]


@dataclass(frozen=True, slots=True)
class DonchianSeries:
    """Önceki `n` mumun en yükseği (`upper`) ve en düşüğü (`lower`)."""

    upper: Series
    lower: Series


def stochastic(candles: Sequence[Candle], *, k: int, d: int) -> StochasticSeries:
    """Hızlı stochastic; %K `k-1`, %D `k+d-2` konumunda başlar."""
    check_period(k, "k")
    check_period(d, "d")
    prices = checked_prices(candles)
    length = len(prices.closes)
    percent_k: list[float | None] = [None] * length
    for end in range(k - 1, length):
        highest = max(prices.highs[end + 1 - k : end + 1])
        lowest = min(prices.lows[end + 1 - k : end + 1])
        if highest > lowest:
            value = 100 * (prices.closes[end] - lowest) / (highest - lowest)
            percent_k[end] = _finite(value, "stochastic", end)
    percent_d: list[float | None] = [None] * length
    for end in range(k + d - 2, length):
        window = percent_k[end + 1 - d : end + 1]
        if all(value is not None for value in window):
            total = math.fsum(value for value in window if value is not None)
            percent_d[end] = _finite(total / d, "stochastic", end)
    return StochasticSeries(tuple(percent_k), tuple(percent_d))


def _ratio(part: float, whole: float) -> float:
    return 0.0 if whole == 0 else 100 * part / whole


def adx(candles: Sequence[Candle], *, period: int) -> AdxSeries:
    """Wilder ADX/DI; DI `period`, ADX `2·period-1` konumunda başlar."""
    check_period(period, "period")
    prices = checked_prices(candles)
    highs, lows, closes = prices.highs, prices.lows, prices.closes
    length = len(closes)
    ranges: list[float] = []
    plus_moves: list[float] = []
    minus_moves: list[float] = []
    for index in range(1, length):
        up = highs[index] - highs[index - 1]
        down = lows[index - 1] - lows[index]
        plus_moves.append(up if up > down and up > 0 else 0.0)
        minus_moves.append(down if down > up and down > 0 else 0.0)
        ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )
    smooth_range = _wilder_values(ranges, period, "adx", 1)
    smooth_plus = _wilder_values(plus_moves, period, "adx", 1)
    smooth_minus = _wilder_values(minus_moves, period, "adx", 1)
    plus_di = [
        _finite(_ratio(move, whole), "adx", period + index)
        for index, (move, whole) in enumerate(zip(smooth_plus, smooth_range, strict=True))
    ]
    minus_di = [
        _finite(_ratio(move, whole), "adx", period + index)
        for index, (move, whole) in enumerate(zip(smooth_minus, smooth_range, strict=True))
    ]
    dx = [
        _finite(_ratio(abs(plus - minus), plus + minus), "adx", period + index)
        for index, (plus, minus) in enumerate(zip(plus_di, minus_di, strict=True))
    ]
    adx_values = _wilder_values(dx, period, "adx", period)
    return AdxSeries(
        _padded(plus_di, length), _padded(minus_di, length), _padded(adx_values, length)
    )


def supertrend(candles: Sequence[Candle], *, period: int, multiplier: float) -> SupertrendSeries:
    """Supertrend çizgisi ve yönü; ilk değer `period-1` konumunda (yön aşağı)."""
    check_period(period, "period")
    width = check_multiplier(multiplier, "multiplier")
    prices = checked_prices(candles)
    highs, lows, closes = prices.highs, prices.lows, prices.closes
    length = len(closes)
    ranges = atr(candles, period=period)
    line: list[float | None] = [None] * length
    up: list[bool | None] = [None] * length
    upper = lower = 0.0
    for index in range(length):
        average = ranges[index]
        if average is None:
            continue
        middle = (highs[index] + lows[index]) / 2
        basic_upper = _finite(middle + width * average, "supertrend", index)
        basic_lower = _finite(middle - width * average, "supertrend", index)
        previous = up[index - 1] if index > 0 else None
        if previous is None:  # the first ATR position: the direction starts down
            upper, lower, rising = basic_upper, basic_lower, False
        else:
            close_before = closes[index - 1]
            if basic_upper < upper or close_before > upper:
                upper = basic_upper
            if basic_lower > lower or close_before < lower:
                lower = basic_lower
            rising = closes[index] >= lower if previous else closes[index] > upper
        up[index] = rising
        line[index] = lower if rising else upper
    return SupertrendSeries(tuple(line), tuple(up))


def donchian(candles: Sequence[Candle], *, period: int) -> DonchianSeries:
    """Konum `t`'de önceki `period` mumun en yükseği ve en düşüğü; ilk değer `period` konumunda."""
    check_period(period, "period")
    prices = checked_prices(candles)
    length = len(prices.closes)
    upper: list[float | None] = [None] * length
    lower: list[float | None] = [None] * length
    for index in range(period, length):
        upper[index] = max(prices.highs[index - period : index])
        lower[index] = min(prices.lows[index - period : index])
    return DonchianSeries(tuple(upper), tuple(lower))
