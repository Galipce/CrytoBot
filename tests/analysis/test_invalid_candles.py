"""Spec 0014 AC-8: geçersiz veri adı konmuş hatayla reddedilir; kullanılmayan alan da denetlenir."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from crytobot.analysis import (
    AnalysisError,
    Candle,
    CandleProblem,
    InvalidCandleError,
    NonFiniteResultError,
    atr,
    bollinger,
    ema,
    macd,
    rsi,
    sma,
)
from tests.analysis.helpers import (
    INDICATOR_IDS,
    INDICATORS,
    Indicator,
    at,
    candle,
    from_closes,
    from_hlc,
)

FIELDS = ["open", "high", "low", "close"]
POSITION = 5


def base() -> list[Candle]:
    """Tablodaki her indikatörü çalıştırmaya yeten geçerli seri."""
    return [candle(i, 10.0, 12.0, 8.0, 11.0) for i in range(60)]


def field_cases() -> list[tuple[str, dict[str, Any], CandleProblem]]:
    cases: list[tuple[str, dict[str, Any], CandleProblem]] = []
    bad_values: list[tuple[str, Any, CandleProblem]] = [
        ("text", "10", CandleProblem.NON_NUMERIC),
        ("none", None, CandleProblem.NON_NUMERIC),
        ("bool", True, CandleProblem.NON_NUMERIC),
        ("decimal", Decimal("10"), CandleProblem.NON_NUMERIC),
        ("nan", float("nan"), CandleProblem.NON_FINITE),
        ("inf", float("inf"), CandleProblem.NON_FINITE),
        ("minus_inf", float("-inf"), CandleProblem.NON_FINITE),
        ("huge_int", 10**400, CandleProblem.NON_FINITE),
        ("zero", 0.0, CandleProblem.NOT_POSITIVE),
        ("negative", -1.0, CandleProblem.NOT_POSITIVE),
    ]
    for field in FIELDS:
        for label, value, problem in bad_values:
            cases.append((f"{field}_{label}", {field: value}, problem))
    return cases


def shape_cases() -> list[tuple[str, dict[str, Any], CandleProblem]]:
    return [
        ("high_below_low", {"high": 7.0}, CandleProblem.HIGH_BELOW_LOW),
        ("open_above_high", {"open": 13.0}, CandleProblem.OPEN_OUTSIDE_RANGE),
        ("open_below_low", {"open": 7.0}, CandleProblem.OPEN_OUTSIDE_RANGE),
        ("close_above_high", {"close": 13.0}, CandleProblem.CLOSE_OUTSIDE_RANGE),
        ("close_below_low", {"close": 7.0}, CandleProblem.CLOSE_OUTSIDE_RANGE),
        ("naive_time", {"open_time": datetime(2024, 1, 1)}, CandleProblem.INVALID_TIME),
        ("text_time", {"open_time": "2024-01-01"}, CandleProblem.INVALID_TIME),
        ("repeated_time", {"open_time": at(POSITION - 1)}, CandleProblem.TIME_NOT_INCREASING),
        ("earlier_time", {"open_time": at(0)}, CandleProblem.TIME_NOT_INCREASING),
    ]


CASES = field_cases() + shape_cases()


@pytest.mark.parametrize("indicator", INDICATORS, ids=INDICATOR_IDS)
@pytest.mark.parametrize(("change", "problem"), [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_invalid_candle_is_rejected(
    indicator: Indicator, change: dict[str, Any], problem: CandleProblem
) -> None:
    candles = base()
    candles[POSITION] = replace(candles[POSITION], **change)
    with pytest.raises(InvalidCandleError) as caught:
        indicator.compute(candles)
    assert caught.value.problem is problem
    assert caught.value.position == POSITION
    assert isinstance(caught.value, AnalysisError)


@pytest.mark.parametrize("indicator", INDICATORS, ids=INDICATOR_IDS)
def test_invalid_candle_beyond_the_warm_up_is_rejected_too(indicator: Indicator) -> None:
    candles = base()
    candles[-1] = replace(candles[-1], open=-1.0)
    with pytest.raises(InvalidCandleError) as caught:
        indicator.compute(candles)
    assert caught.value.position == len(candles) - 1


@pytest.mark.parametrize("indicator", INDICATORS, ids=INDICATOR_IDS)
def test_invalid_candle_in_a_short_series_is_rejected(indicator: Indicator) -> None:
    with pytest.raises(InvalidCandleError) as caught:
        indicator.compute([candle(0, 10.0, 8.0, 9.0, 8.5)])
    assert caught.value.problem is CandleProblem.HIGH_BELOW_LOW


@pytest.mark.parametrize("indicator", INDICATORS, ids=INDICATOR_IDS)
def test_element_that_is_not_a_candle_is_rejected(indicator: Indicator) -> None:
    candles: list[Any] = [*base()[:2], object()]
    with pytest.raises(InvalidCandleError) as caught:
        indicator.compute(candles)
    assert caught.value.problem is CandleProblem.NOT_A_CANDLE
    assert caught.value.position == 2


def test_integer_prices_are_accepted_and_results_are_float() -> None:
    result = sma(from_closes([2, 4, 6]), period=3)
    assert result == (None, None, 4.0)
    assert isinstance(result[2], float)


def test_message_does_not_print_the_raw_value() -> None:
    candles = base()
    candles[1] = replace(candles[1], close=10**5000)
    with pytest.raises(InvalidCandleError) as caught:
        sma(candles, period=3)
    assert caught.value.problem is CandleProblem.NON_FINITE
    assert "0000" not in str(caught.value)


def test_non_finite_result_is_rejected() -> None:
    """`fsum` taşması `OverflowError` olarak sızmaz, adlandırılmış hata olur; kısmi sonuç yok."""
    huge = from_closes([1.7e308] * 4)
    for compute, name in ((sma, "sma"), (ema, "ema")):
        with pytest.raises(NonFiniteResultError) as caught:
            compute(huge, period=3)
        assert caught.value.indicator == name
        assert caught.value.position == 2


def test_non_finite_atr_is_rejected() -> None:
    candles = from_hlc([1.7e308, 1.7e308], [1.0, 1.0], [1.0, 1.0])
    with pytest.raises(NonFiniteResultError) as caught:
        atr(candles, period=2)
    assert caught.value.indicator == "atr"
    assert caught.value.position == 1


def test_rsi_hides_no_infinite_average() -> None:
    """Plan 0014, Risk 7: ortalama kazanç `inf` olup kayıp sonlu kalsa sonuç 100 çıkardı."""
    candles = from_closes([1.0, 1.7e308, 1.0, 1.7e308])
    assert rsi(candles[:3], period=2) == (None, None, 50.0)
    with pytest.raises(NonFiniteResultError) as caught:
        rsi(candles, period=2)
    assert caught.value.indicator == "rsi"
    assert caught.value.position == 3


def test_rsi_seed_overflow_is_rejected() -> None:
    closes = [1.0, 1.7e308, 0.85e308, 1.7e308]
    with pytest.raises(NonFiniteResultError) as caught:
        rsi(from_closes(closes), period=3)
    assert caught.value.indicator == "rsi"
    assert caught.value.position == 3


def test_non_finite_macd_is_rejected() -> None:
    with pytest.raises(NonFiniteResultError) as caught:
        macd(from_closes([1.7e308] * 6), fast=2, slow=3, signal=2)
    assert caught.value.indicator == "macd"


def test_non_finite_macd_signal_is_rejected() -> None:
    """Fiyat ortalamaları sığsa da çizgi aşırı büyür, sinyal ortalaması taşar: konum sinyalindir."""
    closes = [1.0] * 8 + [1.7e308] * 2
    with pytest.raises(NonFiniteResultError) as caught:
        macd(from_closes(closes), fast=1, slow=9, signal=2)
    assert caught.value.indicator == "macd"
    assert caught.value.position == 9


def test_non_finite_bollinger_mean_is_rejected() -> None:
    with pytest.raises(NonFiniteResultError) as caught:
        bollinger(from_closes([1.7e308] * 3), period=3, k=2)
    assert caught.value.indicator == "bollinger"
    assert caught.value.position == 2


def test_non_finite_bollinger_band_is_rejected() -> None:
    """Orta bant sığar, `k * sigma` taşar: sonuç kısmi dönmez."""
    with pytest.raises(NonFiniteResultError) as caught:
        bollinger(from_closes([1, 2, 30, 40]), period=3, k=1.7e308)
    assert caught.value.indicator == "bollinger"
    assert caught.value.position == 2


def _generator(candles: list[Candle]) -> Any:
    return (candle for candle in candles)


NOT_SERIES: dict[str, Callable[[list[Candle]], Any]] = {
    "generator": _generator,
    "iterator": iter,
    "map": lambda candles: map(lambda candle: candle, candles),
    "none": lambda _: None,
    "number": lambda _: 5,
    "empty_dict": lambda _: {},
    "dict": lambda candles: dict.fromkeys(candles, 1),
    "set": set,
    "empty_text": lambda _: "",
    "text": lambda _: "abc",
    "empty_bytes": lambda _: b"",
}


@pytest.mark.parametrize("indicator", INDICATORS, ids=INDICATOR_IDS)
@pytest.mark.parametrize("make", NOT_SERIES.values(), ids=NOT_SERIES.keys())
def test_series_that_is_not_a_sequence_is_rejected(
    indicator: Indicator, make: Callable[[list[Candle]], Any]
) -> None:
    with pytest.raises(InvalidCandleError) as caught:
        indicator.compute(make(base()))
    assert caught.value.problem is CandleProblem.NOT_A_SERIES
    assert caught.value.position == 0


@pytest.mark.parametrize("indicator", INDICATORS, ids=INDICATOR_IDS)
def test_rejected_generator_is_not_consumed(indicator: Indicator) -> None:
    candles = base()
    generator = _generator(candles)
    with pytest.raises(InvalidCandleError):
        indicator.compute(generator)
    assert next(generator) is candles[0]
