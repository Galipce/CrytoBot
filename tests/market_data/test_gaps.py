"""Spec 0017 AC-6: boşlukta yalnız son boşluktan sonrası döner, boşluk adıyla raporlanır (R-6)."""

from crytobot.market_data._candles import parse_series
from crytobot.market_data._types import IssueReason
from tests.market_data.helpers import CLOSE_MS, HOUR, HOUR_MS, NOW, at_ms, candle_row


def _rows_at(*hours_before_close: int) -> list[list[object]]:
    return [candle_row(CLOSE_MS - hours * HOUR_MS) for hours in hours_before_close]


def test_gap_keeps_candles_after_it_and_reports() -> None:
    series = parse_series(_rows_at(6, 5, 3, 2, 1), HOUR, 5, NOW)
    assert series.issue is IssueReason.CANDLE_GAP
    assert series.candles is not None
    assert [candle.open_time for candle in series.candles] == [
        at_ms(CLOSE_MS - 3 * HOUR_MS),
        at_ms(CLOSE_MS - 2 * HOUR_MS),
        at_ms(CLOSE_MS - HOUR_MS),
    ]


def test_two_gaps_use_the_last() -> None:
    series = parse_series(_rows_at(9, 7, 6, 3, 2, 1), HOUR, 6, NOW)
    assert series.issue is IssueReason.CANDLE_GAP
    assert series.candles is not None
    assert len(series.candles) == 3
    assert series.candles[0].open_time == at_ms(CLOSE_MS - 3 * HOUR_MS)


def test_gap_before_the_last_candle_leaves_one() -> None:
    series = parse_series(_rows_at(5, 4, 1), HOUR, 3, NOW)
    assert series.issue is IssueReason.CANDLE_GAP
    assert series.candles is not None
    assert len(series.candles) == 1


def test_no_gap_no_report() -> None:
    series = parse_series(_rows_at(3, 2, 1), HOUR, 3, NOW)
    assert series.issue is None
    assert series.candles is not None
    assert len(series.candles) == 3
