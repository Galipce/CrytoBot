"""Spec 0043 AC-3…AC-6, R-4: aday stratejilerin giriş koşulları, ortak öneri kuralı, ısınma mumu.

Senaryolar elle hesaplandı (`tests/strategy/helpers.py`); sınırlar tam eşitlikle kurulur. AC-6'da
beklenen fiyatlar `Fraction` ile bağımsız hesaplanır (spec 0015 testlerinin yolu).
"""

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from math import ceil, floor
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crytobot.analysis import atr
from crytobot.risk import TradeIntent
from crytobot.strategy import (
    CANDIDATES,
    S3_TREND_PERIOD,
    BreakoutSettings,
    InputProblem,
    InvalidInputError,
    NoProposal,
    NoProposalReason,
    Settings,
    StrategySettings,
    TrendDipSettings,
    TrendFilterSettings,
    candidate,
    candidate_parameters,
    propose,
    required_candles,
)
from crytobot.strategy._proposal import _indicators
from tests.analysis.helpers import from_closes, from_hlc
from tests.strategy.helpers import (
    BREAKOUT_CLOSES,
    BREAKOUT_HIGHS,
    BREAKOUT_LOWS,
    CROSS,
    DIP_BELOW,
    DIP_BUY,
    DIP_EQUAL,
    DIP_RSI,
    PAIR,
    TREND_BELOW,
    TREND_BUY,
    TREND_EQUAL,
    candidate_scenarios,
    make_breakout,
    make_settings,
    make_trend_dip,
    make_trend_filter,
    propose_with,
)


def _reason(result: TradeIntent | NoProposal) -> NoProposalReason | None:
    return result.reason if isinstance(result, NoProposal) else None


# --- AC-3: S1 ---


@pytest.mark.parametrize(
    ("closes", "buys"),
    [(TREND_BUY, True), (TREND_EQUAL, False), (TREND_BELOW, False)],
    ids=["above", "equal", "below"],
)
def test_s1_trend_filter_boundaries(closes: tuple[float, ...], buys: bool) -> None:
    """S0 her üç seride alım üretir; S1 yalnız kapanış ortalamanın kesin üstündeyken."""
    candles = from_closes(closes)
    s0 = propose_with(make_settings(), candles)
    assert isinstance(s0, TradeIntent)
    s1 = propose_with(make_trend_filter(), candles)
    if buys:
        assert s1 == s0  # same entry, stop and target: only the entry condition differs
    else:
        assert s1 == NoProposal(NoProposalReason.NOT_ABOVE_TREND)


def test_s1_keeps_s0_conditions_and_needs_full_average() -> None:
    no_cross = from_closes((10.0, 10.0, 10.0, 10.0))
    assert _reason(propose_with(make_trend_filter(), no_cross)) is NoProposalReason.NO_CROSSOVER
    high_rsi = make_trend_filter(rsi_threshold=Decimal(10))
    assert _reason(propose_with(high_rsi, from_closes(TREND_BUY))) is NoProposalReason.RSI_TOO_HIGH
    long_average = make_trend_filter(trend_period=5)
    assert _reason(propose_with(long_average, from_closes(TREND_BUY))) is (
        NoProposalReason.INSUFFICIENT_HISTORY
    )


# --- AC-4: S2 ---


def _breakout(last_close: float, *, last_high: float | None = None) -> list[Any]:
    highs = (
        *BREAKOUT_HIGHS[:-1],
        max(last_close, BREAKOUT_HIGHS[-1] if last_high is None else last_high),
    )
    closes = (*BREAKOUT_CLOSES[:-1], last_close)
    return from_hlc(highs, BREAKOUT_LOWS, closes)


@pytest.mark.parametrize(
    ("last_close", "buys"),
    [(12.5, True), (12.0, False), (11.5, False)],
    ids=["above", "equal", "below"],
)
def test_s2_breakout_boundaries(last_close: float, buys: bool) -> None:
    """Pencerenin en yüksek fiyatı 12: aşan kapanış alım, eşit ya da altı yok."""
    result = propose_with(make_breakout(), _breakout(last_close))
    if buys:
        assert isinstance(result, TradeIntent) and result.side == "buy"
    else:
        assert result == NoProposal(NoProposalReason.NO_BREAKOUT)


