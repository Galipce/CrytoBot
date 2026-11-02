"""Spec 0007 AC-12: rastgele açılış, dolum ve hesap durumu dizileri, spec'ten yazılmış bağımsız bir
modelle birebir; hiçbir girdi istisna fırlatmaz (BR-2, R-4…R-11)."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from crytobot.portfolio import (
    EMPTY_LEDGER,
    Fill,
    Ledger,
    LedgerOutcome,
    SnapshotOutcome,
    account_state,
    open_ledger,
    record_fill,
)

OPENED = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
NOW = OPENED + timedelta(hours=1)
STOP, TARGET = Decimal("95"), Decimal("110")
EXAMPLES = 300
IDS = ["a", "b", "c", "a b"]  # "a b" breaks the id format
PAIRS = ["BTC/USDT", "ETH/USDT"]


@dataclass(frozen=True)
class Open:
    amount: Decimal | None  # None: an invalid input


@dataclass(frozen=True)
class Record:
    client_order_id: str
    pair: str
    side: str
    amount: Decimal
    price: Decimal
    fee: Decimal
    early: bool  # filled before the opening


@dataclass(frozen=True)
class Snapshot:
    prices: dict[str, Decimal] | None  # None: not a mapping


opens = st.builds(
    Open, st.sampled_from([Decimal("10000"), Decimal("2000"), Decimal("2000"), Decimal(0), None])
)
# 19.249 @ 100.1 + 1.9268249 = 1928.7517249: a 2000 opening pays for one such fill, not two
records = st.builds(
    Record,
    st.sampled_from(IDS[:3] * 3 + IDS[3:]),
    st.sampled_from(PAIRS * 3 + ["XRP/USDT"]),
    st.sampled_from(["buy"] * 3 + ["sell"]),
    st.sampled_from([Decimal("19.249")] * 3 + [Decimal("1"), Decimal(0)]),
    st.sampled_from([Decimal("100.1")] * 3 + [Decimal("50")]),
    st.sampled_from([Decimal("1.9268249")] * 3 + [Decimal(0), Decimal("-1")]),
    st.sampled_from([False] * 9 + [True]),
)
snapshots = st.builds(
    Snapshot,
    st.sampled_from(
        [
            {"BTC/USDT": Decimal("105"), "ETH/USDT": Decimal("60"), "XRP/USDT": Decimal("1")},
            {"BTC/USDT": Decimal("105"), "ETH/USDT": Decimal("60"), "XRP/USDT": Decimal("1")},
            {"BTC/USDT": Decimal("105")},
            {"BTC/USDT": Decimal(0), "ETH/USDT": Decimal("60")},
            {},
            None,
        ]
    ),
)
# most sequences start opened, so fills reach the record rules; some never open
# 1928.7517249: an opening that one such fill spends exactly (balance 0 is accepted, R-5)
EXACT = Decimal("1928.7517249")
starts = st.sampled_from(
    [[Open(Decimal("10000"))]] + [[Open(Decimal("2000"))]] * 3 + [[Open(EXACT)]] + [[]] * 2
)
# the first two fills are sent again at the end: retries reach "already recorded" (R-6)
cases = st.builds(
    lambda start, rest: start + rest + [a for a in rest if isinstance(a, Record)][:2],
    starts,
    st.lists(st.one_of(opens, records, records, records, records, snapshots), max_size=20),
)


@dataclass
class Model:
    """Spec 0007 R-1…R-11, written from the spec in `Fraction`, not from the code."""

    balance: Fraction | None = None
    positions: dict[str, dict[str, Any]] = field(default_factory=dict)
    deposit: Fraction = Fraction(0)
    costs: list[Fraction] = field(default_factory=list)

    def open(self, action: Open) -> str:
        if action.amount is None or action.amount <= 0:
            return "invalid_input"
        if self.balance is not None:
            return "already_open"
        self.balance = self.deposit = Fraction(action.amount)
        return "opened"

    def record(self, action: Record) -> str:
        valid_id = action.client_order_id != "a b"
        if not valid_id or action.amount <= 0 or action.fee < 0:
            return "invalid_input"
        if self.balance is None:
            return "not_opened"
        if action.early:
            return "invalid_input"
        content = (action.pair, action.side, action.amount, action.price, action.fee)
        existing = self.positions.get(action.client_order_id)
        if existing is not None:
            return "already_recorded" if existing["content"] == content else "record_conflict"
        if action.side != "buy":
            return "unsupported_side"
        cost = Fraction(action.amount) * Fraction(action.price) + Fraction(action.fee)
        if cost > self.balance:
            return "insufficient_balance"
        self.balance -= cost
        self.costs.append(cost)
        self.positions[action.client_order_id] = {
            "content": content,
            "pair": action.pair,
            "amount": Fraction(action.amount),
        }
        return "recorded"

    def snapshot(self, action: Snapshot) -> tuple[str, Fraction | None]:
        if action.prices is None:
            return "snapshot_invalid_input", None
        if self.balance is None:
            return "snapshot_not_opened", None
        prices = action.prices
        if any(prices.get(p["pair"], Decimal(0)) <= 0 for p in self.positions.values()):
            return "snapshot_missing_price", None
        equity = self.balance + sum(
            (p["amount"] * Fraction(prices[p["pair"]]) for p in self.positions.values()),
            Fraction(0),
        )
        return "snapshot_ready", equity


def run(actions: list[Any]) -> list[str]:
    """Runs the actions on the code and on the model; checks every step; returns the outcomes."""
    model, ledger, seen = Model(), EMPTY_LEDGER, []
    for action in actions:
        if isinstance(action, Snapshot):
            result: Any = account_state(ledger, action.prices)
            expected, equity = model.snapshot(action)
            assert "snapshot_" + result.outcome.value == expected, (action, result.message)
            if equity is not None:
                assert result.snapshot is not None
                assert Fraction(result.snapshot.equity) == equity
                assert Fraction(result.snapshot.free_balance) == model.balance
                assert result.snapshot.open_positions == len(model.positions)
            seen.append(expected)
            continue
        if isinstance(action, Open):
            result = open_ledger(ledger, action.amount, OPENED)
            expected = model.open(action)
        else:
            fill = Fill(
                action.client_order_id, action.pair, action.side, action.amount, action.price,
                action.fee, STOP, TARGET, OPENED - timedelta(seconds=1) if action.early else NOW,
            )  # fmt: skip
            result = record_fill(ledger, fill)
            expected = model.record(action)
        assert result.outcome.value == expected, (action, result.message)
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
    assert (
        Fraction(ledger.balance) == model.balance == model.deposit - sum(model.costs, Fraction(0))
    )
    assert list(ledger.positions) == list(model.positions)
    # every fill entry debits exactly its position's cost; the entries rebuild the balance
    debits = [Fraction(e.usdt) for e in ledger.entries[1:]]
    assert debits == model.costs
    assert Fraction(ledger.entries[0].usdt) - sum(debits, Fraction(0)) == model.balance


@settings(max_examples=EXAMPLES)
@given(cases)
def test_ledger_matches_the_model(actions: Any) -> None:
    """AC-12 (R-4…R-10): bakiye negatife düşmez, açılış - Σ(tutar + komisyon)'a eşittir;
    pozisyonlar kabul edilen dolumlardır; kasa modelle aynıdır; reddedilen istek defteri bırakır."""
    run(actions)


JUNK: list[Any] = [
    None, True, 0.5, "1", "buy", "a", Decimal("NaN"), Decimal("-Infinity"), Decimal(0),
    Decimal(-1), Decimal("0.001"), Decimal("100"), Decimal("1E+1000000"), Decimal("1E-999999"),
    Decimal("1." + "2" * 28), 10**4300, -(10**4300), Fraction(10**4300), (10**4300,), [1],
    {"BTC/USDT": 10**4300}, {"BTC/USDT": Decimal("1E-999999")}, NOW, datetime(2026, 11, 2),
]  # fmt: skip
junk = st.sampled_from(JUNK)


@settings(max_examples=EXAMPLES)
@given(junk, junk, st.tuples(*[junk] * 9), junk)
def test_no_input_raises(amount: Any, at: Any, fields: tuple[Any, ...], prices: Any) -> None:
    """AC-12 (R-11): rastgele ve aralık dışı girdilerle açılış, dolum ve hesap durumu istisna değil,
    sonuç."""
    opened = open_ledger(EMPTY_LEDGER, amount, at)
    ledger = open_ledger(EMPTY_LEDGER, Decimal("10000"), OPENED).ledger

    recorded = record_fill(ledger, Fill(*fields))
    snapshot = account_state(recorded.ledger, prices)

    assert isinstance(opened.outcome, LedgerOutcome) and isinstance(recorded.outcome, LedgerOutcome)
    assert isinstance(snapshot.outcome, SnapshotOutcome)
    assert (recorded.position is not None) is (recorded.outcome is LedgerOutcome.RECORDED)


# measured at 300 (build): opened 249, recorded 163, already recorded 146, invalid input 710, not
# opened 102, already open 355, record conflict 40, unsupported side 100, insufficient balance 35;
# snapshot ready 352, invalid input 105, not opened 80, missing price 45
def test_outcomes_are_not_vacuous() -> None:
    """AC-12: üreteç her sonucu yeterince üretir."""
    record: Counter[str] = Counter()

    @settings(max_examples=EXAMPLES)
    @given(cases)
    def collect(actions: Any) -> None:
        record.update(run(actions))

    collect()

    outcomes = [o.value for o in LedgerOutcome] + ["snapshot_" + o.value for o in SnapshotOutcome]
    assert {o: record[o] for o in outcomes if record[o] < 20} == {}
