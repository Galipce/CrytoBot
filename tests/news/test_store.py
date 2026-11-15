"""Spec 0046 haber kaydı: tekrar kuralı turlar ve yeniden açılış boyunca, ilk sürüm kalır, yalnız
ekleme (AC-2); config'ten çıkarılan kaynağın kayıtları kalır (AC-9)."""

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from crytobot.news import Fetched, NewsStore
from tests.news.test_collect import START, Harness, make_config, source_table

RSS = (
    '<rss version="2.0"><channel>'
    "<item>{guid}<link>https://example.org/{slug}</link><title>{title}</title>"
    "<description>{text}</description></item></channel></rss>"
)


def rss(title: str = "İlk", text: str = "ilk metin", guid: str = "<guid>n-1</guid>") -> Fetched:
    return Fetched(body=RSS.format(guid=guid, slug="n-1", title=title, text=text).encode())


def single(tmp_path: Path, *names: str) -> Harness:
    sources = [source_table(name) for name in names or ("coindesk",)]
    return Harness(tmp_path, make_config(tmp_path, *sources))


def test_duplicate_not_written_across_rounds_and_reopen(tmp_path: Path) -> None:
    harness = single(tmp_path)
    harness.responses["coindesk"] = rss()
    harness.round()
    harness.round()
    assert harness.summary("coindesk") == "kaynak=coindesk yeni=0 tekrar=1 geçersiz=0"
    restarted = single(tmp_path)  # a new command: the store is opened again
    restarted.responses["coindesk"] = rss()
    restarted.round()
    assert restarted.summary("coindesk") == "kaynak=coindesk yeni=0 tekrar=1 geçersiz=0"
    assert len(restarted.rows()) == 1


def test_first_version_kept(tmp_path: Path) -> None:
    harness = single(tmp_path)
    harness.responses["coindesk"] = rss()
    harness.round()
    first = harness.rows()[0]
    harness.clock.advance(3600)
    harness.responses["coindesk"] = rss(title="Değişti", text="yeni metin")
    harness.round()
    assert harness.rows() == [first]
    assert first["first_seen_at"] == (START + timedelta(seconds=2)).isoformat()
    assert (first["title"], first["body"]) == ("İlk", "ilk metin")


def test_link_is_key_without_id(tmp_path: Path) -> None:
    harness = single(tmp_path)
    harness.responses["coindesk"] = rss(guid="")
    harness.round()
    harness.responses["coindesk"] = rss(guid="", title="Başka başlık")
    harness.round()
    assert [row["key"] for row in harness.rows()] == ["link:https://example.org/n-1"]
    assert harness.summary("coindesk") == "kaynak=coindesk yeni=0 tekrar=1 geçersiz=0"


def test_same_id_two_sources_two_records(tmp_path: Path) -> None:
    harness = single(tmp_path, "coindesk", "atom")
    harness.responses["coindesk"] = rss()
    harness.responses["atom"] = rss()
    harness.round()
    assert [(row["source"], row["key"]) for row in harness.rows()] == [
        ("coindesk", "id:n-1"),
        ("atom", "id:n-1"),
    ]


def test_update_and_delete_rejected(tmp_path: Path) -> None:
    harness = single(tmp_path)
    harness.responses["coindesk"] = rss()
    harness.round()
    with sqlite3.connect(harness.config.store_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE news SET title = 'x'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM news")
    assert harness.rows()[0]["title"] == "İlk"


def test_removed_source_records_kept(tmp_path: Path) -> None:
    """AC-9 (R-10): kaynak config'ten çıkarılınca eski kayıtları kalır."""
    harness = single(tmp_path, "coindesk", "atom")
    harness.round()
    before = harness.rows("source = 'atom'")
    later = single(tmp_path, "coindesk")
    later.round()
    assert later.rows("source = 'atom'") == before != []


def test_unknown_store_format_refused(tmp_path: Path) -> None:
    path = tmp_path / "news.db"
    NewsStore.open(str(path)).close()
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE meta SET value = '99'")
    from crytobot.news import StoreError

    with pytest.raises(StoreError, match="biçimi tanınmıyor"):
        NewsStore.open(str(path))


def test_not_a_database_refused(tmp_path: Path) -> None:
    from crytobot.news import StoreError

    path = tmp_path / "news.db"
    path.write_bytes(b"not sqlite" * 100)
    with pytest.raises(StoreError, match="açılamıyor"):
        NewsStore.open(str(path))
