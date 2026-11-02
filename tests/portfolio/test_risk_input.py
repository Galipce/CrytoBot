"""Spec 0007 AC-11: defterin hesap durumu `risk`'in hesap girdisidir (R-8)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from crytobot.portfolio import (
    EMPTY_LEDGER,
    AccountSnapshot,
    Fill,
    Ledger,
    account_state,
    open_ledger,
    record_fill,
)
from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    AccountState,
    ApprovalReason,
    PairRules,
    TradeApproval,
    TradeIntent,
    approve_trade,
    observe,
)

PAIR = "BTC/USDT"
OPENED = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
NOW = OPENED + timedelta(hours=1)
RULES = PairRules(Decimal("0.001"), Decimal("0.001"), Decimal("5"))
INTENT = TradeIntent(PAIR, "buy", Decimal("100"), Decimal("95"), Decimal("110"))
FILL = Fill(
    "cb-s1-btc-0001",
    PAIR,
    "buy",
    Decimal("19.249"),
    Decimal("100.1"),
    Decimal("1.9268249"),
    Decimal("95"),
    Decimal("110"),
    NOW,
)


def ledger_with(fills: int) -> Ledger:
    ledger = open_ledger(EMPTY_LEDGER, Decimal("10000"), OPENED).ledger
    for i in range(fills):
        ledger = record_fill(ledger, replace(FILL, client_order_id=f"cb-{i}")).ledger
    return ledger


def snapshot_of(ledger: Ledger) -> AccountSnapshot:
    result = account_state(ledger, {PAIR: Decimal("105")})
    assert result.snapshot is not None, result.message
    return result.snapshot


def as_account(snapshot: AccountSnapshot) -> AccountState:
    """What `app` does: the ledger's snapshot as risk's account input (plan 0007 Risk 1)."""
    return AccountState(snapshot.equity, snapshot.free_balance, snapshot.open_positions)


def judge(account: AccountState) -> TradeApproval:
    state = observe(EMPTY_STATE, NOW, account.equity, DEFAULT_LIMITS).state
    return approve_trade(
        INTENT, DEFAULT_LIMITS, account, RULES, frozenset({PAIR}), Decimal("0.001"),
        Decimal("0.0005"), Decimal("0.001"), state, NOW,
    )  # fmt: skip


# (fills, the same account written out by hand): opening only; spec 0006 AC-1's fill at BTC 105
HAND_BUILT: dict[str, tuple[int, AccountState]] = {
    "opening": (0, AccountState(Decimal("10000"), Decimal("10000"), 0)),
    "one_fill": (1, AccountState(Decimal("10092.3932751"), Decimal("8071.2482751"), 1)),
}


@pytest.mark.parametrize("case", list(HAND_BUILT))
def test_snapshot_matches_hand_built_account(case: str) -> None:
    """AC-11 (R-8): defterin durumuyla onay ve kasa gözlemi, aynı değerleri elle veren çağrılarla
    birebir aynı sonucu verir."""
    fills, hand_built = HAND_BUILT[case]

    account = as_account(snapshot_of(ledger_with(fills)))

    assert account == hand_built
    assert judge(account) == judge(hand_built)
    assert observe(EMPTY_STATE, NOW, account.equity, DEFAULT_LIMITS) == observe(
        EMPTY_STATE, NOW, hand_built.equity, DEFAULT_LIMITS
    )
    assert judge(account).approved


def test_five_positions_hit_the_position_limit() -> None:
    """AC-11 (R-8, BR-7): beş açık pozisyonlu defterin durumu pozisyon limiti reddini doğurur."""
    account = as_account(snapshot_of(ledger_with(5)))

    approval = judge(account)

    assert account.open_positions == 5 == DEFAULT_LIMITS.max_open_positions
    assert approval.reason is ApprovalReason.POSITION_LIMIT and approval.amount is None
