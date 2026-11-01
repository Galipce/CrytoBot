"""Spec 0006 AC-11: rastgele istek ve sorgu dizileri, spec'ten yazılmış bağımsız bir modelle
birebir; hiçbir girdi istisna fırlatmaz (BR-9, BR-11)."""

import string
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from crytobot.execution import (
    EMPTY_EXECUTION,
    ExecutionState,
    NotificationKind,
    OrderOutcome,
    OrderRequest,
    OrderStatus,
    PaperExchange,
    QueryOutcome,
    place_order,
    query_order,
)
from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    AccountState,
    PairRules,
    TradeApproval,
    TradeIntent,
    approve_trade,
    observe,
)

PAIR = "BTC/USDT"
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
ACCOUNT = AccountState(Decimal("10000"), Decimal("5000"), 0)
STEP = MIN_AMOUNT = Decimal("0.001")
RULES = PairRules(STEP, MIN_AMOUNT, Decimal("5"))
INTENT = TradeIntent(PAIR, "buy", Decimal("100"), Decimal("95"), Decimal("110"))
LOW_EDGE = replace(INTENT, target=Decimal("100.3"))  # spec 0005: below the threshold
FEE = Decimal("0.001")
EXAMPLES = 300


def judge(intent: TradeIntent) -> TradeApproval:
    state = observe(EMPTY_STATE, NOW, ACCOUNT.equity, DEFAULT_LIMITS).state
    return approve_trade(
        intent, DEFAULT_LIMITS, ACCOUNT, RULES, frozenset({PAIR}), FEE, Decimal("0.0005"),
        Decimal("0.001"), state, NOW,
    )  # fmt: skip


APPROVAL = judge(INTENT)
# (intent, approval): approved, approved with another amount, off the step, rejected by risk,
# judged on another intent, approval without an amount
VARIANTS: dict[str, tuple[TradeIntent, TradeApproval]] = {
    "ok": (INTENT, APPROVAL),
    "other_amount": (INTENT, replace(APPROVAL, amount=Decimal("19.248"))),
    "off_step": (INTENT, replace(APPROVAL, amount=Decimal("19.2495"))),
    "rejected": (LOW_EDGE, judge(LOW_EDGE)),
    "mismatch": (replace(INTENT, target=Decimal("111")), APPROVAL),
    "no_amount": (INTENT, replace(APPROVAL, amount=None)),
}
IDS = ["a", "b", "c", "a b"]  # "a b" breaks the id format
STATUSES = [OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.UNKNOWN]


@dataclass(frozen=True)
class Place:
    intent_id: str
    variant: str
    price: Decimal | None  # None: an invalid input
    slippage: Decimal
    min_notional: Decimal
    mode: str


@dataclass(frozen=True)
class Query:
    client_order_id: str


places = st.builds(
    Place,
    st.sampled_from(IDS[:3] * 3 + IDS[3:]),
    st.sampled_from(["ok"] * 5 + list(VARIANTS)),  # mostly approved: orders get created
    st.sampled_from([Decimal("100"), Decimal("99.5"), Decimal("120")] * 3 + [None]),
    st.sampled_from([Decimal(0), Decimal("0.001")]),
    # 19.249 * 100 * 1.001 = 1926.8249: the minimum notional sits around the boundary
    st.sampled_from([Decimal("5"), Decimal("1926.8249"), Decimal("1926.825")]),
    st.sampled_from(["paper"] * 9 + ["live"]),
)
queries = st.builds(Query, st.sampled_from(["cb-a", "cb-b", "cb-c"] * 3 + ["cb-x"]))
scripts = st.fixed_dictionaries(
    {f"cb-{i}": st.sampled_from([*STATUSES, OrderStatus.UNKNOWN]) for i in "abc"}
)  # fmt: skip
# a later query mostly settles an unknown order, so safe mode is left as well as entered
settles = st.fixed_dictionaries(
    {f"cb-{i}": st.sampled_from([*STATUSES[:2] * 2, OrderStatus.UNKNOWN]) for i in "abc"}
)
cases = st.tuples(
    st.lists(st.one_of(places, queries, queries), min_size=1, max_size=20), scripts, settles
)


@dataclass
class Model:
    """Spec 0006 R-2…R-11, written from the spec in `Fraction`, not from the code."""

    orders: dict[str, dict[str, Any]] = field(default_factory=dict)

    def unknown(self) -> list[str]:
        return [cid for cid, order in self.orders.items() if order["status"] == "unknown"]

    def place(self, action: Place, placements: dict[str, OrderStatus]) -> tuple[str, list[str]]:
        intent, approval = VARIANTS[action.variant]
        valid_id = 1 <= len(action.intent_id) <= 32 and all(
            ch in string.ascii_letters + string.digits + "-_" for ch in action.intent_id
        )
        if not valid_id or action.price is None:
            return "invalid_input", []
        if action.mode != "paper":
            return "unsupported_mode", []
        cid = "cb-" + action.intent_id
        amount = approval.amount if approval.amount and approval.amount > 0 else None
        content = (intent.pair, intent.side, intent.entry, intent.stop, intent.target, amount)
        if cid in self.orders:
            same = self.orders[cid]["content"] == content
            return ("already_exists" if same else "id_conflict"), []
        if self.unknown():
            return "status_unknown", []
        if approval.reason is not None or amount is None or approval.intent != intent:
            return "unapproved", []
        size, price = Fraction(Decimal(amount)), Fraction(action.price)
        fill = price * (1 + Fraction(action.slippage))
        notional = size * fill
        if size % Fraction(STEP) != 0 or size < Fraction(MIN_AMOUNT):
            return "exchange_rule", []
        if notional < Fraction(action.min_notional):
            return "exchange_rule", []
        status = placements[cid].value
        self.orders[cid] = {
            "status": status,
            "content": content,
            "quote": (fill, notional * Fraction(FEE)),
        }
        return "created", (["safe_mode_entered"] if status == "unknown" else [])

    def query(self, action: Query, resolutions: dict[str, OrderStatus]) -> tuple[str, list[str]]:
        order = self.orders.get(action.client_order_id)
        if order is None:
            return "unknown_order", []
        if order["status"] != "unknown" or resolutions[action.client_order_id].value == "unknown":
            return "unchanged", []
        order["status"] = resolutions[action.client_order_id].value
        return "updated", ([] if self.unknown() else ["safe_mode_exited"])


