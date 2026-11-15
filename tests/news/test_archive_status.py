"""Spec 0047 AC-8 (R-8): arşiv durumu — ağsız; katalog başına sayılar, boyut, ileriye dönük kayıtla
örtüşme. Depolar yalnız okunur, dosya oluşturulmaz."""

import sqlite3
from datetime import timedelta
from pathlib import Path

from crytobot.news import (
    ARCHIVE_EMPTY,
    NO_FORWARD,
    ArchiveOutcome,
    Fetched,
    NewsItem,
    NewsStore,
    SourceState,
    archive_status_lines,
)
from crytobot.news._store import store_size
from tests.news.test_archive_run import START, A, B, Binance, Harness, articles


def forward(path: Path, source: str, *keys: str) -> None:
    store = NewsStore.open(str(path))
    try:
        store.write(
            source,
            [NewsItem(key, None, "t", "", False, None, START) for key in keys],
            SourceState(last_success_at=START),
        )
    finally:
        store.close()


def harness(tmp_path: Path) -> Harness:
    return Harness(
        tmp_path, Binance({A: ("Listing", articles(1, 60)), B: ("Delisting", articles(2, 3))})
    )


def test_status_per_catalog_and_size(tmp_path: Path) -> None:
    run = harness(tmp_path)
    run.hook = lambda index, url: Fetched(error="http_500") if index == 2 else None  # A p2
    assert run.run() is ArchiveOutcome.FAILED
    run.hook = None
    run.binance.catalogs[A] = ("Listing", [*run.binance.catalogs[A][1], *articles(3, 1)])
    assert run.run() is ArchiveOutcome.COMPLETE
    del run.binance.catalogs[B]
    run.binance.publish(A, *articles(4, 1, START + timedelta(minutes=1)))
    assert run.run() is ArchiveOutcome.COMPLETE  # B is no longer listed
    lines = archive_status_lines(run.config)
    newest = (START + timedelta(minutes=1)).isoformat()
    oldest_a = (START - timedelta(hours=59)).isoformat()
    last = run.now.isoformat()
    assert lines[0] == (
        f"katalog=Listing kayıt=62 bildirilen=62 fark=0 en_eski={oldest_a} en_yeni={newest}"
        f" tamam son_hata=yok son_çalıştırma={last}"
    )
    assert lines[1].startswith("katalog=Delisting kayıt=3 bildirilen=3 fark=0 ")
    assert lines[1].endswith(" (listede yok)")
    size = store_size(str(run.store_path))
    assert size > 0
    assert lines[2].startswith(f"arşiv: kayıt=65 boyut={size} bayt ({size / 1024:.1f} KB)")
    assert lines[2].endswith(f" {NO_FORWARD}")


def test_difference_and_error_shown(tmp_path: Path) -> None:
    run = harness(tmp_path)
    run.hook = lambda index, url: Fetched(error="timeout") if index == 2 else None
    run.run()
    line = archive_status_lines(run.config)[0]
    assert "kayıt=50 bildirilen=60 fark=10 " in line
    assert " eksik son_hata=timeout " in line


def test_overlap_with_forward_store(tmp_path: Path) -> None:
    """G-5: aynı Binance kimliği ileriye dönük kayıtta `binance-duyuru` türündeki bir kaynakta."""
    run = harness(tmp_path)
    run.run()
    archived = run.archived()
    forward(tmp_path / "news.db", "b", f"id:{archived[0]}", f"id:{archived[1]}", "id:999")
    forward(tmp_path / "news.db", "coindesk", f"id:{archived[2]}")  # not a Binance source
    forward(tmp_path / "news.db", "b", f"link:{archived[3]}")
    before = (tmp_path / "news.db").read_bytes()
    assert archive_status_lines(run.config)[-1].endswith(" örtüşme=2")
    assert (tmp_path / "news.db").read_bytes() == before


def test_no_forward_store_said(tmp_path: Path) -> None:
    run = harness(tmp_path)
    run.run()
    assert archive_status_lines(run.config)[-1].endswith(f" {NO_FORWARD}")
    assert not (tmp_path / "news.db").exists()  # never created by the status


def test_empty_archive_exit_0(tmp_path: Path) -> None:
    """Boş arşiv: bunu söyler, hata vermez, dosya oluşturmaz (çıkış 0: test_news_archive_entry)."""
    run = harness(tmp_path)
    assert archive_status_lines(run.config) == [f"{ARCHIVE_EMPTY} boyut=0 bayt"]
    assert list(tmp_path.iterdir()) == []


def test_catalogs_known_but_nothing_archived(tmp_path: Path) -> None:
    run = harness(tmp_path)
    run.hook = lambda index, url: Fetched(error="timeout") if index == 1 else None
    run.run()
    lines = archive_status_lines(run.config)
    assert lines[0].startswith("katalog=Listing kayıt=0 bildirilen=60 fark=60 en_eski=yok")
    assert lines[-1].startswith(f"{ARCHIVE_EMPTY} boyut=")


def test_status_does_not_write_the_archive(tmp_path: Path) -> None:
    run = harness(tmp_path)
    run.run()
    with sqlite3.connect(run.store_path) as connection:
        before = connection.execute("SELECT COUNT(*) FROM archive").fetchone()
    connection.close()
    data = run.store_path.read_bytes()
    archive_status_lines(run.config)
    assert run.store_path.read_bytes() == data
    assert before == (63,)
