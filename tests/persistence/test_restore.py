"""Spec 0011 AC-3 (R-3): kaydedilen durum başka bir süreçte birebir aynıdır; tutar `float` olmaz."""

import json
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import pytest

from tests.persistence.chain import (
    T0,
    T1,
    T2,
    World,
    bought,
    full_world,
    loaded,
    opened,
    placed,
    recorded,
    seen,
    snapshot,
    sold,
    stored,
)

ROOT = Path(__file__).resolve().parents[2]
CHILD = """
import sys
from pathlib import Path
from tests.persistence.chain import loaded, snapshot
sys.stdout.buffer.write(snapshot(loaded(Path(sys.argv[1]))).encode("ascii", "backslashreplace"))
"""
NEPAL = timezone(timedelta(hours=5, minutes=45, seconds=15))
LONG_PRICE = "1." + "1" * 26
SIXTY_DIGITS = Decimal("0." + "1" * 60)


def demanding_world() -> World:
    """Alım → defter → gözlem → kapanış → defter: sondaki sıfır, UTC dışı fark, sıra."""
    world = opened(Decimal("9" * 27 + ".1"), T0)
    world = bought(world, "z", amount="1.10", price=LONG_PRICE, at=T1)
    world = bought(world, "a", amount="2.50", price="100.10", at=T1.astimezone(NEPAL))
    world = seen(world, "100000.10", at=T1.astimezone(NEPAL))
    world = sold(world, "cb-z", price="1.5", at=T2)
    return seen(world, "100000.20", at=T2)


def sixty_digit_world() -> World:
    """Defterin taşıyabildiği en uzun değer: dolum fiyatı ve kalan bakiye tam 60 basamak."""
    world = placed(opened(Decimal(1)), "l", amount="1", price="0.5")
    order = replace(world.execution.orders["cb-l"], fill_price=SIXTY_DIGITS, fee=Decimal(0))
    execution = replace(world.execution, orders=MappingProxyType({"cb-l": order}))
    return recorded(replace(world, execution=execution), "cb-l")


@pytest.mark.parametrize("build", [demanding_world, sixty_digit_world])
def test_other_process_restores_exactly(tmp_path: Path, build: Callable[[], World]) -> None:
    path = tmp_path / "depo.sqlite"
    world = build()
    stored(path, world)

    child = subprocess.run(
        [sys.executable, "-c", CHILD, str(path)],
        cwd=ROOT,
        capture_output=True,
        check=False,
        timeout=60,
    )

    assert child.returncode == 0, child.stderr
    assert child.stdout.decode("ascii") == snapshot(world).encode(
        "ascii", "backslashreplace"
    ).decode("ascii")


def test_every_kind_of_record_restores_exactly(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    world = full_world()
    stored(path, world)

    state = loaded(path)

    assert snapshot(state) == snapshot(world)
    assert state.execution.unknown == world.execution.unknown
    assert state.execution.quotes["cb-c"] == world.execution.quotes["cb-c"]


def test_digits_and_offsets_survive_literally(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    world = demanding_world()
    stored(path, world)

    state = loaded(path)

    position = state.ledger.positions["cb-a"]
    assert str(position.amount) == "2.50"
    assert position.opened_at.utcoffset() == NEPAL.utcoffset(None)
    fill = state.execution.orders["cb-z"].fill_price
    assert fill == world.execution.orders["cb-z"].fill_price
    assert fill is not None and len(fill.as_tuple().digits) > 28
    assert list(state.ledger.closures) == ["cx-z"]
    assert list(state.execution.orders) == ["cb-z", "cb-a", "cx-z"]


def test_sixty_digits_survive(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, sixty_digit_world())

    state = loaded(path)

    assert state.ledger.positions["cb-l"].cost_price.as_tuple() == SIXTY_DIGITS.as_tuple()
    assert state.ledger.balance is not None
    assert len(state.ledger.balance.as_tuple().digits) == 60


def test_any_pair_name_round_trips(tmp_path: Path) -> None:
    """Çift adı doğrulanmaz: vekil karakter ya da NUL içeren metin de birebir döner."""
    path = tmp_path / "depo.sqlite"
    world = opened()
    world = placed(world, "a")
    order = world.execution.orders["cb-a"]
    odd = replace(order, pair="BTC\ud800/\0USDT")
    world = replace(
        world,
        execution=replace(world.execution, orders={"cb-a": odd}),
    )
    stored(path, world)

    state = loaded(path)

    assert state.execution.orders["cb-a"].pair == "BTC\ud800/\0USDT"


def test_amounts_are_stored_as_text_never_as_numbers(tmp_path: Path) -> None:
    """R-3: satırlarda JSON sayısı yok; tutar hiçbir aşamada `float` olamaz."""
    path = tmp_path / "depo.sqlite"
    stored(path, full_world())

    with closing(sqlite3.connect(path)) as database:
        rows = [
            row
            for table in ("entries", "orders")
            for (row,) in database.execute(f"SELECT row FROM {table}")
        ]
        meta = [value for (value,) in database.execute("SELECT value FROM meta WHERE key='risk'")]

    def no_number(text: str) -> None:
        def refuse(number: str) -> None:
            raise AssertionError(number)

        json.loads(text, parse_float=refuse, parse_int=refuse)

    for row in rows + meta:
        no_number(row)
    assert rows


def test_a_later_time_keeps_its_own_offset(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    world = seen(opened(), "100", at=datetime(2026, 11, 3, 23, 30, tzinfo=UTC))
    stored(path, world)

    state = loaded(path)

    assert state.risk.last_time == world.risk.last_time
    assert state.risk.last_time is not None
    assert state.risk.last_time.utcoffset() == timedelta(0)
