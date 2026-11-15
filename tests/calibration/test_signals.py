"""Spec 0045 AC-2: "al"/"sat" kuralları (R-1), kesişme yalnız kesiştiği mumda, Donchian eşitliği,
ısınma; varsayılan ızgaranın içinde; komşuluk (plan Risk 7, 9)."""

import random
from collections.abc import Callable
from datetime import timedelta

import pytest

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
from crytobot.calibration import INDICATORS, IndicatorSpec, Setting, grid, neighbours, signals
from tests.calibration.helpers import T0

SPECS = {spec.name: spec for spec in INDICATORS}


def walk(count: int = 600, seed: int = 7) -> list[Candle]:
    rng = random.Random(seed)
    price, found = 100.0, []
    for index in range(count):
        close = price * (1 + rng.gauss(0, 0.02))
        high = max(price, close) * (1 + abs(rng.gauss(0, 0.005)))
        low = min(price, close) * (1 - abs(rng.gauss(0, 0.005)))
        found.append(Candle(T0 + index * timedelta(hours=1), price, high, low, close))
        price = close
    return found


def up(a: list[float | None] | tuple[float | None, ...], b: object, t: int) -> bool:
    """Testin kendi kesişme tanımı (R-1 metni): önceki mumda altında ya da eşit, şimdi üstünde."""
    bb = b if isinstance(b, list | tuple) else [b] * len(a)
    if t == 0 or None in (a[t - 1], a[t], bb[t - 1], bb[t]):
        return False
    return bool(a[t - 1] <= bb[t - 1] and a[t] > bb[t])  # type: ignore[operator]


def down(a: list[float | None] | tuple[float | None, ...], b: object, t: int) -> bool:
    bb = b if isinstance(b, list | tuple) else [b] * len(a)
    if t == 0 or None in (a[t - 1], a[t], bb[t - 1], bb[t]):
        return False
    return bool(a[t - 1] >= bb[t - 1] and a[t] < bb[t])  # type: ignore[operator]


Rule = Callable[[list[Candle], Setting], Callable[[int], tuple[bool, bool]]]


def rsi_rule(c: list[Candle], s: Setting) -> Callable[[int], tuple[bool, bool]]:
    v = rsi(c, period=int(s[0]))
    return lambda t: (up(v, s[1], t), down(v, 100 - s[1], t))


def macd_rule(c: list[Candle], s: Setting) -> Callable[[int], tuple[bool, bool]]:
    m = macd(c, fast=int(s[0]), slow=int(s[1]), signal=int(s[2]))
    return lambda t: (up(m.macd, m.signal, t), down(m.macd, m.signal, t))


def bollinger_rule(c: list[Candle], s: Setting) -> Callable[[int], tuple[bool, bool]]:
    b = bollinger(c, period=int(s[0]), k=float(s[1]))
    close = [x.close for x in c]

    def at(t: int) -> tuple[bool, bool]:
        if t == 0 or None in (b.lower[t - 1], b.lower[t]):
            return False, False
        buy = close[t - 1] < b.lower[t - 1] and close[t] >= b.lower[t]  # type: ignore[operator]
        sell = close[t - 1] > b.upper[t - 1] and close[t] <= b.upper[t]  # type: ignore[operator]
        return buy, sell

    return at


def stochastic_rule(c: list[Candle], s: Setting) -> Callable[[int], tuple[bool, bool]]:
    x = stochastic(c, k=int(s[0]), d=int(s[1]))

    def at(t: int) -> tuple[bool, bool]:
        k = x.k[t]
        buy = up(x.k, x.d, t) and k is not None and k < s[2]
        sell = down(x.k, x.d, t) and k is not None and k > 100 - s[2]
        return buy, sell

    return at


def adx_rule(c: list[Candle], s: Setting) -> Callable[[int], tuple[bool, bool]]:
    x = adx(c, period=int(s[0]))

    def at(t: int) -> tuple[bool, bool]:
        strong = x.adx[t] is not None and x.adx[t] >= s[1]  # type: ignore[operator]
        return up(x.plus_di, x.minus_di, t) and strong, up(x.minus_di, x.plus_di, t) and strong

    return at


def supertrend_rule(c: list[Candle], s: Setting) -> Callable[[int], tuple[bool, bool]]:
    d = supertrend(c, period=int(s[0]), multiplier=float(s[1])).up

    def at(t: int) -> tuple[bool, bool]:
        if t == 0:
            return False, False
        return d[t - 1] is False and d[t] is True, d[t - 1] is True and d[t] is False

    return at


def donchian_rule(c: list[Candle], s: Setting) -> Callable[[int], tuple[bool, bool]]:
    x = donchian(c, period=int(s[0]))

    def at(t: int) -> tuple[bool, bool]:
        close = c[t].close
        buy = x.upper[t] is not None and close > x.upper[t]  # type: ignore[operator]
        sell = x.lower[t] is not None and close < x.lower[t]  # type: ignore[operator]
        return buy, sell

    return at


