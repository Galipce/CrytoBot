"""Spec 0011 AC-11 (R-3, R-5, R-8): rastgele dizilerde her kayıt-yükleme sonrası durum, spec'ten
yazılmış bağımsız modelle birebir aynıdır; geçmiş kaybolmaz; yasak yazım reddedilir ve diski
değiştirmez; çelişkisiz dizide işaret yoktur."""

import tempfile
from dataclasses import dataclass, field, replace
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType

from hypothesis import example, given, settings
from hypothesis import strategies as st

from crytobot.execution import OrderStatus, PaperExchange, query_order
from crytobot.persistence import StoredState, StoreOutcome, load_store
from crytobot.portfolio import EMPTY_LEDGER, Ledger
from crytobot.risk import resume
from tests.persistence.chain import (
    DEPOSIT,
    FEE,
    SLIPPAGE,
    T0,
    World,
    bought,
    created,
    opened,
    placed,
    recorded,
    save,
    seen,
    snapshot,
    sold,
)

EXAMPLES = 30
AMOUNTS = ["0.5", "1.10", "2.50"]
PRICES = ["100.10", "99.5", "1.000", "0.00123456"]
EQUITIES = ["10000", "11000.50", "5000", "10000.00"]
Step = tuple[str, str, str]

STEPS = st.lists(
    st.tuples(
        st.sampled_from(
            ["buy", "buy", "close", "rejected", "unknown", "fill", "refuse", "observe", "resume"]
        ),
        st.sampled_from(AMOUNTS),
        st.sampled_from(PRICES),
    ),
    min_size=1,
    max_size=8,
)


@dataclass
class Model:
    """Beklenen durum: `Fraction` ile tam hesap, motoru kullanmaz."""

    balance: Fraction = Fraction(DEPOSIT)
    realized: Fraction = Fraction(0)
    open_ids: list[str] = field(default_factory=list)
    closed_ids: list[str] = field(default_factory=list)
    orders: dict[str, OrderStatus] = field(default_factory=dict)
    costs: dict[str, Fraction] = field(default_factory=dict)
    quoted: dict[str, tuple[str, str]] = field(default_factory=dict)
    entries: int = 1
    peak: Fraction | None = None
    day_start: Fraction | None = None
    halted: bool = False


def fill_of(price: str, up: bool) -> Fraction:
    slip = Fraction(SLIPPAGE)
    return Fraction(Decimal(price)) * (1 + slip if up else 1 - slip)


def apply_buy(model: Model, cid: str, amount: str, price: str) -> None:
    notional = Fraction(Decimal(amount)) * fill_of(price, True)
    cost = notional + notional * Fraction(FEE)
    model.balance -= cost
    model.costs[cid] = cost
    model.open_ids.append(cid)
    model.entries += 1


def apply_close(model: Model, cid: str, amount: str, price: str) -> None:
    notional = Fraction(Decimal(amount)) * fill_of(price, False)
    proceeds = notional - notional * Fraction(FEE)
    model.balance += proceeds
    model.realized += proceeds - model.costs[cid]
    model.open_ids.remove(cid)
    close_id = "cx-" + cid.removeprefix("cb-")
    model.closed_ids.append(close_id)
    model.orders[close_id] = OrderStatus.FILLED
    model.entries += 1


def assert_matches(model: Model, state: World) -> None:
    ledger, execution, risk = state.ledger, state.execution, state.risk
    assert ledger.balance is not None and Fraction(ledger.balance) == model.balance
    assert Fraction(ledger.realized) == model.realized
    assert list(ledger.positions) == model.open_ids
    assert list(ledger.closures) == model.closed_ids
    assert len(ledger.entries) == model.entries
    assert {k: o.status for k, o in execution.orders.items()} == model.orders
    assert list(execution.orders) == list(model.orders)
    unknown = [k for k, status in model.orders.items() if status is OrderStatus.UNKNOWN]
    assert list(execution.quotes) == unknown
    assert risk.halted is model.halted
    peak, day_start = risk.peak_equity, risk.day_start_equity
    assert (None if peak is None else Fraction(peak)) == model.peak
    assert (None if day_start is None else Fraction(day_start)) == model.day_start


def forbidden_writes(world: World, earlier_ledger: Ledger) -> dict[str, World]:
    """R-8'in o anki duruma uyan yasak yazımları: `earlier_ledger`, son kaydı silinmiş defterdir."""
    writes = {"entry_deleted": replace(world, ledger=earlier_ledger)}
    orders = world.execution.orders
    if orders:
        cid = list(orders)[-1]
        changed = {**orders, cid: replace(orders[cid], amount=orders[cid].amount + 1)}
        execution = replace(world.execution, orders=MappingProxyType(changed))
        writes["order_content_changed"] = replace(world, execution=execution)
    risk = world.risk
    if risk.last_time is not None:
        earlier = risk.last_time - timedelta(seconds=1)
        writes["observation_moved_back"] = replace(world, risk=replace(risk, last_time=earlier))
    if risk.halted:
        writes["halt_closed_unlike_resume"] = replace(world, risk=replace(risk, halted=False))
    return writes


