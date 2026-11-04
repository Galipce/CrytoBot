"""Koruyucu yol: bilinmeyen emirlerin sorgusu ve stop/hedef kapanışları (spec 0016 R-2, R-17, R-18).

Dolan emir ve defter kaydı tek kayıtta yazılır. Defter dolu emri reddederse emir yine yazılır:
`save_store` çelişkiyi işaretler, `TurnRun.save` alımı durdurur (R-2, R-7).
"""

from crytobot.app._inputs import PairMarket
from crytobot.app._notices import NoticeKind
from crytobot.app._session import TurnRun
from crytobot.execution import (
    PAPER,
    CloseOrder,
    CloseOrderRequest,
    Order,
    OrderOutcome,
    OrderStatus,
    place_close_order,
    query_order,
)
from crytobot.portfolio import (
    Close,
    CloseReason,
    Decision,
    Fill,
    Ledger,
    close_position,
    exit_decisions,
    record_fill,
)
from crytobot.risk import CloseRequest, approve_close


def _record_buy(run: TurnRun, order: Order) -> Ledger:
    fill = Fill(
        order.client_order_id,
        order.pair,
        order.side,
        order.amount,
        order.fill_price,
        order.fee,
        order.stop,
        order.target,
        run.now,
    )
    return record_fill(run.state.ledger, fill).ledger


def _record_close(run: TurnRun, order: CloseOrder) -> Ledger:
    close = Close(
        order.client_order_id,
        order.position_id,
        order.amount,
        order.fill_price,
        order.fee,
        CloseReason(order.reason),
        run.now,
    )
    return close_position(run.state.ledger, close).ledger


def resolve_unknown(run: TurnRun) -> None:
    """R-17: durumu bilinmeyen emirleri sorar; dolu çıkanı deftere yazar."""
    for client_order_id in run.state.execution.unknown:
        pending = run.state.execution.orders[client_order_id]
        if run.now < pending.created_at:  # the ledger would refuse the fill for good (plan Risk 3)
            continue
        queried = query_order(run.state.execution, client_order_id, run.exchange, run.now)
        order = queried.order
        if queried.state is run.state.execution or order is None:
            continue
        ledger = run.state.ledger
        if order.status is OrderStatus.FILLED:
            ledger = (
                _record_buy(run, order) if isinstance(order, Order) else _record_close(run, order)
            )
        run.save(ledger=ledger, execution=queried.state)
        if isinstance(order, Order):
            run.buys.append(order)
        else:
            run.closes.append(order)


def _close_one(run: TurnRun, decision: Decision) -> None:
    subject = decision.client_order_id
    position = run.state.ledger.positions[subject]
    if run.now < position.opened_at:  # the ledger would refuse the fill for good (plan Risk 3)
        run.refuse_close(subject, f"{decision.pair}: {subject}: zaman pozisyonun açılışından eski")
        return
    data = run.market.get(decision.pair)
    rules = data.rules if isinstance(data, PairMarket) else None
    if rules is None:
        run.refuse_close(subject, f"{decision.pair}: {subject}: borsa kuralı eksik")
        return
    approval = approve_close(
        CloseRequest(subject, decision.pair, decision.amount, decision.reason.value)
    )
    if not approval.approved:
        run.refuse_close(subject, approval.message)
        return
    placed = place_close_order(
        run.state.execution,
        CloseOrderRequest(
            approval,
            rules,
            decision.price,
            run.settings.fee,
            run.settings.slippage,
            PAPER,
        ),
        run.exchange,
        run.now,
    )
    order = placed.order
    if order is None:
        run.refuse_close(subject, placed.message)
        return
    if placed.outcome is OrderOutcome.ALREADY_EXISTS:
        # REJECTED cannot be retried under the same id (B-17); FILLED and missing from the ledger
        # stays as it is, or a clean turn would lift the flag (R-7, plan Risk 10)
        if order.status is OrderStatus.REJECTED:
            run.refuse_close(subject, placed.message)
        return
    ledger = run.state.ledger
    if order.status is OrderStatus.FILLED:
        ledger = _record_close(run, order)
    elif order.status is OrderStatus.REJECTED:
        run.refuse_close(subject, placed.message)
    run.save(ledger=ledger, execution=placed.state)
    run.closes.append(order)


def close_positions(run: TurnRun) -> None:
    """R-1, R-4, R-18: fiyatı taze pozisyonlardan stop ya da hedefe ulaşanlar kapanır."""
    ledger = run.state.ledger
    decided = exit_decisions(ledger, dict(run.report.prices))
    for subject, position in ledger.positions.items():
        if position.pair in decided.missing:  # not evaluated: a refusal still lasts (R-10)
            run.notices.keep(NoticeKind.CLOSE_REFUSED, subject)
    for decision in decided.decisions:
        _close_one(run, decision)
