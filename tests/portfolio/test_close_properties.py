"""Spec 0008 AC-12: rastgele açılış, alım, karar ve kapanış dizileri, spec'ten yazılmış bağımsız bir
modelle birebir; hiçbir girdi istisna fırlatmaz (BR-2, R-1…R-14)."""

from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from crytobot.portfolio import (
    EMPTY_LEDGER,
    Close,
    CloseOutcome,
    CloseReason,
    DecisionOutcome,
    Fill,
    Ledger,
    LedgerOutcome,
    close_position,
    exit_decisions,
    open_ledger,
    record_fill,
)

OPENED = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
NOW = OPENED + timedelta(hours=1)
LATER = NOW + timedelta(hours=1)
STOP, TARGET = Decimal("95"), Decimal("110")
EXAMPLES = 300
AMOUNT = Decimal("19.249")


@dataclass(frozen=True)
class Buy:
    client_order_id: str
    pair: str
    side: str
    fee: Decimal


@dataclass(frozen=True)
class Sell:
    client_order_id: str
    position_id: str
    amount: Decimal
    price: Decimal
    fee: Decimal
    reason: Any  # a `CloseReason` or text, an invalid input
    early: bool  # before the position's opening


@dataclass(frozen=True)
class Decide:
    prices: dict[str, Decimal]


# 19.249 @ 100.1 + 1.9268249 = 1928.7517249: a 10000 opening pays for five such buys, a 4000 one
# for two, a 2000 one for one; fee 1 changes the content of a known buy (a conflict)
buys = st.builds(
    Buy,
    st.sampled_from(["a", "b", "c"] * 2 + ["d", "x", "y", "a b"]),
    st.sampled_from(["BTC/USDT"] * 3 + ["ETH/USDT"]),
    st.sampled_from(["buy"] * 5 + ["sell"] * 2),
    st.sampled_from([Decimal("1.9268249")] * 5 + [Decimal(1), Decimal(-1)]),
)
# "a" is a buy id: a close with it conflicts; "z" is never bought; "x y" breaks the id format
sells = st.builds(
    Sell,
    st.sampled_from(["x", "y", "w"] * 3 + ["a", "x y"]),
    st.sampled_from(["a", "b", "c", "a", "b", "c", "z"]),
    st.sampled_from([AMOUNT] * 9 + [Decimal(1)]),
    st.sampled_from([Decimal("109.945"), Decimal("93.953"), Decimal("100")]),
    st.sampled_from([Decimal("2.116331305")] * 8 + [Decimal(0), Decimal(5000)]),
    st.sampled_from([CloseReason.TARGET, CloseReason.STOP] * 5 + ["hedef"]),
    st.sampled_from([False] * 9 + [True]),
)
decides = st.builds(
    Decide,
    st.sampled_from(
        [
            {"BTC/USDT": Decimal("94"), "ETH/USDT": Decimal("111")},
            {"BTC/USDT": Decimal("100"), "ETH/USDT": Decimal("100")},
            {"BTC/USDT": Decimal("110"), "ETH/USDT": Decimal("95")},
            {"BTC/USDT": Decimal("94")},
            {"BTC/USDT": Decimal(0), "ETH/USDT": Decimal("111")},
            {},
        ]
    ),
)
# most sequences start opened (a few never open); buys "a" and "b" come first, so sales find their
# positions; sales are sent again at the end: the same id reaches "already recorded", a new id
# "v" on the same position "position closed"; the first buys too, open or closed by then
starts = st.sampled_from(
    [[Decimal("10000")]] * 3 + [[Decimal("4000")]] * 2 + [[Decimal("2000")]] * 2 + [[]] * 3
)
FIRST = [Buy("a", "BTC/USDT", "buy", Decimal("1.9268249")), Buy("b", "ETH/USDT", "buy", Decimal(0))]


def again(actions: list[Any]) -> list[Any]:
    sales = [a for a in actions if isinstance(a, Sell)]
    return sales[:3] + [replace(a, client_order_id="v") for a in sales[:2]] + FIRST


cases = st.builds(
    lambda start, rest: start + FIRST + rest + again(rest),
    starts,
    st.lists(
        st.one_of(buys, buys, buys, sells, sells, sells, decides, st.just(Decimal("10000"))),
        max_size=24,
    ),
)


