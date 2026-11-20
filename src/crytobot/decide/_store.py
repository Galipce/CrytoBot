"""Karar kaydı (spec 0059 R-5, AC-5; plan Risk 7): yalnız eklenen SQLite deposu.

`turns` tur başına bir satır (tur anı tekil), `decisions` coin başına; ikisi tek işlemde yazılır,
yarım tur kalmaz. Ham yanıt metni ve haber metni hiç yazılmaz: yalnız ayrıştırılmış alanlar.
Güncelleme ve silme tetikleyiciyle reddedilir. Durum komutu `mode=ro` ile okur (dosya oluşturmaz).
"""

import json
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final

from crytobot.decide._validate import Decision, Status

FORMAT_VERSION: Final = "1"

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL UNIQUE,
    model TEXT NOT NULL,
    prompt_fingerprint TEXT NOT NULL,
    input_fingerprint TEXT,
    outcome TEXT NOT NULL,
    called INTEGER NOT NULL,
    reason TEXT,
    ended_at TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    turn_id INTEGER NOT NULL REFERENCES turns(id),
    coin TEXT NOT NULL,
    status TEXT NOT NULL,
    action TEXT,
    entry_low REAL,
    entry_high REAL,
    stop REAL,
    target REAL,
    valid_hours INTEGER,
    confidence INTEGER,
    reasons TEXT NOT NULL,
    reason TEXT,
    UNIQUE (turn_id, coin)
);
CREATE TRIGGER IF NOT EXISTS turns_no_update BEFORE UPDATE ON turns
BEGIN SELECT RAISE(ABORT, 'turns are append-only'); END;
CREATE TRIGGER IF NOT EXISTS turns_no_delete BEFORE DELETE ON turns
BEGIN SELECT RAISE(ABORT, 'turns are append-only'); END;
CREATE TRIGGER IF NOT EXISTS decisions_no_update BEFORE UPDATE ON decisions
BEGIN SELECT RAISE(ABORT, 'decisions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS decisions_no_delete BEFORE DELETE ON decisions
BEGIN SELECT RAISE(ABORT, 'decisions are append-only'); END;
"""


class DecideStoreError(Exception):
    """Karar kaydı açılamıyor, okunamıyor ya da yazılamıyor."""


@dataclass(frozen=True)
class Turn:
    """Bir turun kaydı. `outcome`: `ok`, `şema dışı`, `sınır`, `kota bekleniyor`, `veri yok` ya da
    çağrı sınıfı (`timeout`, `no_session`, `quota`, `unknown`, `stopped`)."""

    at: datetime
    model: str
    prompt_fingerprint: str
    input_fingerprint: str | None
    outcome: str
    called: bool
    decisions: tuple[Decision, ...]
    reason: str | None = None
    ended_at: datetime | None = None  # the call's end (quota wait is derived from it, R-3)


def _text(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _check_format(connection: sqlite3.Connection) -> None:
    row = connection.execute("SELECT value FROM meta WHERE name = 'format'").fetchone()
    if row is None or row[0] != FORMAT_VERSION:
        raise DecideStoreError("karar kaydının biçimi tanınmıyor")


class DecideStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @classmethod
    def open(cls, path: str) -> "DecideStore":
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(path, timeout=0, isolation_level=None)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(_SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO meta (name, value) VALUES ('format', ?)", (FORMAT_VERSION,)
            )
            _check_format(connection)
        except (sqlite3.Error, OSError):
            if connection is not None:
                connection.close()
            raise DecideStoreError("karar kaydı açılamıyor") from None
        except DecideStoreError:
            if connection is not None:
                connection.close()
            raise
        return cls(connection)

    def close(self) -> None:
        self._connection.close()

    def has_turn(self, at: datetime) -> bool:
        try:
            row = self._connection.execute("SELECT 1 FROM turns WHERE at = ?", (_text(at),))
            return row.fetchone() is not None
        except sqlite3.Error:
            raise DecideStoreError("karar kaydı okunamıyor") from None

    def calls_on(self, day: date) -> int:
        """O UTC gününde Claude'a giden çağrı sayısı (başarılı ya da başarısız)."""
        try:
            rows = self._connection.execute("SELECT at FROM turns WHERE called = 1").fetchall()
        except sqlite3.Error:
            raise DecideStoreError("karar kaydı okunamıyor") from None
        return sum(
            datetime.fromisoformat(str(row[0])).astimezone(UTC).date() == day for row in rows
        )

    def last_quota_at(self) -> datetime | None:
        """Son kota yanıtlı çağrının bitişi (0051 R-5 gibi kayıttan; yeniden başlatmada da)."""
        try:
            row = self._connection.execute(
                "SELECT MAX(ended_at) FROM turns WHERE outcome = 'quota'"
            ).fetchone()
        except sqlite3.Error:
            raise DecideStoreError("karar kaydı okunamıyor") from None
        return None if row is None or row[0] is None else datetime.fromisoformat(str(row[0]))

    def write(self, turn: Turn) -> None:
        connection = self._connection
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.Error:
            raise DecideStoreError("karar kaydı yazılamıyor") from None
        try:
            cursor = connection.execute(
                "INSERT INTO turns (at, model, prompt_fingerprint, input_fingerprint, outcome,"
                " called, reason, ended_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _text(turn.at),
                    turn.model,
                    turn.prompt_fingerprint,
                    turn.input_fingerprint,
                    turn.outcome,
                    int(turn.called),
                    turn.reason,
                    None if turn.ended_at is None else _text(turn.ended_at),
                ),
            )
            turn_id = cursor.lastrowid
            for d in turn.decisions:
                connection.execute(
                    "INSERT INTO decisions (turn_id, coin, status, action, entry_low, entry_high,"
                    " stop, target, valid_hours, confidence, reasons, reason)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        turn_id,
                        d.coin,
                        d.status.value,
                        d.action,
                        d.entry_low,
                        d.entry_high,
                        d.stop,
                        d.target,
                        d.valid_hours,
                        d.confidence,
                        json.dumps(list(d.reasons), ensure_ascii=False),
                        d.reason,
                    ),
                )
            connection.execute("COMMIT")
        except BaseException as error:  # a forced stop as well: nothing half-written (AC-8)
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            if isinstance(error, sqlite3.IntegrityError):
                raise DecideStoreError("tur zaten yazılmış") from None
            if isinstance(error, sqlite3.Error):
                raise DecideStoreError("karar kaydı yazılamıyor") from None
            raise


