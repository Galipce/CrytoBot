"""Alım yolu: `strategy` → `risk` → dolum kapıları → `execution` → defter (spec 0016 R-2, R-3).

Her alımdan sonra kasa aynı anla yeniden gözlenir: onay, son gözlemin kasasını ister (plan Risk 4).
"""

import hashlib
from datetime import UTC, datetime
from decimal import (
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    localcontext,
)

from crytobot.app._inputs import PairMarket
from crytobot.app._notices import NoticeKind
from crytobot.app._result import BuyHalt, PairNote, PairOutcome
from crytobot.app._session import TurnRun, buy_fill
from crytobot.execution import (
    CLIENT_ID_PREFIX,
    OrderRequest,
    OrderStatus,
    place_order,
    stop_client_id,
)
from crytobot.portfolio import AccountSnapshot, SnapshotOutcome, account_state, record_fill
from crytobot.risk import (
    HARD_CAPS,
    AccountState,
    PairRules,
    TradeApproval,
    approve_trade,
    edge_clears,
)
from crytobot.strategy import NoProposal, propose

_INTENT_ID_LENGTH = 32
# as `execution` and `portfolio` calculate: a result past 60 digits raises (Known traps)
_BOUNDED = Context(prec=60, traps=[DivisionByZero, Inexact, InvalidOperation, Overflow])


def intent_id(pair: str, open_time: datetime) -> str:
    """R-3: çift ve son mumun açılışından türer; aynı an, başka zaman diliminde de aynı kimlik."""
    moment = open_time.astimezone(UTC).isoformat()
    return hashlib.sha256(f"{pair}|{moment}".encode()).hexdigest()[:_INTENT_ID_LENGTH]


def _fill_gate(
    run: TurnRun,
    amount: Decimal,
    price: Decimal,
    spread: Decimal,
    stop: Decimal,
    target: Decimal,
    account: AccountSnapshot,
) -> PairNote | None:
    """Plan Risk 1, 2, A-1; spec 0020 R-2…R-9: `risk` slippage'lı girişe göre boyutlar, dolum
    güncel fiyat ve slippage'la olur.

    Sıra (spec 0020 R-5): bakiye defterin kalıcı reddini (R-7), sabit üst sınır BR-4'ün
    aşılmasını, stop/hedef sonraki turda kesin zararla kapanan alımı önler — kapanış güncel
    fiyatla karşılaştırır, stop tarafı bu yüzden dolumla değil fiyatla denetlenir (A-3); config
    limiti dolumdaki riski, BR-8 katı güncel fiyattaki kârı denetler. Kapı yalnız emrin oluşup
    oluşmayacağına karar verir, miktarı değiştirmez (R-6). Kayıp formülü `risk._size`'ın
    kopyasıdır, giriş yerine güncel fiyatla: orada değişirse burada da değişir (Known traps).
    BR-8 formülü `risk`'indir (`edge_clears`).
    """
    fee, slippage = Decimal(run.settings.fee), Decimal(run.settings.slippage)
    limits = run.settings.limits
    try:
        with localcontext(_BOUNDED):
            fill = price * (1 + slippage)
            slipped_stop = stop * (1 - slippage)
            notional = amount * fill
            commission = notional * fee
            cost = notional + commission
            loss = amount * (fill - slipped_stop) + commission + amount * slipped_stop * fee
            cap = account.equity * HARD_CAPS.per_trade_risk
            limit = account.equity * limits.per_trade_risk
    except DecimalException:  # R-9: a risk that does not fit is named as the cap
        return PairNote.RISK_CAP_AT_FILL
    if cost > account.free_balance:
        return PairNote.FILL_EXCEEDS_BALANCE
    if loss > cap:
        return PairNote.RISK_CAP_AT_FILL
    if price <= stop or fill >= target:
        return PairNote.FILL_OUTSIDE_STOP_TARGET
    if loss > limit:
        return PairNote.RISK_LIMIT_AT_FILL
    if not edge_clears(price, target, fee, spread, slippage, limits.profit_cost_multiple):
        return PairNote.INSUFFICIENT_EDGE_AT_FILL
    return None


def _note(run: TurnRun, pair: str, note: PairNote, message: str) -> None:
    run.pairs.append(PairOutcome(pair, note, f"{pair}: {message}"))


