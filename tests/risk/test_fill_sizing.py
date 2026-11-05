"""Spec 0020 AC-1, AC-2: miktar slippage'lı girişle boyutlanır; spread ve bakiye sınırı etkilenmez.
AC-9, R-4, R-9: `edge_clears` onaydaki BR-8 formülüdür; sığmayan hesap kat sağlanmamış sayılır.

Kasa 10000, işlem riski %1, ücret 0.001, slippage 0.001, spread 0.0005, adım 0.001, giriş 10,
stop 8, hedef 14. Elle hesap: slippage'lı giriş 10.01, birim kayıp
(10.01 - 8) + 10.01 * 0.001 + 8 * 0.001 = 2.02801; 100 // (0.001 * 2.02801) = 49309.
"""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    AccountState,
    ApprovalReason,
    PairRules,
    TradeApproval,
    TradeIntent,
    approve_trade,
    edge_clears,
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


def cents(low: int, high: int) -> st.SearchStrategy[Decimal]:
    return st.integers(low, high).map(lambda n: Decimal(n).scaleb(-2))


def rates(high: int) -> st.SearchStrategy[Decimal]:
    return st.integers(0, high).map(lambda n: Decimal(n).scaleb(-4))


@settings(max_examples=300)
@given(
    entry=cents(100, 100_000),
    gain=cents(1, 2_000),
    fee=rates(50),
    spread=rates(50),
    slippage=rates(50),
    multiple=cents(100, 1_000),
)
def test_edge_clears_matches_approval(
    entry: Decimal,
    gain: Decimal,
    fee: Decimal,
    spread: Decimal,
    slippage: Decimal,
    multiple: Decimal,
) -> None:
    """AC-9 (R-4): giriş fiyata eşitken `edge_clears`, onayın BR-8 kararıyla birebir aynıdır."""
    target = entry + gain
    intent = TradeIntent(PAIR, "buy", entry, entry / 2, target)
    limits = replace(DEFAULT_LIMITS, profit_cost_multiple=multiple)
    state = observe(EMPTY_STATE, NOW, ACCOUNT.equity, limits).state
    approval = approve_trade(
        intent, limits, ACCOUNT, RULES, frozenset({PAIR}), fee, spread, slippage, state, NOW
    )

    cleared = approval.reason is not ApprovalReason.INSUFFICIENT_EDGE
    assert edge_clears(entry, target, fee, spread, slippage, multiple) is cleared


def test_edge_clears_only_above_the_multiple() -> None:
    """R-4: AC-8'in elle hesabı: fiyat 100, hedef 101, spread 0.005: kâr 1 = 2 * 0.5, geçmez."""
    costs = (Decimal(0), Decimal("0.005"), Decimal(0), Decimal(2))

    assert edge_clears(Decimal(100), Decimal(101), *costs) is False
    assert edge_clears(Decimal("99.9"), Decimal(101), *costs) is True


def test_unfit_edge_does_not_clear() -> None:
    """R-9: 60 basamağa sığmayan spread: istisna yok, kat sağlanmamış sayılır."""
    long_spread = Decimal("0.0005" + "0" * 80 + "1")

    assert edge_clears(Decimal(10), Decimal(14), FEE, long_spread, SLIPPAGE, Decimal(2)) is False
    assert edge_clears(Decimal(10), Decimal(14), FEE, SPREAD, SLIPPAGE, Decimal(2)) is True
