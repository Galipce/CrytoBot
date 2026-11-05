"""Spec 0017 AC-5: kapanmamış mum sessizce çıkar, saate eşit kapanış kapanmıştır (R-5)."""

from datetime import timedelta

from crytobot.market_data._candles import parse_series, request_end_ms
from crytobot.market_data._types import IssueReason
from tests.market_data.helpers import CLOSE_MS, HOUR, HOUR_MS, at_ms, candle_rows

CLOSED_AT = at_ms(CLOSE_MS)
ONE_MS = timedelta(milliseconds=1)


def test_candle_closing_after_clock_is_dropped() -> None:
    series = parse_series(candle_rows(3), HOUR, 3, CLOSED_AT - ONE_MS)
    assert series.candles is not None
    assert [candle.open_time for candle in series.candles] == [
        at_ms(CLOSE_MS - 3 * HOUR_MS),
        at_ms(CLOSE_MS - 2 * HOUR_MS),
    ]


def test_candle_closing_at_clock_stays() -> None:
    series = parse_series(candle_rows(3), HOUR, 3, CLOSED_AT)
    assert series.candles is not None
    assert series.candles[-1].open_time == at_ms(CLOSE_MS - HOUR_MS)
    assert len(series.candles) == 3


def test_unclosed_candle_gives_no_issue() -> None:
    assert parse_series(candle_rows(3), HOUR, 3, CLOSED_AT - ONE_MS).issue is None


def test_only_an_unclosed_candle_is_an_empty_series() -> None:
    series = parse_series(candle_rows(1), HOUR, 1, CLOSED_AT - ONE_MS)
    assert series.candles is None
    assert series.issue is IssueReason.NO_CANDLES


def test_request_ends_at_last_closed_candle() -> None:
    assert request_end_ms(CLOSED_AT, HOUR) == CLOSE_MS - 1
    assert request_end_ms(CLOSED_AT + 59 * timedelta(minutes=1), HOUR) == CLOSE_MS - 1
    assert request_end_ms(CLOSED_AT - ONE_MS, HOUR) == CLOSE_MS - HOUR_MS - 1
