"""Spec 0022 AC-8 (R-8): aralık sınırları, kaçan sınırlar, geri giden saat, uykudan uyanma."""

from datetime import UTC, datetime, timedelta

import pytest

from crytobot.app._schedule import (
    Due,
    after_turn,
    boundary_at_or_before,
    due,
    seconds_until,
)

HOUR = timedelta(hours=1)
B = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("moment", "interval", "expected"),
    [
        (B, HOUR, B),
        (B + timedelta(minutes=59, seconds=59), HOUR, B),
        (B - timedelta(microseconds=1), HOUR, B - HOUR),
        (B + timedelta(minutes=7), timedelta(minutes=5), B + timedelta(minutes=5)),
        (B + 5 * HOUR, timedelta(hours=4), B + 4 * HOUR),  # 4h boundaries are 0, 4, 8, 12, 16…
        (B + 3 * HOUR, timedelta(days=1), B - 12 * HOUR),  # UTC midnight
    ],
)
def test_boundary_is_a_utc_multiple_of_the_interval(
    moment: datetime, interval: timedelta, expected: datetime
) -> None:
    assert boundary_at_or_before(moment, interval) == expected


def test_other_time_zone_gives_the_same_boundary() -> None:
    from datetime import timezone

    local = (B + timedelta(minutes=30)).astimezone(timezone(timedelta(hours=3)))
    assert boundary_at_or_before(local, HOUR) == B


def test_start_on_boundary_runs_once_for_it() -> None:
    """İlk tur sınırda atıldı: aynı sınır ikinci tur almaz, sıradaki sınır beklenir."""
    last, missed = after_turn(B, B + timedelta(seconds=20), HOUR)
    assert (last, missed) == (B, 0)
    assert due(last, B + timedelta(seconds=21), HOUR) is None
    assert due(last, B + HOUR - timedelta(microseconds=1), HOUR) is None
    assert due(last, B + HOUR, HOUR) == Due(B + HOUR, 0)


@pytest.mark.parametrize(("ended", "missed"), [(1.5, 1), (2.5, 2), (2.0, 2), (0.99, 0)])
def test_overrun_skips_and_counts_missed(ended: float, missed: int) -> None:
    """Sınırı aşan tur: kaçan sınır telafi edilmez, bir sonraki gelecek sınır beklenir."""
    end = B + ended * HOUR
    last, counted = after_turn(B, end, HOUR)
    assert counted == missed
    assert due(last, end, HOUR) is None  # the boundary passed during the turn takes no turn
    next_due = due(last, last + HOUR, HOUR)
    assert next_due == Due(B + (missed + 1) * HOUR, 0)


def test_clock_going_back_repeats_no_boundary() -> None:
    last, missed = after_turn(B, B - 2 * HOUR, HOUR)  # the clock went back during the turn
    assert (last, missed) == (B, 0)
    for back in (B - HOUR, B - timedelta(seconds=1), B, B + timedelta(minutes=30)):
        assert due(last, back, HOUR) is None
    assert seconds_until(last, B - HOUR, HOUR) == 2 * 3600
    assert due(last, B + HOUR, HOUR) == Due(B + HOUR, 0)


@pytest.mark.parametrize(("woke", "missed"), [(3.25, 2), (1.5, 0), (24.0, 23)])
def test_wake_after_sleep_counts_missed(woke: float, missed: int) -> None:
    """Uykuda görülmeden geçen sınırlar kaçmıştır; uyanılan aralığın sınırı görülmüştür."""
    now = B + woke * HOUR
    assert due(B, now, HOUR) == Due(boundary_at_or_before(now, HOUR), missed)


def test_seconds_until_next_boundary() -> None:
    assert seconds_until(B, B + timedelta(minutes=45), HOUR) == 15 * 60
    assert seconds_until(B, B + 2 * HOUR, HOUR) == 0.0
