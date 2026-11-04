"""Spec 0015 AC-8: geçersiz ayar ve girdi adı konmuş hatayla reddedilir; varsayılan yoktur."""

import inspect
from decimal import Decimal
from typing import Any

import pytest

from crytobot.analysis import CandleProblem
from crytobot.strategy import (
    InputProblem,
    InvalidCandlesError,
    InvalidInputError,
    NonFiniteIndicatorError,
    StrategyError,
    StrategySettings,
    propose,
)
from tests.analysis.helpers import candle, from_closes
from tests.strategy.helpers import CROSS_FROM_EQUAL, PAIR, run


def problem_of(**arguments: Any) -> InvalidInputError:
    with pytest.raises(InvalidInputError) as caught:
        run(**arguments)
    return caught.value


PERIODS = ("fast_period", "slow_period", "rsi_period", "atr_period")
BAD_PERIODS: list[tuple[Any, InputProblem]] = [
    (0, InputProblem.NOT_POSITIVE),
    (-1, InputProblem.NOT_POSITIVE),
    (2.0, InputProblem.NOT_INTEGER),
    (True, InputProblem.NOT_INTEGER),
    (Decimal(2), InputProblem.NOT_INTEGER),
    ("2", InputProblem.NOT_INTEGER),
    (None, InputProblem.NOT_INTEGER),
]
NOT_NUMBERS: list[Any] = [0.5, 2.0, True, False, "2", None]
NON_FINITE = [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")]


@pytest.mark.parametrize("period", PERIODS)
@pytest.mark.parametrize(("value", "problem"), BAD_PERIODS)
def test_invalid_period_is_rejected(period: str, value: Any, problem: InputProblem) -> None:
    error = problem_of(**{period: value})
    assert error.problem is problem
    assert error.name == period


@pytest.mark.parametrize(("fast", "slow"), [(2, 2), (3, 2)])
def test_fast_must_be_below_slow(fast: int, slow: int) -> None:
    error = problem_of(fast_period=fast, slow_period=slow)
    assert error.problem is InputProblem.FAST_NOT_BELOW_SLOW


@pytest.mark.parametrize("value", [0, -1, Decimal(0), Decimal("100.0000001"), 101])
def test_invalid_threshold_is_rejected(value: Any) -> None:
    error = problem_of(rsi_threshold=value)
    assert error.problem is InputProblem.OUT_OF_RANGE
    assert error.name == "rsi_threshold"


@pytest.mark.parametrize("value", [1, 100, Decimal(100), Decimal("0.0001")])
def test_threshold_limits_are_accepted(value: Any) -> None:
    run(rsi_threshold=value)


@pytest.mark.parametrize("name", ["k", "r"])
@pytest.mark.parametrize("value", [0, -1, Decimal(0), Decimal("-0.5")])
def test_invalid_k_and_r_are_rejected(name: str, value: Any) -> None:
    error = problem_of(**{name: value})
    assert error.problem is InputProblem.NOT_POSITIVE
    assert error.name == name


@pytest.mark.parametrize("name", ["k", "r", "rsi_threshold", "tick"])
@pytest.mark.parametrize("value", NON_FINITE)
def test_non_finite_values_are_rejected(name: str, value: Decimal) -> None:
    error = problem_of(**{name: value})
    assert error.problem is InputProblem.NON_FINITE
    assert error.name == name


@pytest.mark.parametrize("name", ["k", "r", "rsi_threshold", "tick"])
@pytest.mark.parametrize("value", NOT_NUMBERS)
def test_float_and_bool_money_values_are_rejected(name: str, value: Any) -> None:
    error = problem_of(**{name: value})
    assert error.problem is InputProblem.NOT_A_NUMBER
    assert error.name == name


@pytest.mark.parametrize("value", [0, -1, Decimal(0), Decimal("-0.01")])
def test_invalid_tick_is_rejected(value: Any) -> None:
    error = problem_of(tick=value)
    assert error.problem is InputProblem.NOT_POSITIVE
    assert error.name == "tick"


@pytest.mark.parametrize("name", ["k", "r", "tick"])
@pytest.mark.parametrize(
    "value",
    [
        Decimal("1E+41"),
        Decimal("1E-41"),
        Decimal("1E+999999"),
        Decimal("1E-999999"),
        Decimal("1E+999999999999999999"),
        Decimal("1.2345678901234567890123456789"),
        10**41,
    ],
)
def test_out_of_scale_values_are_rejected(name: str, value: Any) -> None:
    error = problem_of(**{name: value})
    assert error.problem is InputProblem.OUT_OF_SCALE
    assert error.name == name


@pytest.mark.parametrize("name", ["k", "r", "tick"])
@pytest.mark.parametrize(
    "value",
    [
        Decimal("1E+40"),
        Decimal("1E-40"),
        Decimal("1.234567890123456789012345678"),
        Decimal("2.5000000000000000000000000000000000"),
    ],
)
def test_values_at_the_scale_limit_are_accepted(name: str, value: Any) -> None:
    run(**{name: value})


@pytest.mark.parametrize(
    ("name", "problem"),
    [
        ("k", InputProblem.OUT_OF_SCALE),
        ("r", InputProblem.OUT_OF_SCALE),
        ("tick", InputProblem.OUT_OF_SCALE),
        ("rsi_threshold", InputProblem.OUT_OF_RANGE),
    ],
)
def test_huge_integer_does_not_break_the_message(name: str, problem: InputProblem) -> None:
    error = problem_of(**{name: 10**5000})
    assert error.problem is problem
    assert name in str(error)


def test_huge_negative_period_does_not_break_the_message() -> None:
    error = problem_of(fast_period=-(10**5000))
    assert "fast_period" in str(error)


@pytest.mark.parametrize("pair", ["", None, 1, True, b"BTC/USDT", ["BTC/USDT"]])
def test_invalid_pair_is_rejected(pair: Any) -> None:
    assert problem_of(pair=pair).problem is InputProblem.INVALID_PAIR


@pytest.mark.parametrize("flag", [0, 1, None, "true", Decimal(1)])
def test_invalid_position_flag_is_rejected(flag: Any) -> None:
    assert problem_of(position_open=flag).problem is InputProblem.NOT_A_FLAG


@pytest.mark.parametrize("settings", [None, {}, "settings", 1])
def test_object_that_is_not_settings_is_rejected(settings: Any) -> None:
    with pytest.raises(InvalidInputError) as caught:
        propose(pair=PAIR, candles=[], position_open=False, tick=1, settings=settings)
    assert caught.value.problem is InputProblem.NOT_SETTINGS


def test_settings_have_no_defaults() -> None:
    parameters = inspect.signature(StrategySettings).parameters
    assert len(parameters) == 7
    assert all(p.default is inspect.Parameter.empty for p in parameters.values())


def test_propose_has_no_defaults() -> None:
    parameters = inspect.signature(propose).parameters
    assert all(p.default is inspect.Parameter.empty for p in parameters.values())
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in parameters.values())


