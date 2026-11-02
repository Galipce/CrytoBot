"""Spec 0009 AC-12: rastgele alım ve kapanış talebi, onay, emir ve sorgu dizileri, spec'ten yazılmış
bağımsız bir modelle birebir; hiçbir girdi istisna fırlatmaz (BR-9, BR-11, R-1…R-13)."""

import re
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta, tzinfo
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from types import MappingProxyType
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from crytobot.execution import (
    EMPTY_EXECUTION,
    CloseOrder,
    CloseOrderRequest,
    ExecutionState,
    OrderOutcome,
    OrderRequest,
    OrderStatus,
    PaperExchange,
    QueryOutcome,
    place_close_order,
    place_order,
    query_order,
)
from crytobot.risk import (
    CloseApproval,
    CloseRefusal,
    CloseRequest,
    PairRules,
    TradeApproval,
    TradeIntent,
    approve_close,
)

NOW = datetime(2026, 11, 2, 11, 0, tzinfo=UTC)
EXAMPLES = 300
RULES = PairRules(Decimal("0.001"), Decimal("0.001"), Decimal("5"))
FEE, SLIPPAGE = Decimal("0.001"), Decimal("0.0005")
INTENT = TradeIntent("BTC/USDT", "buy", Decimal("100"), Decimal("95"), Decimal("110"))
POSITION_ID = re.compile(r"cb-[A-Za-z0-9_-]{1,32}")
STATUSES = list(OrderStatus)


@dataclass(frozen=True)
class Buy:
    intent_id: str


@dataclass(frozen=True)
class Sell:
    position_id: str
    pair: str
    amount: Decimal
    reason: str
    approval: (
        str  # "approved" (via risk), "by_hand" (approved, unchecked), "refused", "trade", "none"
    )
    price: Decimal
    mode: str


@dataclass(frozen=True)
class Ask:
    client_order_id: str


buys = st.builds(Buy, st.sampled_from(["a", "b", "c"]))
sells = st.builds(
    Sell,
    st.sampled_from(["cb-a", "cb-b", "cb-a", "cb-b", "cb-z", "a"]),
    st.sampled_from(["BTC/USDT"] * 4 + ["ETH/USDT"]),
    st.sampled_from([Decimal("19.249")] * 4 + [Decimal("19.248"), Decimal(0)]),
    st.sampled_from(["hedef", "stop", "hedef", "stop", "elle"]),
    st.sampled_from(["approved"] * 6 + ["by_hand", "refused", "trade", "none"]),
    # 0.25: 19.249 * 0.25 * 0.9995 is below the 5 USDT minimum notional
    st.sampled_from([Decimal("110")] * 6 + [Decimal("0.25"), Decimal(0)]),
    st.sampled_from(["paper"] * 9 + ["live"]),
)
asks = st.builds(Ask, st.sampled_from(["cx-a", "cx-b", "cb-a", "cb-b", "cx-q"]))
ids = ["cb-a", "cb-b", "cb-c", "cx-a", "cx-b", "cx-z"]
# each run's simulator: how every order is placed and how an unknown one resolves when asked
venues = st.builds(
    lambda placed, resolved: PaperExchange(
        MappingProxyType(dict(zip(ids, placed, strict=True))),
        MappingProxyType(dict(zip(ids, resolved, strict=True))),
    ),
    st.lists(st.sampled_from([OrderStatus.FILLED] * 2 + STATUSES), min_size=6, max_size=6),
    st.lists(st.sampled_from(STATUSES), min_size=6, max_size=6),
)


def again(actions: list[Any]) -> list[Any]:
    """The first sales again (same content: "already exists"; the other reason: "id conflict"),
    then every order is asked about (an unknown one may resolve)."""
    sales = [a for a in actions if isinstance(a, Sell)][:3]
    flipped = [replace(a, reason="stop" if a.reason == "hedef" else "hedef") for a in sales]
    return sales + flipped + [Ask(i) for i in ("cb-a", "cb-b", "cx-a", "cx-b")]


cases = st.builds(
    lambda venue, actions: (venue, actions + again(actions)),
    venues,
    st.lists(st.one_of(buys, sells, sells, sells, asks), min_size=1, max_size=20),
)


