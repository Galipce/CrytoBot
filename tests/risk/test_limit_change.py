"""Spec 0002 AC-6…AC-9: limit değiştirme isteğinin kanala ve üst sınıra göre kararı (BR-13)."""

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from crytobot.risk import (
    DEFAULT_LIMITS,
    HARD_CAPS,
    LimitChange,
    RejectReason,
    RiskLimits,
    decide_change,
)

CHANNELS = ["cli", "telegram"]
CURRENT = DEFAULT_LIMITS  # 0.01 / 0.03 / 0.15 / 5
LOWER = {
    "per_trade_risk": Decimal("0.005"),
    "daily_loss_limit": Decimal("0.02"),
    "max_drawdown": Decimal("0.1"),
    "max_open_positions": 3,
}
BETWEEN_LOWER_AND_CURRENT = {
    "per_trade_risk": Decimal("0.008"),
    "daily_loss_limit": Decimal("0.025"),
    "max_drawdown": Decimal("0.12"),
    "max_open_positions": 4,
}
HIGHER = {
    "per_trade_risk": Decimal("0.015"),
    "daily_loss_limit": Decimal("0.04"),
    "max_drawdown": Decimal("0.2"),
    "max_open_positions": 7,
}
ABOVE_CAP = {
    "per_trade_risk": Decimal("0.0200001"),
    "daily_loss_limit": Decimal("0.0500001"),
    "max_drawdown": Decimal("0.2500001"),
    "max_open_positions": 9,
}


def with_limit(limits: RiskLimits, name: str, value: Any) -> RiskLimits:
    return replace(limits, **{name: value})


@pytest.mark.parametrize("name", sorted(LOWER))
@pytest.mark.parametrize("channel", CHANNELS)
def test_lowering_or_same_value_accepted_from_any_channel(channel: str, name: str) -> None:
    """AC-6 (BR-13): düşürme ve aynı değer her kanaldan kabul; yalnızca istenen limit değişir."""
    lowered = decide_change(CURRENT, LimitChange(name, LOWER[name], channel))
    same = decide_change(CURRENT, LimitChange(name, getattr(CURRENT, name), channel))

    assert lowered.accepted and lowered.reason is None
    assert lowered.limits == with_limit(CURRENT, name, LOWER[name])
    assert same.accepted and same.limits == CURRENT


@pytest.mark.parametrize("name", sorted(HIGHER))
def test_telegram_increase_is_rejected(name: str) -> None:
    """AC-7 (BR-13): Telegram'dan artırma, üst sınırın altında olsa bile reddedilir."""
    decision = decide_change(CURRENT, LimitChange(name, HIGHER[name], "telegram"))

    assert not decision.accepted
    assert decision.reason is RejectReason.TELEGRAM_INCREASE
    assert decision.limits == CURRENT
    assert name in decision.message


@pytest.mark.parametrize("name", sorted(LOWER))
def test_telegram_increase_from_lowered_value_is_rejected(name: str) -> None:
    """AC-7 (BR-13): güncel değerle karşılaştırılır; düşürülen limit Telegram'dan geri çıkmaz."""
    lowered = with_limit(CURRENT, name, LOWER[name])

    decision = decide_change(
        lowered, LimitChange(name, BETWEEN_LOWER_AND_CURRENT[name], "telegram")
    )

    assert decision.reason is RejectReason.TELEGRAM_INCREASE
    assert decision.limits == lowered


@pytest.mark.parametrize("name", sorted(HIGHER))
def test_cli_increase_up_to_cap_is_accepted(name: str) -> None:
    """AC-8: CLI'den artırma üst sınıra kadar (eşit dahil) kabul edilir."""
    cap = getattr(HARD_CAPS, name)

    raised = decide_change(CURRENT, LimitChange(name, HIGHER[name], "cli"))
    at_cap = decide_change(CURRENT, LimitChange(name, cap, "cli"))

    assert raised.accepted and raised.limits == with_limit(CURRENT, name, HIGHER[name])
    assert at_cap.accepted and at_cap.limits == with_limit(CURRENT, name, cap)


@pytest.mark.parametrize("name", sorted(ABOVE_CAP))
@pytest.mark.parametrize("channel", CHANNELS)
def test_above_cap_is_rejected_from_any_channel(channel: str, name: str) -> None:
    """AC-8 (R-2): üst sınırı aşan değer her kanaldan "üst sınır aşımı" ile reddedilir."""
    decision = decide_change(CURRENT, LimitChange(name, ABOVE_CAP[name], channel))

    assert decision.reason is RejectReason.ABOVE_CAP
    assert decision.limits == CURRENT
    assert name in decision.message and str(getattr(HARD_CAPS, name)) in decision.message


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (LimitChange("per_trade_risk", "0.005", "cli"), RejectReason.INVALID_VALUE),
        (LimitChange("per_trade_risk", 0.005, "cli"), RejectReason.INVALID_VALUE),
        (LimitChange("per_trade_risk", Decimal("NaN"), "telegram"), RejectReason.INVALID_VALUE),
        (LimitChange("per_trade_risk", Decimal("0"), "cli"), RejectReason.INVALID_VALUE),
        (LimitChange("max_open_positions", True, "cli"), RejectReason.INVALID_VALUE),
        (LimitChange("max_open_positions", Decimal("3"), "cli"), RejectReason.INVALID_VALUE),
        (LimitChange("Per_Trade_Risk", Decimal("0.005"), "cli"), RejectReason.UNKNOWN_LIMIT),
        (LimitChange("per_trade_risk", Decimal("0.005"), "CLI"), RejectReason.UNKNOWN_CHANNEL),
        (LimitChange("per_trade_risk", Decimal("0.005"), "email"), RejectReason.UNKNOWN_CHANNEL),
    ],
    ids=[
        "value_string",
        "value_float",
        "value_nan",
        "value_zero",
        "value_bool",
        "positions_decimal",
        "limit_case",
        "channel_case",
        "channel_unknown",
    ],
)
def test_invalid_request_is_rejected(change: LimitChange, reason: RejectReason) -> None:
    """AC-9: geçersiz değer, bilinmeyen limit veya kanal reddedilir; neden adlandırılır."""
    decision = decide_change(CURRENT, change)

    assert not decision.accepted
    assert decision.reason is reason
    assert decision.limits == CURRENT
    assert decision.message
