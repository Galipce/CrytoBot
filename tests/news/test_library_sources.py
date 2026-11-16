"""Spec 0048 AC-2 (R-2, Q-5; plan Risk 6): kütüphanenin kaynakları — arşiv ve ileriye dönük kaydın
`binance-duyuru` kayıtları, kimliğe göre birleştirme, kaynak işareti, yalnız okuma."""

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crytobot.news import (
    FROM_ARCHIVE,
    FROM_BOTH,
    FROM_FORWARD,
    RULES_FINGERPRINT,
    ArchiveItem,
    ArchiveStore,
    ArchiveStoreError,
    CatalogState,
    NewsItem,
    NewsStore,
    SourceState,
    read_library_sources,
)

T0 = datetime(2024, 3, 1, 12, 0, tzinfo=UTC)
LISTING = 48


def archive(path: Path, *items: tuple[str, str, datetime | None]) -> None:
    store = ArchiveStore.open(str(path))
    try:
        rows = [ArchiveItem(aid, None, title, False, at, T0) for aid, title, at in items]
        store.write_page(LISTING, "New Cryptocurrency Listing", rows, CatalogState(LISTING, "x"))
    finally:
        store.close()


def forward(path: Path, source: str, *items: tuple[str, str, datetime | None, datetime]) -> None:
    store = NewsStore.open(str(path))
    try:
        rows = [NewsItem(key, None, title, "", False, at, seen) for key, title, at, seen in items]
        store.write(source, rows, SourceState(last_success_at=T0))
    finally:
        store.close()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path, table: str) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
    finally:
        connection.close()


def test_same_id_merged_mark_both_first_seen(tmp_path: Path) -> None:
    seen = T0 + timedelta(minutes=3)
    archive(tmp_path / "a.db", ("1", "Binance Will List Pepe (PEPE)", T0), ("2", "Old", T0))
    forward(
        tmp_path / "n.db",
        "binance-duyuru",
        ("id:1", "Binance Will List Pepe (PEPE)", T0, seen),
        ("id:3", "Binance Will Delist ABC", None, seen),
    )
    # the same id seen later under a second Binance source: the earliest first-seen moment stays
    forward(tmp_path / "n.db", "binance-2", ("id:1", "x", T0, seen + timedelta(hours=1)))

    sources = read_library_sources(
        str(tmp_path / "a.db"), str(tmp_path / "n.db"), ("binance-duyuru", "binance-2")
    )

    by_id = {item.article_id: item for item in sources.announcements}
    assert list(by_id) == ["1", "2", "3"]
    merged = by_id["1"]
    assert (merged.origin, merged.first_seen, merged.published) == (FROM_BOTH, seen, T0)
    assert (merged.catalog, merged.title) == (
        "New Cryptocurrency Listing",
        "Binance Will List Pepe (PEPE)",
    )
    assert (merged.event_type, merged.direction, merged.coins) == (
        "spot listeleme",
        "olumlu",
        ("PEPE",),
    )
    assert (by_id["2"].origin, by_id["2"].first_seen) == (FROM_ARCHIVE, None)
    assert (by_id["3"].origin, by_id["3"].catalog, by_id["3"].first_seen) == (
        FROM_FORWARD,
        None,
        seen,
    )
    assert (sources.archive_records, sources.forward_records) == (2, 2)
    assert sources.rules_fingerprint == RULES_FINGERPRINT


def test_rss_records_excluded(tmp_path: Path) -> None:
    archive(tmp_path / "a.db")
    forward(tmp_path / "n.db", "coindesk", ("id:9", "Bitcoin rallies", T0, T0))
    forward(tmp_path / "n.db", "binance-duyuru", ("link:https://x", "No id", T0, T0))

    sources = read_library_sources(
        str(tmp_path / "a.db"), str(tmp_path / "n.db"), ("binance-duyuru",)
    )

    assert sources.announcements == ()
    assert sources.forward_records == 0


def test_sources_unchanged(tmp_path: Path) -> None:
    archive(tmp_path / "a.db", ("1", "Binance Will List Pepe (PEPE)", T0))
    forward(tmp_path / "n.db", "binance-duyuru", ("id:1", "t", T0, T0))
    before = (rows(tmp_path / "a.db", "archive"), rows(tmp_path / "n.db", "news"))
    sha = (digest(tmp_path / "a.db"), digest(tmp_path / "n.db"))
    names = sorted(path.name for path in tmp_path.iterdir())

    read_library_sources(str(tmp_path / "a.db"), str(tmp_path / "n.db"), ("binance-duyuru",))

    assert (rows(tmp_path / "a.db", "archive"), rows(tmp_path / "n.db", "news")) == before
    assert (digest(tmp_path / "a.db"), digest(tmp_path / "n.db")) == sha
    assert sorted(path.name for path in tmp_path.iterdir()) == names


def test_read_while_collector_writes(tmp_path: Path) -> None:
    archive(tmp_path / "a.db", ("1", "Binance Will List Pepe (PEPE)", T0))
    forward(tmp_path / "n.db", "binance-duyuru", ("id:1", "t", T0, T0))
    collector = NewsStore.open(str(tmp_path / "n.db"))
    writer = sqlite3.connect(tmp_path / "a.db", isolation_level=None)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("BEGIN IMMEDIATE")  # the archive command holds its write transaction
        sources = read_library_sources(
            str(tmp_path / "a.db"), str(tmp_path / "n.db"), ("binance-duyuru",)
        )
        writer.execute("ROLLBACK")
    finally:
        writer.close()
        collector.close()
    assert [item.origin for item in sources.announcements] == [FROM_BOTH]


def test_no_forward_store_archive_only(tmp_path: Path) -> None:
    archive(tmp_path / "a.db", ("1", "Binance Will Delist ABC", None))

    sources = read_library_sources(str(tmp_path / "a.db"), str(tmp_path / "none.db"), ("b",))

    assert sources.forward_records is None
    assert [(a.origin, a.published) for a in sources.announcements] == [(FROM_ARCHIVE, None)]
    assert not (tmp_path / "none.db").exists()


def test_missing_or_foreign_archive_refused(tmp_path: Path) -> None:
    with pytest.raises(ArchiveStoreError, match="arşiv yok"):
        read_library_sources(str(tmp_path / "a.db"), str(tmp_path / "n.db"), ())
    assert not (tmp_path / "a.db").exists()
    (tmp_path / "a.db").write_bytes(b"not sqlite at all, just text" * 10)
    with pytest.raises(ArchiveStoreError, match="arşiv okunamıyor"):
        read_library_sources(str(tmp_path / "a.db"), str(tmp_path / "n.db"), ())
