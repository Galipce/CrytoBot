"""Spec 0010 AC-8: gerçekçi aralıkta alım → defter → karar → onay → satış → defter dizileri,
spec'ten yazılmış bağımsız bir modelle birebir; her emir dolar, defter her dolumu alır."""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from crytobot.execution import (
    EMPTY_EXECUTION,
    CloseOrderRequest,
    OrderOutcome,
    OrderRequest,
    OrderStatus,
    PaperExchange,
    place_close_order,
    place_order,
)
from crytobot.portfolio import (
    EMPTY_LEDGER,
    Close,
    CloseOutcome,
    CloseReason,
    Fill,
    LedgerOutcome,
    close_position,
    exit_decisions,
    open_ledger,
    record_fill,
)
from crytobot.risk import CloseRequest, PairRules, TradeApproval, TradeIntent, approve_close

OPENED = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
NOW = OPENED + timedelta(hours=1)
EXAMPLES = 300
PAIR = "ADA/USDT"
RULES = PairRules(Decimal("0.00000001"), Decimal(0), Decimal(0))
VENUE = PaperExchange()
LONG = 45  # digits: proceeds this long are what the 60 digit bound is for (R-5)
STOP = Decimal("1E-20")  # below every price: a sale here is always at its target


@dataclass(frozen=True)
class Trade:
    amount: Decimal
    buy_price: Decimal
    sell_price: Decimal
    close_it: bool


def scaled(digits: int, whole: int = 10) -> Any:
    """R-5: `whole` whole digits and `digits` decimals, above zero."""
    top = 10 ** (whole + digits) - 1
    # both ends of the range: the longest values are what the bound is about
    return st.one_of(
        st.integers(1, top), st.integers(top - 10**6, top), st.integers(1, 10**digits)
    ).map(lambda n: Decimal(n).scaleb(-digits))


trades = st.builds(
    Trade, scaled(8), scaled(8), scaled(8), st.sampled_from([True, True, True, False])
)
# the longest proceeds of R-5: a big amount bought for little and sold high, at full digit rates
TOP = 10**18 - 1
long_trades = st.builds(
    Trade,
    st.integers(TOP - 10**6, TOP).map(lambda n: Decimal(n).scaleb(-8)),
    st.just(Decimal("0.00000001")),
    st.integers(TOP - 10**6, TOP).map(lambda n: Decimal(n).scaleb(-8)),
    st.just(True),
)
cases = st.tuples(
    scaled(0, whole=13),
    st.one_of(st.integers(0, 999), st.integers(990, 999)).map(lambda n: Decimal(n).scaleb(-6)),
    st.one_of(st.integers(0, 9999), st.integers(9990, 9999)).map(lambda n: Decimal(n).scaleb(-5)),
    st.lists(st.one_of(trades, long_trades), min_size=1, max_size=5),
)


def run(case: Any) -> list[str]:
    """Runs a sequence on the code and on the model; checks every step; returns the outcomes."""
    opening, slippage, rate, sequence = case
    ledger = open_ledger(EMPTY_LEDGER, opening, OPENED).ledger
    state = EMPTY_EXECUTION
    balance, realized, seen = Fraction(opening), Fraction(0), []
    slip, fee_rate = Fraction(slippage), Fraction(rate)
    for i, trade in enumerate(sequence):
        intent = TradeIntent(PAIR, "buy", trade.buy_price, STOP, trade.sell_price)
        approval = TradeApproval(trade.amount, None, False, "", intent)
        request = OrderRequest(
            f"t{i}", intent, approval, RULES, trade.buy_price, rate, slippage, "paper"
        )
        placed = place_order(state, request, VENUE, NOW)
        order = placed.order
        assert placed.outcome is OrderOutcome.CREATED, placed.message
        assert order is not None and order.status is OrderStatus.FILLED
        assert order.fill_price is not None and order.fee is not None
        state = placed.state
        notional = Fraction(trade.amount) * Fraction(trade.buy_price) * (1 + slip)
        cost = notional * (1 + fee_rate)
        assert (Fraction(order.fill_price), Fraction(order.fee)) == (
            Fraction(trade.buy_price) * (1 + slip),
            notional * fee_rate,
        )
        fill = Fill(
            order.client_order_id, PAIR, "buy", trade.amount, order.fill_price, order.fee, STOP,
            trade.sell_price, NOW,
        )  # fmt: skip
        recorded = record_fill(ledger, fill)
        if cost > balance:
            assert recorded.outcome is LedgerOutcome.INSUFFICIENT_BALANCE, recorded.message
            seen.append("insufficient")
            continue
        assert recorded.outcome is LedgerOutcome.RECORDED, recorded.message
        ledger, balance = recorded.ledger, balance - cost
        seen.append("recorded")
        assert ledger.balance is not None and Fraction(ledger.balance) == balance
        if not trade.close_it:
            continue
        decisions = exit_decisions(ledger, {PAIR: trade.sell_price}).decisions
        decision = next(d for d in decisions if d.client_order_id == order.client_order_id)
        close_request = CloseRequest(
            decision.client_order_id, decision.pair, decision.amount, decision.reason.value
        )
        sale = CloseOrderRequest(
            approve_close(close_request), RULES, decision.price, rate, slippage, "paper"
        )
        sold = place_close_order(state, sale, VENUE, NOW)
        closing = sold.order
        assert sold.outcome is OrderOutcome.CREATED, sold.message
        assert closing is not None and closing.status is OrderStatus.FILLED
        assert closing.fill_price is not None and closing.fee is not None
        state = sold.state
        closed = close_position(
            ledger,
            Close(
                closing.client_order_id, closing.position_id, closing.amount, closing.fill_price,
                closing.fee, CloseReason(closing.reason), NOW,
            ),
        )  # fmt: skip
        assert closed.outcome is CloseOutcome.CLOSED, closed.message
        sale_value = Fraction(trade.amount) * Fraction(trade.sell_price) * (1 - slip)
        proceeds = sale_value * (1 - fee_rate)
        ledger, balance = closed.ledger, balance + proceeds
        realized += proceeds - cost
        seen.append("closed")
        assert ledger.balance is not None
        assert (Fraction(ledger.balance), Fraction(ledger.realized)) == (balance, realized)
        assert closed.closure is not None
        # BR-2's arithmetic stays within the bound (R-2): exact, never over 60 digits
        for value in (ledger.balance, ledger.realized, closed.closure.proceeds):
            assert len(value.as_tuple().digits) <= 60
        if len(closed.closure.proceeds.as_tuple().digits) >= LONG:
            seen.append("long_proceeds")
    return seen


@settings(max_examples=EXAMPLES)
@given(cases)
def test_fills_match_the_model(case: Any) -> None:
    """AC-8 (R-2…R-5, BR-2): gerçekçi aralıkta her emir dolar, defter her dolumu alır (bakiye
    yetiyorsa); bakiye ve gerçekleşen toplam modelle birebir, 60 basamak aşılmaz."""
    run(case)


def test_fill_outcomes_are_not_vacuous() -> None:
    """AC-8: üreteç alımı, kapanışı, yetersiz bakiyeyi ve uzun satış gelirini yeterince üretir."""
    record: Counter[str] = Counter()

    @settings(max_examples=EXAMPLES)
    @given(cases)
    def collect(case: Any) -> None:
        record.update(run(case))

    collect()

    wanted = ("recorded", "closed", "insufficient", "long_proceeds")
    assert {o: record[o] for o in wanted if record[o] < 20} == {}, record
