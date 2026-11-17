"""Skor kaydı: skorlayıcının kendi SQLite deposu (spec 0051 R-1, R-2, R-6, R-8, R-9; plan step 3,
Risk 6).

Her tablo yalnız eklenir; UPDATE ve DELETE tetikleyicilerle reddedilir. `meta` biçimi ve başlangıç
anını bir kez taşır. Bir çağrı süreç başlamadan `calls`'a yazılır, sonucu `call_ends`'e eklenir:
süreç ortada öldürülürse çağrı sayılmış ve sonuçsuz kalır (günlük sınır muhafazakâr). Bir haberin
tek sonucu `results`'tadır (UNIQUE): "skorlandı", "şema dışı" ya da "bayat"; olay skorları ve ret
nedenleri aynı işlemde yazılır. Günlük çağrı sayısı ve kota beklemesi kayıttan türetilir: yeniden
başlatma onları sıfırlamaz. WAL kipi; `timeout=0` ve `closing` (conventions, spec 0011).
"""

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path

FORMAT_VERSION = "1"
_TABLES = ("meta", "calls", "call_ends", "results", "event_scores", "rejections")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY,
    news_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    day TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS call_ends (
    call_id INTEGER PRIMARY KEY REFERENCES calls (id),
    outcome TEXT NOT NULL,
    seconds REAL NOT NULL,
    ended_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
    news_id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    at TEXT NOT NULL,
    call_id INTEGER REFERENCES calls (id),
    model TEXT,
    prompt_fingerprint TEXT,
    context_fingerprint TEXT,
    rejected INTEGER NOT NULL,
    schema_reason TEXT,
    reply_size INTEGER
);
CREATE TABLE IF NOT EXISTS event_scores (
    id INTEGER PRIMARY KEY,
    news_id INTEGER NOT NULL REFERENCES results (news_id),
    coin TEXT NOT NULL,
    name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    severity INTEGER NOT NULL,
    quote TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rejections (
    news_id INTEGER NOT NULL REFERENCES results (news_id),
    reason TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (news_id, reason)
);
""" + "".join(
    f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table}"
    f" BEGIN SELECT RAISE(ABORT, 'score record is append-only'); END;"
    f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table}"
    f" BEGIN SELECT RAISE(ABORT, 'score record is append-only'); END;"
    for table in _TABLES
)


class ScoreStoreError(Exception):
    """Skor kaydı açılamıyor, okunamıyor ya da yazılamıyor."""


class ResultKind(StrEnum):
    SCORED = "skorlandı"
    SCHEMA = "şema dışı"
    STALE = "bayat"


@dataclass(frozen=True)
class EventScore:
    coin: str
    name: str
    event_type: str
    direction: str
    severity: int
    quote: str


@dataclass(frozen=True)
class ScoreResult:
    """Bir haberin tek sonucu. "bayat"ta çağrı, model ve parmak izleri yoktur."""

    news_id: int
    kind: ResultKind
    at: datetime
    model: str | None = None
    prompt_fingerprint: str | None = None
    context_fingerprint: str | None = None
    scores: tuple[EventScore, ...] = ()
    rejections: tuple[tuple[str, int], ...] = ()
    schema_reason: str | None = None
    reply_size: int | None = None


@dataclass(frozen=True)
class CallEnd:
    outcome: str
    seconds: float
    at: datetime


def _text(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _day(moment: datetime) -> str:
    return moment.astimezone(UTC).date().isoformat()


def _check_format(connection: sqlite3.Connection) -> None:
    row = connection.execute("SELECT value FROM meta WHERE name = 'format'").fetchone()
    if row is None or row[0] != FORMAT_VERSION:
        raise ScoreStoreError("skor kaydının biçimi tanınmıyor")


class ScoreStore:
    """Skorlayıcının açık bağlantısı. `open` dosyayı, şemayı ve başlangıç anını (bir kez) yazar."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @classmethod
    def open(cls, path: str, now: datetime) -> "ScoreStore":
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(path, timeout=0, isolation_level=None)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(_SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO meta (name, value) VALUES ('format', ?)", (FORMAT_VERSION,)
            )
            _check_format(connection)
            connection.execute(
                "INSERT OR IGNORE INTO meta (name, value) VALUES ('started_at', ?)", (_text(now),)
            )
        except (sqlite3.Error, OSError):
            if connection is not None:
                connection.close()
            raise ScoreStoreError("skor kaydı açılamıyor") from None
        except ScoreStoreError:
            if connection is not None:
                connection.close()
            raise
        return cls(connection)

    def close(self) -> None:
        self._connection.close()

    def _one(self, sql: str, parameters: Sequence[object] = ()) -> tuple[object, ...] | None:
        try:
            row = self._connection.execute(sql, parameters).fetchone()
        except sqlite3.Error:
            raise ScoreStoreError("skor kaydı okunamıyor") from None
        return None if row is None else tuple(row)

    @property
    def started_at(self) -> datetime:
        row = self._one("SELECT value FROM meta WHERE name = 'started_at'")
        if row is None:
            raise ScoreStoreError("skor kaydı okunamıyor")
        return datetime.fromisoformat(str(row[0]))

    def resulted(self) -> frozenset[int]:
        try:
            rows = self._connection.execute("SELECT news_id FROM results").fetchall()
        except sqlite3.Error:
            raise ScoreStoreError("skor kaydı okunamıyor") from None
        return frozenset(int(row[0]) for row in rows)

    def calls_on(self, day: date) -> int:
        row = self._one("SELECT COUNT(*) FROM calls WHERE day = ?", (day.isoformat(),))
        return 0 if row is None else int(str(row[0]))

    def last_quota_at(self) -> datetime | None:
        row = self._one(
            "SELECT MAX(ended_at) FROM call_ends WHERE outcome = 'quota'",
        )
        return None if row is None or row[0] is None else datetime.fromisoformat(str(row[0]))

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        connection = self._connection
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.Error:
            raise ScoreStoreError("skor kaydı yazılamıyor") from None
        try:
            yield
            connection.execute("COMMIT")
        except BaseException as error:  # a forced stop as well: nothing half-written
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            if isinstance(error, sqlite3.Error):
                raise ScoreStoreError("skor kaydı yazılamıyor") from None
            raise

    def begin_call(self, news_id: int, at: datetime) -> int:
        """Çağrı süreç başlamadan sayılır (plan Risk 6)."""
        with self._transaction():
            cursor = self._connection.execute(
                "INSERT INTO calls (news_id, started_at, day) VALUES (?, ?, ?)",
                (news_id, _text(at), _day(at)),
            )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def _end(self, call_id: int, end: CallEnd) -> None:
        self._connection.execute(
            "INSERT INTO call_ends (call_id, outcome, seconds, ended_at) VALUES (?, ?, ?, ?)",
            (call_id, end.outcome, end.seconds, _text(end.at)),
        )

    def end_call(self, call_id: int, end: CallEnd) -> None:
        """Sonuçsuz biten çağrı (geçici hata): haber sonraki turda yeniden denenir."""
        with self._transaction():
            self._end(call_id, end)

    def write_result(
        self, result: ScoreResult, call_id: int | None = None, end: CallEnd | None = None
    ) -> None:
        """Sonuç, olay skorları, ret nedenleri ve çağrının sonu tek işlemde."""
        with self._transaction():
            if call_id is not None and end is not None:
                self._end(call_id, end)
            self._connection.execute(
                "INSERT INTO results (news_id, kind, at, call_id, model, prompt_fingerprint,"
                " context_fingerprint, rejected, schema_reason, reply_size)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result.news_id,
                    result.kind.value,
                    _text(result.at),
                    call_id,
                    result.model,
                    result.prompt_fingerprint,
                    result.context_fingerprint,
                    sum(count for _, count in result.rejections),
                    result.schema_reason,
                    result.reply_size,
                ),
            )
            for score in result.scores:
                self._connection.execute(
                    "INSERT INTO event_scores (news_id, coin, name, event_type, direction,"
                    " severity, quote) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        result.news_id,
                        score.coin,
                        score.name,
                        score.event_type,
                        score.direction,
                        score.severity,
                        score.quote,
                    ),
                )
            for reason, count in result.rejections:
                self._connection.execute(
                    "INSERT INTO rejections (news_id, reason, count) VALUES (?, ?, ?)",
                    (result.news_id, reason, count),
                )


