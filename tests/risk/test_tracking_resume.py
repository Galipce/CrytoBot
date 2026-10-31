"""Spec 0004 AC-6: drawdown durdurmasını yalnızca CLI kaldırır (BR-6)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from crytobot.risk import DEFAULT_LIMITS, EMPTY_STATE, RiskState, TrackingReason, observe, resume

T0 = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)


def observed(*equities: str) -> RiskState:
    state = EMPTY_STATE
    for i, equity in enumerate(equities):
        state = observe(state, T0 + timedelta(hours=i), Decimal(equity), DEFAULT_LIMITS).state
    return state


HALTED = observed("10000", "8400")


def test_cli_resume_lifts_halt_and_resets_peak() -> None:
    """AC-6 (BR-6): CLI isteği durdurmayı kaldırır, zirve kasa son kasa olur; yeniden durmaz."""
    assert HALTED.halted

    update = resume(HALTED, "cli")

    assert update.accepted and not update.state.halted
    assert update.state.peak_equity == Decimal("8400")
    later = observe(update.state, T0 + timedelta(hours=5), Decimal("8300"), DEFAULT_LIMITS)
    assert later.accepted and not later.state.halted


@pytest.mark.parametrize(
    ("channel", "reason"),
    [
        ("telegram", TrackingReason.TELEGRAM_RESUME),
        ("CLI", TrackingReason.UNKNOWN_CHANNEL),
        ("sms", TrackingReason.UNKNOWN_CHANNEL),
        (" cli", TrackingReason.UNKNOWN_CHANNEL),
    ],
    ids=["telegram", "cli_case", "sms", "cli_space"],
)
def test_resume_rejected_from_other_channels(channel: str, reason: TrackingReason) -> None:
    """AC-6 (BR-6): Telegram ve bilinmeyen kanal reddedilir; durum değişmez."""
    update = resume(HALTED, channel)

    assert update.reason is reason and not update.accepted
    assert update.state == HALTED


def test_resume_without_halt_changes_nothing() -> None:
    """AC-6: durdurma yokken CLI isteği durumu değiştirmez ve bunu belirtir."""
    state = observed("10000", "9500")

    update = resume(state, "cli")

    assert update.reason is TrackingReason.NOT_HALTED
    assert update.state == state
    assert "durdurma yok" in update.message


def test_resume_on_empty_state_rejected() -> None:
    """AC-6: hiç gözlem yokken kaldırma isteği geçersizdir."""
    update = resume(EMPTY_STATE, "cli")

    assert update.reason is TrackingReason.EMPTY_STATE and update.state == EMPTY_STATE
