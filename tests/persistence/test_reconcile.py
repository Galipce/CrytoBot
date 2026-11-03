"""Spec 0011 AC-7 (R-7, R-8): geçerli ama çelişen durum yüklenir, işaret ve kimlik taşır (BR-11)."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from crytobot.execution import OrderStatus
from crytobot.persistence import StoreOutcome, load_store
from crytobot.portfolio import EMPTY_LEDGER, Fill, record_fill
from tests.persistence.chain import (
    EMPTY_WORLD,
    T1,
    World,
    bought,
    created,
    full_world,
    loaded,
    opened,
    placed,
    recorded,
    save,
    sell_placed,
    snapshot,
    sold,
    stored,
)


def without_order(world: World, client_order_id: str) -> World:
    orders = {k: v for k, v in world.execution.orders.items() if k != client_order_id}
    return replace(world, execution=replace(world.execution, orders=MappingProxyType(orders)))


def with_order(world: World, client_order_id: str, **changes: Any) -> World:
    order = replace(world.execution.orders[client_order_id], **changes)
    orders = {**world.execution.orders, client_order_id: order}
    return replace(world, execution=replace(world.execution, orders=MappingProxyType(orders)))


def ledger_without_order() -> World:
    world = bought(opened())
    return without_order(world, "cb-a")


def rejected_but_recorded() -> World:
    return with_order(
        bought(opened()), "cb-a", status=OrderStatus.REJECTED, fill_price=None, fee=None
    )


def unknown_but_recorded() -> World:
    world = with_order(
        bought(opened()), "cb-a", status=OrderStatus.UNKNOWN, fill_price=None, fee=None
    )
    quote = {"cb-a": (Decimal("100"), Decimal("0.1"))}
    return replace(world, execution=replace(world.execution, quotes=MappingProxyType(quote)))


def filled_but_ledger_refused() -> World:
    """0010 R-6: emir doldu, defter reddetti (yetersiz bakiye)."""
    world = placed(opened(Decimal("1")), "a", amount="2.50")
    order = world.execution.orders["cb-a"]
    fill = Fill(
        "cb-a",
        order.pair,
        order.side,
        order.amount,
        order.fill_price,
        order.fee,
        Decimal("95"),
        Decimal("110"),
        T1,
    )
    assert not record_fill(world.ledger, fill).accepted
    return world


CONFLICTS: dict[str, tuple[World, tuple[str, ...]]] = {
    "filled_buy_without_record": (placed(opened()), ("cb-a",)),
    "filled_buy_ledger_refused": (filled_but_ledger_refused(), ("cb-a",)),
    "filled_close_without_record": (sell_placed(bought(opened())), ("cx-a",)),
    "position_without_order": (ledger_without_order(), ("cb-a",)),
    "position_order_rejected": (rejected_but_recorded(), ("cb-a",)),
    "position_order_unknown": (unknown_but_recorded(), ("cb-a",)),
    "closure_without_order": (without_order(sold(bought(opened())), "cx-a"), ("cx-a",)),
    "closed_position_without_order": (without_order(sold(bought(opened())), "cb-a"), ("cb-a",)),
    "amount_differs": (with_order(bought(opened()), "cb-a", amount=Decimal("3")), ("cb-a",)),
    "fill_price_differs": (
        with_order(bought(opened()), "cb-a", fill_price=Decimal("3")),
        ("cb-a",),
    ),
    "fee_differs": (with_order(bought(opened()), "cb-a", fee=Decimal("3")), ("cb-a",)),
    "close_amount_differs": (
        with_order(sold(bought(opened())), "cx-a", amount=Decimal("3")),
        ("cx-a",),
    ),
    "close_price_differs": (
        with_order(sold(bought(opened())), "cx-a", fill_price=Decimal("3")),
        ("cx-a",),
    ),
    "close_fee_differs": (
        with_order(sold(bought(opened())), "cx-a", fee=Decimal("3")),
        ("cx-a",),
    ),
}


@pytest.mark.parametrize("case", list(CONFLICTS))
def test_conflict_is_loaded_with_a_flag_and_its_ids(tmp_path: Path, case: str) -> None:
    path = tmp_path / "depo.sqlite"
    world, expected = CONFLICTS[case]
    stored(path, world)

    result = load_store(path, "paper")

    assert result.outcome is StoreOutcome.LOADED
    assert result.conflicts == expected and not result.reconciled
    assert "mutabakat tutmuyor" in result.message
    assert all(cid in result.message for cid in expected)
    assert result.state is not None
    assert snapshot(result.state) == snapshot(world)


def test_flagged_state_can_be_saved_and_keeps_its_flag(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    world = placed(opened())

    result = save(path, created(path), world)

    assert result.outcome is StoreOutcome.SAVED
    assert result.conflicts == ("cb-a",)
    assert "mutabakat tutmuyor" in result.message


def test_flag_clears_once_the_ledger_catches_up(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    state = stored(path, placed(opened()))

    result = save(path, state, recorded(placed(opened()), "cb-a"))

    assert result.outcome is StoreOutcome.SAVED and result.reconciled
    assert load_store(path, "paper").reconciled


@pytest.mark.parametrize(
    "world",
    [EMPTY_WORLD, opened(), bought(opened()), sold(bought(opened())), full_world()],
    ids=["empty", "opened", "bought", "sold", "full"],
)
def test_consistent_state_has_no_flag(tmp_path: Path, world: World) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, world)

    result = load_store(path, "paper")

    assert result.reconciled and result.conflicts == ()
    assert "mutabakat" not in result.message


def test_empty_store_has_no_flag(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    created(path)

    assert load_store(path, "paper").reconciled


def test_trailing_zero_is_no_money_difference(tmp_path: Path) -> None:
    """R-7 sayısaldır: `2.50` ile `2.5` aynı miktardır."""
    path = tmp_path / "depo.sqlite"
    stored(path, with_order(bought(opened()), "cb-a", amount=Decimal("2.5")))

    assert load_store(path, "paper").reconciled


def test_many_conflicts_stay_short_in_the_message(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    world = opened()
    for i in range(50):
        world = placed(world, f"n{i}", amount="0.5")
    stored(path, world)

    result = load_store(path, "paper")

    assert len(result.conflicts) == 50
    assert len(result.message) < 200
    assert "47 kimlik daha" in result.message


def test_ledger_only_state_with_empty_ledger_is_loaded(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    state = stored(path, replace(placed(opened()), ledger=opened().ledger))

    assert loaded(path).execution.orders.keys() == state.execution.orders.keys()
    assert state.ledger != EMPTY_LEDGER
