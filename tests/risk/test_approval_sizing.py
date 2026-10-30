"""Spec 0003 AC-1…AC-4: onaylı miktar risk bütçesi, serbest bakiye ve borsa kurallarıyla (BR-4)."""

from dataclasses import replace
from decimal import Decimal

import pytest

from crytobot.risk import (
    DEFAULT_LIMITS,
    AccountState,
    ApprovalReason,
    PairRules,
    TradeApproval,
    TradeIntent,
    approve_trade,
)

PAIR = "BTC/USDT"
INTENT = TradeIntent(PAIR, "buy", Decimal("100"), Decimal("95"))
ACCOUNT = AccountState(Decimal("10000"), Decimal("5000"), 0)
STEP = Decimal("0.001")
RULES = PairRules(STEP, Decimal("0.001"), Decimal("5"))
FEE = Decimal("0.001")


def approve(
    intent: TradeIntent = INTENT,
    account: AccountState = ACCOUNT,
    rules: PairRules = RULES,
    fee: Decimal = FEE,
) -> TradeApproval:
    return approve_trade(intent, DEFAULT_LIMITS, account, rules, frozenset({PAIR}), fee)


def loss_at_stop(amount: Decimal, intent: TradeIntent, fee: Decimal) -> Decimal:
    entry, stop = Decimal(str(intent.entry)), Decimal(str(intent.stop))
    return amount * (entry - stop) + amount * entry * fee + amount * stop * fee


def test_happy_path_amount_is_exact() -> None:
    """AC-1 (BR-4): kasa 10000, risk %1, giriş 100, stop 95, ücret 0.001 → tam olarak 19.249."""
    result = approve()

    assert result.approved and result.reason is None
    assert result.amount == Decimal("19.249")
    assert not result.limited_by_balance
    assert PAIR in result.message


def test_amount_is_largest_step_within_budget() -> None:
    """AC-2 (BR-4): onaylı miktarın kaybı bütçede, bir adım fazlasınınki dışında."""
    result = approve()

    assert result.amount is not None
    assert loss_at_stop(result.amount, INTENT, FEE) == Decimal("99.998555") <= Decimal("100")
    assert loss_at_stop(result.amount + STEP, INTENT, FEE) == Decimal("100.00375")


def test_loss_equal_to_budget_is_approved() -> None:
    """AC-2: kayıp bütçeye tam eşitse o miktar onaylanır (giriş 100, stop 90, ücret 0 → 10)."""
    result = approve(intent=replace(INTENT, stop=Decimal("90")), fee=Decimal("0"))

    assert result.approved and result.amount == Decimal("10")


def test_amount_limited_by_free_balance() -> None:
    """AC-3: serbest bakiye 1000 → ücret dahil sığan en büyük miktar 9.990 ve sınır belirtilir."""
    result = approve(account=replace(ACCOUNT, free_balance=Decimal("1000")))

    assert result.approved and result.amount == Decimal("9.990")
    assert result.limited_by_balance
    assert Decimal("9.991") * Decimal("100") * (1 + FEE) > Decimal("1000")


def test_zero_free_balance_is_below_minimum() -> None:
    """AC-3: serbest bakiye 0 → borsa asgarisinin altında, miktar yok."""
    result = approve(account=replace(ACCOUNT, free_balance=Decimal("0")))

    assert result.reason is ApprovalReason.BELOW_MINIMUM and result.amount is None


# AC-1 approves 19.249 (notional 1924.9); each minimum sits exactly there, then one step above it
MINIMUMS = {
    "amount": (PairRules(Decimal("0.001"), Decimal("19.249"), Decimal("0")), "amount"),
    "notional": (PairRules(Decimal("0.001"), Decimal("0"), Decimal("1924.9")), "notional"),
}


@pytest.mark.parametrize("case", list(MINIMUMS))
def test_minimums_inclusive_and_one_step_below_rejected(case: str) -> None:
    """AC-4: asgariye eşit miktar/tutar onaylanır; asgari bir adım yukarıdaysa reddedilir."""
    rules, field = MINIMUMS[case]
    one_step_more = (
        replace(rules, min_amount=Decimal("19.250"))
        if field == "amount"
        else replace(rules, min_notional=Decimal("1925.0"))
    )

    at_minimum = approve(rules=rules)
    below = approve(rules=one_step_more)

    assert at_minimum.approved and at_minimum.amount == Decimal("19.249")
    assert below.reason is ApprovalReason.BELOW_MINIMUM and below.amount is None
    assert PAIR in below.message and "19.249" in below.message
