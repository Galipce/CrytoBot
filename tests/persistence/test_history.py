"""Spec 0011 AC-8 (R-8): geçmiş diskte de değişmez; reddedilen kayıt depoyu değiştirmez."""

from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from crytobot.execution import OrderStatus, PaperExchange, query_order
from crytobot.persistence import StoreOutcome
from crytobot.risk import EMPTY_STATE, resume
from tests.persistence.chain import (
    T0,
    T1,
    T2,
    World,
    bought,
    loaded,
    opened,
    placed,
    recorded,
    save,
    saved,
    seen,
    sell_placed,
    sell_recorded,
    snapshot,
    sold,
    stored,
)


def orders_edited(world: World, orders: dict[str, Any]) -> World:
    return replace(world, execution=replace(world.execution, orders=MappingProxyType(orders)))


def order_changed(world: World, cid: str, **changes: Any) -> World:
    order = replace(world.execution.orders[cid], **changes)
    return orders_edited(world, {**world.execution.orders, cid: order})


def order_renamed(world: World, cid: str, intent_id: str) -> World:
    """Yalnız `execution` değişir: defter eski kimliği taşımaya devam eder."""
    order: Any = world.execution.orders[cid]
    new_id = f"cb-{intent_id}"
    return orders_edited(
        world, {new_id: replace(order, client_order_id=new_id, intent_id=intent_id)}
    )


def quote_changed(world: World, cid: str, fill: str, fee: str) -> World:
    quotes = {**world.execution.quotes, cid: (Decimal(fill), Decimal(fee))}
    return replace(world, execution=replace(world.execution, quotes=MappingProxyType(quotes)))


def resolved(world: World, cid: str, status: OrderStatus) -> World:
    exchange = PaperExchange(resolutions=MappingProxyType({cid: status}))
    result = query_order(world.execution, cid, exchange, T2)
    return replace(world, execution=result.state)


BASE = bought(opened())
TWO_BUYS = bought(BASE, "b")
HALTED = seen(seen(BASE, "10000"), "5000", T2)
UNKNOWN = placed(opened(), "u", status=OrderStatus.UNKNOWN)
WITH_FILLED_AND_UNKNOWN = placed(BASE, "u", status=OrderStatus.UNKNOWN)


def lifted(world: World) -> World:
    return replace(world, risk=resume(world.risk, "cli").state)


# (what is on disk, the write that must be refused)
FORBIDDEN: dict[str, tuple[World, World]] = {
    "entry_deleted": (TWO_BUYS, replace(TWO_BUYS, ledger=BASE.ledger)),
    "entry_changed": (BASE, bought(opened(), "a", amount="2.51")),
    "entry_only_trailing_zero_changed": (
        bought(opened(), "a", price="100.10"),
        bought(opened(), "a", price="100.100"),
    ),
    "opening_changed": (BASE, bought(opened(Decimal("100000.11")))),
    "order_deleted": (
        TWO_BUYS,
        orders_edited(TWO_BUYS, {"cb-a": TWO_BUYS.execution.orders["cb-a"]}),
    ),
    "order_reordered": (
        TWO_BUYS,
        orders_edited(TWO_BUYS, dict(reversed(list(TWO_BUYS.execution.orders.items())))),
    ),
    "order_id_changed": (BASE, order_renamed(BASE, "cb-a", "z")),
    "order_content_changed": (BASE, order_changed(BASE, "cb-a", stop=Decimal("90"))),
    "order_time_changed": (BASE, order_changed(BASE, "cb-a", created_at=T2)),
    "filled_order_rejected": (
        BASE,
        order_changed(BASE, "cb-a", status=OrderStatus.REJECTED, fill_price=None, fee=None),
    ),
    "rejected_order_filled": (
        placed(opened(), "r", status=OrderStatus.REJECTED),
        order_changed(
            placed(opened(), "r", status=OrderStatus.REJECTED),
            "cb-r",
            status=OrderStatus.FILLED,
            fill_price=Decimal("100"),
            fee=Decimal("1"),
        ),
    ),
    "filled_order_price_changed": (
        WITH_FILLED_AND_UNKNOWN,
        order_changed(WITH_FILLED_AND_UNKNOWN, "cb-a", fill_price=Decimal("1")),
    ),
    "unknown_filled_at_another_price": (
        UNKNOWN,
        replace(
            order_changed(
                UNKNOWN,
                "cb-u",
                status=OrderStatus.FILLED,
                fill_price=Decimal("1"),
                fee=Decimal("1"),
            ),
            execution=replace(
                order_changed(
                    UNKNOWN,
                    "cb-u",
                    status=OrderStatus.FILLED,
                    fill_price=Decimal("1"),
                    fee=Decimal("1"),
                ).execution,
                quotes=MappingProxyType({}),
            ),
        ),
    ),
    "unknown_quote_changed": (UNKNOWN, quote_changed(UNKNOWN, "cb-u", "1", "1")),
    "observation_moved_back": (seen(BASE, "100", T2), seen(BASE, "100", T1)),
    "observation_emptied": (seen(BASE, "100", T1), replace(BASE, risk=EMPTY_STATE)),
    "halt_closed_with_another_peak": (
        HALTED,
        replace(HALTED, risk=replace(HALTED.risk, halted=False, peak_equity=Decimal("6000"))),
    ),
    "halt_closed_keeping_the_peak": (
        HALTED,
        replace(HALTED, risk=replace(HALTED.risk, halted=False)),
    ),
    "halt_closed_with_another_last_equity": (
        HALTED,
        replace(
            HALTED,
            risk=replace(
                HALTED.risk, halted=False, last_equity=Decimal("6000"), peak_equity=Decimal("6000")
            ),
        ),
    ),
    "halt_closed_at_another_time": (
        HALTED,
        replace(
            lifted(HALTED), risk=replace(lifted(HALTED).risk, last_time=T2 + timedelta(minutes=1))
        ),
    ),
}


