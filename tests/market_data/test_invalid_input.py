"""Spec 0017 AC-15: geçersiz girdi adıyla reddedilir, çağrı gitmez; katı sayı (plan Risk 11)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from crytobot.market_data._numbers import exact_decimal, ms_from_utc, utc_from_ms
from crytobot.market_data._types import (
    InputProblem,
    ReadSettings,
    pairs_problem,
    settings_problem,
)

GOOD: dict[str, Any] = {
    "exchange": "binance",
    "candle_interval": timedelta(hours=1),
    "candle_count": 3,
    "call_timeout": timedelta(seconds=5),
    "read_budget": timedelta(seconds=30),
}


def test_good_settings_pass() -> None:
    assert settings_problem(ReadSettings(**GOOD)) is None


@pytest.mark.parametrize(
    ("name", "value", "problem"),
    [
        ("exchange", None, InputProblem.EXCHANGE),
        ("exchange", "okx", InputProblem.EXCHANGE),
        ("exchange", 1, InputProblem.EXCHANGE),
        ("candle_interval", None, InputProblem.CANDLE_INTERVAL),
        ("candle_interval", "1h", InputProblem.CANDLE_INTERVAL),
        ("candle_interval", timedelta(weeks=1), InputProblem.CANDLE_INTERVAL),
        ("candle_interval", timedelta(minutes=7), InputProblem.CANDLE_INTERVAL),
        ("candle_count", None, InputProblem.CANDLE_COUNT),
        ("candle_count", 0, InputProblem.CANDLE_COUNT),
        ("candle_count", 1001, InputProblem.CANDLE_COUNT),
        ("candle_count", 1.0, InputProblem.CANDLE_COUNT),
        ("candle_count", True, InputProblem.CANDLE_COUNT),
        ("call_timeout", None, InputProblem.CALL_TIMEOUT),
        ("call_timeout", 5, InputProblem.CALL_TIMEOUT),
        ("call_timeout", timedelta(0), InputProblem.CALL_TIMEOUT),
        ("read_budget", None, InputProblem.READ_BUDGET),
        ("read_budget", timedelta(seconds=-1), InputProblem.READ_BUDGET),
    ],
)
def test_each_invalid_setting_is_named(name: str, value: object, problem: InputProblem) -> None:
    assert settings_problem(ReadSettings(**{**GOOD, name: value})) is problem


def test_settings_of_another_type_are_named() -> None:
    assert settings_problem(GOOD) is InputProblem.SETTINGS


@pytest.mark.parametrize(
    ("pairs", "problem"),
    [
        ("BTC/USDT", InputProblem.PAIRS),
        (None, InputProblem.PAIRS),
        ({"BTC/USDT"}, InputProblem.PAIRS),
        (["BTC/USDT", 1], InputProblem.PAIR_NOT_TEXT),
        ([["BTC/USDT"]], InputProblem.PAIR_NOT_TEXT),
        ([""], InputProblem.PAIR_NOT_TEXT),
        (["BTC/USDT", "BTC/USDT"], InputProblem.PAIR_DUPLICATE),
        (["BTC/USDT", "ETH/USDT"], None),
        ([], None),
    ],
)
def test_pair_lists(pairs: object, problem: InputProblem | None) -> None:
    assert pairs_problem(pairs) is problem


@pytest.mark.parametrize(
    "text",
    [
        "1_000",
        " 1",
        "1 ",
        "1e4",
        "NaN",
        "Infinity",
        "-1",
        "+1",
        ".5",
        "5.",
        "",
        "٣",
        "1" * 41,
        "0." + "1" * 19,
    ],
)
def test_non_plain_text_is_not_a_number(text: str) -> None:
    assert exact_decimal(text) is None


@pytest.mark.parametrize("value", [1, 1.5, None, True, Decimal(1), b"1"])
def test_only_text_is_a_number(value: object) -> None:
    assert exact_decimal(value) is None


def test_text_converts_exactly() -> None:
    assert str(exact_decimal("80308.35000000")) == "80308.35000000"
    assert str(exact_decimal("0." + "1" * 18)) == "0." + "1" * 18


def test_milliseconds_convert_to_aware_utc() -> None:
    assert utc_from_ms(1000) == datetime(1970, 1, 1, 0, 0, 1, tzinfo=UTC)
    moment = utc_from_ms(0)
    assert moment is not None
    assert moment.utcoffset() == timedelta(0)
    assert ms_from_utc(moment) == 0


@pytest.mark.parametrize("value", [-1, 1.5, "1000", None, True, 10**30])
def test_bad_milliseconds_are_refused(value: object) -> None:
    assert utc_from_ms(value) is None