def broken_series() -> list[Any]:
    """İkinci konumdaki mumda `high < low`."""
    return [*from_closes((10.0, 8.0)), candle(2, 9.0, 8.0, 9.5, 9.0), *from_closes((10.0,))]


def test_invalid_candle_keeps_problem_and_position() -> None:
    with pytest.raises(InvalidCandlesError) as caught:
        run(candles=broken_series())
    assert caught.value.problem is CandleProblem.HIGH_BELOW_LOW
    assert caught.value.position == 2
    assert isinstance(caught.value, StrategyError)


@pytest.mark.parametrize(
    ("series", "problem"),
    [
        (iter(from_closes(CROSS_FROM_EQUAL)), CandleProblem.NOT_A_SERIES),
        ("candles", CandleProblem.NOT_A_SERIES),
        ([None], CandleProblem.NOT_A_CANDLE),
    ],
)
def test_input_that_is_not_a_candle_series_is_rejected(series: Any, problem: CandleProblem) -> None:
    with pytest.raises(InvalidCandlesError) as caught:
        run(candles=series)
    assert caught.value.problem is problem


@pytest.mark.parametrize(
    "arguments",
    [
        {"k": 2.0},
        {"fast_period": 0},
        {"rsi_threshold": 0},
        {"tick": 0},
        {"pair": ""},
        {"position_open": 1},
    ],
)
def test_setting_error_wins_over_candle_error(arguments: dict[str, Any]) -> None:
    with pytest.raises(InvalidInputError):
        run(candles=broken_series(), **arguments)


def test_candle_error_wins_over_position_open() -> None:
    with pytest.raises(InvalidCandlesError):
        run(candles=broken_series(), position_open=True)


@pytest.mark.parametrize("position_open", [False, True])
def test_non_finite_indicator_is_a_named_error(position_open: bool) -> None:
    """İki kapanışın toplamı `float`'a sığmaz; hata `POSITION_OPEN`'ın arkasına saklanmaz."""
    with pytest.raises(NonFiniteIndicatorError) as caught:
        run((1.7e308, 1.7e308, 1.7e308), position_open=position_open)
    assert caught.value.indicator == "ema"
    assert caught.value.position == 1
    assert isinstance(caught.value, StrategyError)
