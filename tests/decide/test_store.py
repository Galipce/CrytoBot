"""Spec 0059 AC-5: kayıt yalnız eklenir; ham yanıt yok; aynı tur iki kez yazılmaz; yarım tur yok."""

import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from crytobot.decide import (
    PROMPT_FINGERPRINT,
    DecideStore,
    DecideStoreError,
    Decision,
    Status,
    Turn,
    read_decide_snapshot,
)
from tests.decide.helpers import BOUNDARY, HOUR

BUY = Decision("SOL", Status.BUY, 98.0, 100.0, 95.0, 105.0, 4, 3, ("rsi14 50 üstü",), action="al")
DROPPED = Decision("ETH", Status.INCONSISTENT, 1.0, 2.0, 3.0, 4.0, 4, 3, ("x",), "stop", "al")


def turn(
    at: datetime = BOUNDARY,
    decisions: tuple[Decision, ...] = (BUY, DROPPED),
    called: bool = True,
    outcome: str = "ok",
) -> Turn:
    return Turn(at, "claude-sonnet-5-5", PROMPT_FINGERPRINT, "f" * 64, outcome, called, decisions)


def test_append_only_no_reply_text(tmp_path: Path) -> None:
    path = str(tmp_path / "decide.db")
    store = DecideStore.open(path)
    store.write(turn())
    store.close()
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT coin, status, action, stop, reasons, reason FROM decisions ORDER BY coin"
        ).fetchall()
        assert rows == [
            ("ETH", "tutarsız", "al", 3.0, '["x"]', "stop"),
            ("SOL", "al", "al", 95.0, '["rsi14 50 üstü"]', None),
        ]
        columns = {row[1] for row in connection.execute("PRAGMA table_info(turns)")}
        assert columns == {
            "id", "at", "model", "prompt_fingerprint", "input_fingerprint", "outcome", "called",
            "reason",
        }  # fmt: skip
        for statement in ("UPDATE turns SET outcome = 'x'", "DELETE FROM decisions"):
            with pytest.raises(sqlite3.DatabaseError, match="append-only"):
                connection.execute(statement)


def test_turn_written_once(tmp_path: Path) -> None:
    store = DecideStore.open(str(tmp_path / "decide.db"))
    store.write(turn())
    assert store.has_turn(BOUNDARY) and not store.has_turn(BOUNDARY + HOUR)
    with pytest.raises(DecideStoreError, match="tur zaten yazılmış"):
        store.write(turn())
    store.close()


def test_forced_stop_leaves_no_half_turn(tmp_path: Path) -> None:
    class Boom(tuple[str, ...]):
        def __iter__(self) -> Iterator[str]:
            raise KeyboardInterrupt  # a second Ctrl+C in the middle of the write

    path = str(tmp_path / "decide.db")
    store = DecideStore.open(path)
    broken = Decision("ETH", Status.WAIT, reasons=Boom(), action="bekle")
    with pytest.raises(KeyboardInterrupt):
        store.write(turn(decisions=(BUY, broken)))
    assert not store.has_turn(BOUNDARY)
    store.close()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM decisions").fetchone() == (0,)


def test_calls_counted_per_utc_day(tmp_path: Path) -> None:
    store = DecideStore.open(str(tmp_path / "decide.db"))
    store.write(turn())
    store.write(turn(at=BOUNDARY + HOUR, called=False, outcome="sınır", decisions=()))
    store.write(turn(at=BOUNDARY + 20 * HOUR, decisions=()))  # next UTC day
    assert store.calls_on(BOUNDARY.date()) == 1
    store.close()


def test_snapshot_read_only_and_missing(tmp_path: Path) -> None:
    path = tmp_path / "decide.db"
    assert read_decide_snapshot(str(path), BOUNDARY.date()) is None
    assert not path.exists()  # status never creates the record
    store = DecideStore.open(str(path))
    store.write(turn())
    store.write(turn(at=BOUNDARY + HOUR, decisions=(Decision("SOL", Status.WAIT, action="bekle"),)))
    store.close()
    snapshot = read_decide_snapshot(str(path), BOUNDARY.date())
    assert snapshot is not None
    assert [t.at for t in snapshot.turns] == [BOUNDARY + HOUR, BOUNDARY]
    assert {d.coin: d.status for d in snapshot.latest} == {"SOL": "bekle", "ETH": "tutarsız"}
    assert snapshot.counts == {"al": 1, "tutarsız": 1, "bekle": 1}
    assert snapshot.calls_today == 2


def test_unknown_format_refused(tmp_path: Path) -> None:
    path = tmp_path / "decide.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO meta VALUES ('format', '9')")
    with pytest.raises(DecideStoreError, match="biçimi tanınmıyor"):
        DecideStore.open(str(path))
    with pytest.raises(DecideStoreError, match="biçimi tanınmıyor"):
        read_decide_snapshot(str(path), BOUNDARY.date())
