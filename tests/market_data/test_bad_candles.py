"""Spec 0017 AC-13: bozuk yanıtta tüm seri adıyla eksik, onarım yok (R-13; plan Risk 12)."""

import pytest

from crytobot.market_data._candles import parse_series
from crytobot.market_data._types import IssueReason
from tests.market_data.helpers import CLOSE_MS, HOUR, HOUR_MS, NOW, candle_row, candle_rows

FIRST = CLOSE_MS - 3 * HOUR_MS
SECOND = CLOSE_MS - 2 * HOUR_MS
THIRD = CLOSE_MS - HOUR_MS


def _with_bad_middle(**prices: object) -> list[list[object]]:
    return [candle_row(FIRST), candle_row(SECOND, **prices), candle_row(THIRD)]


BAD_SERIES = [
    ("high_below_low", _with_bad_middle(high="8.00"), IssueReason.HIGH_BELOW_LOW),
    ("zero_price", _with_bad_middle(low="0.00"), IssueReason.NOT_POSITIVE),
    ("negative_price", _with_bad_middle(low="-1.00"), IssueReason.NOT_POSITIVE),
    ("not_a_number_text", _with_bad_middle(close="abc"), IssueReason.NOT_A_NUMBER),
    ("not_a_number_float", _with_bad_middle(close=10.5), IssueReason.NOT_A_NUMBER),
    ("not_a_number_none", _with_bad_middle(close=None), IssueReason.NOT_A_NUMBER),
    ("nan", _with_bad_middle(close="NaN"), IssueReason.NOT_A_NUMBER),
    (
        "time_not_a_number",
        [candle_row(FIRST), ["x", "10", "11", "9", "10"]],
        IssueReason.NOT_A_NUMBER,
    ),
    (
        "duplicate_time",
        [candle_row(FIRST), candle_row(FIRST), candle_row(SECOND)],
        IssueReason.DUPLICATE_TIME,
    ),
    (
        "out_of_order",
        [candle_row(THIRD), candle_row(FIRST), candle_row(SECOND)],
        IssueReason.TIME_OUT_OF_ORDER,
    ),
    (
        "off_interval",
        [candle_row(FIRST + 1), candle_row(SECOND), candle_row(THIRD)],
        IssueReason.TIME_OFF_INTERVAL,
    ),
    # plan Risk 12: analysis refuses these too
    ("open_above_high", _with_bad_middle(open_="12.00"), IssueReason.PRICE_OUTSIDE_RANGE),
    ("open_below_low", _with_bad_middle(open_="8.00"), IssueReason.PRICE_OUTSIDE_RANGE),
    ("close_above_high", _with_bad_middle(close="12.00"), IssueReason.PRICE_OUTSIDE_RANGE),
    ("close_below_low", _with_bad_middle(close="8.00"), IssueReason.PRICE_OUTSIDE_RANGE),
    ("short_row", [candle_row(FIRST), [SECOND, "10", "11"]], IssueReason.MALFORMED_RESPONSE),
    ("row_is_not_a_list", [candle_row(FIRST), "row"], IssueReason.MALFORMED_RESPONSE),
]


@pytest.mark.parametrize(
    ("rows", "reason"),
    [(rows, reason) for _, rows, reason in BAD_SERIES],
    ids=[name for name, _, _ in BAD_SERIES],
)
def test_bad_series_is_missing_by_name(rows: list[object], reason: IssueReason) -> None:
    series = parse_series(rows, HOUR, 3, NOW)
    assert series.candles is None
    assert series.issue is reason


@pytest.mark.parametrize("response", ["text", None, {"a": 1}, 7])
def test_response_that_is_not_a_list_is_malformed(response: object) -> None:
    series = parse_series(response, HOUR, 3, NOW)
    assert series.candles is None
    assert series.issue is IssueReason.MALFORMED_RESPONSE


def test_time_at_the_end_of_the_calendar_is_refused() -> None:
    last_hour_ms = 253402297200000  # 9999-12-31 23:00: closing it does not fit a datetime
    series = parse_series([candle_row(last_hour_ms)], HOUR, 3, NOW)
    assert series.candles is None
    assert series.issue is IssueReason.NOT_A_NUMBER


def test_more_candles_than_requested_is_bad() -> None:
    series = parse_series(candle_rows(3), HOUR, 2, NOW)
    assert series.candles is None
    assert series.issue is IssueReason.TOO_MANY_CANDLES


def test_empty_answer_is_an_empty_series() -> None:
    series = parse_series([], HOUR, 3, NOW)
    assert series.candles is None
    assert series.issue is IssueReason.NO_CANDLES


def test_no_repaired_or_partial_series() -> None:
    """Bozuk tek satır, sağlam satırları da götürür; sıralanmış ya da süzülmüş seri dönmez."""
    for _, rows, _reason in BAD_SERIES:
        assert parse_series(rows, HOUR, 3, NOW).candles is None


def test_good_series_keeps_exact_values() -> None:
    rows = [candle_row(FIRST, "10.10", "11.20", "9.30", "10.40")]
    series = parse_series(rows, HOUR, 3, NOW)
    assert series.candles is not None
    candle = series.candles[0]
    values = (candle.open, candle.high, candle.low, candle.close)
    assert [str(value) for value in values] == ["10.10", "11.20", "9.30", "10.40"]


def test_fewer_candles_than_requested_is_not_an_error() -> None:
    series = parse_series(candle_rows(2), HOUR, 1000, NOW)
    assert series.issue is None
    assert series.candles is not None
    assert len(series.candles) == 2