def _approved_buy(
    run: TurnRun, pair: str, data: PairMarket, approval: TradeApproval, identity: str
) -> None:
    order_request = OrderRequest(
        identity,
        approval.intent,
        approval,
        data.rules,
        data.price,
        run.settings.fee,
        run.settings.slippage,
        run.state.mode,
    )
    placed = place_order(run.state.execution, order_request, run.exchange, run.now)
    order = placed.order
    if not placed.created or order is None:
        run.pairs.append(PairOutcome(pair, placed.outcome, placed.message))
        return
    ledger = run.state.ledger
    if order.status is OrderStatus.FILLED:
        ledger = record_fill(ledger, buy_fill(order, run.now)).ledger
        if run.state.mode == "live":
            stop_id = stop_client_id(order.client_order_id)
            limit_price = order.stop * (1 - run.settings.slippage)
            place_stop = getattr(run.exchange, "place_stop_order", None)
            if callable(place_stop):
                stop_status = place_stop(
                    client_order_id=stop_id,
                    symbol=pair,
                    amount=order.amount,
                    stop_price=order.stop,
                    limit_price=limit_price,
                )
                if stop_status not in (OrderStatus.NEW, OrderStatus.FILLED):
                    run.halt(BuyHalt.STOP_ORDER_FAILED)
                    run.notices.enter(
                        NoticeKind.SAFE_MODE,
                        "",
                        f"güvenli mod: borsa stop emri başarısız ({stop_id})",
                    )
            else:
                run.halt(BuyHalt.STOP_ORDER_FAILED)
                run.notices.enter(
                    NoticeKind.SAFE_MODE,
                    "",
                    f"güvenli mod: borsa stop adaptörü bulunamadı ({stop_id})",
                )
    run.save(ledger=ledger, execution=placed.state)
    run.buys.append(order)
    if not run.buying_stopped:
        run.observe_equity()


def _buy_pair(run: TurnRun, pair: str) -> None:
    data = run.market[pair]
    assert isinstance(data, PairMarket)  # checked by the data gate, or buying has stopped
    assert data.candles is not None and data.tick is not None  # likewise
    ledger = run.state.ledger
    proposal = propose(
        pair=pair,
        candles=data.candles,
        position_open=any(position.pair == pair for position in ledger.positions.values()),
        tick=data.tick,
        settings=run.settings.strategy,
    )
    if isinstance(proposal, NoProposal):
        run.pairs.append(PairOutcome(pair, proposal.reason, f"{pair}: {proposal.reason.value}"))
        return
    identity = intent_id(pair, data.candles[-1].open_time)
    if CLIENT_ID_PREFIX + identity in run.state.execution.orders:
        _note(run, pair, PairNote.ALREADY_ORDERED, "bu mumdan emir zaten oluştu")
        return
    snapshot = account_state(ledger, dict(run.report.prices))
    account = snapshot.snapshot
    if snapshot.outcome is not SnapshotOutcome.READY or account is None:
        run.observe_equity()  # names why the equity cannot be calculated and stops buying
        return
    assert isinstance(data.rules, PairRules)  # checked by the data gate
    approval = approve_trade(
        proposal,
        run.settings.limits,
        AccountState(account.equity, account.free_balance, account.open_positions),
        data.rules,
        frozenset(run.settings.whitelist),
        run.settings.fee,
        data.spread,
        run.settings.slippage,
        run.state.risk,
        run.now,
    )
    amount = approval.amount
    if not approval.approved or amount is None:
        assert approval.reason is not None  # a refusal names its reason
        run.pairs.append(PairOutcome(pair, approval.reason, approval.message))
        return
    assert data.price is not None and data.spread is not None  # checked by the data gate
    assert isinstance(proposal.stop, Decimal) and isinstance(proposal.target, Decimal)  # likewise
    price, spread = Decimal(data.price), Decimal(data.spread)
    note = _fill_gate(run, amount, price, spread, proposal.stop, proposal.target, account)
    if note is not None:
        _note(run, pair, note, "dolum fiyatıyla emir oluşmaz")
        return
    _approved_buy(run, pair, data, approval, identity)


def buy_pairs(run: TurnRun) -> None:
    """R-1, R-2: beyaz liste sırasıyla; her onay önceki adımların bakiyesini görür."""
    for pair in run.settings.whitelist:
        if run.buying_stopped:
            return
        _buy_pair(run, pair)
