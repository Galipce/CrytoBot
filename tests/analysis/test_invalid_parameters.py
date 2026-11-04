"""Spec 0014 AC-9: geçersiz parametre adı konmuş hatayla reddedilir; varsayılan yoktur."""

import inspect
from collections.abc import Callable
from dataclasses import astuple, dataclass
from typing import Any

import pytest

from crytobot.analysis import (
    AnalysisError,
    InvalidParameterError,
    ParameterProblem,
    atr,
    ema,
    rsi,
    sma,
)
from tests.analysis.helpers import from_closes


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
