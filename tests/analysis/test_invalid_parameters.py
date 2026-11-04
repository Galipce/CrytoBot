"""Spec 0014 AC-9: geçersiz parametre adı konmuş hatayla reddedilir; varsayılan yoktur."""

import inspect
from collections.abc import Callable
from dataclasses import astuple, dataclass
from decimal import Decimal
from typing import Any

import pytest

from crytobot.analysis import (
    AnalysisError,
    InvalidParameterError,
    ParameterProblem,
    atr,
    bollinger,
    ema,
    macd,
    rsi,
    sma,
)
from tests.analysis.helpers import candle, from_closes


@dataclass(frozen=True)
class Call:
    """İndikatör, geçerli parametreleri ve periyot olarak denetlenen adlar."""

    function: Callable[..., Any]
    valid: dict[str, Any]
    periods: tuple[str, ...]


CALLS = {
    "sma": Call(sma, {"period": 3}, ("period",)),
    "ema": Call(ema, {"period": 3}, ("period",)),
    "rsi": Call(rsi, {"period": 3}, ("period",)),
    "atr": Call(atr, {"period": 3}, ("period",)),
    "macd": Call(macd, {"fast": 2, "slow": 3, "signal": 2}, ("fast", "slow", "signal")),
    "bollinger": Call(bollinger, {"period": 3, "k": 2.0}, ("period",)),
}
PERIODS = [(name, period) for name, call in CALLS.items() for period in call.periods]
BAD_PERIODS: list[tuple[Any, ParameterProblem]] = [
    (0, ParameterProblem.NOT_POSITIVE),
    (-1, ParameterProblem.NOT_POSITIVE),
    (2.0, ParameterProblem.NOT_INTEGER),
    (True, ParameterProblem.NOT_INTEGER),
    ("3", ParameterProblem.NOT_INTEGER),
    (None, ParameterProblem.NOT_INTEGER),
]


@pytest.mark.parametrize(("indicator", "period"), PERIODS)
@pytest.mark.parametrize(("value", "problem"), BAD_PERIODS)
def test_invalid_period_is_rejected(
    indicator: str, period: str, value: Any, problem: ParameterProblem
) -> None:
    call = CALLS[indicator]
    with pytest.raises(InvalidParameterError) as caught:
        call.function(from_closes(range(1, 60)), **{**call.valid, period: value})
    assert caught.value.problem is problem
    assert caught.value.name == period
    assert isinstance(caught.value, AnalysisError)


@pytest.mark.parametrize("indicator", CALLS)
def test_parameters_have_no_defaults(indicator: str) -> None:
    call = CALLS[indicator]
    signature = inspect.signature(call.function)
    for name in call.valid:
        parameter = signature.parameters[name]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        call.function(from_closes(range(1, 60)))


@pytest.mark.parametrize(("indicator", "period"), PERIODS)
def test_invalid_parameter_wins_over_empty_series(indicator: str, period: str) -> None:
    call = CALLS[indicator]
    with pytest.raises(InvalidParameterError):
        call.function([], **{**call.valid, period: 0})
    result = call.function([], **call.valid)
    parts = (result,) if isinstance(result, tuple) else astuple(result)
    assert all(part == () for part in parts)


@pytest.mark.parametrize(("indicator", "period"), PERIODS)
def test_huge_integer_does_not_break_the_message(indicator: str, period: str) -> None:
    call = CALLS[indicator]
    with pytest.raises(InvalidParameterError) as caught:
        call.function(from_closes(range(1, 9)), **{**call.valid, period: -(10**5000)})
    assert period in str(caught.value)


@pytest.mark.parametrize(("fast", "slow"), [(3, 3), (4, 3), pytest.param(10**5000, 3, id="huge")])
def test_macd_fast_must_be_below_slow(fast: int, slow: int) -> None:
    with pytest.raises(InvalidParameterError) as caught:
        macd(from_closes(range(1, 60)), fast=fast, slow=slow, signal=2)
    assert caught.value.problem is ParameterProblem.FAST_NOT_BELOW_SLOW
    assert caught.value.name == "fast"


@pytest.mark.parametrize(
    ("k", "problem"),
    [
        (0, ParameterProblem.NOT_POSITIVE),
        (0.0, ParameterProblem.NOT_POSITIVE),
        (-1.0, ParameterProblem.NOT_POSITIVE),
        (float("inf"), ParameterProblem.NON_FINITE),
        (float("-inf"), ParameterProblem.NON_FINITE),
        (float("nan"), ParameterProblem.NON_FINITE),
        pytest.param(10**5000, ParameterProblem.NON_FINITE, id="huge"),
        (True, ParameterProblem.NON_NUMERIC),
        ("2", ParameterProblem.NON_NUMERIC),
        (Decimal("2"), ParameterProblem.NON_NUMERIC),
        (None, ParameterProblem.NON_NUMERIC),
    ],
)
def test_bollinger_k_must_be_positive_and_finite(k: Any, problem: ParameterProblem) -> None:
    with pytest.raises(InvalidParameterError) as caught:
        bollinger(from_closes(range(1, 9)), period=3, k=k)
    assert caught.value.problem is problem
    assert caught.value.name == "k"
    assert "0000" not in str(caught.value)


def test_bollinger_integer_k_is_accepted() -> None:
    closes = from_closes(range(1, 9))
    assert bollinger(closes, period=3, k=2) == bollinger(closes, period=3, k=2.0)


@pytest.mark.parametrize("indicator", ["sma", "ema", "rsi", "atr", "bollinger"])
def test_huge_valid_period_is_all_missing(indicator: str) -> None:
    call = CALLS[indicator]
    result = call.function(from_closes(range(1, 9)), **{**call.valid, "period": 10**5000})
    parts = (result,) if isinstance(result, tuple) else astuple(result)
    assert all(part == (None,) * 8 for part in parts)


def test_huge_valid_macd_periods_are_all_missing() -> None:
    candles = from_closes(range(1, 9))
    slow = macd(candles, fast=2, slow=10**5000, signal=2)
    assert slow.macd == slow.signal == slow.histogram == (None,) * 8
    signal = macd(candles, fast=2, slow=3, signal=10**5000)
    assert signal.macd[2] is not None
    assert signal.signal == signal.histogram == (None,) * 8


@pytest.mark.parametrize(
    ("indicator", "name", "value"),
    [*((indicator, period, 0) for indicator, period in PERIODS), ("bollinger", "k", 0)],
)
def test_invalid_parameter_wins_over_invalid_candle(indicator: str, name: str, value: int) -> None:
    """Plan 0014, Risk 6: önce parametre, sonra veri; boş seri bu sırayı ayırt etmez."""
    call = CALLS[indicator]
    invalid_candle = candle(0, 10.0, 8.0, 9.0, 8.5)
    with pytest.raises(InvalidParameterError) as caught:
        call.function([invalid_candle], **{**call.valid, name: value})
    assert caught.value.name == name


def test_macd_order_rule_wins_over_invalid_candle() -> None:
    """Plan 0014, Risk 6: `fast >= slow` da parametre kuralıdır, veri denetiminden önce gelir."""
    invalid_candle = candle(0, 10.0, 8.0, 9.0, 8.5)
    with pytest.raises(InvalidParameterError) as caught:
        macd([invalid_candle], fast=3, slow=3, signal=2)
    assert caught.value.problem is ParameterProblem.FAST_NOT_BELOW_SLOW
