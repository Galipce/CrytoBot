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
from crytobot.app._result import PairNote, PairOutcome
from crytobot.app._session import TurnRun
from crytobot.execution import (
    CLIENT_ID_PREFIX,
    PAPER,
    OrderRequest,
    OrderStatus,
    place_order,
)
from crytobot.portfolio import AccountSnapshot, Fill, SnapshotOutcome, account_state, record_fill
from crytobot.risk import HARD_CAPS, AccountState, PairRules, TradeApproval, approve_trade
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
    stop: Decimal,
    target: Decimal,
    account: AccountSnapshot,
) -> PairNote | None:
    """Plan Risk 1, 2, A-1: `risk` girişe göre boyutlar, dolum güncel fiyat ve slippage'la olur.

    Birincisi defterin kalıcı reddini (R-7), ikincisi sabit üst sınırın aşılmasını, üçüncüsü
    sonraki turda kesin zararla kapanan alımı önler. Kayıp formülü `risk._size`'ın kopyasıdır:
    orada değişirse burada da değişir (Known traps).
    """
    fee, slippage = Decimal(run.settings.fee), Decimal(run.settings.slippage)
    try:
        with localcontext(_BOUNDED):
            fill = price * (1 + slippage)
            notional = amount * fill
            commission = notional * fee
            cost = notional + commission
            loss = amount * (fill - stop) + commission + amount * stop * fee
            cap = account.equity * HARD_CAPS.per_trade_risk
    except DecimalException:
        return PairNote.RISK_CAP_AT_FILL
    if cost > account.free_balance:
        return PairNote.FILL_EXCEEDS_BALANCE
    if loss > cap:
        return PairNote.RISK_CAP_AT_FILL
    return PairNote.FILL_OUTSIDE_STOP_TARGET if fill <= stop or fill >= target else None


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
        PAPER,
    )
    placed = place_order(run.state.execution, order_request, run.exchange, run.now)
    order = placed.order
    if not placed.created or order is None:
        run.pairs.append(PairOutcome(pair, placed.outcome, placed.message))
        return
    ledger = run.state.ledger
    if order.status is OrderStatus.FILLED:
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
        ledger = record_fill(ledger, fill).ledger
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
    assert data.price is not None  # checked by the data gate
    assert isinstance(proposal.stop, Decimal) and isinstance(proposal.target, Decimal)  # likewise
    price = Decimal(data.price)
    note = _fill_gate(run, amount, price, proposal.stop, proposal.target, account)
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