@dataclass
class Model:
    """Spec 0008 R-1…R-14 (ve spec 0007'nin alımı), `Fraction` ile, koddan değil spec'ten."""

    balance: Fraction | None = None
    deposit: Fraction = Fraction(0)
    open: dict[str, dict[str, Any]] = field(default_factory=dict)
    shut: dict[str, dict[str, Any]] = field(default_factory=dict)  # bought id → position
    closes: dict[str, dict[str, Any]] = field(default_factory=dict)  # close id → closure
    realized: list[Fraction] = field(default_factory=list)

    def opening(self, amount: Decimal) -> str:
        if self.balance is not None:
            return "buy_already_open"
        self.balance = self.deposit = Fraction(amount)
        return "buy_opened"

    def buy(self, action: Buy) -> str:
        if action.client_order_id == "a b" or action.fee < 0:
            return "buy_invalid_input"
        if self.balance is None:
            return "buy_not_opened"
        if action.client_order_id in self.closes:
            return "buy_record_conflict"
        content = (action.pair, action.side, action.fee)
        known = self.open.get(action.client_order_id) or self.shut.get(action.client_order_id)
        if known is not None:
            same = known["content"] == content
            return "buy_already_recorded" if same else "buy_record_conflict"
        if action.side != "buy":
            return "buy_unsupported_side"
        cost = Fraction(AMOUNT) * Fraction("100.1") + Fraction(action.fee)
        if cost > self.balance:
            return "buy_insufficient_balance"
        self.balance -= cost
        self.open[action.client_order_id] = {"content": content, "pair": action.pair, "cost": cost}
        return "buy_recorded"

    def sell(self, action: Sell) -> str:
        if action.client_order_id == "x y" or not isinstance(action.reason, CloseReason):
            return "close_invalid_input"
        proceeds = Fraction(action.amount) * Fraction(action.price) - Fraction(action.fee)
        if proceeds < 0:
            return "close_invalid_input"
        if self.balance is None:
            return "close_not_opened"
        content = (action.position_id, action.amount, action.price, action.fee, action.reason)
        closure = self.closes.get(action.client_order_id)
        if closure is not None:
            same = closure["content"] == content
            return "close_already_recorded" if same else "close_record_conflict"
        if action.client_order_id in self.open or action.client_order_id in self.shut:
            return "close_record_conflict"
        position = self.open.get(action.position_id)
        if position is None:
            closed = action.position_id in self.shut
            return "close_position_closed" if closed else "close_position_not_found"
        if action.amount != AMOUNT or action.early:
            return "close_invalid_input"
        self.balance += proceeds
        self.realized.append(proceeds - position["cost"])
        self.shut[action.position_id] = self.open.pop(action.position_id)
        self.closes[action.client_order_id] = {"content": content}
        return "close_closed"

    def decide(self, action: Decide) -> tuple[str, list[tuple[Any, ...]], list[str]]:
        """Kararlar (kimlik, çift, miktar, neden, fiyat) ve eksik çiftler, ilk görülme sırasıyla."""
        if self.balance is None:
            return "decide_not_opened", [], []
        decisions: list[tuple[Any, ...]] = []
        missing: list[str] = []
        for client_order_id, position in self.open.items():
            pair = position["pair"]
            price = action.prices.get(pair, Decimal(0))
            if price <= 0:
                missing += [] if pair in missing else [pair]
                continue
            reason = (
                CloseReason.STOP
                if price <= STOP
                else CloseReason.TARGET
                if price >= TARGET
                else None
            )
            if reason is not None:
                decisions.append((client_order_id, pair, AMOUNT, reason, price))
        outcome = "decide_missing_price" if missing else "decide_ready"
        return outcome, decisions, missing


def run(actions: list[Any]) -> list[str]:
    """Runs the actions on the code and on the model; checks every step; returns the outcomes."""
    model, ledger, seen = Model(), EMPTY_LEDGER, []
    for action in actions:
        result: Any
        if isinstance(action, Decide):
            result = exit_decisions(ledger, action.prices)
            expected, decisions, missing = model.decide(action)
            assert "decide_" + result.outcome.value == expected, result.message
            assert [
                (d.client_order_id, d.pair, d.amount, d.reason, d.price) for d in result.decisions
            ] == decisions
            assert list(result.missing) == missing
            seen.append(expected)
            continue
        if isinstance(action, Decimal):
            result = open_ledger(ledger, action, OPENED)
            expected = model.opening(action)
            outcome = "buy_" + result.outcome.value
        elif isinstance(action, Buy):
            fill = Fill(
                action.client_order_id, action.pair, action.side, AMOUNT, Decimal("100.1"),
                action.fee, STOP, TARGET, NOW,
            )  # fmt: skip
            result = record_fill(ledger, fill)
            expected = model.buy(action)
            outcome = "buy_" + result.outcome.value
        else:
            close = Close(
                action.client_order_id, action.position_id, action.amount, action.price,
                action.fee, action.reason, NOW - timedelta(seconds=1) if action.early else LATER,
            )  # fmt: skip
            result = close_position(ledger, close)
            expected = model.sell(action)
            outcome = "close_" + result.outcome.value
        assert outcome == expected, (action, result.message)
        if not result.accepted:
            assert result.ledger is ledger
        ledger = result.ledger
        check_ledger(ledger, model)
        seen.append(expected)
    return seen


