"""Haber kaydı: `news`'in kendi SQLite deposu (spec 0046 R-2, R-3, R-6, R-8, R-9; plan Risk 2, 10,
11).

`news` tablosu yalnız eklenir: UNIQUE(kaynak, anahtar) ve `INSERT OR IGNORE` tekrarı yazmaz, ilk
sürüm kalır; UPDATE ve DELETE tetikleyicilerle reddedilir. `source_state` kaynak başına son başarı,
son hata, kesinti başı ve bildirim gitti mi bilgisini taşır; yeniden başlatma onu sıfırlamaz. Bir
kaynağın kayıtları ve durumu tek işlemde yazılır: işlem herhangi bir istisnayla (zorla durdurma
dahil) kesilirse geri alınır. WAL kipi: durum komutu çalışan toplayıcıyı beklemez. `timeout=0` ve
`closing` (conventions, spec 0011). Bot deposuna hiçbir zaman dokunmaz.
"""

import os
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from crytobot.news._items import NewsItem

FORMAT_VERSION = "1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    key TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    link TEXT,
    published_at TEXT,
    truncated INTEGER NOT NULL,
    first_seen_at TEXT NOT NULL,
    UNIQUE (source, key)
);
CREATE TRIGGER IF NOT EXISTS news_no_update BEFORE UPDATE ON news
BEGIN SELECT RAISE(ABORT, 'news is append-only'); END;
CREATE TRIGGER IF NOT EXISTS news_no_delete BEFORE DELETE ON news
BEGIN SELECT RAISE(ABORT, 'news is append-only'); END;
CREATE TABLE IF NOT EXISTS source_state (
    source TEXT PRIMARY KEY,
    last_success_at TEXT,
    last_error TEXT,
    last_error_at TEXT,
    outage_started_at TEXT,
    alert_sent INTEGER NOT NULL
);
"""


class StoreError(Exception):
    """Haber kaydı açılamıyor, okunamıyor ya da yazılamıyor."""


@dataclass(frozen=True)
class SourceState:
    last_success_at: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    outage_started_at: datetime | None = None
    alert_sent: bool = False


@dataclass(frozen=True)
class SourceSummary:
    state: SourceState
    records: int


@dataclass(frozen=True)
class StoreSnapshot:
    """Durum komutunun okuduğu hâl (R-8). `sources`: kaynak adı → özet."""

    sources: dict[str, SourceSummary]
    records: int
    size_bytes: int


def _text(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(UTC).isoformat()


def _moment(text: object) -> datetime | None:
    return None if text is None else datetime.fromisoformat(str(text))


def _state(row: Sequence[object] | None) -> SourceState:
    if row is None:
        return SourceState()
    success, error, error_at, outage, sent = row
    return SourceState(
        _moment(success),
        None if error is None else str(error),
        _moment(error_at),
        _moment(outage),
        bool(sent),
    )


_STATE_COLUMNS = "last_success_at, last_error, last_error_at, outage_started_at, alert_sent"


class NewsStore:
    """Toplayıcının açık bağlantısı. `open` dosyayı ve şemayı oluşturur."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @classmethod
    def open(cls, path: str) -> "NewsStore":
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(path, timeout=0, isolation_level=None)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(_SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO meta (name, value) VALUES ('format', ?)", (FORMAT_VERSION,)
            )
            row = connection.execute("SELECT value FROM meta WHERE name = 'format'").fetchone()
            if row is None or row[0] != FORMAT_VERSION:
                raise StoreError("haber kaydının biçimi tanınmıyor")
        except (sqlite3.Error, OSError):
            if connection is not None:
                connection.close()
            raise StoreError("haber kaydı açılamıyor") from None
        except StoreError:
            if connection is not None:
                connection.close()
            raise
        return cls(connection)

    def close(self) -> None:
        self._connection.close()

    def state(self, source: str) -> SourceState:
        try:
            row = self._connection.execute(
                f"SELECT {_STATE_COLUMNS} FROM source_state WHERE source = ?", (source,)
            ).fetchone()
        except sqlite3.Error:
            raise StoreError("haber kaydı okunamıyor") from None
        return _state(row)

    def write(self, source: str, items: Sequence[NewsItem], state: SourceState) -> list[bool]:
        """Kaynağın kayıtları ve durumu tek işlemde; öğe başına yazıldı mı (tekrar: `False`)."""
        connection = self._connection
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.Error:
            raise StoreError("haber kaydı yazılamıyor") from None
        try:
            written = [self._insert(source, item) for item in items]
            connection.execute(
                f"INSERT OR REPLACE INTO source_state (source, {_STATE_COLUMNS})"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    source,
                    _text(state.last_success_at),
                    state.last_error,
                    _text(state.last_error_at),
                    _text(state.outage_started_at),
                    int(state.alert_sent),
                ),
            )
            connection.execute("COMMIT")
        except BaseException as error:  # a forced stop as well: nothing half-written (AC-8)
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            if isinstance(error, sqlite3.Error):
                raise StoreError("haber kaydı yazılamıyor") from None
            raise
        return written

    def _insert(self, source: str, item: NewsItem) -> bool:
        cursor = self._connection.execute(
            "INSERT OR IGNORE INTO news (source, key, title, body, link, published_at,"
            " truncated, first_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source,
                item.key,
                item.title,
                item.text,
                item.link,
                _text(item.published),
                int(item.truncated),
                _text(item.first_seen),
            ),
        )
        return cursor.rowcount == 1