def assert_refused(path: Path, state: StoredState, writes: dict[str, World]) -> None:
    before = path.read_bytes()
    for name, write in writes.items():
        result = save(path, state, write)
        assert result.outcome is StoreOutcome.HISTORY_IMMUTABLE, (name, result.message)
        assert result.state is None
        assert path.read_bytes() == before, name


@given(steps=STEPS)
# every forbidden write applies on this one: an observation, then a halt, with an order and a record
@example(
    steps=[
        ("observe", "0.5", "100.10"),
        ("buy", "0.5", "100.10"),
        ("observe", "0.5", "100.10"),
    ]
)
# the unknown -> filled -> ledger path, which random lists rarely reach
@example(
    steps=[
        ("unknown", "1.10", "99.5"),
        ("fill", "0.5", "1.000"),
        ("close", "0.5", "1.000"),
    ]
)
@settings(max_examples=EXAMPLES, deadline=None)
def test_every_save_and_load_matches_the_model(steps: list[Step]) -> None:
    with tempfile.TemporaryDirectory(prefix="crytobot-store-") as folder:
        path = Path(folder) / "depo.sqlite"
        state = created(path)
        world = opened()
        result = save(path, state, world)
        assert result.state is not None
        state = result.state
        model = Model()
        earlier_ledger = EMPTY_LEDGER
        history: list[str] = []
        known_orders: list[str] = []
        at = T0
        for index, (kind, amount, price) in enumerate(steps):
            at += timedelta(minutes=1)
            before_step = world.ledger
            cid = f"cb-{index}"
            if kind == "buy" and not any(s is OrderStatus.UNKNOWN for s in model.orders.values()):
                world = bought(world, str(index), amount=amount, price=price, at=at)
                model.orders[cid] = OrderStatus.FILLED
                apply_buy(model, cid, amount, price)
            elif kind == "close" and world.ledger.positions:
                position_id = next(iter(world.ledger.positions))
                position_amount = str(world.ledger.positions[position_id].amount)
                world = sold(world, position_id, price=price, at=at)
                apply_close(model, position_id, position_amount, price)
            elif kind == "rejected" and not world.execution.unknown:
                world = placed(
                    world,
                    str(index),
                    amount=amount,
                    price=price,
                    status=OrderStatus.REJECTED,
                    at=at,
                )
                model.orders[cid] = OrderStatus.REJECTED
            elif kind == "unknown" and not world.execution.unknown:
                world = placed(
                    world, str(index), amount=amount, price=price, status=OrderStatus.UNKNOWN, at=at
                )
                model.orders[cid] = OrderStatus.UNKNOWN
                model.quoted[cid] = (amount, price)
            elif kind == "fill" and world.execution.unknown:
                pending = world.execution.unknown[0]
                exchange = PaperExchange(
                    resolutions=MappingProxyType({pending: OrderStatus.FILLED})
                )
                outcome = query_order(world.execution, pending, exchange, at)
                world = recorded(replace(world, execution=outcome.state), pending)
                model.orders[pending] = OrderStatus.FILLED
                apply_buy(model, pending, *model.quoted[pending])
            elif kind == "refuse" and world.execution.unknown:
                pending = world.execution.unknown[0]
                exchange = PaperExchange(
                    resolutions=MappingProxyType({pending: OrderStatus.REJECTED})
                )
                outcome = query_order(world.execution, pending, exchange, at)
                world = replace(world, execution=outcome.state)
                model.orders[pending] = OrderStatus.REJECTED
            elif kind == "observe":
                equity = EQUITIES[index % len(EQUITIES)]
                world = seen(world, equity, at)
                number = Fraction(Decimal(equity))
                model.day_start = number if model.day_start is None else model.day_start
                model.peak = number if model.peak is None else max(model.peak, number)
                model.halted = model.halted or (model.peak - number) / model.peak >= Fraction(
                    15, 100
                )
            elif kind == "resume" and world.risk.halted:
                world = replace(world, risk=resume(world.risk, "cli").state)
                model.peak = Fraction(world.risk.last_equity or 0)
                model.halted = False
            result = save(path, state, world)
            assert result.outcome is StoreOutcome.SAVED, result.message
            assert result.state is not None and result.reconciled
            state = result.state

            reloaded = load_store(path, "paper")

            assert reloaded.outcome is StoreOutcome.LOADED and reloaded.reconciled
            assert reloaded.state is not None
            assert snapshot(reloaded.state) == snapshot(world)
            assert reloaded.state.revision == state.revision
            assert_matches(
                model, World(reloaded.state.ledger, reloaded.state.execution, reloaded.state.risk)
            )
            entries = [repr(e) for e in reloaded.state.ledger.entries]
            orders = list(reloaded.state.execution.orders)
            assert entries[: len(history)] == history
            assert orders[: len(known_orders)] == known_orders
            history, known_orders = entries, orders

            if len(world.ledger.entries) > len(before_step.entries):
                earlier_ledger = before_step
            assert_refused(path, state, forbidden_writes(world, earlier_ledger))