def check_ledger(ledger: Ledger, model: Model) -> None:
    if model.balance is None:
        assert ledger.balance is None and ledger.entries == ()
        return
    assert ledger.balance is not None and ledger.balance >= 0  # BR-2: never negative
    assert Fraction(ledger.balance) == model.balance
    assert list(ledger.positions) == list(model.open)
    assert list(ledger.closures) == list(model.closes)
    assert Fraction(ledger.realized) == sum(model.realized, Fraction(0))
    assert [Fraction(c.realized) for c in ledger.closures.values()] == model.realized
    # R-6: opening - the open buys' cost + the realized profit and loss = USDT
    open_cost = sum((p["cost"] for p in model.open.values()), Fraction(0))
    assert model.deposit - open_cost + sum(model.realized, Fraction(0)) == model.balance


@settings(max_examples=EXAMPLES)
@given(cases)
def test_closures_match_the_model(actions: Any) -> None:
    """AC-12 (R-1…R-13): bakiye negatife düşmez, açılış - Σ açık alış maliyeti + Σ K/Z'ye
    eşittir; açık ve kapanmış pozisyonlar, K/Z ve kararlar modelle aynıdır; reddedilen istek
    defteri bırakır."""
    run(actions)


JUNK: list[Any] = [
    None, True, 0.5, "1", "stop", "hedef", "a", CloseReason.STOP, Decimal("NaN"),
    Decimal("-Infinity"), Decimal(0), Decimal(-1), Decimal("0.001"), Decimal("19.249"),
    Decimal("1E+1000000"), Decimal("1E-999999"), Decimal("1." + "2" * 28), 10**4300, -(10**4300),
    Fraction(10**4300), (10**4300,), [1], {"BTC/USDT": 10**4300},
    {"BTC/USDT": Decimal("1E-999999")}, LATER, datetime(2026, 11, 2),
]  # fmt: skip
junk = st.sampled_from(JUNK)
# each field is mostly valid, so whole requests reach the record, scale and acceptance paths too
# (plan 0008 A-2); a 28-digit price is in scale but its sale does not fit in 28 digits
VALID: list[list[Any]] = [
    ["x"], ["a"], [AMOUNT], [Decimal("109.945"), Decimal("109.9450000000000000000000001")],
    [Decimal("2.116331305"), Decimal("1E-70")], [CloseReason.TARGET], [LATER],
]  # fmt: skip
# about four valid values to one junk value per field
close_fields = st.tuples(*[st.sampled_from(v * (4 * len(JUNK) // len(v)) + JUNK) for v in VALID])


def no_raise(fields: tuple[Any, ...], prices: Any) -> str:
    """Closes and decides on one opened position; checks no exception and a coherent result."""
    ledger = record_fill(
        open_ledger(EMPTY_LEDGER, Decimal("10000"), OPENED).ledger,
        Fill("a", "BTC/USDT", "buy", AMOUNT, Decimal("100.1"), Decimal(0), STOP, TARGET, NOW),
    ).ledger

    closed = close_position(ledger, Close(*fields))
    decided = exit_decisions(ledger, prices)

    assert isinstance(closed.outcome, CloseOutcome)
    assert isinstance(decided.outcome, DecisionOutcome)
    assert (closed.closure is not None) is (
        closed.outcome in (CloseOutcome.CLOSED, CloseOutcome.ALREADY_RECORDED)
    )
    unrepresentable = "ölçek hesaplanamıyor" in closed.message
    return "unrepresentable" if unrepresentable else closed.outcome.value


@settings(max_examples=EXAMPLES)
@given(close_fields, junk)
def test_no_close_input_raises(fields: tuple[Any, ...], prices: Any) -> None:
    """AC-12 (R-14): rastgele ve aralık dışı girdilerle kapanış ve karar istisna değil, sonuç."""
    no_raise(fields, prices)


def test_close_outcomes_are_not_vacuous() -> None:
    """AC-12: üreteçler her sonucu yeterince üretir; "istisna yok" üreteci kabule ve ölçek adımına
    ulaşır (plan 0008 A-2)."""
    record: Counter[str] = Counter()

    @settings(max_examples=EXAMPLES)
    @given(cases)
    def collect(actions: Any) -> None:
        record.update(run(actions))

    collect()

    outcomes = (
        [f"buy_{o.value}" for o in LedgerOutcome]
        + [f"close_{o.value}" for o in CloseOutcome]
        + [f"decide_{o.value}" for o in DecisionOutcome if o is not DecisionOutcome.INVALID_INPUT]
    )
    assert {o: record[o] for o in outcomes if record[o] < 20} == {}, record

    raised: Counter[str] = Counter()

    @settings(max_examples=EXAMPLES)
    @given(close_fields, junk)
    def collect_raised(fields: tuple[Any, ...], prices: Any) -> None:
        raised[no_raise(fields, prices)] += 1

    collect_raised()

    # plan 0008 A-2: the no-raise property reaches acceptance and the scale step
    assert raised["closed"] >= 20 and raised["unrepresentable"] >= 20, raised
