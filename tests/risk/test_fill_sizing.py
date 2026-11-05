"""Spec 0020 AC-1, AC-2: miktar slippage'lı girişle boyutlanır; spread ve bakiye sınırı etkilenmez.

Kasa 10000, işlem riski %1, ücret 0.001, slippage 0.001, spread 0.0005, adım 0.001, giriş 10,
stop 8, hedef 14. Elle hesap: slippage'lı giriş 10.01, birim kayıp
(10.01 - 8) + 10.01 * 0.001 + 8 * 0.001 = 2.02801; 100 // (0.001 * 2.02801) = 49309.
"""

from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest

from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    AccountState,
    PairRules,
    TradeApproval,
    TradeIntent,
    approve_trade,
    observe,
)

PAIR = "BTC/USDT"
NOW = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
ACCOUNT = AccountState(Decimal(10000), Decimal(10000), 0)
RULES = PairRules(Decimal("0.001"), Decimal("0.001"), Decimal(10))
INTENT = TradeIntent(PAIR, "buy", Decimal(10), Decimal(8), Decimal(14))
FEE, SPREAD, SLIPPAGE = Decimal("0.001"), Decimal("0.0005"), Decimal("0.001")


def approve(
    account: AccountState = ACCOUNT, spread: Any = SPREAD, slippage: Any = SLIPPAGE
) -> TradeApproval:
    state = observe(EMPTY_STATE, NOW, account.equity, DEFAULT_LIMITS).state
    return approve_trade(
        INTENT, DEFAULT_LIMITS, account, RULES, frozenset({PAIR}), FEE, spread, slippage, state, NOW
    )


def risk_at_slipped_entry(amount: Decimal) -> Fraction:
    """R-1, bağımsız: tam kesirle miktar * birim kayıp (dolum = giriş * (1 + slippage))."""
    fill = Fraction(10) * (1 + Fraction(SLIPPAGE))
    unit = (fill - 8) + fill * Fraction(FEE) + 8 * Fraction(FEE)
    return Fraction(amount) * unit


def test_amount_is_sized_at_slipped_entry() -> None:
    """AC-1 (R-1): miktar tam 49.309, risk ~99.999; bir adım fazlası (49.310) limiti aşar."""
    result = approve()

    assert result.approved and result.amount == Decimal("49.309")
    assert not result.limited_by_balance
    assert risk_at_slipped_entry(Decimal("49.309")) <= 100
    assert risk_at_slipped_entry(Decimal("49.310")) > 100


def test_zero_slippage_keeps_the_amount() -> None:
    """AC-1 (R-1): slippage 0 ile aynı öneride miktar bugünkü gibi 49.554 kalır."""
    result = approve(slippage=Decimal(0))

    assert result.approved and result.amount == Decimal("49.554")


@pytest.mark.parametrize("spread", [Decimal(0), SPREAD, Decimal("0.01")])
def test_spread_does_not_change_the_amount(spread: Decimal) -> None:
    """AC-2 (R-1): spread miktarı etkilemez."""
    result = approve(spread=spread)

    assert result.approved and result.amount == Decimal("49.309")


@pytest.mark.parametrize("slippage", [Decimal(0), SLIPPAGE, Decimal("0.01")])
def test_balance_limited_amount_ignores_slippage(slippage: Decimal) -> None:
    """AC-2 (R-1): serbest bakiye 300: 300 // (0.001 * 10 * 1.001) = 29970; slippage değiştirmez."""
    result = approve(account=AccountState(Decimal(10000), Decimal(300), 0), slippage=slippage)

    assert result.approved and result.amount == Decimal("29.970")
    assert result.limited_by_balance