@pytest.mark.parametrize("case", list(FORBIDDEN))
def test_forbidden_write_is_refused_and_changes_nothing(tmp_path: Path, case: str) -> None:
    path = tmp_path / "depo.sqlite"
    on_disk, write = FORBIDDEN[case]
    state = stored(path, on_disk)
    before = path.read_bytes()

    result = save(path, state, write)

    assert result.outcome is StoreOutcome.HISTORY_IMMUTABLE, result.message
    assert result.state is None and result.message == "geçmiş değiştirilemez"
    assert path.read_bytes() == before
    assert loaded(path).revision == state.revision


Advance = Callable[[World], World]
ALLOWED: dict[str, tuple[World, Advance]] = {
    "unknown_filled": (UNKNOWN, lambda w: resolved(w, "cb-u", OrderStatus.FILLED)),
    "unknown_rejected": (UNKNOWN, lambda w: resolved(w, "cb-u", OrderStatus.REJECTED)),
    "unknown_stays": (UNKNOWN, lambda w: w),
    "new_buy": (BASE, lambda w: bought(w, "b")),
    "new_close": (BASE, sold),
    "new_observation": (seen(BASE, "100", T1), lambda w: seen(w, "101", T2)),
    "same_time_observation": (seen(BASE, "100", T1), lambda w: seen(w, "101", T1)),
    "first_observation": (BASE, lambda w: seen(w, "100", T0)),
    "resume": (HALTED, lifted),
    "halt_starts": (seen(BASE, "10000"), lambda w: seen(w, "5000", T2)),
    "nothing_changes": (BASE, lambda w: w),
}


@pytest.mark.parametrize("case", list(ALLOWED))
def test_allowed_write_is_accepted_and_restored(tmp_path: Path, case: str) -> None:
    path = tmp_path / "depo.sqlite"
    on_disk, advance = ALLOWED[case]
    state = stored(path, on_disk)
    world = advance(on_disk)

    after = saved(path, state, world)

    assert after.revision == state.revision + 1
    assert snapshot(loaded(path)) == snapshot(world)


def test_filled_unknown_order_can_then_reach_the_ledger(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    state = stored(path, UNKNOWN)
    world = resolved(UNKNOWN, "cb-u", OrderStatus.FILLED)
    state = saved(path, state, world)

    world = recorded(world, "cb-u")

    saved(path, state, world)
    assert snapshot(loaded(path)) == snapshot(world)


def test_writer_left_behind_is_a_stale_write(tmp_path: Path) -> None:
    """İki açık bağlantı: öndeki yazar, geride kalanın kaydı "eski yazım" alır, depo değişmez."""
    path = tmp_path / "depo.sqlite"
    stored(path, BASE)
    ahead, behind = loaded(path), loaded(path)
    saved(path, ahead, bought(BASE, "b"))
    before = path.read_bytes()

    result = save(path, behind, bought(BASE, "c"))

    assert result.outcome is StoreOutcome.STALE_WRITE and result.message == "eski yazım"
    assert result.state is None
    assert path.read_bytes() == before


def test_write_from_the_last_save_is_not_stale(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    state = stored(path, BASE)

    state = saved(path, state, bought(BASE, "b"))

    saved(path, state, bought(bought(BASE, "b"), "c"))


def test_close_after_a_saved_order_keeps_every_row(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    state = stored(path, BASE)
    ordered = sell_placed(BASE)
    state = saved(path, state, ordered)

    final = sell_recorded(ordered, "cx-a")
    saved(path, state, final)

    assert snapshot(loaded(path)) == snapshot(final)