@dataclass
class Model:
    """Spec 0009 (ve spec 0006'nın alımı), `Fraction` ile, koddan değil spec'ten."""

    venue: PaperExchange
    orders: dict[str, dict[str, Any]] = field(default_factory=dict)

    def unknown(self) -> list[str]:
        return [cid for cid, order in self.orders.items() if order["status"] is OrderStatus.UNKNOWN]

    def create(self, cid: str, content: tuple[Any, ...], quote: tuple[Fraction, Fraction]) -> str:
        self.orders[cid] = {
            "content": content,
            "status": self.venue.placements.get(cid, OrderStatus.FILLED),
            "quote": quote,
        }
        return "created"

    def buy(self, action: Buy) -> str:
        cid = "cb-" + action.intent_id
        if cid in self.orders:
            return "already_exists"
        if self.unknown():  # safe mode stops a buy (spec 0006 R-9)
            return "status_unknown"
        fill = Fraction(100) * (1 + 0)
        return self.create(cid, (), (fill, Fraction(1) * fill * Fraction(FEE)))

    def sell(self, action: Sell) -> str:
        if action.price <= 0:
            return "invalid_input"
        if action.mode != "paper":
            return "unsupported_mode"
        valid = (
            POSITION_ID.fullmatch(action.position_id) is not None
            and action.amount > 0
            and action.reason in ("stop", "hedef")
        )
        approved = action.approval == "by_hand" or (action.approval == "approved" and valid)
        if not approved:
            return "unapproved"
        if not valid:  # an approval built by hand around a malformed request
            return "invalid_input"
        cid = "cx-" + action.position_id.removeprefix("cb-")
        content = (action.position_id, action.pair, action.amount, action.reason)
        if cid in self.orders:
            same = self.orders[cid]["content"] == content
            return "already_exists" if same else "id_conflict"
        fill = Fraction(action.price) * (1 - Fraction(SLIPPAGE))
        notional = Fraction(action.amount) * fill
        if notional < 5:
            return "exchange_rule"
        return self.create(cid, content, (fill, notional * Fraction(FEE)))

    def ask(self, action: Ask) -> str:
        order = self.orders.get(action.client_order_id)
        if order is None:
            return "unknown_order"
        if order["status"] is not OrderStatus.UNKNOWN:
            return "unchanged"
        status = self.venue.resolutions.get(action.client_order_id, OrderStatus.UNKNOWN)
        if status is OrderStatus.UNKNOWN:
            return "unchanged"
        order["status"] = status
        return "updated"


def approval_for(action: Sell) -> Any:
    request = CloseRequest(action.position_id, action.pair, action.amount, action.reason)
    if action.approval == "approved":
        return approve_close(request)
    if action.approval == "by_hand":
        return CloseApproval(None, "elle kuruldu", request)
    if action.approval == "refused":
        return CloseApproval(CloseRefusal.INVALID_INPUT, "ret", request)
    if action.approval == "trade":
        return TradeApproval(Decimal("19.249"), None, False, "", INTENT)
    return None


def run(case: tuple[PaperExchange, list[Any]]) -> list[str]:
    """Runs the actions on the code and on the model; checks every step; returns the outcomes."""
    venue, actions = case
    model, state, seen = Model(venue), EMPTY_EXECUTION, []
    for action in actions:
        result: Any
        if isinstance(action, Ask):
            result = query_order(state, action.client_order_id, venue, NOW)
            expected = "ask_" + model.ask(action)
            assert "ask_" + result.outcome.value == expected, result.message
            if result.outcome is not QueryOutcome.UPDATED:
                assert result.state is state
        else:
            if isinstance(action, Buy):
                request = OrderRequest(
                    action.intent_id, INTENT, TradeApproval(Decimal(1), None, False, "", INTENT),
                    RULES, Decimal("100"), FEE, Decimal(0), "paper",
                )  # fmt: skip
                result = place_order(state, request, venue, NOW)
                expected = "buy_" + model.buy(action)
                outcome = "buy_" + result.outcome.value
            else:
                close = CloseOrderRequest(
                    approval_for(action), RULES, action.price, FEE, SLIPPAGE, action.mode
                )
                result = place_close_order(state, close, venue, NOW)
                expected = "close_" + model.sell(action)
                outcome = "close_" + result.outcome.value
            assert outcome == expected, (action, result.message)
            if result.outcome is not OrderOutcome.CREATED:
                assert result.state is state
        state = result.state
        check_state(state, model)
        seen.append(expected)
    return seen


def check_state(state: ExecutionState, model: Model) -> None:
    assert list(state.orders) == list(model.orders)
    for cid, order in state.orders.items():
        expected = model.orders[cid]
        assert order.status is expected["status"]
        if isinstance(order, CloseOrder):
            assert (order.position_id, order.pair, order.amount, order.reason) == expected[
                "content"
            ]
            assert order.side == "sell" and cid == "cx-" + order.position_id.removeprefix("cb-")
        if order.status is OrderStatus.FILLED:
            assert order.fill_price is not None and order.fee is not None
            assert (Fraction(order.fill_price), Fraction(order.fee)) == expected["quote"]
        else:
            assert order.fill_price is None and order.fee is None
    assert list(state.unknown) == model.unknown()


@settings(max_examples=EXAMPLES)
@given(cases)
def test_close_orders_match_the_model(case: Any) -> None:
    """AC-12 (R-1…R-13): pozisyon başına en fazla bir kapanış emri; kapanış güvenli modda
    reddedilmez, alım kapanışın `bilinmiyor`u yüzünden durur; dolum ve komisyon modelle aynı;
    reddedilen istek durumu bırakır."""
    run(case)