def ema_rule(c: list[Candle], s: Setting) -> Callable[[int], tuple[bool, bool]]:
    fast, slow = ema(c, period=int(s[0])), ema(c, period=int(s[1]))
    return lambda t: (up(fast, slow, t), down(fast, slow, t))


RULES: dict[str, Rule] = {
    "RSI": rsi_rule,
    "MACD": macd_rule,
    "Bollinger": bollinger_rule,
    "Stochastic": stochastic_rule,
    "ADX/DI": adx_rule,
    "Supertrend": supertrend_rule,
    "Donchian": donchian_rule,
    "EMA kesişimi": ema_rule,
}


@pytest.mark.parametrize("name", list(RULES))
def test_buy_and_sell_rules(name: str) -> None:
    """R-1: her mumda testin kendi kuralı ile `signals` aynı sonucu verir (varsayılan ve bir
    ayar)."""
    spec = SPECS[name]
    candles = walk()
    for setting in (spec.default, grid(spec)[0]):
        found = signals(spec, setting, candles)
        rule = RULES[name](candles, setting)
        expected = [rule(t) for t in range(len(candles))]
        assert found.buy == tuple(t for t, (buy, _) in enumerate(expected) if buy)
        assert found.sell == tuple(t for t, (_, sell) in enumerate(expected) if sell)
        assert found.buy or found.sell  # the walk is long enough to cross


def test_eight_indicators_in_spec_order() -> None:
    assert [spec.name for spec in INDICATORS] == list(RULES)
    assert [len(grid(spec)) for spec in INDICATORS] == [25, 48, 20, 24, 16, 16, 5, 16]


@pytest.mark.parametrize("spec", INDICATORS, ids=lambda spec: spec.name)
def test_default_inside_grid(spec: IndicatorSpec) -> None:
    assert spec.default in grid(spec)


def _closes(values: list[float]) -> list[Candle]:
    return [
        Candle(T0 + i * timedelta(hours=1), v, v * 1.001, v * 0.999, v)
        for i, v in enumerate(values)
    ]


def test_cross_only_on_crossing_candle() -> None:
    """EMA(5) EMA(21)'i bir kez yukarı keser; üstte kalan mumlar yeni sinyal vermez."""
    values = [100.0] * 40 + [100.0 + i for i in range(1, 30)]
    candles = _closes(values)
    found = signals(SPECS["EMA kesişimi"], (5, 21), candles)
    assert len(found.buy) == 1
    fast, slow = ema(candles, period=5), ema(candles, period=21)
    t = found.buy[0]
    assert fast[t - 1] <= slow[t - 1] and fast[t] > slow[t]  # type: ignore[operator]
    assert all(fast[i] > slow[i] for i in range(t, len(candles)))  # type: ignore[operator]
    assert found.sell == ()


def test_donchian_equality_no_signal() -> None:
    """Kapanış önceki n mumun en yükseğine eşitse sinyal yok; aşarsa var."""
    flat = [Candle(T0 + i * timedelta(hours=1), 100, 101, 99, 100) for i in range(12)]
    equal = [*flat, Candle(T0 + 12 * timedelta(hours=1), 100, 101, 99, 101)]
    above = [*flat, Candle(T0 + 12 * timedelta(hours=1), 100, 101.5, 99, 101.5)]
    spec = SPECS["Donchian"]
    assert signals(spec, (10,), equal).buy == ()
    assert signals(spec, (10,), above).buy == (12,)


@pytest.mark.parametrize("spec", INDICATORS, ids=lambda spec: spec.name)
def test_no_signal_during_warmup(spec: IndicatorSpec) -> None:
    """Değeri olmayan konumda sinyal yok: 5 mum hiçbir ayarın ısınmasına yetmez."""
    candles = walk(5)
    for setting in grid(spec):
        found = signals(spec, setting, candles)
        assert (found.buy, found.sell) == ((), ()), setting


def test_rsi_needs_period_candles_before_any_signal() -> None:
    candles = walk(400, seed=3)
    found = signals(SPECS["RSI"], (28, 40), candles)
    assert found.buy and min(found.buy) > 28


def test_neighbours_one_step_in_one_parameter() -> None:
    assert neighbours(SPECS["RSI"], (14, 30)) == ((10, 30), (21, 30), (14, 25), (14, 35))
    assert neighbours(SPECS["RSI"], (7, 20)) == ((10, 20), (7, 25))
    assert neighbours(SPECS["Donchian"], (100,)) == ((55,),)
    macd_near = neighbours(SPECS["MACD"], (12, 26, 9))
    assert len(macd_near) == 6
    assert all(near[0] < near[1] for near in macd_near)