@dataclass(frozen=True)
class TurnView:
    at: datetime
    outcome: str
    called: bool
    reason: str | None


@dataclass(frozen=True)
class DecisionView:
    at: datetime
    coin: str
    status: str
    entry_low: float | None
    entry_high: float | None
    stop: float | None
    target: float | None
    reason: str | None


@dataclass(frozen=True)
class DecideSnapshot:
    turns: tuple[TurnView, ...]
    latest: tuple[DecisionView, ...]  # coin başına son karar
    counts: dict[str, int]  # durum → sayı (bütün kayıt)
    calls_today: int  # verilen UTC gününde Claude'a giden çağrı (bütün kayıt)


def _moment(value: object) -> datetime:
    return datetime.fromisoformat(str(value))


def read_decide_snapshot(path: str, today: date, last: int = 5) -> DecideSnapshot | None:
    """Kayıt yoksa `None` (dosya oluşturulmaz); okunamıyorsa `DecideStoreError`."""
    if not Path(path).is_file():
        return None
    uri = f"{Path(path).resolve().as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=0)) as connection:
            _check_format(connection)
            turns = connection.execute(
                "SELECT at, outcome, called, reason FROM turns ORDER BY at DESC LIMIT ?", (last,)
            ).fetchall()
            latest = connection.execute(
                "SELECT t.at, d.coin, d.status, d.entry_low, d.entry_high, d.stop, d.target,"
                " d.reason"
                " FROM decisions d JOIN turns t ON t.id = d.turn_id"
                " WHERE t.at = (SELECT MAX(t2.at) FROM turns t2 JOIN decisions d2"
                " ON t2.id = d2.turn_id WHERE d2.coin = d.coin) ORDER BY d.coin"
            ).fetchall()
            counts = dict(
                connection.execute("SELECT status, COUNT(*) FROM decisions GROUP BY status")
            )
            called = connection.execute("SELECT at FROM turns WHERE called = 1").fetchall()
            calls_today = sum(_moment(row[0]).astimezone(UTC).date() == today for row in called)
    except (sqlite3.Error, ValueError, TypeError):
        raise DecideStoreError("karar kaydı okunamıyor") from None
    return DecideSnapshot(
        tuple(
            TurnView(_moment(a), str(o), bool(c), None if r is None else str(r))
            for a, o, c, r in turns
        ),
        tuple(
            DecisionView(_moment(a), str(c), str(s), lo, hi, st, tg, None if r is None else str(r))
            for a, c, s, lo, hi, st, tg, r in latest
        ),
        {str(k): int(v) for k, v in counts.items()},
        calls_today,
    )


def statuses() -> Sequence[str]:
    return tuple(status.value for status in Status)
