"""Testlerin durumu: gerçek motorlarla alım → defter → gözlem → kapanış → defter zinciri.

Depoya yazılan her durum `place_order`, `record_fill`, `close_position`, `observe` gibi gerçek
fonksiyonlardan gelir; elle kurulan yalnız çelişki ya da yasak yazım için bozulan alanlardır.
Onaylar sabit miktarlı: risk boyutlaması burada sınanmıyor, `execution` onayın biçimine bakar.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

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
    place_close_order,
    place_order,
)
from crytobot.persistence import (
    StoredState,
    StoreOutcome,
    StoreResult,
    create_store,
    load_store,
    save_store,
)
from crytobot.portfolio import (
    EMPTY_LEDGER,
    Close,
    CloseOutcome,
    CloseReason,
    Fill,
    Ledger,
    LedgerOutcome,
    close_position,
    open_ledger,
    record_fill,
)
from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    CloseRequest,
    PairRules,
    RiskState,
    TradeApproval,
    TradeIntent,
    approve_close,
    observe,
)

ISTANBUL = timezone(timedelta(hours=3))
T0 = datetime(2026, 11, 3, 9, 0, tzinfo=ISTANBUL)
T1 = T0 + timedelta(minutes=1)
T2 = T0 + timedelta(minutes=2)
PAIR = "BTC/USDT"
RULES = PairRules(Decimal("0.00000001"), Decimal(0), Decimal(0))
FEE, SLIPPAGE = Decimal("0.001"), Decimal("0.001")
DEPOSIT = Decimal("100000.10")


@dataclass(frozen=True)
class World:
    """Kalıcı durumun üç parçası."""

    ledger: Ledger
    execution: ExecutionState
    risk: RiskState


EMPTY_WORLD = World(EMPTY_LEDGER, EMPTY_EXECUTION, EMPTY_STATE)


def opened(deposit: Decimal = DEPOSIT, at: datetime = T0) -> World:
    return replace(EMPTY_WORLD, ledger=open_ledger(EMPTY_LEDGER, deposit, at).ledger)


def placed(
    world: World,
    intent_id: str = "a",
    amount: str = "2.50",
    price: str = "100.10",
    at: datetime = T1,
    status: OrderStatus = OrderStatus.FILLED,
) -> World:
    """Yalnız emir: defter henüz bilmiyor."""
    entry = Decimal(price)
    intent = TradeIntent(PAIR, "buy", entry, entry / 2, entry * 2)
    approval = TradeApproval(Decimal(amount), None, False, "onay", intent)
    request = OrderRequest(intent_id, intent, approval, RULES, entry, FEE, SLIPPAGE, "paper")
    exchange = PaperExchange(placements=MappingProxyType({f"cb-{intent_id}": status}))
    result = place_order(world.execution, request, exchange, at)
    assert result.outcome is OrderOutcome.CREATED, result.message
    return replace(world, execution=result.state)


def recorded(world: World, client_order_id: str) -> World:
    """Dolan alım emri deftere yazılır."""
    order = world.execution.orders[client_order_id]
    assert isinstance(order, Order)
    fill = Fill(
        client_order_id,
        order.pair,
        order.side,
        order.amount,
        order.fill_price,
        order.fee,
        order.stop,
        order.target,
        order.created_at,
    )
    result = record_fill(world.ledger, fill)
    assert result.outcome is LedgerOutcome.RECORDED, result.message
    return replace(world, ledger=result.ledger)


def bought(world: World, intent_id: str = "a", **order: Any) -> World:
    return recorded(placed(world, intent_id, **order), f"cb-{intent_id}")


def sell_placed(
    world: World,
    position_id: str = "cb-a",
    price: str = "110.50",
    at: datetime = T2,
    status: OrderStatus = OrderStatus.FILLED,
) -> World:
    position = world.ledger.positions[position_id]
    close = CloseRequest(position_id, position.pair, position.amount, "hedef")
    close_id = "cx-" + position_id.removeprefix("cb-")
    request = CloseOrderRequest(approve_close(close), RULES, Decimal(price), FEE, SLIPPAGE, "paper")
    exchange = PaperExchange(placements=MappingProxyType({close_id: status}))
    result = place_close_order(world.execution, request, exchange, at)
    assert result.outcome is OrderOutcome.CREATED, result.message
    return replace(world, execution=result.state)


def sell_recorded(world: World, close_id: str) -> World:
    order = world.execution.orders[close_id]
    assert isinstance(order, CloseOrder)
    close = Close(
        close_id,
        order.position_id,
        order.amount,
        order.fill_price,
        order.fee,
        CloseReason(order.reason),
        order.created_at,
    )
    result = close_position(world.ledger, close)
    assert result.outcome is CloseOutcome.CLOSED, result.message
    return replace(world, ledger=result.ledger)


def sold(world: World, position_id: str = "cb-a", **order: Any) -> World:
    close_id = "cx-" + position_id.removeprefix("cb-")
    return sell_recorded(sell_placed(world, position_id, **order), close_id)


def seen(world: World, equity: str, at: datetime = T1) -> World:
    update = observe(world.risk, at, Decimal(equity), DEFAULT_LIMITS)
    assert update.accepted, update.message
    return replace(world, risk=update.state)


def full_world() -> World:
    """Açılış, kapanmış alım, açık alım, durumu bilinmeyen emir ve gözlem: her kayıt türü."""
    world = sold(bought(opened()))
    world = bought(world, "b", amount="1.10", price="50.5")
    world = placed(world, "c", amount="0.5", status=OrderStatus.UNKNOWN)
    return seen(world, "100000.10")


def snapshot(state: World | StoredState) -> str:
    """Birebir karşılaştırma: `repr` sondaki sıfırları, UTC farkını ve sıraları da taşır."""
    return repr(
        (
            state.ledger.entries,
            state.ledger.balance,
            state.ledger.realized,
            list(state.ledger.positions.items()),
            list(state.ledger.closures.items()),
            list(state.execution.orders.items()),
            list(state.execution.quotes.items()),
            state.risk,
        )
    )


def created(path: Path, mode: str = "paper") -> StoredState:
    result = create_store(path, mode)
    assert result.outcome is StoreOutcome.CREATED, result.message
    assert result.state is not None
    return result.state


def save(path: Path, base: StoredState, world: World) -> StoreResult:
    return save_store(path, base, world.ledger, world.execution, world.risk)


def saved(path: Path, base: StoredState, world: World) -> StoredState:
    result = save(path, base, world)
    assert result.outcome is StoreOutcome.SAVED, result.message
    assert result.state is not None
    return result.state


def stored(path: Path, world: World, mode: str = "paper") -> StoredState:
    """Yeni depo ve içinde `world`."""
    return saved(path, created(path, mode), world)


def loaded(path: Path, mode: str = "paper") -> StoredState:
    result = load_store(path, mode)
    assert result.outcome is StoreOutcome.LOADED, result.message
    assert result.state is not None
    return result.state
