"""Spec 0017 AC-15: geçersiz girdi adıyla reddedilir, çağrı gitmez; katı sayı (plan Risk 11)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from crytobot.market_data import read_market_data
from crytobot.market_data._numbers import exact_decimal, ms_from_utc, utc_from_ms
from crytobot.market_data._types import (
    InputProblem,
    ReadSettings,
    pairs_problem,
    settings_problem,
)
from tests.market_data.helpers import BTC, NOW, FakeExchange, candle_rows, clock_at, make_settings

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


def _no_tz() -> datetime:
    return datetime(2026, 11, 5, 12, 0)


def _not_a_time() -> Any:
    return "now"


def _clock_raises() -> datetime:
    raise RuntimeError("no clock")


@pytest.mark.parametrize(
    ("pairs", "settings", "clock", "problem"),
    [
        ([BTC], make_settings(exchange="okx"), clock_at(), InputProblem.EXCHANGE),
        ([BTC], make_settings(exchange=None), clock_at(), InputProblem.EXCHANGE),
        ([BTC], make_settings(candle_interval=None), clock_at(), InputProblem.CANDLE_INTERVAL),
        ([BTC], make_settings(candle_count=None), clock_at(), InputProblem.CANDLE_COUNT),
        ([BTC], make_settings(call_timeout=None), clock_at(), InputProblem.CALL_TIMEOUT),
        ([BTC], make_settings(read_budget=None), clock_at(), InputProblem.READ_BUDGET),
        ([BTC], None, clock_at(), InputProblem.SETTINGS),
        ([BTC, BTC], make_settings(), clock_at(), InputProblem.PAIR_DUPLICATE),
        ([BTC, 1], make_settings(), clock_at(), InputProblem.PAIR_NOT_TEXT),
        (BTC, make_settings(), clock_at(), InputProblem.PAIRS),
        ([BTC], make_settings(), None, InputProblem.CLOCK),
        ([BTC], make_settings(), _no_tz, InputProblem.CLOCK),
        ([BTC], make_settings(), _not_a_time, InputProblem.CLOCK),
        ([BTC], make_settings(), _clock_raises, InputProblem.CLOCK),
        ([], make_settings(exchange="okx"), clock_at(), InputProblem.EXCHANGE),
    ],
)
def test_invalid_input_is_named_without_calls(
    pairs: Any, settings: Any, clock: Any, problem: InputProblem
) -> None:
    exchange = FakeExchange()
    connections: list[int] = []

    def connect() -> FakeExchange:
        connections.append(1)
        return exchange

    read = read_market_data(pairs, settings, clock, connect=connect)
    assert read.input_problem is problem
    assert read.pairs == ()
    assert read.read_at is None
    assert connections == []
    assert exchange.calls == []


def test_empty_list_gives_empty_result() -> None:
    connections: list[int] = []

    def connect() -> FakeExchange:
        connections.append(1)
        return FakeExchange()

    read = read_market_data([], make_settings(), clock_at(), connect=connect)
    assert read.pairs == ()
    assert read.input_problem is None
    assert read.read_at == NOW
    assert connections == []


@pytest.mark.parametrize(
    ("count", "problem"),
    [(1, None), (1000, None), (0, InputProblem.CANDLE_COUNT), (1001, InputProblem.CANDLE_COUNT)],
)
def test_candle_count_bounds(count: int, problem: InputProblem | None) -> None:
    exchange = FakeExchange(klines={"BTCUSDT": candle_rows(1)})
    settings = make_settings(candle_count=count)
    read = read_market_data([BTC], settings, clock_at(), connect=lambda: exchange)
    assert read.input_problem is problem
    if problem is None:
        assert exchange.kline_requests[0]["limit"] == count
        assert read.pairs[0].candles is not None
    else:
        assert exchange.calls == []


def test_fewer_candles_is_a_short_series() -> None:
    exchange = FakeExchange(klines={"BTCUSDT": candle_rows(2)})
    read = read_market_data(
        [BTC], make_settings(candle_count=1000), clock_at(), connect=lambda: exchange
    )
    btc = read.pairs[0]
    assert btc.issues == ()
    assert btc.candles is not None
    assert len(btc.candles) == 2
    assert exchange.calls.count("klines BTCUSDT") == 1  # R-16: one candle request per pair
