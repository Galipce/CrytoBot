"""Arşiv deposu: geçmiş Binance duyurularının kendi SQLite deposu (spec 0047 R-2, R-3, R-4, R-8;
plan Risk 3).

`archive` tablosu yalnız eklenir: UNIQUE(article_id) ve `INSERT OR IGNORE` tekrarı yazmaz, ilk
sürüm kataloğuyla kalır (G-1); UPDATE ve DELETE tetikleyicilerle reddedilir. Her kayıt
`origin = 'archive'` taşır ("arşivden"); ilk görme anı sütunu yoktur, arşive alınma anı onun yerine
kullanılamaz. `catalog_state` (değişebilir) katalog başına ad, son bildirilen toplam, sıradaki
sayfa, tamam, son hata, listede mi ve son çalıştırma anını taşır. Bir sayfanın kayıtları ve katalog
durumu tek işlemde yazılır: işlem herhangi bir istisnayla (zorla durdurma dahil) kesilirse geri
alınır, yarım kayıt kalmaz. WAL, `timeout=0`, `closing` (conventions, spec 0011). İleriye dönük
haber kaydına ve bot deposuna hiçbir zaman yazmaz.
"""

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from crytobot.news._items import RawItem, clean, publish_time, truncate_utf8

FORMAT_VERSION = "1"
ARCHIVE_SOURCE = "binance-duyuru"
ORIGIN = "archive"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS archive (
    id INTEGER PRIMARY KEY,
    article_id TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    catalog_id INTEGER NOT NULL,
    catalog_name TEXT NOT NULL,
    link TEXT,
    title TEXT NOT NULL,
    truncated INTEGER NOT NULL,
    published_at TEXT,
    archived_at TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin = 'archive')
);
CREATE TRIGGER IF NOT EXISTS archive_no_update BEFORE UPDATE ON archive
BEGIN SELECT RAISE(ABORT, 'archive is append-only'); END;
CREATE TRIGGER IF NOT EXISTS archive_no_delete BEFORE DELETE ON archive
BEGIN SELECT RAISE(ABORT, 'archive is append-only'); END;
CREATE TABLE IF NOT EXISTS catalog_state (
    catalog_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    reported_total INTEGER,
    next_page INTEGER NOT NULL,
    complete INTEGER NOT NULL,
    listed INTEGER NOT NULL,
    last_error TEXT,
    last_run_at TEXT
);
"""


class ArchiveStoreError(Exception):
    """Arşiv açılamıyor, okunamıyor ya da yazılamıyor."""


@dataclass(frozen=True)
class ArchiveItem:
    """Yazılacak arşiv kaydı (Terimler: arşiv kaydı). `published`: bilinmiyorsa `None`."""

    article_id: str
    link: str | None
    title: str
    truncated: bool
    published: datetime | None
    archived_at: datetime


def prepare_archive(raw: RawItem, archived_at: datetime) -> ArchiveItem | None:
    """Arşiv kaydı; kimliği ya da başlığı boşsa `None` (geçersiz, R-6). Başlık 0046'nın kuralıyla
    kesilir (G-6); arşive alınma anından 5 dakikadan kesin ileri yayın anı bilinmiyor (G-4)."""
    article_id = clean(raw.item_id or "").strip()
    title = clean(raw.title).strip()
    if not article_id or not title:
        return None
    title, truncated = truncate_utf8(title)
    return ArchiveItem(
        article_id,
        raw.link,
        title,
        truncated,
        publish_time(raw.published, archived_at),
        archived_at,
    )


@dataclass(frozen=True)
class CatalogState:
    catalog_id: int
    name: str
    reported_total: int | None = None
    next_page: int = 1
    complete: bool = False
    listed: bool = True
    last_error: str | None = None
    last_run_at: datetime | None = None


def _text(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(UTC).isoformat()


def _moment(text: object) -> datetime | None:
    return None if text is None else datetime.fromisoformat(str(text))


_STATE_COLUMNS = (
    "catalog_id, name, reported_total, next_page, complete, listed, last_error, last_run_at"
)


def _state(row: Sequence[object]) -> CatalogState:
    catalog_id, name, total, next_page, complete, listed, error, run_at = row
    return CatalogState(
        int(str(catalog_id)),
        str(name),
        None if total is None else int(str(total)),
        int(str(next_page)),
        bool(complete),
        bool(listed),
        None if error is None else str(error),
        _moment(run_at),
    )


class ArchiveStore:
    """Arşiv komutunun açık bağlantısı. `open` dosyayı ve şemayı oluşturur."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @classmethod
    def open(cls, path: str) -> "ArchiveStore":
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
                raise ArchiveStoreError("arşivin biçimi tanınmıyor")
        except (sqlite3.Error, OSError):
            if connection is not None:
                connection.close()
            raise ArchiveStoreError("arşiv açılamıyor") from None
        except ArchiveStoreError:
            if connection is not None:
                connection.close()
            raise
        return cls(connection)

    def close(self) -> None:
        self._connection.close()

    def states(self) -> dict[int, CatalogState]:
        try:
            rows = self._connection.execute(
                f"SELECT {_STATE_COLUMNS} FROM catalog_state"
            ).fetchall()
        except sqlite3.Error:
            raise ArchiveStoreError("arşiv okunamıyor") from None
        return {int(row[0]): _state(row) for row in rows}

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        connection = self._connection
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.Error:
            raise ArchiveStoreError("arşiv yazılamıyor") from None
        try:
            yield
            connection.execute("COMMIT")
        except BaseException as error:  # a forced stop as well: nothing half-written (R-4)
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            if isinstance(error, sqlite3.Error):
                raise ArchiveStoreError("arşiv yazılamıyor") from None
            raise

    def _save_state(self, state: CatalogState) -> None:
        self._connection.execute(
            f"INSERT OR REPLACE INTO catalog_state ({_STATE_COLUMNS})"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                state.catalog_id,
                state.name,
                state.reported_total,
                state.next_page,
                int(state.complete),
                int(state.listed),
                state.last_error,
                _text(state.last_run_at),
            ),
        )

    def discover(self, states: Sequence[CatalogState], at: datetime) -> None:
        """Keşfin sonucu tek işlemde: listede olmayan katalog `listed = 0` olur (G-7)."""
        with self._transaction():
            self._connection.execute("UPDATE catalog_state SET listed = 0")
            for state in states:
                self._save_state(state)
            self._connection.execute(
                "INSERT OR REPLACE INTO meta (name, value) VALUES ('last_run_at', ?)", (_text(at),)
            )

    def existing(self, article_ids: Sequence[str]) -> set[str]:
        """Arşivde zaten bulunan kimlikler."""
        found: set[str] = set()
        try:
            for start in range(0, len(article_ids), 500):
                chunk = tuple(article_ids[start : start + 500])
                marks = ", ".join("?" for _ in chunk)
                found.update(
                    str(row[0])
                    for row in self._connection.execute(
                        f"SELECT article_id FROM archive WHERE article_id IN ({marks})", chunk
                    )
                )
        except sqlite3.Error:
            raise ArchiveStoreError("arşiv okunamıyor") from None
        return found

    def save_state(self, state: CatalogState) -> None:
        with self._transaction():
            self._save_state(state)

    def write_page(
        self, catalog_id: int, catalog_name: str, items: Sequence[ArchiveItem], state: CatalogState
    ) -> list[bool]:
        """Sayfanın kayıtları ve katalog durumu tek işlemde; öğe başına yazıldı mı (tekrar:
        `False`)."""
        with self._transaction():
            written = [self._insert(catalog_id, catalog_name, item) for item in items]
            self._save_state(state)
        return written

    def _insert(self, catalog_id: int, catalog_name: str, item: ArchiveItem) -> bool:
        cursor = self._connection.execute(
            "INSERT OR IGNORE INTO archive (article_id, source, catalog_id, catalog_name, link,"
            " title, truncated, published_at, archived_at, origin)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item.article_id,
                ARCHIVE_SOURCE,
                catalog_id,
                catalog_name,
                item.link,
                item.title,
                int(item.truncated),
                _text(item.published),
                _text(item.archived_at),
                ORIGIN,
            ),
        )
        return cursor.rowcount == 1