def store_size(path: str) -> int:
    """Depo ve WAL dosyasının bayt toplamı (G-8)."""
    total = 0
    for each in (path, f"{path}-wal"):
        try:
            total += os.path.getsize(each)
        except OSError:
            continue
    return total


def read_snapshot(path: str) -> StoreSnapshot | None:
    """Durum komutu: depo yoksa `None` (dosya oluşturulmaz); okunamıyorsa `StoreError`.

    `mode=rw`: salt okuma da öldürülmüş sürecin günlüğünü geri alabilmeli (conventions, 0011).
    """
    if not Path(path).is_file():
        return None
    uri = f"{Path(path).resolve().as_uri()}?mode=rw"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=0)) as connection:
            row = connection.execute("SELECT value FROM meta WHERE name = 'format'").fetchone()
            if row is None or row[0] != FORMAT_VERSION:
                raise StoreError("haber kaydının biçimi tanınmıyor")
            counts = dict(
                connection.execute("SELECT source, COUNT(*) FROM news GROUP BY source").fetchall()
            )
            states = {
                str(row[0]): _state(row[1:])
                for row in connection.execute(
                    f"SELECT source, {_STATE_COLUMNS} FROM source_state"
                ).fetchall()
            }
    except (sqlite3.Error, ValueError):
        raise StoreError("haber kaydı okunamıyor") from None
    names = set(counts) | set(states)
    sources = {
        str(name): SourceSummary(states.get(str(name), SourceState()), int(counts.get(name, 0)))
        for name in names
    }
    return StoreSnapshot(sources, sum(int(each) for each in counts.values()), store_size(path))


@dataclass(frozen=True)
class ForwardItem:
    """Skorlayıcının okuduğu haber (spec 0051 R-1): kayıt kimliği, kaynak adı, başlık, saklanan
    metin, yayın ve ilk görme anı."""

    record_id: int
    source: str
    title: str
    text: str
    published: datetime | None
    first_seen: datetime


def read_forward(path: str, since: datetime) -> tuple[ForwardItem, ...] | None:
    """İlk görme anı `since`'ten sonra (ya da eşit) olan haberler, ilk görme anı ve kimlik
    sırasıyla. Depo yoksa `None` (dosya oluşturulmaz); okunamıyorsa `StoreError`.

    `mode=ro`: hiçbir satır yazılmaz; WAL kipinde çalışan toplayıcıyı beklemez, toplayıcı da onu
    beklemez (spec 0051 R-8, AC-7). Conventions'taki "`mode=ro` sıcak günlüğü geri alamaz" tuzağı
    rollback günlüğüne aittir: WAL'de yazılmamış işlem okuyucuya hiç görünmez (review I-1)."""
    if not Path(path).is_file():
        return None
    uri = f"{Path(path).resolve().as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=0)) as connection:
            row = connection.execute("SELECT value FROM meta WHERE name = 'format'").fetchone()
            if row is None or row[0] != FORMAT_VERSION:
                raise StoreError("haber kaydının biçimi tanınmıyor")
            rows = connection.execute(
                "SELECT id, source, title, body, published_at, first_seen_at FROM news"
                " WHERE first_seen_at >= ?",
                (_text(since),),
            ).fetchall()
        items = [
            ForwardItem(
                int(record_id),
                str(source),
                str(title),
                str(body),
                _moment(published),
                datetime.fromisoformat(str(first_seen)),
            )
            for record_id, source, title, body, published, first_seen in rows
        ]
    except (sqlite3.Error, ValueError, TypeError):
        raise StoreError("haber kaydı okunamıyor") from None
    # text order and time order agree for one writer's format; the moment decides, not the text
    kept = [item for item in items if item.first_seen >= since]
    return tuple(sorted(kept, key=lambda item: (item.first_seen, item.record_id)))
