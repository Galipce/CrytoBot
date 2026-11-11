"""Koruyucu yol: bilinmeyen emirlerin sorgusu ve stop/hedef kapanışları (spec 0016 R-2, R-17, R-18).

Dolan emir ve defter kaydı tek kayıtta yazılır. Defter dolu emri reddederse emir yine yazılır:
`save_store` çelişkiyi işaretler, `TurnRun.save` alımı durdurur (R-2, R-7).

Spec 0037 R-3 (D-2): canlıda kapanış satışı kısmen dolabilir; dolan kısım kapanış olarak yazılır,
kalan pozisyon açık kalır ve borsa stopu kalan miktarla yeni nesil kimlikle hemen verilir. Kapanış
ve stop kimliğinin nesli pozisyonun kısmi kapanış sayısıdır (`Ledger.parts`, plan Risk 3).
"""

from decimal import Decimal

from crytobot.app._inputs import PairMarket
from crytobot.app._notices import NoticeKind
from crytobot.app._session import TurnRun, buy_fill
from crytobot.execution import (
    PARTS,
    SELL,
    CloseOrder,
    CloseOrderRequest,
    ExchangeFill,
    FillVerdict,
    Order,
    OrderOutcome,
    OrderStatus,
    judge_fill,
    place_close_order,
    query_order,
    record_stop_fill,
    stop_client_id,
)
from crytobot.portfolio import (
    Close,
    CloseReason,
    Closure,
    Decision,
    Ledger,
    close_position,
    exit_decisions,
    record_fill,
)
from crytobot.risk import CloseRequest, approve_close


def _record_buy(run: TurnRun, order: Order) -> Ledger:
    return record_fill(run.state.ledger, buy_fill(order, run.now)).ledger


def _record_close(run: TurnRun, order: CloseOrder) -> tuple[Ledger, Closure | None]:
    """Dolan kapanış emrinin defter kaydı; canlıda dolan kısım (spec 0037 R-3, D-2), paper ve
    backtest'te tam kapanış (R-7)."""
    close = Close(
        order.client_order_id,
        order.position_id,
        order.position_amount,
        order.fill_price,
        order.fee,
        CloseReason(order.reason),
        run.now,
    )
    if run.state.mode == "live":
        res = close_position(run.state.ledger, close, partial=True)
    else:  # paper and backtest call exactly as before: a full close only (R-7)
        res = close_position(run.state.ledger, close)
    if res.closure is not None:
        run.closures.append(res.closure)
    return res.ledger, res.closure


def _is_partial(closure: Closure | None) -> bool:
    return closure is not None and closure.amount < closure.position.amount


def _step(run: TurnRun, order: Order | CloseOrder) -> Decimal | None:
    """Canlı alımın net miktarı için çiftin miktar adımı (spec 0036 R-2); yoksa `None`."""
    if run.state.mode != "live" or not isinstance(order, Order):
        return None
    rules = run.rules_of(order.pair)
    step = None if rules is None else rules.amount_step
    return step if isinstance(step, Decimal) and step.is_finite() and step > 0 else None


def resolve_unknown(run: TurnRun) -> None:
    """R-17: durumu bilinmeyen emirleri sorar; dolu çıkanı deftere yazar. Spec 0036 R-8: "emir yok"
    gözlemi süreç belleğinde sonraki tura taşınır; R-5: desteklenmeyen dolum bildirilir."""
    missing = run.memory.missing_orders
    for client_order_id in run.state.execution.unknown:
        pending = run.state.execution.orders[client_order_id]
        if run.now < pending.created_at:  # the ledger would refuse the fill for good (plan Risk 3)
            continue
        queried = query_order(
            run.state.execution,
            client_order_id,
            run.exchange,
            run.now,
            step=_step(run, pending),
            missing_seen=client_order_id in missing,
            fee_rate=Decimal(run.settings.fee),  # spec 0037 R-4: an unpriced third asset's fee
        )
        if queried.not_found:
            missing.add(client_order_id)
        else:
            missing.discard(client_order_id)
        if queried.unsupported is not None:
            run.unsupported_fill(client_order_id, pending.pair, queried.unsupported)
        order = queried.order
        if queried.state is run.state.execution or order is None:
            continue
        run.notices.clear(NoticeKind.UNSUPPORTED_FILL, client_order_id)
        ledger = run.state.ledger
        if order.status is OrderStatus.FILLED:
            # a partial close's rest gets its stop from sync_exchange_stops (spec 0037 R-3)
            ledger = (
                _record_buy(run, order)
                if isinstance(order, Order)
                else _record_close(run, order)[0]
            )
        run.save(ledger=ledger, execution=queried.state)
        run.note_fill(order)
        if isinstance(order, Order):
            run.buys.append(order)
        else:
            run.closes.append(order)


