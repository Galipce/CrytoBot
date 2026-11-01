"""Spec 0006 AC-7…AC-9: durumu bilinmeyen emir varken güvenli mod (BR-11)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from crytobot.execution import (
    EMPTY_EXECUTION,
    ExecutionState,
    NotificationKind,
    OrderOutcome,
    OrderRequest,
    OrderResult,
    OrderStatus,
    PaperExchange,
    QueryOutcome,
    place_order,
    query_order,
)
from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    AccountState,
    PairRules,
    TradeIntent,
    approve_trade,
    observe,
)

PAIR = "BTC/USDT"
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=1)
ACCOUNT = AccountState(Decimal("10000"), Decimal("5000"), 0)
RULES = PairRules(Decimal("0.001"), Decimal("0.001"), Decimal("5"))
INTENT = TradeIntent(PAIR, "buy", Decimal("100"), Decimal("95"), Decimal("110"))
FEE, SLIPPAGE = Decimal("0.001"), Decimal("0.001")
APPROVAL = approve_trade(
    INTENT,
    DEFAULT_LIMITS,
    ACCOUNT,
    RULES,
    frozenset({PAIR}),
    FEE,
    Decimal("0.0005"),
    SLIPPAGE,
    observe(EMPTY_STATE, NOW, ACCOUNT.equity, DEFAULT_LIMITS).state,
    NOW,
)
UNKNOWN, FILLED, REJECTED = OrderStatus.UNKNOWN, OrderStatus.FILLED, OrderStatus.REJECTED


def exchange(placements: Any = None, resolutions: Any = None) -> PaperExchange:
    return PaperExchange(placements or {}, resolutions or {})


def place(
    state: ExecutionState, intent_id: str, venue: PaperExchange, now: datetime = NOW
) -> OrderResult:
    request = OrderRequest(
        intent_id, INTENT, APPROVAL, RULES, Decimal("100"), FEE, SLIPPAGE, "paper"
    )
    return place_order(state, request, venue, now)


def test_unknown_status_enters_safe_mode_once() -> None:
    """AC-7 (R-7, R-9, R-10, R-11): `bilinmiyor` emir kaydedilir, tek giriş bildirimi; sonraki istek
    "durum belirsiz" alır ve emri adlandırır, yeni bildirim yok; aynı kimlik → "zaten var"."""
    venue = exchange({"cb-a": UNKNOWN})

    entered = place(EMPTY_EXECUTION, "a", venue)
    blocked = place(entered.state, "b", venue, LATER)
    again = place(entered.state, "a", venue, LATER)

    order = entered.order
    assert entered.created and order is not None and order.status is UNKNOWN
    assert order.fill_price is None and order.fee is None
    assert "dolum fiyatı" not in entered.message
    assert [n.kind for n in entered.notifications] == [NotificationKind.SAFE_MODE_ENTERED]
    note = entered.notifications[0]
    assert (note.client_order_id, note.pair, note.at) == ("cb-a", PAIR, NOW)
    assert entered.state.unknown == ("cb-a",)
    assert blocked.outcome is OrderOutcome.STATUS_UNKNOWN and blocked.order is None
    assert "durum belirsiz" in blocked.message and "cb-a" in blocked.message
    assert blocked.notifications == () and blocked.state is entered.state
    assert again.outcome is OrderOutcome.ALREADY_EXISTS and again.order == order


@pytest.mark.parametrize("status", [FILLED, REJECTED], ids=["filled", "rejected"])
def test_resolved_query_leaves_safe_mode(status: OrderStatus) -> None:
    """AC-8 (R-9, R-10): sorgu emri netleştirir → durum güncellenir, tek çıkış bildirimi, sonraki
    istek emir oluşturur; dolarsa dolum fiyatı ve komisyon yerleştirmedeki istekten gelir."""
    venue = exchange({"cb-a": UNKNOWN}, {"cb-a": status})
    entered = place(EMPTY_EXECUTION, "a", venue)

    resolved = query_order(entered.state, "cb-a", venue, LATER)
    after = place(resolved.state, "b", venue, LATER)

    order = resolved.order
    assert resolved.outcome is QueryOutcome.UPDATED and order is not None
    assert order.status is status and resolved.state.unknown == ()
    if status is FILLED:
        assert order.fill_price == Decimal("100.1") and order.fee == Decimal("1.9268249")
    else:
        assert order.fill_price is None and order.fee is None
    assert [n.kind for n in resolved.notifications] == [NotificationKind.SAFE_MODE_EXITED]
    assert (resolved.notifications[0].client_order_id, resolved.notifications[0].at) == (
        "cb-a",
        LATER,
    )
    assert after.created and after.notifications == ()


def test_two_unknown_orders_both_must_resolve() -> None:
    """AC-8 (R-9): iki emir `bilinmiyor` iken biri netleşince güvenli mod sürer, ikisi de netleşince
    biter; bildirim yalnız girişte ve son çıkışta."""
    # the second order can only be unknown if it was placed before the first one turned unknown:
    # build that state from two separate placements
    venue = exchange({"cb-a": UNKNOWN, "cb-b": UNKNOWN}, {"cb-a": FILLED, "cb-b": FILLED})
    first = place(EMPTY_EXECUTION, "a", venue)
    second = place(EMPTY_EXECUTION, "b", venue)
    both = ExecutionState(
        {**first.state.orders, **second.state.orders},
        {**first.state.quotes, **second.state.quotes},
    )

    one = query_order(both, "cb-a", venue, LATER)
    two = query_order(one.state, "cb-b", venue, LATER)

    assert one.outcome is QueryOutcome.UPDATED and one.state.unknown == ("cb-b",)
    assert one.notifications == ()
    assert place(one.state, "c", venue).outcome is OrderOutcome.STATUS_UNKNOWN
    assert (
        two.state.unknown == () and two.notifications[0].kind is NotificationKind.SAFE_MODE_EXITED
    )
    assert place(two.state, "c", venue).created


def test_query_rules() -> None:
    """AC-8 (R-9): sorgu yine `bilinmiyor` → güvenli mod sürer, bildirim yok; kayıtlı olmayan emir →
    "bilinmeyen emir"; netleşmiş emrin sorgusu → değişiklik yok."""
    venue = exchange({"cb-a": UNKNOWN})
    entered = place(EMPTY_EXECUTION, "a", venue)
    filled = place(EMPTY_EXECUTION, "z", venue)

    still = query_order(entered.state, "cb-a", venue, LATER)
    missing = query_order(entered.state, "cb-nope", venue, LATER)
    not_text = query_order(entered.state, ["cb-a"], venue, LATER)
    settled = query_order(filled.state, "cb-z", venue, LATER)
    no_zone = query_order(entered.state, "cb-a", venue, datetime(2026, 11, 2, 10, 1))

    assert still.outcome is QueryOutcome.UNCHANGED and still.state is entered.state
    assert still.notifications == ()
    for result in (missing, not_text):
        assert result.outcome is QueryOutcome.UNKNOWN_ORDER and result.state is entered.state
        assert "bilinmeyen emir" in result.message
    assert settled.outcome is QueryOutcome.UNCHANGED and settled.state is filled.state
    assert no_zone.outcome is QueryOutcome.INVALID_INPUT and no_zone.state is entered.state


def test_rejected_order_is_not_safe_mode() -> None:
    """AC-9 (R-7, R-8): simülatör emri `reddedildi` döndürür → güvenli mod yok, bildirim yok; aynı
    kimlik → "zaten var"."""
    venue = exchange({"cb-a": REJECTED})

    rejected = place(EMPTY_EXECUTION, "a", venue)
    again = place(rejected.state, "a", venue)
    other = place(rejected.state, "b", venue)

    order = rejected.order
    assert rejected.created and order is not None and order.status is REJECTED
    assert order.fill_price is None and rejected.notifications == ()
    assert "dolum fiyatı" not in rejected.message
    assert rejected.state.unknown == ()
    assert again.outcome is OrderOutcome.ALREADY_EXISTS and again.order == order
    assert other.created
