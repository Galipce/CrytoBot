"""Spec 0004 AC-1, AC-3…AC-5, AC-8: gün başı ve zirve kasa, drawdown durdurması (BR-5, BR-6)."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    RiskState,
    TrackingReason,
    observe,
)

T0 = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)


def observed(
    *equities: str, start: datetime = T0, step: timedelta = timedelta(hours=1)
) -> RiskState:
    """Equities observed one `step` apart from `start`; every observation must be accepted."""
    state = EMPTY_STATE
    for i, equity in enumerate(equities):
        update = observe(state, start + i * step, Decimal(equity), DEFAULT_LIMITS)
        assert update.accepted, update.message
        state = update.state
    return state


def test_first_observation_sets_day_and_equities() -> None:
    """AC-1: ilk gözlem günü, gün başı ve zirve kasayı belirler; durdurma yok."""
    state = observed("10000")

    assert state.day == date(2026, 11, 2)
    assert state.day_start_equity == state.peak_equity == state.last_equity == Decimal("10000")
    assert state.last_time == T0
    assert not state.halted


def test_peak_follows_the_highest_equity() -> None:
    """AC-1: yüksek kasa zirveyi yükseltir, düşük kasa değiştirmez; gün başı aynı kalır."""
    state = observed("10000", "10500", "10200")

    assert state.peak_equity == Decimal("10500")
    assert state.day_start_equity == Decimal("10000")
    assert state.last_equity == Decimal("10200")


def test_new_utc_day_resets_day_start() -> None:
    """AC-3 (BR-5): 00:00:00 UTC'deki ilk gözlem yeni günün gün başı kasasıdır."""
    late = datetime(2026, 11, 2, 23, 59, 59, tzinfo=UTC)
    state = observed("10000", "9600", start=late - timedelta(hours=1))

    update = observe(
        state, datetime(2026, 11, 3, 0, 0, 0, tzinfo=UTC), Decimal("9650"), DEFAULT_LIMITS
    )

    assert update.accepted
    assert update.state.day == date(2026, 11, 3)
    assert update.state.day_start_equity == Decimal("9650")
    assert update.state.peak_equity == Decimal("10000")


def test_non_utc_time_counts_by_utc_day() -> None:
    """AC-3: UTC dışı zaman dilimli zaman UTC gününe göre değerlendirilir."""
    istanbul = timezone(timedelta(hours=3))

    state = observe(
        EMPTY_STATE, datetime(2026, 11, 3, 1, 30, tzinfo=istanbul), Decimal("10000"), DEFAULT_LIMITS
    ).state

    assert state.day == date(2026, 11, 2)


@pytest.mark.parametrize(
    ("equity", "halted"),
    [("8501", False), ("8500", True), ("8000", True)],
    ids=["below_limit", "at_limit", "past_limit"],
)
def test_drawdown_halts_at_limit(equity: str, halted: bool) -> None:
    """AC-4 (BR-6): zirve 10000, limit %15 — kasa 8500'e (tam %15) inince durum durdurulur."""
    state = observed("10000", equity)

    assert state.halted is halted


def test_halt_survives_recovery_and_new_day() -> None:
    """AC-5 (BR-6): durdurma kasa toparlansa da, yeni UTC günü gelse de sürer."""
    state = observed("10000", "8500", "10000")
    assert state.halted

    next_day = observe(
        state, datetime(2026, 11, 3, 9, 0, tzinfo=UTC), Decimal("10000"), DEFAULT_LIMITS
    )

    assert next_day.accepted and next_day.state.halted


def test_same_time_observation_is_accepted() -> None:
    """AC-8: son gözlemle aynı zamanlı gözlem geçerlidir."""
    state = observed("10000")

    update = observe(state, T0, Decimal("9900"), DEFAULT_LIMITS)

    assert update.accepted and update.state.last_equity == Decimal("9900")


INVALID = {
    "naive_time": (datetime(2026, 11, 2, 11, 0), Decimal("10000"), "zaman"),
    "earlier_time": (T0 - timedelta(seconds=1), Decimal("10000"), "eski"),
    "equity_zero": (T0, Decimal("0"), "kasa Decimal('0')"),
    "equity_negative": (T0, Decimal("-1"), "kasa Decimal('-1')"),
    "equity_nan": (T0, Decimal("NaN"), "kasa Decimal('NaN')"),
    "equity_float": (T0, 9900.0, "kasa 9900.0"),
}


@pytest.mark.parametrize("case", list(INVALID))
def test_invalid_observation_is_rejected(case: str) -> None:
    """AC-8: geçersiz gözlem reddedilir, durum değişmez, neden adlandırılır."""
    at, equity, named = INVALID[case]
    state = observed("10000")

    update = observe(state, at, equity, DEFAULT_LIMITS)

    assert update.reason is TrackingReason.INVALID_OBSERVATION and not update.accepted
    assert update.state == state
    assert named in update.message


def test_observation_with_invalid_limits_is_rejected() -> None:
    """AC-8: geçersiz limitlerle gözlem durumu ilerletmez; drawdown ölçülemez (fail-closed)."""
    state = observed("10000")

    update = observe(
        state, T0, Decimal("8000"), replace(DEFAULT_LIMITS, max_drawdown=Decimal("NaN"))
    )

    assert update.reason is TrackingReason.INVALID_OBSERVATION and update.state == state
    assert "max_drawdown" in update.message


def test_equity_past_the_default_exponent_range_is_observed() -> None:
    """R-6: sonlu, pozitif her kasa bir sonuç verir; varsayılan üs sınırını aşan kasa da."""
    update = observe(EMPTY_STATE, T0, Decimal("1E+999999999"), DEFAULT_LIMITS)

    assert update.accepted and update.state.peak_equity == Decimal("1E+999999999")
