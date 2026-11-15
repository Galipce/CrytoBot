"""Sekiz indikatörün "al"/"sat" kuralları, varsayılanları, ızgaraları (spec 0045 R-1; Risk 7, 9).

Liste, kurallar, varsayılanlar ve ızgaralar spec'te sabittir; burada sabit sırayla durur ve hiçbir
sonuca göre değişmez. Bir ayar, ızgara parametrelerinin değerleridir (sırası
`IndicatorSpec.params`); türetilmiş parametre (`üst = 100 - alt`) ayara girmez, kuralda hesaplanır.

Kesişme (Risk 7): `a` `b`'yi aşağıdan yukarı keser ⇔ `a[t-1] ≤ b[t-1]` ve `a[t] > b[t]`; yukarıdan
aşağı keser ⇔ `a[t-1] ≥ b[t-1]` ve `a[t] < b[t]`. Eşik kesişmesi aynıdır (`b` sabit). Kesişme yalnız
kesiştiği mumda sinyal verir. Bollinger "bandın içine döner": `kapanış[t-1] < alt[t-1]` ve
`kapanış[t] ≥ alt[t]` (üst bant simetrik). Donchian kesişme değildir: koşulu sağlayan her mum
sinyaldir (`kapanış[t] > önceki n mumun en yükseği`; eşitlik sinyal değildir). Değeri olmayan
(ısınma) konumda sinyal yoktur.

Izgara sırası parametrelerin kartezyen çarpımıdır (ilk parametre en yavaş değişir); geçersiz ayar
(`hızlı ≥ yavaş`) çıkarılır. Komşu (Q-6, Risk 9): tek bir ızgara parametresi bir adım farklı olan
geçerli ayar.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import product

from crytobot.analysis import (
    Candle,
    adx,
    bollinger,
    donchian,
    ema,
    macd,
    rsi,
    stochastic,
    supertrend,
)

Number = int | float
Setting = tuple[Number, ...]
Values = Sequence[float | None]


@dataclass(frozen=True, slots=True)
class Signals:
    """Sinyal mumlarının konumları (artan sıra): `buy` "al", `sell` "sat"."""

    buy: tuple[int, ...]
    sell: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class IndicatorSpec:
    """Bir indikatör: ad, ızgara parametreleri, varsayılan, eksenler, kural."""

    name: str
    params: tuple[str, ...]
    default: Setting
    axes: tuple[tuple[Number, ...], ...]
    rule: Callable[[Sequence[Candle], Setting], Signals]
    valid: Callable[[Setting], bool] = lambda _: True
    derived: Callable[[Setting], tuple[tuple[str, Number], ...]] = lambda _: ()


def cross_up(a: Values, b: Values, t: int) -> bool:
    """`a` `b`'yi `t`'de aşağıdan yukarı keser."""
    if t < 1:
        return False
    a0, a1, b0, b1 = a[t - 1], a[t], b[t - 1], b[t]
    if a0 is None or a1 is None or b0 is None or b1 is None:
        return False
    return a0 <= b0 and a1 > b1


def cross_down(a: Values, b: Values, t: int) -> bool:
    """`a` `b`'yi `t`'de yukarıdan aşağı keser."""
    if t < 1:
        return False
    a0, a1, b0, b1 = a[t - 1], a[t], b[t - 1], b[t]
    if a0 is None or a1 is None or b0 is None or b1 is None:
        return False
    return a0 >= b0 and a1 < b1


def _constant(value: float, length: int) -> tuple[float, ...]:
    return (value,) * length


def _crossings(length: int, buy: Callable[[int], bool], sell: Callable[[int], bool]) -> Signals:
    return Signals(
        tuple(t for t in range(length) if buy(t)), tuple(t for t in range(length) if sell(t))
    )


def _rsi(candles: Sequence[Candle], setting: Setting) -> Signals:
    period, low = int(setting[0]), float(setting[1])
    values = rsi(candles, period=period)
    n = len(values)
    lower, upper = _constant(low, n), _constant(100 - low, n)
    return _crossings(
        n, lambda t: cross_up(values, lower, t), lambda t: cross_down(values, upper, t)
    )


def _macd(candles: Sequence[Candle], setting: Setting) -> Signals:
    fast, slow, signal = (int(value) for value in setting)
    series = macd(candles, fast=fast, slow=slow, signal=signal)
    line, smooth = series.macd, series.signal
    return _crossings(
        len(line), lambda t: cross_up(line, smooth, t), lambda t: cross_down(line, smooth, t)
    )


def _bollinger(candles: Sequence[Candle], setting: Setting) -> Signals:
    period, width = int(setting[0]), float(setting[1])
    bands = bollinger(candles, period=period, k=width)
    closes = [candle.close for candle in candles]
    lower, upper = bands.lower, bands.upper

    def buy(t: int) -> bool:
        if t < 1:
            return False
        before, now = lower[t - 1], lower[t]
        return (
            before is not None and now is not None and closes[t - 1] < before and closes[t] >= now
        )

    def sell(t: int) -> bool:
        if t < 1:
            return False
        before, now = upper[t - 1], upper[t]
        return (
            before is not None and now is not None and closes[t - 1] > before and closes[t] <= now
        )

    return _crossings(len(closes), buy, sell)


def _stochastic(candles: Sequence[Candle], setting: Setting) -> Signals:
    k, d, low = int(setting[0]), int(setting[1]), float(setting[2])
    series = stochastic(candles, k=k, d=d)
    fast, slow = series.k, series.d

    def buy(t: int) -> bool:
        value = fast[t]
        return cross_up(fast, slow, t) and value is not None and value < low

    def sell(t: int) -> bool:
        value = fast[t]
        return cross_down(fast, slow, t) and value is not None and value > 100 - low

    return _crossings(len(fast), buy, sell)


def _adx(candles: Sequence[Candle], setting: Setting) -> Signals:
    period, threshold = int(setting[0]), float(setting[1])
    series = adx(candles, period=period)
    plus, minus, strength = series.plus_di, series.minus_di, series.adx

    def strong(t: int) -> bool:
        value = strength[t]
        return value is not None and value >= threshold

    return _crossings(
        len(plus),
        lambda t: cross_up(plus, minus, t) and strong(t),
        lambda t: cross_up(minus, plus, t) and strong(t),
    )


def _supertrend(candles: Sequence[Candle], setting: Setting) -> Signals:
    period, width = int(setting[0]), float(setting[1])
    up = supertrend(candles, period=period, multiplier=width).up
    return _crossings(
        len(up),
        lambda t: t >= 1 and up[t - 1] is False and up[t] is True,
        lambda t: t >= 1 and up[t - 1] is True and up[t] is False,
    )


def _donchian(candles: Sequence[Candle], setting: Setting) -> Signals:
    channel = donchian(candles, period=int(setting[0]))
    closes = [candle.close for candle in candles]

    def buy(t: int) -> bool:
        value = channel.upper[t]
        return value is not None and closes[t] > value

    def sell(t: int) -> bool:
        value = channel.lower[t]
        return value is not None and closes[t] < value

    return _crossings(len(closes), buy, sell)


def _ema_cross(candles: Sequence[Candle], setting: Setting) -> Signals:
    fast = ema(candles, period=int(setting[0]))
    slow = ema(candles, period=int(setting[1]))
    return _crossings(
        len(fast), lambda t: cross_up(fast, slow, t), lambda t: cross_down(fast, slow, t)
    )


def _fast_below_slow(setting: Setting) -> bool:
    return setting[0] < setting[1]


def _upper_from_lower(name: str) -> Callable[[Setting], tuple[tuple[str, Number], ...]]:
    def derived(setting: Setting) -> tuple[tuple[str, Number], ...]:
        return ((name, 100 - setting[-1]),)

    return derived


INDICATORS: tuple[IndicatorSpec, ...] = (
    IndicatorSpec(
        "RSI",
        ("n", "alt"),
        (14, 30),
        ((7, 10, 14, 21, 28), (20, 25, 30, 35, 40)),
        _rsi,
        derived=_upper_from_lower("üst"),
    ),
    IndicatorSpec(
        "MACD",
        ("hızlı", "yavaş", "sinyal"),
        (12, 26, 9),
        ((6, 8, 12, 16), (20, 26, 34, 42), (5, 9, 13)),
        _macd,
        valid=_fast_below_slow,
    ),
    IndicatorSpec(
        "Bollinger",
        ("n", "m"),
        (20, 2.0),
        ((10, 15, 20, 30, 40), (1.5, 2.0, 2.5, 3.0)),
        _bollinger,
    ),
    IndicatorSpec(
        "Stochastic",
        ("k", "d", "alt"),
        (14, 3, 20),
        ((5, 9, 14, 21), (3, 5), (10, 20, 30)),
        _stochastic,
        derived=_upper_from_lower("üst"),
    ),
    IndicatorSpec(
        "ADX/DI",
        ("n", "eşik"),
        (14, 25),
        ((7, 10, 14, 21), (15, 20, 25, 30)),
        _adx,
    ),
    IndicatorSpec(
        "Supertrend",
        ("n", "m"),
        (10, 3.0),
        ((7, 10, 14, 21), (1.5, 2.0, 3.0, 4.0)),
        _supertrend,
    ),
    IndicatorSpec("Donchian", ("n",), (20,), ((10, 20, 30, 55, 100),), _donchian),
    IndicatorSpec(
        "EMA kesişimi",
        ("hızlı", "yavaş"),
        (9, 21),
        ((5, 9, 12, 20), (21, 26, 50, 100)),
        _ema_cross,
        valid=_fast_below_slow,
    ),
)


def indicator(name: str) -> IndicatorSpec | None:
    return next((spec for spec in INDICATORS if spec.name == name), None)


def grid(spec: IndicatorSpec) -> tuple[Setting, ...]:
    """Izgaranın geçerli ayarları, sabit sırayla."""
    return tuple(setting for setting in product(*spec.axes) if spec.valid(setting))


def neighbours(spec: IndicatorSpec, setting: Setting) -> tuple[Setting, ...]:
    """Tek parametresi bir adım farklı geçerli ayarlar; parametre sırasıyla, önce küçük adım."""
    found: list[Setting] = []
    for axis, values in enumerate(spec.axes):
        position = values.index(setting[axis])
        for step in (-1, 1):
            other = position + step
            if 0 <= other < len(values):
                candidate = (*setting[:axis], values[other], *setting[axis + 1 :])
                if spec.valid(candidate):
                    found.append(candidate)
    return tuple(found)


def number_text(value: Number) -> str:
    """`14`, `2`, `1.5`: tam sayı değerli ondalık tam sayı gibi yazılır."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def setting_label(spec: IndicatorSpec, setting: Setting) -> str:
    """`n=14 alt=30 üst=70` biçiminde; türetilmiş parametre dahil."""
    pairs = [*zip(spec.params, setting, strict=True), *spec.derived(setting)]
    return " ".join(f"{name}={number_text(value)}" for name, value in pairs)


def signals(spec: IndicatorSpec, setting: Setting, candles: Sequence[Candle]) -> Signals:
    """R-1: ayarın "al" ve "sat" sinyalleri; `candles` dosyadaki mevcut mumlardır (boşluk
    doldurulmaz)."""
    return spec.rule(candles, setting)


def in_grid(spec: IndicatorSpec, setting: Setting) -> bool:
    return setting in grid(spec)