@dataclass(frozen=True)
class CatalogSummary:
    """Durum komutunun bir kataloğu (R-8)."""

    state: CatalogState
    records: int
    oldest: datetime | None
    newest: datetime | None


@dataclass(frozen=True)
class ArchiveSnapshot:
    catalogs: list[CatalogSummary]
    records: int
    article_ids: frozenset[str]
    last_run_at: datetime | None


def read_only(path: str) -> sqlite3.Connection:
    """Durum komutu yalnız SELECT yapar; var olan dosyayı `mode=rw` açar (plan A-2): dosya
    oluşturmaz, `mode=ro` gibi WAL yan dosyalarını bırakmaz, öldürülmüş sürecin WAL'ını kurtarır
    (conventions, spec 0011)."""
    return sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=rw", uri=True, timeout=0)


def read_archive(path: str) -> ArchiveSnapshot | None:
    """Arşiv yoksa `None`; okunamıyorsa `ArchiveStoreError`."""
    if not Path(path).is_file():
        return None
    try:
        with closing(read_only(path)) as connection:
            row = connection.execute("SELECT value FROM meta WHERE name = 'format'").fetchone()
            if row is None or row[0] != FORMAT_VERSION:
                raise ArchiveStoreError("arşivin biçimi tanınmıyor")
            run = connection.execute("SELECT value FROM meta WHERE name = 'last_run_at'").fetchone()
            states = [
                _state(each)
                for each in connection.execute(
                    f"SELECT {_STATE_COLUMNS} FROM catalog_state ORDER BY catalog_id"
                ).fetchall()
            ]
            counts = {
                int(each[0]): (int(each[1]), _moment(each[2]), _moment(each[3]))
                for each in connection.execute(
                    "SELECT catalog_id, COUNT(*), MIN(published_at), MAX(published_at)"
                    " FROM archive GROUP BY catalog_id"
                ).fetchall()
            }
            ids = frozenset(
                str(each[0]) for each in connection.execute("SELECT article_id FROM archive")
            )
    except (sqlite3.Error, ValueError):
        raise ArchiveStoreError("arşiv okunamıyor") from None
    known = {state.catalog_id for state in states}
    for catalog_id in sorted(set(counts) - known):  # records of a catalog with no state: shown
        states.append(CatalogState(catalog_id, str(catalog_id), listed=False))
    catalogs = [
        CatalogSummary(state, *counts.get(state.catalog_id, (0, None, None))) for state in states
    ]
    return ArchiveSnapshot(catalogs, len(ids), ids, None if run is None else _moment(run[0]))


def forward_binance_ids(path: str, sources: Sequence[str]) -> frozenset[str] | None:
    """İleriye dönük kayıttaki `binance-duyuru` türü kaynakların kimlikleri (R-8, G-5); kayıt yoksa
    `None`. Kayıt yalnız okunur."""
    if not Path(path).is_file():
        return None
    if not sources:
        return frozenset()
    marks = ", ".join("?" for _ in sources)
    try:
        with closing(read_only(path)) as connection:
            rows = connection.execute(
                f"SELECT key FROM news WHERE source IN ({marks}) AND key LIKE 'id:%'",
                tuple(sources),
            ).fetchall()
    except sqlite3.Error:
        raise ArchiveStoreError("haber kaydı okunamıyor") from None
    return frozenset(str(row[0])[3:] for row in rows)
