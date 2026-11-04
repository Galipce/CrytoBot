"""Sinyalleri birleştirip işlem önerisi (yön, giriş, stop, hedef) üretmek."""

from crytobot.strategy._inputs import (
    InputProblem,
    InvalidCandlesError,
    InvalidInputError,
    NonFiniteIndicatorError,
    StrategyError,
    StrategySettings,
)

__all__: list[str] = [
    "InputProblem",
    "InvalidCandlesError",
    "InvalidInputError",
    "NonFiniteIndicatorError",
    "StrategyError",
    "StrategySettings",
]
