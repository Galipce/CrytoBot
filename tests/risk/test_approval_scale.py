"""Spec 0005 AC-8: onayın her sayısal girdisi varsayılan üs aralığıyla sınırlı (R-7, B-8)."""

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
    RiskLimits,
    TradeApproval,
    TradeIntent,
    approve_trade,
    observe,
)

PAIR = "BTC/USDT"
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
BASE: dict[str, Any] = {
    "entry": Decimal("100"),
    "stop": Decimal("95"),
    "equity": Decimal("10000"),
    "free": Decimal("5000"),
    "fee": Decimal("0.001"),
    "step": Decimal("0.001"),
    "min_amount": Decimal("0.001"),
    "min_notional": Decimal("5"),
}
HUGE_OUT, TINY_OUT = Decimal("1E+1000000"), Decimal("1E-1000000")
HUGE_IN, TINY_IN = Decimal("9.99E+999999"), Decimal("1E-999999")


def approve(overrides: dict[str, Decimal], limits: RiskLimits = DEFAULT_LIMITS) -> TradeApproval:
    v = {**BASE, **overrides}
    account = AccountState(v["equity"], v["free"], 0)
    state = observe(EMPTY_STATE, NOW, v["equity"], limits).state
    return approve_trade(
        TradeIntent(PAIR, "buy", v["entry"], v["stop"]),
        limits,
        account,
        PairRules(v["step"], v["min_amount"], v["min_notional"]),
        frozenset({PAIR}),
        v["fee"],
        state,
        NOW,
    )


# (input, end, the reason it is rejected with, the label in the message)
OUTSIDE: dict[str, tuple[str, Decimal, ApprovalReason, str]] = {
    "equity-huge": ("equity", HUGE_OUT, ApprovalReason.INVALID_INPUT, "kasa"),
    "equity-tiny": ("equity", TINY_OUT, ApprovalReason.INVALID_INPUT, "kasa"),
    "free-huge": ("free", HUGE_OUT, ApprovalReason.INVALID_INPUT, "serbest bakiye"),
    "free-tiny": ("free", TINY_OUT, ApprovalReason.INVALID_INPUT, "serbest bakiye"),
    "fee-tiny": ("fee", TINY_OUT, ApprovalReason.INVALID_INPUT, "ücret"),
    "step-huge": ("step", HUGE_OUT, ApprovalReason.INVALID_INPUT, "miktar adımı"),
    "step-tiny": ("step", TINY_OUT, ApprovalReason.INVALID_INPUT, "miktar adımı"),
    "min_amount-huge": ("min_amount", HUGE_OUT, ApprovalReason.INVALID_INPUT, "asgari miktar"),
    "min_amount-tiny": ("min_amount", TINY_OUT, ApprovalReason.INVALID_INPUT, "asgari miktar"),
    "min_notional-huge": ("min_notional", HUGE_OUT, ApprovalReason.INVALID_INPUT, "asgari tutar"),
    "min_notional-tiny": ("min_notional", TINY_OUT, ApprovalReason.INVALID_INPUT, "asgari tutar"),
    "entry-huge": ("entry", HUGE_OUT, ApprovalReason.INVALID_ENTRY, "giriş"),
    "entry-tiny": ("entry", TINY_OUT, ApprovalReason.INVALID_ENTRY, "giriş"),
    "stop-tiny": ("stop", TINY_OUT, ApprovalReason.INVALID_STOP, "stop"),
}


@pytest.mark.parametrize("case", list(OUTSIDE))
def test_input_past_the_range_is_named(case: str) -> None:
    """AC-8 (R-7): aralığın hemen dışındaki girdi kendi nedeni, değeri ve aralığıyla reddedilir."""
    name, value, reason, label = OUTSIDE[case]

    result = approve({name: value})

    assert result.reason is reason and result.amount is None
    assert f"{label} {value} ölçeği" in result.message and "999999" in result.message


@pytest.mark.parametrize("case", list(OUTSIDE))
def test_input_inside_the_range_is_not_a_scale_rejection(case: str) -> None:
    """AC-8 (R-7): aralığın hemen içindeki girdi ölçek yüzünden reddedilmez (istisna da yok)."""
    name, value, _, _ = OUTSIDE[case]
    inside = HUGE_IN if value == HUGE_OUT else TINY_IN

    result = approve({name: inside})

    assert "ölçeği" not in result.message


@pytest.mark.parametrize("name", ["stop", "fee"])
def test_backlog_b8_repro_is_a_named_rejection(name: str) -> None:
    """AC-8 (B-8): stop ya da ücret `1E-999999999999` `MemoryError` değil, adlandırılmış rettir."""
    result = approve({name: Decimal("1E-999999999999")})

    assert result.reason is not None and result.amount is None
    assert "ölçeği" in result.message


def test_tiny_limit_stays_bounded() -> None:
    """Spec 0005 Constraints: ölçeksiz kalan çok küçük oran limiti sınırsız hesaba yol açmaz."""
    tiny = replace(DEFAULT_LIMITS, per_trade_risk=Decimal("1E-999999999"))

    result = approve({}, limits=tiny)

    assert result.reason is ApprovalReason.BELOW_MINIMUM and result.amount is None