def _stop_fill(run: TurnRun, stop_id: str, pair: str, amount: Decimal) -> ExchangeFill:
    """Spec 0036 (plan Risk 3): dolan stopun borsadaki gerçek dolumu; tahmin yedeği yoktur."""
    query_fn = getattr(run.exchange, "query_fill", None)
    if not callable(query_fn):
        return ExchangeFill(FillVerdict.INCOMPLETE, "borsa dolumu sorulamıyor")
    try:
        reply = query_fn(stop_id, symbol=pair)
    except Exception as error:
        run.raise_if_banned(error)
        reason = f"dolum sorgusu başarısız ({type(error).__name__})"
        return ExchangeFill(FillVerdict.INCOMPLETE, reason)
    order = getattr(reply, "order", None)
    if getattr(reply, "missing", False) or order is None:
        return ExchangeFill(FillVerdict.INCOMPLETE, "borsa dolumu bildirmedi")
    trades = getattr(reply, "trades", None)
    price_fn = getattr(run.exchange, "last_price", None)
    return judge_fill(  # spec 0037 R-4; a ban while pricing the fee is not swallowed (Risk 9)
        order,
        trades,
        side=SELL,
        pair=pair,
        amount=amount,
        step=None,
        asset_price=price_fn if callable(price_fn) else None,
        fee_rate=Decimal(run.settings.fee),
    )


def _record_stop_fill(run: TurnRun, subject: str) -> None:
    """Spec 0034 R-6, F-1: dolan borsa stopu defterde kapanış, emir durumunda FILLED `cs-` kapanış
    emri olarak tek kayıtta yazılır; mutabakat çelişki görmez. Spec 0036: borsanın gerçek dolumuyla;
    eksik ya da desteklenmeyen dolum deftere yazılmaz, alım durur."""
    position = run.state.ledger.positions[subject]
    part = run.state.ledger.parts(subject)
    stop_id = stop_client_id(subject, part)
    fill = _stop_fill(run, stop_id, position.pair, position.amount)
    if fill.verdict is not FillVerdict.COMPLETE or fill.price is None or fill.fee is None:
        run.stop_failed(subject, f"dolan borsa stopu deftere yazılamadı ({stop_id}): {fill.reason}")
        return
    price, fee = fill.price, fill.fee
    close = Close(stop_id, subject, position.amount, price, fee, CloseReason.STOP, run.now)
    res = close_position(run.state.ledger, close)
    if res.closure is None:  # never dropped in silence (F-9)
        run.stop_failed(subject, f"dolan borsa stopu deftere yazılamadı ({stop_id}): {res.message}")
        return
    order, execution = record_stop_fill(
        run.state.execution, subject, position.pair, position.amount, fill, run.now, part
    )
    run.closures.append(res.closure)
    run.save(ledger=res.ledger, execution=execution)
    run.closes.append(order)
    run.note_fill(order)


def _stop_missing(run: TurnRun, stop_id: str, pair: str) -> bool:
    """Borsada bu kimlikle emir hiç yok mu (verilmemiş stop). Belirsizse `False`: fail-closed."""
    fetch_fn = getattr(run.exchange, "fetch_order", None)
    if not callable(fetch_fn):
        return False
    try:
        return fetch_fn(stop_id, symbol=pair) is None
    except Exception as error:
        run.raise_if_banned(error)
        return False