def test_s2_window_excludes_last_candle() -> None:
    """Son mumun kendi `high`'ı pencerede değildir; pencerenin önündeki mum da değildir."""
    tall_last = _breakout(12.5, last_high=14.0)  # inside the window it would block
    assert isinstance(propose_with(make_breakout(), tall_last), TradeIntent)
    # one candle before the window, higher than everything: outside N=3, ignored
    earlier = from_hlc((50.0, *BREAKOUT_HIGHS), (9.0, *BREAKOUT_LOWS), (10.0, *BREAKOUT_CLOSES))
    assert isinstance(propose_with(make_breakout(), earlier), TradeIntent)
    # the same candle inside a window of 4 blocks the breakout
    assert propose_with(make_breakout(breakout_period=4), earlier) == NoProposal(
        NoProposalReason.NO_BREAKOUT
    )
    short = _breakout(12.5)[1:]
    assert _reason(propose_with(make_breakout(), short)) is NoProposalReason.INSUFFICIENT_HISTORY


# --- AC-5: S3 ---


def test_s3_boundaries() -> None:
    """Kapanış ortalamanın üstünde ve RSI eşiğin altında: alım; RSI tam eşikte, kapanış
    ortalamaya eşit ya da altında: yok."""
    assert isinstance(propose_with(make_trend_dip(), from_closes(DIP_BUY)), TradeIntent)
    at_threshold = make_trend_dip(rsi_threshold=DIP_RSI)
    assert propose_with(at_threshold, from_closes(DIP_BUY)) == NoProposal(
        NoProposalReason.RSI_TOO_HIGH
    )
    for closes in (DIP_EQUAL, DIP_BELOW):
        assert propose_with(make_trend_dip(), from_closes(closes)) == NoProposal(
            NoProposalReason.NOT_ABOVE_TREND
        )


def test_s3_average_is_fixed_at_200() -> None:
    assert S3_TREND_PERIOD == 200
    assert "trend_period" not in candidate_parameters("S3")  # type: ignore[operator]
    short = from_closes(DIP_BUY[1:])
    assert _reason(propose_with(make_trend_dip(), short)) is NoProposalReason.INSUFFICIENT_HISTORY


# --- AC-6: her aday alım, k*ATR stop, r*risk hedef ---

SCALES = st.sampled_from(
    [
        (1e-6, Decimal("0.00000001")),
        (0.01, Decimal("0.00001")),
        (1.0, Decimal("0.01")),
        (10000.0, Decimal("0.01")),
    ]
)
STOP_MULTIPLES = st.decimals(min_value=Decimal(1), max_value=Decimal(3), places=2)
TARGET_MULTIPLES = st.decimals(min_value=Decimal(1), max_value=Decimal(5), places=2)


def _fraction(value: float | Decimal) -> Fraction:
    return Fraction(Decimal(repr(value)) if isinstance(value, float) else value)


@given(scale_and_tick=SCALES, k=STOP_MULTIPLES, r=TARGET_MULTIPLES, index=st.integers(0, 3))
def test_every_candidate_buys_with_atr_stop(
    scale_and_tick: tuple[float, Decimal], k: Decimal, r: Decimal, index: int
) -> None:
    """Her adayın önerisi alımdır; stop = giriş - k*ATR, hedef = giriş + r*(giriş - stop),
    tick'e yuvarlanmış (giriş yukarı, stop ve hedef aşağı)."""
    scale, tick = scale_and_tick
    base, candles = candidate_scenarios(scale)[index]
    settings = replace(base, k=k, r=r)
    result = propose_with(settings, candles, tick=tick)
    assert isinstance(result, TradeIntent)
    close = _fraction(candles[-1].close)
    volatility = atr(candles, period=settings.atr_period)[-1]
    assert volatility is not None
    raw_stop = close - Fraction(k) * _fraction(volatility)
    raw_target = close + Fraction(r) * (close - raw_stop)
    step = Fraction(tick)
    assert result.side == "buy"
    assert isinstance(result.entry, Decimal) and isinstance(result.stop, Decimal)
    assert isinstance(result.target, Decimal)
    assert Fraction(result.entry) == ceil(close / step) * step
    assert Fraction(result.stop) == floor(raw_stop / step) * step
    assert Fraction(result.target) == floor(raw_target / step) * step
    assert 0 < result.stop < result.entry < result.target