def run(case: tuple[list[Any], dict[str, OrderStatus], dict[str, OrderStatus]]) -> list[str]:
    """Runs the actions on the code and on the model; checks every step; returns the outcomes."""
    actions, placements, resolutions = case
    venue = PaperExchange(placements, resolutions)
    model, state, seen = Model(), EMPTY_EXECUTION, []
    for action in actions:
        if isinstance(action, Place):
            intent, approval = VARIANTS[action.variant]
            rules = replace(RULES, min_notional=action.min_notional)
            request = OrderRequest(
                action.intent_id, intent, approval, rules, action.price, FEE, action.slippage,
                action.mode,
            )  # fmt: skip
            result: Any = place_order(state, request, venue, NOW)
            expected, notes = model.place(action, placements)
        else:
            result = query_order(state, action.client_order_id, venue, NOW)
            expected, notes = model.query(action, resolutions)
        assert result.outcome.value == expected, (action, result.message)
        assert [n.kind.value for n in result.notifications] == notes, action
        if expected not in ("created", "updated"):
            assert result.state is state
        state = result.state
        check_state(state, model)
        seen += [expected, *notes]
    return seen


def check_state(state: ExecutionState, model: Model) -> None:
    assert list(state.orders) == list(model.orders)
    for cid, order in state.orders.items():
        expected = model.orders[cid]
        assert order.status.value == expected["status"]
        if order.status is OrderStatus.FILLED:
            fill, fee = expected["quote"]
            assert (Fraction(order.fill_price), Fraction(order.fee)) == (fill, fee)  # type: ignore[arg-type]
        else:
            assert order.fill_price is None and order.fee is None
    assert list(state.unknown) == model.unknown()


@settings(max_examples=EXAMPLES)
@given(cases)
def test_requests_match_the_model(case: Any) -> None:
    """AC-11 (R-2, R-4, R-7, R-9, R-10): onaysız ya da kurala aykırı istek emir oluşturmaz, aynı
    kimlik ikinci emir oluşturmaz, bilinmeyen emir varken yeni emir yok, her geçiş tek bildirim."""
    run(case)


JUNK: list[Any] = [
    None, True, 0.5, "1", "paper", "a", Decimal("NaN"), Decimal("-Infinity"), Decimal(0),
    Decimal(-1), Decimal("0.001"), Decimal("100"), Decimal("1E+1000000"), Decimal("1E-999999"),
    Decimal("1." + "2" * 28), 10**4300, -(10**4300), Fraction(10**4300), (10**4300,), [1],
    INTENT, APPROVAL, RULES, NOW, datetime(2026, 11, 2),
]  # fmt: skip
junk = st.sampled_from(JUNK)


@settings(max_examples=EXAMPLES)
@given(st.tuples(*[junk] * 9), junk, scripts)
def test_no_input_raises(values: tuple[Any, ...], query_id: Any, placements: Any) -> None:
    """AC-11 (R-12): rastgele ve aralık dışı girdilerle istek ve sorgu istisna değil, sonuç."""
    *fields, now = values
    venue = PaperExchange(placements, placements)

    result = place_order(EMPTY_EXECUTION, OrderRequest(*fields), venue, now)
    asked = query_order(result.state, query_id, venue, now)

    assert isinstance(result.outcome, OrderOutcome) and isinstance(asked.outcome, QueryOutcome)
    assert (result.order is not None) is (result.outcome is OrderOutcome.CREATED)


# measured at 300 (build): created 159, invalid input 197, exchange rule 114, unapproved 120,
# status unknown 51, id conflict 39, already exists 56, updated 31 (= safe mode exits 31)
def test_decisions_are_not_vacuous() -> None:
    """AC-11: üreteç her sonucu yeterince üretir; güvenli moda giriş ve çıkış da olur."""
    record: Counter[str] = Counter()

    @settings(max_examples=EXAMPLES)
    @given(cases)
    def collect(case: Any) -> None:
        record.update(run(case))

    collect()

    outcomes = [o.value for o in OrderOutcome] + ["updated", "unchanged", "unknown_order"]
    outcomes += [kind.value for kind in NotificationKind]
    assert {o: record[o] for o in outcomes if record[o] < 20} == {}