class BadOffset(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(days=2)  # outside the range `datetime` accepts: ValueError

    def dst(self, dt: datetime | None) -> None:
        return None

    def tzname(self, dt: datetime | None) -> str:
        return "bad"


JUNK: list[Any] = [
    None, True, 0.5, "1", "paper", "hedef", "cb-a", Decimal("NaN"), Decimal("-Infinity"),
    Decimal(0), Decimal(-1), Decimal("0.001"), Decimal("1E+1000000"), Decimal("1E-999999"),
    Decimal("1." + "2" * 28), 10**4300, -(10**4300), Fraction(10**4300), (10**4300,), [1],
    PairRules(None, None, None), PairRules(10**4300, -1, Decimal("NaN")), NOW,
    datetime(2026, 11, 2),
]  # fmt: skip
JUNK += [
    Enum("TextEnum", {"HEDEF": "hedef"}, type=str).HEDEF,  # type: ignore[attr-defined]
    "BAD_OFFSET",  # no_raise turns it into the time: Hypothesis cannot print such a datetime
]
junk = st.sampled_from(JUNK)
# each field is valid eight times out of nine, so requests reach the scale and acceptance paths
# (a 28-digit price's fill, or a remainder by a 1E-999999 step, does not fit in 28 digits)
VALID: list[list[Any]] = [
    ["cb-a"], ["BTC/USDT"], [Decimal("19.249")], ["hedef"],
    [RULES, PairRules(Decimal("1E-999999"), Decimal(0), Decimal(0))],
    [Decimal("110"), Decimal("109.9450000000000000000000001")], [FEE], [SLIPPAGE, Decimal("1E-70")],
    ["paper"], [NOW],
]  # fmt: skip
wraps = st.sampled_from(["risk"] * 4 + ["by_hand", "junk_request", "junk_approval"])
fields = st.tuples(*[st.sampled_from(v * (8 * len(JUNK) // len(v)) + JUNK) for v in VALID])


def no_raise(values: tuple[Any, ...], wrap: str) -> str:
    """Approves and places one close; checks no exception and a coherent result."""
    values = tuple(NOW.replace(tzinfo=BadOffset()) if v == "BAD_OFFSET" else v for v in values)
    request = CloseRequest(*values[:4])
    approval: Any = approve_close(request)
    assert isinstance(approval.reason, CloseRefusal | None)
    if wrap == "by_hand":  # an approval built by hand: execution checks the request again
        approval = CloseApproval(None, "", request)
    elif wrap == "junk_request":  # ... around something that is no close request
        approval = CloseApproval(None, "", values[0])
    elif wrap == "junk_approval":
        approval = values[0]
    assert isinstance(approve_close(values[0]).reason, CloseRefusal | None)
    close = CloseOrderRequest(approval, *values[4:9])
    result = place_close_order(EMPTY_EXECUTION, close, PaperExchange(), values[9])

    assert isinstance(result.outcome, OrderOutcome)
    assert (result.order is not None) is (result.outcome is OrderOutcome.CREATED)
    unrepresentable = "ölçek hesaplanamıyor" in result.message
    return "unrepresentable" if unrepresentable else result.outcome.value


@settings(max_examples=EXAMPLES)
@given(fields, wraps)
def test_no_close_order_input_raises(values: tuple[Any, ...], wrap: str) -> None:
    """AC-12 (R-13): rastgele ve aralık dışı girdilerle kapanış onayı ve emri istisna değil,
    sonuç."""
    no_raise(values, wrap)


def test_close_order_outcomes_are_not_vacuous() -> None:
    """AC-12: üreteçler her sonucu yeterince üretir; "istisna yok" üreteci kabule ve ölçek adımına
    ulaşır."""
    record: Counter[str] = Counter()

    @settings(max_examples=EXAMPLES)
    @given(cases)
    def collect(case: Any) -> None:
        record.update(run(case))

    collect()

    closes = [o.value for o in OrderOutcome if o is not OrderOutcome.STATUS_UNKNOWN]
    outcomes = (
        [f"close_{o}" for o in closes]
        + ["buy_created", "buy_already_exists", "buy_status_unknown"]
        + ["ask_updated", "ask_unchanged", "ask_unknown_order"]
    )
    assert {o: record[o] for o in outcomes if record[o] < 20} == {}, record

    raised: Counter[str] = Counter()

    @settings(max_examples=EXAMPLES)
    @given(fields, wraps)
    def collect_raised(values: tuple[Any, ...], wrap: str) -> None:
        raised[no_raise(values, wrap)] += 1

    collect_raised()

    assert raised["created"] >= 20 and raised["unrepresentable"] >= 20, raised
