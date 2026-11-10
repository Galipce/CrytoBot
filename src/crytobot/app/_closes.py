"""Koruyucu yol: bilinmeyen emirlerin sorgusu ve stop/hedef kapanışları (spec 0016 R-2, R-17, R-18).

Dolan emir ve defter kaydı tek kayıtta yazılır. Defter dolu emri reddederse emir yine yazılır:
`save_store` çelişkiyi işaretler, `TurnRun.save` alımı durdurur (R-2, R-7).
"""

from decimal import Decimal

from crytobot.app._inputs import PairMarket
from crytobot.app._notices import NoticeKind
from crytobot.app._result import BuyHalt
from crytobot.app._session import TurnRun, buy_fill
from crytobot.execution import (
    CloseOrder,
    CloseOrderRequest,
    Order,
    OrderOutcome,
    OrderStatus,
    place_close_order,
    query_order,
    stop_client_id,
)
from crytobot.portfolio import (
    Close,
    CloseReason,
    Decision,
    Ledger,
    close_position,
    exit_decisions,
    record_fill,
)
from crytobot.risk import CloseRequest, approve_close


def _record_buy(run: TurnRun, order: Order) -> Ledger:
    return record_fill(run.state.ledger, buy_fill(order, run.now)).ledger


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
    res = close_position(run.state.ledger, close)
    if res.closure is not None:
        run.closures.append(res.closure)
    return res.ledger


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


def sync_exchange_stops(run: TurnRun) -> None:
    """Spec 0034 R-6, AC-5: Canlı modda tur başında borsa stop emirlerini denetler.
    Dolan stopları deftere CloseReason.STOP ile işler; mutabakat öncesi bakiye eşitlenir."""
    if run.state.mode != "live":
        return
    query_fn = getattr(run.exchange, "query", None)
    if not callable(query_fn):
        return
    fetch_fn = getattr(run.exchange, "fetch_order", None)

    for subject, position in list(run.state.ledger.positions.items()):
        stop_id = stop_client_id(subject)
        try:
            status = query_fn(stop_id, symbol=position.pair)
        except Exception as err:
            run.halt(BuyHalt.STOP_ORDER_FAILED)
            run.notices.enter(
                NoticeKind.SAFE_MODE,
                "",
                f"güvenli mod: stop sorgusu başarısız ({stop_id}, {type(err).__name__})",
            )
            continue

        if status is OrderStatus.UNKNOWN:
            run.halt(BuyHalt.STOP_ORDER_FAILED)
            run.notices.enter(
                NoticeKind.SAFE_MODE,
                "",
                f"güvenli mod: stop emri durumu belirsiz ({stop_id})",
            )
        elif status is OrderStatus.FILLED:
            fill_price = position.stop
            fee = None
            if callable(fetch_fn):
                try:
                    raw = fetch_fn(stop_id, symbol=position.pair)
                    if isinstance(raw, dict):
                        avg = raw.get("average") or raw.get("price")
                        if avg is not None:
                            fill_price = Decimal(str(avg))
                        raw_fee = raw.get("fee")
                        if isinstance(raw_fee, dict) and raw_fee.get("cost") is not None:
                            fee = Decimal(str(raw_fee["cost"]))
                except Exception:
                    pass
            if fee is None:
                fee = position.amount * fill_price * run.settings.fee

            close = Close(
                stop_id,
                subject,
                position.amount,
                fill_price,
                fee,
                CloseReason.STOP,
                run.now,
            )
            res = close_position(run.state.ledger, close)
            if res.closure is not None:
                run.closures.append(res.closure)
            run.save(ledger=res.ledger)


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
    if run.state.mode == "live":
        stop_id = stop_client_id(subject)
        cancel_fn = getattr(run.exchange, "cancel_order", None)
        if callable(cancel_fn):
            try:
                cancel_status = cancel_fn(stop_id, symbol=decision.pair)
            except Exception as err:
                run.halt(BuyHalt.STOP_ORDER_FAILED)
                run.notices.enter(
                    NoticeKind.SAFE_MODE,
                    "",
                    f"güvenli mod: stop iptali başarısız ({stop_id}, {type(err).__name__})",
                )
                run.refuse_close(
                    subject, f"{decision.pair}: {subject}: borsa stop iptali başarısız"
                )
                return

            if cancel_status is OrderStatus.UNKNOWN:
                run.halt(BuyHalt.STOP_ORDER_FAILED)
                run.notices.enter(
                    NoticeKind.SAFE_MODE,
                    "",
                    f"güvenli mod: stop emri iptali belirsiz ({stop_id})",
                )
                run.refuse_close(subject, f"{decision.pair}: {subject}: borsa stop iptali belirsiz")
                return

            if cancel_status is OrderStatus.FILLED:
                fill_price = position.stop
                fee = None
                fetch_fn = getattr(run.exchange, "fetch_order", None)
                if callable(fetch_fn):
                    try:
                        raw = fetch_fn(stop_id, symbol=decision.pair)
                        if isinstance(raw, dict):
                            avg = raw.get("average") or raw.get("price")
                            if avg is not None:
                                fill_price = Decimal(str(avg))
                            raw_fee = raw.get("fee")
                            if isinstance(raw_fee, dict) and raw_fee.get("cost") is not None:
                                fee = Decimal(str(raw_fee["cost"]))
                    except Exception:
                        pass
                if fee is None:
                    fee = position.amount * fill_price * run.settings.fee

                close = Close(
                    stop_id,
                    subject,
                    position.amount,
                    fill_price,
                    fee,
                    CloseReason.STOP,
                    run.now,
                )
                res = close_position(run.state.ledger, close)
                if res.closure is not None:
                    run.closures.append(res.closure)
                run.save(ledger=res.ledger)
                return
    placed = place_close_order(
        run.state.execution,
        CloseOrderRequest(
            approval,
            rules,
            decision.price,
            run.settings.fee,
            run.settings.slippage,
            run.state.mode,
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
