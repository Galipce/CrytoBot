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
    "target": Decimal("200"),
    "equity": Decimal("10000"),
    "free": Decimal("5000"),
    "fee": Decimal("0.001"),
    "spread": Decimal("0"),
    "slippage": Decimal("0"),
    "step": Decimal("0.001"),
    "min_amount": Decimal("0.001"),
    "min_notional": Decimal("5"),
    "positions": 0,
}
HUGE_OUT, TINY_OUT = Decimal("1E+1000000"), Decimal("1E-1000000")
HUGE_IN, TINY_IN = Decimal("9.99E+999999"), Decimal("1E-999999")


def approve(overrides: dict[str, Any], limits: RiskLimits = DEFAULT_LIMITS) -> TradeApproval:
    v = {**BASE, **overrides}
    account = AccountState(v["equity"], v["free"], v["positions"])
    state = observe(EMPTY_STATE, NOW, v["equity"], limits).state
    return approve_trade(
        TradeIntent(PAIR, "buy", v["entry"], v["stop"], v["target"]),
        limits,
        account,
        PairRules(v["step"], v["min_amount"], v["min_notional"]),
        frozenset({PAIR}),
        v["fee"],
        v["spread"],
        v["slippage"],
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
    "spread-tiny": ("spread", TINY_OUT, ApprovalReason.INVALID_INPUT, "spread"),
    "slippage-tiny": ("slippage", TINY_OUT, ApprovalReason.INVALID_INPUT, "slippage"),
    "step-huge": ("step", HUGE_OUT, ApprovalReason.INVALID_INPUT, "miktar adımı"),
    "step-tiny": ("step", TINY_OUT, ApprovalReason.INVALID_INPUT, "miktar adımı"),
    "min_amount-huge": ("min_amount", HUGE_OUT, ApprovalReason.INVALID_INPUT, "asgari miktar"),
    "min_amount-tiny": ("min_amount", TINY_OUT, ApprovalReason.INVALID_INPUT, "asgari miktar"),
    "min_notional-huge": ("min_notional", HUGE_OUT, ApprovalReason.INVALID_INPUT, "asgari tutar"),
    "min_notional-tiny": ("min_notional", TINY_OUT, ApprovalReason.INVALID_INPUT, "asgari tutar"),
    "entry-huge": ("entry", HUGE_OUT, ApprovalReason.INVALID_ENTRY, "giriş"),
    "entry-tiny": ("entry", TINY_OUT, ApprovalReason.INVALID_ENTRY, "giriş"),
    "stop-tiny": ("stop", TINY_OUT, ApprovalReason.INVALID_STOP, "stop"),
    "target-huge": ("target", HUGE_OUT, ApprovalReason.INVALID_TARGET, "hedef"),
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


@pytest.mark.parametrize("name", ["stop", "fee", "spread", "slippage"])
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


BIG: Any = 10**4300  # past Python 3.12's 4300-digit int -> str limit (review round 1 F-1)


@pytest.mark.parametrize("sign", [1, -1], ids=["big", "negative_big"])
@pytest.mark.parametrize("name", list(BASE))
def test_huge_int_input_is_a_named_rejection(name: str, sign: int) -> None:
    """AC-8, AC-11 (R-7): 4300 basamağı aşan `int` girdi `ValueError` değil, bir sonuç verir."""
    result = approve({name: sign * BIG})

    assert (result.amount is None) is (result.reason is not None)
    if sign < 0:  # no input may be negative
        assert result.reason is not None


def test_huge_int_multiple_is_shown_in_the_message() -> None:
    """R-3, R-7: elle kurulmuş dev `int` kat, ret mesajında değeriyle adlandırılır."""
    limits = replace(DEFAULT_LIMITS, profit_cost_multiple=BIG)

    result = approve({"target": Decimal("101")}, limits=limits)

    assert result.reason is ApprovalReason.INSUFFICIENT_EDGE
    assert f"kat 1{'0' * 4300}" in result.message


@pytest.mark.parametrize(
    ("at", "equity"), [(NOW, -BIG), (BIG, Decimal("10000"))], ids=["negative_equity", "time"]
)
def test_huge_int_observation_is_a_named_rejection(at: Any, equity: Any) -> None:
    """Spec 0004 R-7: dev `int` kasa ya da zaman gözlemi `ValueError` değil, gözlem reddidir."""
    update = observe(EMPTY_STATE, at, equity, DEFAULT_LIMITS)

    assert update.reason is not None and update.state == EMPTY_STATE
