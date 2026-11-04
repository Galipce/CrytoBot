"""Spec 0015 AC-8: geçersiz ayar ve girdi adı konmuş hatayla reddedilir; varsayılan yoktur."""

import inspect
from decimal import Decimal
from typing import Any

import pytest

from crytobot.strategy import InputProblem, InvalidInputError, StrategyError, StrategySettings
from crytobot.strategy._inputs import check_inputs
from tests.strategy.helpers import PAIR, make_settings


def call(*, tick: Any = 1, pair: Any = PAIR, position_open: Any = False, **settings: Any) -> None:
    check_inputs(
        pair=pair, position_open=position_open, tick=tick, settings=make_settings(**settings)
    )


def problem_of(**arguments: Any) -> InvalidInputError:
    with pytest.raises(InvalidInputError) as caught:
        call(**arguments)
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
    call(rsi_threshold=value)


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
    call(**{name: value})


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
        check_inputs(pair=PAIR, position_open=False, tick=1, settings=settings)
    assert caught.value.problem is InputProblem.NOT_SETTINGS


def test_settings_have_no_defaults() -> None:
    parameters = inspect.signature(StrategySettings).parameters
    assert len(parameters) == 7
    assert all(p.default is inspect.Parameter.empty for p in parameters.values())


def test_input_error_is_a_strategy_error() -> None:
    assert issubclass(InvalidInputError, StrategyError)
