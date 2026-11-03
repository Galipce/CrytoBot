"""Spec 0011 AC-10 (R-10): hatalar adıyla döner, istisna yok, depo değişmez, mesaj kısa, sırsız."""

import gc
import sqlite3
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import closing
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.persistence import StoreOutcome, _store, create_store, load_store, save_store
from tests.persistence.chain import (
    T1,
    bought,
    created,
    full_world,
    loaded,
    opened,
    save,
    seen,
    stored,
)

HOLD_EXCLUSIVE = """
import sqlite3, sys
database = sqlite3.connect(sys.argv[1], isolation_level=None)
database.execute("BEGIN EXCLUSIVE")
print("tutuyorum", flush=True)
sys.stdin.read()
"""
LONG_TEXT = "x" * 1_000_000
BUSY_LIMIT_S = 5.0


def holder(path: Path) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [sys.executable, "-c", HOLD_EXCLUSIVE, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "tutuyorum"
    return process


def test_store_held_by_another_process_is_busy_within_the_limit(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    state = stored(path, opened())
    process = holder(path)
    try:
        start = time.perf_counter()
        loading = load_store(path, "paper")
        loading_took = time.perf_counter() - start

        start = time.perf_counter()
        saving = save(path, state, bought(opened()))
        saving_took = time.perf_counter() - start
    finally:
        process.communicate(timeout=30)

    assert loading.outcome is StoreOutcome.BUSY and loading.message == "depo meşgul"
    assert loading.state is None
    assert saving.outcome is StoreOutcome.BUSY and saving.state is None
    assert loading_took <= BUSY_LIMIT_S and saving_took <= BUSY_LIMIT_S
    assert loaded(path).revision == state.revision


@pytest.fixture
def connections(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[sqlite3.Connection]]:
    """Depoda açılan bağlantılar; döngüsel GC kapalı: kapatmayan kodu çöp toplayıcı kurtarmasın."""
    made: list[sqlite3.Connection] = []
    real = sqlite3.connect

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        made.append(real(*args, **kwargs))
        return made[-1]

    monkeypatch.setattr(sqlite3, "connect", connect)
    gc.disable()
    try:
        yield made
    finally:
        gc.enable()


def assert_all_closed(made: list[sqlite3.Connection]) -> None:
    assert made
    for connection in made:
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")


def test_busy_store_keeps_no_connection_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, connections: list[sqlite3.Connection]
) -> None:
    path = tmp_path / "depo.sqlite"
    state = stored(path, opened())
    monkeypatch.setattr(_store, "BUSY_WAIT_S", 0.2)
    process = holder(path)
    try:
        connections.clear()
        loading = load_store(path, "paper")
        saving = save(path, state, bought(opened()))
    finally:
        process.communicate(timeout=30)

    assert loading.outcome is StoreOutcome.BUSY and saving.outcome is StoreOutcome.BUSY
    assert_all_closed(connections)
    path.unlink()  # Windows refuses this while a handle is open
    assert not path.exists()


def test_file_that_is_no_store_keeps_no_connection_open(
    tmp_path: Path, connections: list[sqlite3.Connection]
) -> None:
    path = tmp_path / "notlar.txt"
    path.write_bytes(b"notlarim" * 200)

    result = load_store(path, "paper")

    assert result.outcome is StoreOutcome.UNREADABLE
    assert_all_closed(connections)
    path.unlink()
    assert not path.exists()


def test_create_failing_on_its_first_pragma_leaves_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, connections: list[sqlite3.Connection]
) -> None:
    class FailingPragma(sqlite3.Connection):
        def execute(self, sql: str, *args: Any) -> sqlite3.Cursor:
            if sql.startswith("PRAGMA"):
                raise sqlite3.OperationalError("database is locked")
            return super().execute(sql, *args)

    tracked = sqlite3.connect

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        return tracked(*args, factory=FailingPragma, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    path = tmp_path / "depo.sqlite"

    result = create_store(path, "paper")

    assert result.outcome is StoreOutcome.WRITE_FAILED
    assert_all_closed(connections)
    assert not path.exists()


def test_unreachable_path_is_named(tmp_path: Path) -> None:
    state = created(tmp_path / "depo.sqlite")

    assert load_store(tmp_path, "paper").outcome is StoreOutcome.UNREADABLE
    assert save(tmp_path, state, opened()).outcome is StoreOutcome.WRITE_FAILED


def test_save_to_a_missing_store_creates_nothing(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    state = created(tmp_path / "baska.sqlite")

    result = save(path, state, opened())

    assert result.outcome is StoreOutcome.NOT_FOUND and result.message == "depo yok"
    assert not path.exists()


def test_save_to_a_file_that_is_no_store_leaves_it_alone(tmp_path: Path) -> None:
    path = tmp_path / "notlar.txt"
    path.write_bytes(b"notlarim" * 200)
    state = created(tmp_path / "depo.sqlite")

    result = save(path, state, opened())

    assert result.outcome is StoreOutcome.WRITE_FAILED and result.state is None
    assert path.read_bytes() == b"notlarim" * 200


GOOD = bought(opened())
BAD_WRITES: dict[str, tuple[Any, Any, Any]] = {
    "ledger_not_a_ledger": ("defter", GOOD.execution, GOOD.risk),
    "balance_differs": (replace(GOOD.ledger, balance=Decimal("1")), GOOD.execution, GOOD.risk),
    "orders_not_state": (GOOD.ledger, "emirler", GOOD.risk),
    "unknown_without_quote": (
        full_world().ledger,
        replace(full_world().execution, quotes={}),
        full_world().risk,
    ),
    "risk_not_state": (GOOD.ledger, GOOD.execution, "risk"),
    "risk_impossible": (
        GOOD.ledger,
        GOOD.execution,
        replace(seen(GOOD, "100", T1).risk, peak_equity=Decimal("1")),
    ),
}


@pytest.mark.parametrize("case", list(BAD_WRITES))
def test_state_that_could_not_be_read_back_is_never_written(tmp_path: Path, case: str) -> None:
    path = tmp_path / "depo.sqlite"
    state = stored(path, opened())
    before = path.read_bytes()
    ledger, execution, risk = BAD_WRITES[case]

    result = save_store(path, state, ledger, execution, risk)

    assert result.outcome is StoreOutcome.INVALID_INPUT and result.state is None
    assert result.message.startswith("geçersiz girdi")
    assert len(result.message) < 200
    assert path.read_bytes() == before


def test_long_values_do_not_reach_the_message(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    state = stored(path, opened())
    hand_built: Any = replace  # deliberately a wrong field type
    entry = hand_built(GOOD.ledger.entries[1], usdt=LONG_TEXT)
    ledger = replace(GOOD.ledger, entries=(GOOD.ledger.entries[0], entry))

    result = save_store(path, state, ledger, GOOD.execution, GOOD.risk)

    assert result.outcome is StoreOutcome.INVALID_INPUT
    assert LONG_TEXT not in result.message and len(result.message) < 200


def test_message_never_carries_the_path(tmp_path: Path) -> None:
    secret = tmp_path / "gizli-klasor"
    results = [
        load_store(secret / "depo.sqlite", "paper"),
        load_store(tmp_path, "paper"),
    ]

    assert all("gizli" not in result.message for result in results)


@pytest.mark.parametrize("base", [None, "taban", 1], ids=["none", "text", "int"])
def test_base_that_is_no_stored_state_is_invalid(tmp_path: Path, base: Any) -> None:
    path = tmp_path / "depo.sqlite"
    created(path)

    result = save_store(path, base, opened().ledger, opened().execution, opened().risk)

    assert result.outcome is StoreOutcome.INVALID_INPUT


def test_save_with_no_path_is_invalid(tmp_path: Path) -> None:
    state = created(tmp_path / "depo.sqlite")

    result = save_store(None, state, opened().ledger, opened().execution, opened().risk)

    assert result.outcome is StoreOutcome.INVALID_INPUT


@pytest.mark.parametrize(
    ("statement", "outcome"),
    [
        ("UPDATE meta SET value = '{bozuk' WHERE key = 'risk'", StoreOutcome.UNREADABLE),
        ("DELETE FROM meta WHERE key = 'risk'", StoreOutcome.WRITE_FAILED),
        ("DELETE FROM meta WHERE key = 'mode'", StoreOutcome.UNREADABLE),
        ("DELETE FROM meta WHERE key = 'ledger'", StoreOutcome.UNREADABLE),
        ("UPDATE meta SET value = '{bozuk' WHERE key = 'ledger'", StoreOutcome.UNREADABLE),
        ("UPDATE meta SET value = '[]' WHERE key = 'ledger'", StoreOutcome.UNREADABLE),
        ("DELETE FROM entries WHERE seq = 0", StoreOutcome.UNREADABLE),
        ("DROP TABLE orders", StoreOutcome.WRITE_FAILED),
        ("UPDATE orders SET row = '{bozuk' WHERE seq = 0", StoreOutcome.HISTORY_IMMUTABLE),
        ("UPDATE orders SET row = '[]' WHERE seq = 0", StoreOutcome.HISTORY_IMMUTABLE),
    ],
    ids=[
        "risk_broken",
        "risk_lost",
        "mode_lost",
        "ledger_lost",
        "ledger_broken",
        "ledger_short",
        "row_lost",
        "table_lost",
        "order_broken",
        "order_empty",
    ],
)
def test_save_over_a_damaged_store_writes_nothing(
    tmp_path: Path, statement: str, outcome: StoreOutcome
) -> None:
    path = tmp_path / "depo.sqlite"
    state = stored(path, bought(opened()))
    with closing(sqlite3.connect(path)) as database:
        database.execute(statement)
        database.commit()
    before = path.read_bytes()

    result = save(path, state, bought(bought(opened()), "b"))

    assert result.outcome is outcome and result.state is None
    assert path.read_bytes() == before


def test_path_as_text_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "depo adı %20 #1.sqlite"
    state = created(path)

    assert save(path, state, opened()).outcome is StoreOutcome.SAVED
    assert load_store(str(path), "paper").outcome is StoreOutcome.LOADED
