"""Defter ↔ emir mutabakatı (spec 0011 R-7): doğrulanmış iki taraf birbiriyle çelişiyor mu."""

from collections.abc import Mapping
from decimal import Decimal

from crytobot.execution import CloseOrder, ExecutionState, Order, OrderStatus
from crytobot.portfolio import Closure, Ledger, Position


def conflicts(ledger: Ledger, execution: ExecutionState) -> tuple[str, ...]:
    """Çelişen kimlikler, bulunma sırasıyla. Karşılaştırma sayısaldır: `1.10` ile `1.1` para farkı
    değildir. Yeni alımı durdurmak `app`'in işidir (spec 0011 Constraints)."""
    # spec 0037 (plan Risk 5): a buy is matched by its recorded position, not by the rest a
    # partial close left open
    bought = ledger.filled_positions()
    closures = ledger.closures
    found: dict[str, None] = {}
    for cid, order in execution.orders.items():
        if order.status is not OrderStatus.FILLED:
            continue
        # spec 0036 D-3, R-10: a live fill is matched by its net amount
        expected = (order.position_amount, order.fill_price, order.fee)
        if _ledger_side(bought, closures, order) != expected:
            found[cid] = None
    for cid in bought:
        if not _filled(execution, cid, Order):
            found[cid] = None
    for cid in closures:
        if not _filled(execution, cid, CloseOrder):
            found[cid] = None
    return tuple(found)


def _ledger_side(
    bought: Mapping[str, Position], closures: Mapping[str, Closure], order: Order | CloseOrder
) -> tuple[Decimal, Decimal, Decimal] | None:
    """Emrin defterdeki karşılığı: miktar, dolum fiyatı, komisyon."""
    if isinstance(order, Order):
        position = bought.get(order.client_order_id)
        return None if position is None else (position.amount, position.cost_price, position.fee)
    closure = closures.get(order.client_order_id)
    return None if closure is None else (closure.amount, closure.price, closure.fee)


def _filled(execution: ExecutionState, cid: str, kind: type[Order | CloseOrder]) -> bool:
    order = execution.orders.get(cid)
    return isinstance(order, kind) and order.status is OrderStatus.FILLED