def test_candidate_set_is_fixed() -> None:
    """R-2: dört aday, bu sırayla; her adın kendi ayar tipi ve parametreleri."""
    assert [kind.name for kind in CANDIDATES] == ["S0", "S1", "S2", "S3"]
    expected = (StrategySettings, TrendFilterSettings, BreakoutSettings, TrendDipSettings)
    assert expected == CANDIDATES
    assert candidate("S2") is BreakoutSettings
    assert candidate("S4") is None and candidate(None) is None
    assert candidate_parameters("S0") == (
        "fast_period",
        "slow_period",
        "rsi_period",
        "rsi_threshold",
        "atr_period",
        "k",
        "r",
    )
    assert candidate_parameters("S1") == (*candidate_parameters("S0"), "trend_period")  # type: ignore[misc]
    assert candidate_parameters("S2") == ("breakout_period", "atr_period", "k", "r")
    assert candidate_parameters("S3") == ("rsi_period", "rsi_threshold", "atr_period", "k", "r")
    assert candidate_parameters("x") is None
    settings = make_breakout(breakout_period=55)
    assert settings.parameters() == (
        ("breakout_period", 55),
        ("atr_period", 2),
        ("k", Decimal(2)),
        ("r", Decimal(2)),
    )


# --- R-4: ısınma mumu ---


@pytest.mark.parametrize(
    ("settings", "needed"),
    [
        (make_settings(fast_period=12, slow_period=26, rsi_period=14, atr_period=14), 27),
        (make_settings(fast_period=2, slow_period=3, rsi_period=14, atr_period=14), 15),
        (make_settings(fast_period=2, slow_period=3, rsi_period=2, atr_period=20), 20),
        (make_trend_filter(fast_period=12, slow_period=26, trend_period=150), 150),
        (make_trend_filter(trend_period=2), 3),
        (make_breakout(breakout_period=100, atr_period=14), 101),
        (make_breakout(breakout_period=3, atr_period=14), 14),
        (make_trend_dip(rsi_period=14, atr_period=14), 200),
    ],
)
def test_required_candles(settings: Settings, needed: int) -> None:
    """Tam yeten mum sayısında adayın okuduğu her göstergenin değeri var, bir eksiğinde yok."""
    assert required_candles(settings) == needed
    assert _warm(settings, needed)
    assert not _warm(settings, needed - 1)


def _warm(settings: Settings, count: int) -> bool:
    """Testerede (RSI hep tanımlı) adayın okuduğu son değerlerin hepsi var mı."""
    candles = from_closes(tuple(100.0 + (position % 3) for position in range(count)))
    series = _indicators(candles, settings)
    needed = [series.atr[-1] if series.atr else None]
    if series.fast is not None and series.slow is not None:
        needed += [series.fast[-2] if count > 1 else None, series.slow[-2] if count > 1 else None]
    if series.rsi is not None:
        needed.append(series.rsi[-1] if series.rsi else None)
    if series.trend is not None:
        needed.append(series.trend[-1] if series.trend else None)
    if isinstance(settings, BreakoutSettings) and count < settings.breakout_period + 1:
        return False
    return all(value is not None for value in needed)


def test_candidate_settings_refused_by_name() -> None:
    """Her adayın geçersiz alanı adıyla reddedilir; `required_candles` aynı denetimden geçer."""
    cases: list[tuple[Settings, str, InputProblem]] = [
        (make_trend_filter(trend_period=0), "trend_period", InputProblem.NOT_POSITIVE),
        (
            make_trend_filter(fast_period=3, slow_period=2),
            "fast_period",
            InputProblem.FAST_NOT_BELOW_SLOW,
        ),
        (make_breakout(breakout_period=True), "breakout_period", InputProblem.NOT_INTEGER),
        (make_breakout(k=Decimal(0)), "k", InputProblem.NOT_POSITIVE),
        (make_trend_dip(rsi_threshold=Decimal(101)), "rsi_threshold", InputProblem.OUT_OF_RANGE),
        (make_trend_dip(atr_period=-1), "atr_period", InputProblem.NOT_POSITIVE),
    ]
    for settings, name, problem in cases:
        with pytest.raises(InvalidInputError) as proposed:
            propose(pair=PAIR, candles=(), position_open=True, tick=1, settings=settings)
        with pytest.raises(InvalidInputError) as warmed:
            required_candles(settings)
        for caught in (proposed, warmed):
            assert (caught.value.name, caught.value.problem) == (name, problem)
    with pytest.raises(InvalidInputError) as caught:
        required_candles(object())
    assert caught.value.problem is InputProblem.NOT_SETTINGS


def test_s0_unchanged_scenario() -> None:
    """S0'ın bugünkü senaryosu aynen alım üretir (spec 0015 testleri de aynen koşar)."""
    assert isinstance(propose_with(make_settings(), from_closes(CROSS)), TradeIntent)
