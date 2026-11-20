"""Spec 0060 plan step 1: karar kaydının salt okunur okuyucusu."""

import sqlite3
from pathlib import Path

import pytest

from crytobot.decide import (
    PROMPT_FINGERPRINT,
    DecideStore,
    DecideStoreError,
    Decision,
    Status,
    Turn,
    read_decision_record,
)
from tests.decide.helpers import BOUNDARY, HOUR


def test_reads_turns_and_decisions(tmp_path: Path) -> None:
    path = str(tmp_path / "decide.db")
    store = DecideStore.open(path)
    buy = Decision("SOL", Status.BUY, 98.0, 100.0, 95.0, 105.0, 4, 3, ("a",), action="al")
    waited = Decision("ETH", Status.WAIT, reason="timeout")
    store.write(Turn(BOUNDARY, "m", PROMPT_FINGERPRINT, None, "ok", True, (buy,)))
    store.write(Turn(BOUNDARY + HOUR, "m", PROMPT_FINGERPRINT, None, "timeout", True, (waited,)))
    store.close()
    before = Path(path).read_bytes()
    record = read_decision_record(path)
    assert record is not None and record.skipped == 0
    assert [(t.at, t.outcome, t.called) for t in record.turns] == [
        (BOUNDARY, "ok", True),
        (BOUNDARY + HOUR, "timeout", True),
    ]
    sol, eth = record.decisions
    assert (sol.coin, sol.status, sol.action, sol.entry_high, sol.valid_hours) == (
        "SOL",
        "al",
        "al",
        100.0,
        4,
    )
    assert (eth.status, eth.action) == ("bekle", None)  # a no-decision turn's wait
    assert Path(path).read_bytes() == before


def test_missing_and_unknown(tmp_path: Path) -> None:
    assert read_decision_record(str(tmp_path / "none.db")) is None
    assert not (tmp_path / "none.db").exists()
    path = tmp_path / "other.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO meta VALUES ('format', '9')")
    with pytest.raises(DecideStoreError, match="biçimi tanınmıyor"):
        read_decision_record(str(path))