def sync_exchange_stops(run: TurnRun) -> None:
    """Spec 0034 R-5, R-6, review round 1 F-1, F-2: her canlı turda her açık pozisyonun borsa
    stopu denetlenir. Dolan stop kapanış olarak yazılır; hiç verilmemiş stop (ör. durumu sonradan
    netleşen alım) yeniden verilir; belirsiz, iptal ya da reddedilmiş stop alımı durdurur."""
    if run.state.mode != "live":
        return
    query_fn = getattr(run.exchange, "query", None)
    if not callable(query_fn):
        return
    for subject, position in list(run.state.ledger.positions.items()):
        part = run.state.ledger.parts(subject)  # spec 0037: the stop of the current generation
        if run.now < position.opened_at:  # the ledger would refuse the close (plan Risk 3)
            run.notices.keep(NoticeKind.STOP_ORDER_FAILED, subject)
            continue
        if part >= PARTS:
            run.stop_failed(subject, f"pozisyon {part} kez kısmen kapandı; elle bakılmalı")
            continue
        stop_id = stop_client_id(subject, part)
        try:
            status = query_fn(stop_id, symbol=position.pair)
        except Exception as error:
            run.raise_if_banned(error)
            run.stop_failed(subject, f"stop sorgusu başarısız ({stop_id}, {type(error).__name__})")
            continue
        if status is OrderStatus.NEW:
            continue
        if status is OrderStatus.FILLED:
            _record_stop_fill(run, subject)
        elif status is OrderStatus.UNKNOWN:
            run.stop_failed(subject, f"stop emri durumu belirsiz ({stop_id})")
        elif _stop_missing(run, stop_id, position.pair):
            run.place_exchange_stop(subject, position.pair, position.amount, position.stop, part)
        else:  # canceled or rejected under this id: the id cannot be reused safely
            run.stop_failed(
                subject, f"pozisyonun borsa stopu yok ({stop_id}, {status.value}); elle bakılmalı"
            )


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
    part = run.state.ledger.parts(subject)
    if part >= PARTS:  # plan 0037 Risk 3: no close id is left; fail-closed
        run.stop_failed(subject, f"pozisyon {part} kez kısmen kapandı; elle bakılmalı")
        run.refuse_close(subject, f"{decision.pair}: {subject}: kapanış kimliği kalmadı")
        return
    if run.state.mode == "live" and not _stop_cancelled(run, subject, decision.pair, part):
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
            part,
        ),
        run.exchange,
        run.now,
    )
    order = placed.order
    if order is None:
        run.refuse_close(subject, placed.message)
        return
    if placed.unsupported is not None:  # spec 0036 R-5: not in the ledger, never retried
        run.unsupported_fill(order.client_order_id, decision.pair, placed.unsupported)
    if placed.outcome is OrderOutcome.ALREADY_EXISTS:
        # REJECTED cannot be retried under the same id (B-17); FILLED and missing from the ledger
        # stays as it is, or a clean turn would lift the flag (R-7, plan Risk 10)
        if order.status is OrderStatus.REJECTED:
            run.refuse_close(subject, placed.message)
        return
    ledger, closure = run.state.ledger, None
    if order.status is OrderStatus.FILLED:
        ledger, closure = _record_close(run, order)
    elif order.status is OrderStatus.REJECTED:
        run.refuse_close(subject, placed.message)
    run.save(ledger=ledger, execution=placed.state)
    run.closes.append(order)
    run.note_fill(order)
    if _is_partial(closure):  # spec 0037 R-3: the rest is protected again at once
        rest = run.state.ledger.positions[subject]
        part = run.state.ledger.parts(subject)
        run.place_exchange_stop(subject, rest.pair, rest.amount, rest.stop, part)


def _stop_cancelled(run: TurnRun, subject: str, pair: str, part: int) -> bool:
    """Spec 0034 R-7, review round 1 F-5: satışa yalnız stopun iptali teyit edilince (ya da borsada
    hiç yoksa) geçilir. Dolmuşsa kapanış stop dolumudur; başka her sonuçta kapanış reddedilir.
    Spec 0037: iptal edilen, pozisyonun bugünkü nesildeki stopudur."""
    stop_id = stop_client_id(subject, part)
    cancel_fn = getattr(run.exchange, "cancel_order", None)
    if not callable(cancel_fn):
        run.stop_failed(subject, f"borsa stop iptali yapılamıyor ({stop_id})")
        run.refuse_close(subject, f"{pair}: {subject}: borsa stop iptali yapılamıyor")
        return False
    try:
        status = cancel_fn(stop_id, symbol=pair)
    except Exception as error:
        run.raise_if_banned(error)
        run.stop_failed(subject, f"stop iptali başarısız ({stop_id}, {type(error).__name__})")
        run.refuse_close(subject, f"{pair}: {subject}: borsa stop iptali başarısız")
        return False
    if status is OrderStatus.CANCELED:
        return True
    if status is OrderStatus.FILLED:
        _record_stop_fill(run, subject)
        return False
    if status is OrderStatus.REJECTED and _stop_missing(run, stop_id, pair):
        return True
    run.stop_failed(subject, f"stop iptali teyit edilmedi ({stop_id}, {status.value})")
    run.refuse_close(subject, f"{pair}: {subject}: borsa stop iptali teyit edilmedi")
    return False


def close_positions(run: TurnRun) -> None:
    """R-1, R-4, R-18: fiyatı taze pozisyonlardan stop ya da hedefe ulaşanlar kapanır."""
    ledger = run.state.ledger
    decided = exit_decisions(ledger, dict(run.report.prices))
    for subject, position in ledger.positions.items():
        if position.pair in decided.missing:  # not evaluated: a refusal still lasts (R-10)
            run.notices.keep(NoticeKind.CLOSE_REFUSED, subject)
    for decision in decided.decisions:
        _close_one(run, decision)
