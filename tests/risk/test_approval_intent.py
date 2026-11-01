"""Spec 0006 AC-12 (R-14): onay sonucu karara bağladığı öneriyi değiştirmeden taşır (BR-9)."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    AccountState,
    ApprovalReason,
    PairRules,
    RiskState,
    TradeIntent,
    approve_trade,
    observe,
)

PAIR = "BTC/USDT"
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
ACCOUNT = AccountState(Decimal("10000"), Decimal("5000"), 0)
RULES = PairRules(Decimal("0.001"), Decimal("0.001"), Decimal("5"))
INTENT = TradeIntent(PAIR, "buy", Decimal("100"), Decimal("95"), Decimal("110"))
TINY_STEP = PairRules(Decimal("1E-999999"), Decimal("0"), Decimal("0"))

# one case per outcome of approve_trade, each built from spec 0003-0005 examples
CASES: dict[str, tuple[dict[str, Any], ApprovalReason | None]] = {
    "approved": ({}, None),
    "invalid_input": ({"fee": None}, ApprovalReason.INVALID_INPUT),
    "not_buy": ({"intent": replace(INTENT, side="sell")}, ApprovalReason.NOT_BUY),
    "invalid_stop": ({"intent": replace(INTENT, stop=None)}, ApprovalReason.INVALID_STOP),
    "insufficient_edge": (
        {"intent": replace(INTENT, target=Decimal("100.3"))},  # cost 0.2003, threshold 0.4006
        ApprovalReason.INSUFFICIENT_EDGE,
    ),
    "position_limit": (
        {"account": replace(ACCOUNT, open_positions=5)},
        ApprovalReason.POSITION_LIMIT,
    ),
    "below_minimum": (
        {"account": replace(ACCOUNT, free_balance=Decimal("1"))},
        ApprovalReason.BELOW_MINIMUM,
    ),
    "unrepresentable": (
        {
            "intent": TradeIntent(PAIR, "buy", Decimal("1"), Decimal("0.5"), Decimal("2")),
            "account": AccountState(Decimal("100000"), Decimal("100000"), 0),
            "rules": TINY_STEP,
        },
        ApprovalReason.INVALID_INPUT,
    ),
}


def fresh(account: AccountState) -> RiskState:
    return observe(EMPTY_STATE, NOW, account.equity, DEFAULT_LIMITS).state


@pytest.mark.parametrize("case", list(CASES))
def test_approval_carries_the_intent(case: str) -> None:
    """AC-12 (R-14): onayda da her ret yolunda da sonuç, verilen önerinin kendisini taşır."""
    overrides, reason = CASES[case]
    v: dict[str, Any] = {
        "intent": INTENT,
        "account": ACCOUNT,
        "rules": RULES,
        "fee": Decimal("0.001"),
    } | overrides

    result = approve_trade(
        v["intent"],
        DEFAULT_LIMITS,
        v["account"],
        v["rules"],
        frozenset({PAIR}),
        v["fee"],
        Decimal(0),
        Decimal(0),
        fresh(v["account"]),
        NOW,
    )

    assert result.reason is reason
    assert result.intent is v["intent"]
