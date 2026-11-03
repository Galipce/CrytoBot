"""Spec 0011 AC-5 (R-5): hata ve süreç ölümü sonrası depoda önceki ya da yeni durumun tamamı."""

import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from crytobot.persistence import StoreOutcome
from tests.persistence.chain import (
    bought,
    full_world,
    loaded,
    opened,
    save,
    saved,
    seen,
    snapshot,
    stored,
)

ROOT = Path(__file__).resolve().parents[2]

# dies inside the real write, with SQLite's cache forced to spill: a hot journal is left behind
DIE_IN_TRANSACTION = """
import os, sys
from contextlib import closing
from pathlib import Path
from crytobot.persistence import _store
from crytobot.persistence._codec import encode_entry, encode_orders, encode_risk, encode_summary
from tests.persistence.chain import bought, loaded, opened, seen

path = Path(sys.argv[1])
world = seen(opened(), "100")
for i in range(150):
    world = bought(world, f"n{i}", amount="0.5")
image = _store._Image(
    [encode_entry(e) for e in world.ledger.entries],
    encode_orders(world.execution),
    encode_summary(world.ledger),
    encode_risk(world.risk),
)
database = _store._connect(path)
database.execute("PRAGMA cache_size=1")
database.execute("BEGIN EXCLUSIVE")
stored_entries = _store._rows(database, "entries")
stored_orders = _store._rows(database, "orders")
_store._write(database, stored_entries, stored_orders, image, 2)
os._exit(9)
"""

# saves forever and reports each revision that was really committed
SAVE_FOREVER = """
import sys
from pathlib import Path
from crytobot.persistence import StoreOutcome
from tests.persistence.chain import bought, created, opened, save, saved

path = Path(sys.argv[1])
state = saved(path, created(path), opened())
world = opened()
i = 0
while True:
    world = bought(world, f"n{i}", amount="0.5")
    result = save(path, state, world)
    assert result.outcome is StoreOutcome.SAVED, result.message
    state = result.state
    print(i, flush=True)
    i += 1
"""


def child(script: str, path: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", script, str(path)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


@pytest.mark.parametrize(
    "trigger",
    [
        "BEFORE INSERT ON entries",
        "BEFORE INSERT ON orders",
        "BEFORE UPDATE ON meta",
    ],
)
def test_injected_write_error_keeps_the_previous_state(tmp_path: Path, trigger: str) -> None:
    path = tmp_path / "depo.sqlite"
    before = bought(opened())
    state = stored(path, before)
    with closing(sqlite3.connect(path)) as database:
        database.execute(f"CREATE TRIGGER fail {trigger} BEGIN SELECT RAISE(ABORT, 'disk'); END")
        database.commit()

    result = save(path, state, seen(bought(before, "b"), "100"))

    assert result.outcome is StoreOutcome.WRITE_FAILED and result.message == "yazılamadı"
    assert result.state is None
    after = loaded(path)
    assert snapshot(after) == snapshot(before)
    assert after.revision == state.revision


def test_failed_write_can_be_retried_once_the_cause_is_gone(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    before = bought(opened())
    state = stored(path, before)
    with closing(sqlite3.connect(path)) as database:
        database.execute(
            "CREATE TRIGGER fail BEFORE UPDATE ON meta BEGIN SELECT RAISE(ABORT, 'disk'); END"
        )
        database.commit()
    next_world = bought(before, "b")
    assert save(path, state, next_world).outcome is StoreOutcome.WRITE_FAILED
    with closing(sqlite3.connect(path)) as database:
        database.execute("DROP TRIGGER fail")
        database.commit()

    saved(path, state, next_world)

    assert snapshot(loaded(path)) == snapshot(next_world)


def test_process_killed_inside_the_transaction_leaves_the_previous_state(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    world = opened()
    stored(path, world)
    journal = Path(f"{path}-journal")

    process = child(DIE_IN_TRANSACTION, path)
    _, stderr = process.communicate(timeout=60)

    assert process.returncode == 9, stderr
    assert journal.exists(), "the test needs a hot journal to prove the rollback"
    state = loaded(path)
    assert snapshot(state) == snapshot(world)
    assert state.revision == 1
    assert not journal.exists()
    saved(path, state, full_world())


@pytest.mark.parametrize("reports", [1, 3, 6])
def test_process_killed_while_saving_leaves_a_whole_state(tmp_path: Path, reports: int) -> None:
    path = tmp_path / "depo.sqlite"
    process = child(SAVE_FOREVER, path)
    assert process.stdout is not None
    for _ in range(reports):
        assert process.stdout.readline().strip(), "the child stopped saving"

    process.kill()
    process.communicate(timeout=60)

    state = loaded(path)
    fills = state.revision - 1  # revision 1 is the opening alone
    assert fills >= reports
    expected = opened()
    for i in range(fills):
        expected = bought(expected, f"n{i}", amount="0.5")
    assert snapshot(state) == snapshot(expected)
