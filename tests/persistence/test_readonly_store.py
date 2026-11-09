"""Spec 0031 AC-3 (R-2, R-4): Salt-okunur SQLite bağlantı ve bekleme testleri."""

import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from crytobot.persistence import (
    StoreOutcome,
    create_store,
    load_store,
)
from tests.persistence.chain import (
    bought,
    loaded,
    opened,
    save,
    stored,
)

HOLD_EXCLUSIVE = """
import sqlite3, sys
database = sqlite3.connect(sys.argv[1], isolation_level=None)
database.execute("BEGIN EXCLUSIVE")
print("tutuyorum", flush=True)
sys.stdin.read()
"""


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


def test_load_store_readonly_loads_existing_state(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, opened())

    res = load_store(path, "paper", readonly=True)

    assert res.outcome is StoreOutcome.LOADED
    assert res.state is not None
    assert res.state.mode == "paper"
    assert res.state.revision == 1


def test_load_store_readonly_refuses_invalid_readonly_argument(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, opened())

    for invalid_val in ["true", 1, None, [], {}]:
        res = load_store(path, "paper", readonly=invalid_val)  # type: ignore[arg-type]
        assert res.outcome is StoreOutcome.INVALID_INPUT
        assert res.state is None


def test_load_store_readonly_on_missing_store_returns_not_found(tmp_path: Path) -> None:
    path = tmp_path / "olmayan.sqlite"

    res = load_store(path, "paper", readonly=True)

    assert res.outcome is StoreOutcome.NOT_FOUND
    assert res.state is None


def test_load_store_readonly_when_locked_returns_busy_within_limit(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, opened())
    process = holder(path)
    try:
        start = time.perf_counter()
        res = load_store(path, "paper", readonly=True)
        elapsed = time.perf_counter() - start
    finally:
        process.communicate(timeout=30)

    assert res.outcome is StoreOutcome.BUSY
    assert res.state is None
    assert elapsed <= 5.0
