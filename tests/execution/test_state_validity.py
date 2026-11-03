"""Spec 0011 AC-13 (R-13, B-13), R-6: tahminsiz bilinmeyen emir; emir durumunun doğrulanması."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest

from crytobot.execution import (
    EMPTY_EXECUTION,
    CloseOrder,
    CloseOrderRequest,
    ExecutionState,
    Order,
    OrderOutcome,
    OrderRequest,
    OrderStatus,
    PaperExchange,
    QueryOutcome,
    execution_problems,
    place_close_order,
    place_order,
    query_order,
)
from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    AccountState,
    CloseRequest,
    PairRules,
    TradeIntent,
    approve_close,
    approve_trade,
    observe,
)

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
CID = "cb-a"
CLOSE_ID = "cx-a"
INTENT = TradeIntent("BTC/USDT", "buy", Decimal("100"), Decimal("95"), Decimal("110"))
RULES = PairRules(Decimal("0.001"), Decimal("0.001"), Decimal("5"))
FEE, SLIPPAGE = Decimal("0.001"), Decimal("0.001")


hand_built: Any = replace  # deliberately wrong field types


def bought(status: OrderStatus = OrderStatus.FILLED) -> ExecutionState:
    risk = observe(EMPTY_STATE, NOW, Decimal("10000"), DEFAULT_LIMITS).state
    approval = approve_trade(
        INTENT,
        DEFAULT_LIMITS,
        AccountState(Decimal("10000"), Decimal("5000"), 0),
        RULES,
        frozenset({"BTC/USDT"}),
        FEE,
        Decimal(0),
        SLIPPAGE,
        risk,
        NOW,
    )
    request = OrderRequest("a", INTENT, approval, RULES, Decimal("100"), FEE, SLIPPAGE, "paper")
    exchange = PaperExchange(placements=MappingProxyType({CID: status}))
    result = place_order(EMPTY_EXECUTION, request, exchange, NOW)
    assert result.outcome is OrderOutcome.CREATED
    return result.state


def closed(status: OrderStatus = OrderStatus.FILLED) -> ExecutionState:
    state = bought()
    close = CloseRequest(CID, "BTC/USDT", state.orders[CID].amount, "stop")
    request = CloseOrderRequest(approve_close(close), RULES, Decimal("95"), FEE, SLIPPAGE, "paper")
    exchange = PaperExchange(placements=MappingProxyType({CLOSE_ID: status}))
    result = place_close_order(state, request, exchange, NOW)
    assert result.outcome is OrderOutcome.CREATED, result.message
    return result.state


@pytest.mark.parametrize("resolution", [OrderStatus.FILLED, OrderStatus.REJECTED, None])
def test_b13_unknown_order_without_quote_is_invalid_input(resolution: OrderStatus | None) -> None:
    state = replace(bought(OrderStatus.UNKNOWN), quotes=MappingProxyType({}))
    resolutions = {} if resolution is None else {CID: resolution}
    exchange = PaperExchange(resolutions=MappingProxyType(resolutions))

    result = query_order(state, CID, exchange, NOW)

    assert result.outcome is QueryOutcome.INVALID_INPUT
    assert result.message.startswith("geçersiz girdi")
    assert result.state is state


def test_b13_unknown_order_with_quote_still_resolves() -> None:
    exchange = PaperExchange(resolutions=MappingProxyType({CID: OrderStatus.FILLED}))

    result = query_order(bought(OrderStatus.UNKNOWN), CID, exchange, NOW)

    assert result.outcome is QueryOutcome.UPDATED
    assert result.state.orders[CID].status is OrderStatus.FILLED


@pytest.mark.parametrize(
    "state",
    [
        EMPTY_EXECUTION,
        bought(),
        bought(OrderStatus.REJECTED),
        bought(OrderStatus.UNKNOWN),
        closed(),
        closed(OrderStatus.REJECTED),
        closed(OrderStatus.UNKNOWN),
    ],
)
def test_states_the_engine_builds_have_no_problems(state: ExecutionState) -> None:
    assert execution_problems(state) == []


def _buy(**changes: Any) -> ExecutionState:
    state = bought()
    order = state.orders[CID]
    assert isinstance(order, Order)
    return replace(state, orders=MappingProxyType({CID: replace(order, **changes)}))


def _sell(**changes: Any) -> ExecutionState:
    state = closed()
    order = state.orders[CLOSE_ID]
    assert isinstance(order, CloseOrder)
    return replace(
        state, orders=MappingProxyType({**state.orders, CLOSE_ID: replace(order, **changes)})
    )


def _unknown(**quotes: Any) -> ExecutionState:
    return replace(bought(OrderStatus.UNKNOWN), quotes=MappingProxyType(quotes))


BROKEN: dict[str, Any] = {
    "not_a_state": "emirler",
    "orders_not_a_mapping": ExecutionState(("x",), MappingProxyType({})),  # type: ignore[arg-type]
    "quotes_not_a_mapping": ExecutionState(MappingProxyType({}), ("x",)),  # type: ignore[arg-type]
    "not_an_order": hand_built(EMPTY_EXECUTION, orders=MappingProxyType({CID: "emir"})),
    "key_differs": replace(bought(), orders=MappingProxyType({"cb-b": bought().orders[CID]})),
    "bad_buy_id": _buy(client_order_id="zz-a", intent_id="a"),
    "intent_differs": _buy(intent_id="b"),
    "intent_malformed": _buy(client_order_id="cb-a b", intent_id="a b"),
    "buy_side_wrong": _buy(side="sell"),
    "pair_not_text": _buy(pair=1),
    "entry_nan": _buy(entry=Decimal("NaN")),
    "entry_int": _buy(entry=100),
    "stop_zero": _buy(stop=Decimal(0)),
    "stop_too_long": _buy(stop=Decimal("1." + "1" * 28)),
    "target_out_of_scale": _buy(target=Decimal("1E+1000000")),
    "amount_negative": _buy(amount=Decimal("-1")),
    "status_unknown_value": _buy(status="dolu"),
    "filled_without_fill": _buy(fill_price=None),
    "filled_without_fee": _buy(fee=None),
    "fill_too_long": _buy(fill_price=Decimal("1." + "1" * 60)),
    "fee_negative": _buy(fee=Decimal("-1")),
    "rejected_with_fill": _buy(status=OrderStatus.REJECTED),
    "naive_time": _buy(created_at=NOW.replace(tzinfo=None)),
    "time_not_a_time": _buy(created_at="2026"),
    "bad_close_id": _sell(client_order_id="cx-b"),
    "bad_position_id": _sell(position_id="zz"),
    "position_id_malformed": _sell(position_id="cb-a b", client_order_id="cx-a b"),
    "close_side_wrong": _sell(side="buy"),
    "close_reason_wrong": _sell(reason="başka"),
    "close_amount_zero": _sell(amount=Decimal(0)),
    "close_pair_not_text": _sell(pair=None),
    "unknown_without_quote": _unknown(),
    "quote_without_unknown": replace(
        bought(), quotes=MappingProxyType({CID: (Decimal(1), Decimal(1))})
    ),
    "quote_not_a_pair": _unknown(**{CID: "tahmin"}),
    "quote_too_short": _unknown(**{CID: (Decimal(1),)}),
    "quote_bad_fill": _unknown(**{CID: (Decimal(0), Decimal(1))}),
    "quote_bad_fee": _unknown(**{CID: (Decimal(1), Decimal("NaN"))}),
}


@pytest.mark.parametrize("case", list(BROKEN))
def test_broken_state_is_named_without_raw_input(case: str) -> None:
    """Spec 0011 R-6: sorun adlandırılır, ham girdi mesaja girmez."""
    problems = execution_problems(BROKEN[case])

    assert problems
    assert all(len(problem) < 200 for problem in problems)