@dataclass(frozen=True)
class ScoreSnapshot:
    """Durum komutunun okuduğu hâl (R-9)."""

    started_at: datetime
    results: dict[str, int]
    resulted_ids: frozenset[int]
    scores: dict[tuple[str, int], int]
    rejections: dict[str, int]
    calls_today: int
    last_scored_at: datetime | None
    last_error: str | None


ERROR_OUTCOMES = ("timeout", "no_session", "quota", "unknown")


def read_score_snapshot(path: str, today: date) -> ScoreSnapshot | None:
    """Kayıt yoksa `None` (dosya oluşturulmaz); okunamıyorsa `ScoreStoreError`. `mode=ro`."""
    if not Path(path).is_file():
        return None
    uri = f"{Path(path).resolve().as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=0)) as connection:
            _check_format(connection)
            started = connection.execute(
                "SELECT value FROM meta WHERE name = 'started_at'"
            ).fetchone()
            if started is None:
                raise ScoreStoreError("skor kaydı okunamıyor")
            results = dict(
                connection.execute("SELECT kind, COUNT(*) FROM results GROUP BY kind").fetchall()
            )
            ids = frozenset(
                int(row[0]) for row in connection.execute("SELECT news_id FROM results")
            )
            scores = {
                (str(direction), int(severity)): int(count)
                for direction, severity, count in connection.execute(
                    "SELECT direction, severity, COUNT(*) FROM event_scores"
                    " GROUP BY direction, severity"
                )
            }
            rejections = dict(
                connection.execute(
                    "SELECT reason, SUM(count) FROM rejections GROUP BY reason"
                ).fetchall()
            )
            calls = connection.execute(
                "SELECT COUNT(*) FROM calls WHERE day = ?", (today.isoformat(),)
            ).fetchone()
            scored = connection.execute(
                "SELECT MAX(at) FROM results WHERE kind = ?", (ResultKind.SCORED.value,)
            ).fetchone()
            marks = ", ".join("?" for _ in ERROR_OUTCOMES)
            error = connection.execute(
                "SELECT outcome, ended_at FROM call_ends"
                f" WHERE outcome IN ({marks}) ORDER BY ended_at DESC, call_id DESC LIMIT 1",
                ERROR_OUTCOMES,
            ).fetchone()
            schema = connection.execute(
                "SELECT MAX(at) FROM results WHERE kind = ?", (ResultKind.SCHEMA.value,)
            ).fetchone()
            snapshot = ScoreSnapshot(
                datetime.fromisoformat(str(started[0])),
                {str(kind): int(count) for kind, count in results.items()},
                ids,
                scores,
                {str(reason): int(count) for reason, count in rejections.items()},
                int(calls[0]),
                None if scored[0] is None else datetime.fromisoformat(str(scored[0])),
                _last_error(error, schema[0]),
            )
    except (sqlite3.Error, ValueError, TypeError):
        raise ScoreStoreError("skor kaydı okunamıyor") from None
    return snapshot


def _last_error(call: Sequence[object] | None, schema_at: object) -> str | None:
    """Son hatanın adı: en yeni sonuçsuz çağrı sınıfı ya da "şema dışı"."""
    candidates: list[tuple[datetime, str]] = []
    if call is not None:
        candidates.append((datetime.fromisoformat(str(call[1])), str(call[0])))
    if schema_at is not None:
        candidates.append((datetime.fromisoformat(str(schema_at)), ResultKind.SCHEMA.value))
    return None if not candidates else max(candidates)[1]
