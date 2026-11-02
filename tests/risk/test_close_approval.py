"""Spec 0009 AC-1, AC-2, AC-9: kapanış onayı giriş kurallarına bakmaz, yalnızca biçimi denetler."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest

from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    AccountState,
    ApprovalReason,
    CloseRefusal,
    CloseRequest,
    PairRules,
    RiskState,
    TradeIntent,
    approve_close,
    approve_trade,
    observe,
)

PAIR = "BTC/USDT"
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
REQUEST = CloseRequest("cb-s1-btc-0001", PAIR, Decimal("19.249"), "hedef")
RULES = PairRules(Decimal("0.001"), Decimal("0.001"), Decimal("5"))
INTENT = TradeIntent(PAIR, "buy", Decimal("100"), Decimal("95"), Decimal("200"))
NOTHING: Any = None  # a field value outside its type, as a hand-built value may carry


@pytest.mark.parametrize("reason", ["stop", "hedef"])
def test_close_is_approved_unchanged(reason: str) -> None:
    """AC-1 (R-1): biçimi geçerli kapanış talebi onaylanır; talep değişmeden taşınır."""
    request = replace(REQUEST, reason=reason)

    approval = approve_close(request)

    assert approval.approved and approval.reason is None
    assert approval.request is request
    assert "cb-s1-btc-0001 kapanışı onaylandı" in approval.message and reason in approval.message


def observed(*equities: str) -> RiskState:
    state = EMPTY_STATE
    for i, equity in enumerate(equities):
        at = NOW - timedelta(minutes=len(equities) - 1 - i)
        state = observe(state, at, Decimal(equity), DEFAULT_LIMITS).state
    return state


# (risk state, equity, open positions, whitelist, intent): each one an entry rule refusing a buy
BLOCKED: dict[str, tuple[RiskState, str, int, frozenset[str], TradeIntent, ApprovalReason]] = {
    "daily_loss": (
        observed("10000", "9700"), "9700", 0, frozenset({PAIR}), INTENT,
        ApprovalReason.DAILY_LOSS_LIMIT,
    ),
    "drawdown_halt": (
        observed("10000", "8500"), "8500", 0, frozenset({PAIR}), INTENT,
        ApprovalReason.DRAWDOWN_HALT,
    ),
    "position_limit": (
        observed("10000"), "10000", 5, frozenset({PAIR}), INTENT, ApprovalReason.POSITION_LIMIT,
    ),
    "not_whitelisted": (
        observed("10000"), "10000", 0, frozenset(), INTENT, ApprovalReason.NOT_WHITELISTED,
    ),
    "no_stop": (
        observed("10000"), "10000", 0, frozenset({PAIR}), replace(INTENT, stop=None),
        ApprovalReason.INVALID_STOP,
    ),
    # a zero equity is no input for a buy at all; a close needs no equity (plan 0009 A-1)
    "zero_equity": (
        observed("10000"), "0", 0, frozenset({PAIR}), INTENT, ApprovalReason.INVALID_INPUT,
    ),
    "thin_edge": (
        observed("10000"), "10000", 0, frozenset({PAIR}), replace(INTENT, target=Decimal("100.1")),
        ApprovalReason.INSUFFICIENT_EDGE,
    ),
}  # fmt: skip


@pytest.mark.parametrize("case", list(BLOCKED))
def test_entry_limits_do_not_block_a_close(case: str) -> None:
    """AC-2 (R-2, R-15; BR-3…BR-8): bir alımı reddeden giriş kuralı ve durum kapanışı engellemez;
    işlem önerisi onayının aynı durumdaki reddi değişmez."""
    state, equity, positions, whitelist, intent, refusal = BLOCKED[case]
    account = AccountState(Decimal(equity), Decimal(equity), positions)

    buy = approve_trade(
        intent, DEFAULT_LIMITS, account, RULES, whitelist, Decimal("0.001"), Decimal("0.0005"),
        Decimal("0.001"), state, NOW,
    )  # fmt: skip
    close = approve_close(replace(REQUEST, pair="XRP/USDT" if case == "not_whitelisted" else PAIR))

    assert buy.reason is refusal and buy.amount is None
    assert close.approved


LONG = Decimal("1." + "2" * 28)  # 29 significant digits
INVALID: dict[str, tuple[dict[str, Any], str]] = {
    "position-no_prefix": ({"position_id": "s1-btc-0001"}, "pozisyon kimliği 's1-btc-0001'"),
    "position-cx_prefix": ({"position_id": "cx-s1-btc-0001"}, "pozisyon kimliği"),
    "position-33_chars": ({"position_id": "cb-" + "x" * 33}, "pozisyon kimliği"),
    "position-space": ({"position_id": "cb-s1 btc"}, "pozisyon kimliği"),
    "position-not_text": ({"position_id": 42}, "pozisyon kimliği 42"),
    "pair-not_text": ({"pair": NOTHING}, "çift None metin"),
    "amount-zero": ({"amount": Decimal(0)}, "miktar 0 sıfırdan büyük"),
    "amount-negative": ({"amount": Decimal(-1)}, "miktar -1 sıfırdan büyük"),
    "amount-nan": ({"amount": Decimal("NaN")}, "sıfırdan büyük"),
    "amount-float": ({"amount": 19.249}, "miktar 19.249 sıfırdan büyük"),
    "amount-bool": ({"amount": True}, "miktar True sıfırdan büyük"),
    "amount-fraction": ({"amount": Fraction(1, 3)}, "sıfırdan büyük"),
    "amount-huge_int": ({"amount": -(10**4300)}, "miktar <4301 basamaklı sayı> sıfırdan büyük"),
    "amount-out_of_scale": ({"amount": Decimal("1E+1000000")}, "ölçeği varsayılan üs aralığı"),
    "amount-29_digits": ({"amount": LONG}, "<29 basamaklı sayı> 28 anlamlı basamaktan uzun"),
    "reason-other": ({"reason": "elle"}, "neden 'elle' stop ya da hedef"),
    "reason-not_text": ({"reason": NOTHING}, "neden None stop ya da hedef"),
}


@pytest.mark.parametrize("case", list(INVALID))
def test_invalid_close_request_is_named(case: str) -> None:
    """AC-9 (R-8, R-13): biçime uymayan kapanış talebi → "geçersiz girdi", girdi ve kuralı
    adlandırılır, istisna yok, mesaj kısa."""
    overrides, fragment = INVALID[case]

    approval = approve_close(replace(REQUEST, **overrides))

    assert approval.reason is CloseRefusal.INVALID_INPUT and not approval.approved
    assert "geçersiz girdi" in approval.message and fragment in approval.message, approval.message
    assert len(approval.message) < 500
