"""Spec 0047 AC-3 (R-3), AC-6 (başlık olduğu gibi), R-4 (yarım kayıt yok): arşiv deposu."""

import dataclasses
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crytobot.app import ForcedStop
from crytobot.news import (
    ORIGIN,
    ArchiveItem,
    ArchiveStore,
    ArchiveStoreError,
    CatalogState,
    read_archive,
)

AT = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def item(article_id: str, title: str = "t", at: datetime = AT) -> ArchiveItem:
    return ArchiveItem(article_id, None, title, False, None, at)


def state(catalog_id: int = 1, name: str = "A", **changes: object) -> CatalogState:
    return dataclasses.replace(CatalogState(catalog_id, name), **changes)  # type: ignore[arg-type]


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ArchiveStore]:
    opened = ArchiveStore.open(str(tmp_path / "archive.db"))
    yield opened
    opened.close()


def rows(path: Path) -> list[tuple[object, ...]]:
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT article_id, catalog_id, catalog_name, title, archived_at, origin FROM archive"
            " ORDER BY id"
        ).fetchall()


def test_same_id_written_once_across_pages_catalogs_runs(tmp_path: Path) -> None:
    path = tmp_path / "archive.db"
    first = ArchiveStore.open(str(path))
    assert first.write_page(1, "A", [item("1"), item("2")], state()) == [True, True]
    assert first.write_page(1, "A", [item("2"), item("3")], state()) == [False, True]  # page
    assert first.write_page(2, "B", [item("3"), item("4")], state(2, "B")) == [False, True]
    first.close()
    again = ArchiveStore.open(str(path))  # a later run
    assert again.write_page(2, "B", [item("1"), item("5")], state(2, "B")) == [False, True]
    again.close()
    assert [row[0] for row in rows(path)] == ["1", "2", "3", "4", "5"]


def test_first_version_kept(store: ArchiveStore, tmp_path: Path) -> None:
    store.write_page(1, "A", [item("7", "first")], state())
    later = AT + timedelta(hours=1)
    store.write_page(2, "B", [item("7", "second", later)], state(2, "B"))
    assert rows(tmp_path / "archive.db") == [("7", 1, "A", "first", AT.isoformat(), ORIGIN)]


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE archive SET title = 'x'",
        "UPDATE archive SET catalog_name = 'x'",
        "DELETE FROM archive",
        "INSERT INTO archive (article_id, source, catalog_id, catalog_name, title, truncated,"
        " archived_at, origin) VALUES ('9', 's', 1, 'A', 't', 0, 'x', 'forward')",
    ],
)
def test_update_and_delete_rejected(store: ArchiveStore, tmp_path: Path, statement: str) -> None:
    store.write_page(1, "A", [item("1")], state())
    path = tmp_path / "archive.db"
    with sqlite3.connect(path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(statement)
    assert [row[0] for row in rows(path)] == ["1"]


def test_title_stored_verbatim(store: ArchiveStore, tmp_path: Path) -> None:
    """AC-6: başlık olduğu gibi saklanır (işaretleme, tırnak, SQL benzeri metin dahil)."""
    title = "<script>alert('x')</script> '; DROP TABLE archive; -- ${HOME} `rm -rf`"
    store.write_page(1, "A", [item("1", title)], state())
    assert rows(tmp_path / "archive.db")[0][3] == title


def test_no_first_seen_column(store: ArchiveStore, tmp_path: Path) -> None:
    """R-2: arşiv kaydı ilk görme anı taşımaz."""
    with sqlite3.connect(tmp_path / "archive.db") as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(archive)")]
    assert "first_seen_at" not in columns
    assert {"source", "catalog_name", "article_id", "link", "title", "published_at"} <= set(columns)
    assert {"archived_at", "origin", "truncated"} <= set(columns)


def test_forced_stop_mid_page_rolls_back(
    store: ArchiveStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R-4: sayfanın kayıtları ve durumu tek işlemde; zorla durma hepsini geri alır."""
    store.write_page(1, "A", [item("1")], state(next_page=2))
    insert = store._insert

    def second_one_stops(catalog_id: int, catalog_name: str, each: ArchiveItem) -> bool:
        if each.article_id == "3":
            raise ForcedStop
        return insert(catalog_id, catalog_name, each)

    monkeypatch.setattr(store, "_insert", second_one_stops)
    with pytest.raises(ForcedStop):
        store.write_page(1, "A", [item("2"), item("3")], state(next_page=3))
    assert [row[0] for row in rows(tmp_path / "archive.db")] == ["1"]
    assert store.states()[1].next_page == 2


def test_state_round_trip_and_discovery_unlists(store: ArchiveStore) -> None:
    store.discover([state(1, "A", reported_total=5), state(2, "B", reported_total=7)], AT)
    store.save_state(state(1, "A", reported_total=5, next_page=4, last_error="timeout"))
    store.discover([state(2, "B", reported_total=8)], AT)
    states = store.states()
    assert states[1] == state(
        1, "A", reported_total=5, next_page=4, listed=False, last_error="timeout"
    )
    assert states[2].reported_total == 8 and states[2].listed


def test_existing_ids(store: ArchiveStore) -> None:
    store.write_page(1, "A", [item(str(n)) for n in range(1200)], state())
    asked = [str(n) for n in range(1100, 1300)]
    assert store.existing(asked) == {str(n) for n in range(1100, 1200)}


def test_unopenable_and_foreign_format(tmp_path: Path) -> None:
    with pytest.raises(ArchiveStoreError):
        ArchiveStore.open(str(tmp_path / "missing" / "archive.db"))
    path = tmp_path / "foreign.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO meta VALUES ('format', '99')")
    connection.close()
    with pytest.raises(ArchiveStoreError, match="biçimi"):
        ArchiveStore.open(str(path))
    with pytest.raises(ArchiveStoreError, match="biçimi"):
        read_archive(str(path))


def test_read_archive_missing_creates_nothing(tmp_path: Path) -> None:
    assert read_archive(str(tmp_path / "none.db")) is None
    assert list(tmp_path.iterdir()) == []
