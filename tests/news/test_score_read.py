"""Spec 0053 AC-9, AC-10 (R-1, R-10; plan step 5): skor ve haber kaydı `mode=ro`, kilitsiz okunur;
bozuk satır atlanır ve sayılır; kayıt yoksa dosya oluşturulmaz."""

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crytobot.news import (
    EventScore,
    NewsItem,
    NewsStore,
    ResultKind,
    ScoreResult,
    ScoreStore,
    ScoreStoreError,
    SourceState,
    StoreError,
    read_news_sources,
    read_score_record,
)

AT = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _score_store(path: Path) -> None:
    store = ScoreStore.open(str(path), AT)
    try:
        store.write_result(
            ScoreResult(
                7,
                ResultKind.SCORED,
                AT,
                "claude-sonnet",
                "pp",
                "cc",
                (EventScore("BTC", "Bitcoin", "hack", "olumsuz", 3, "q"),),
            )
        )
        store.write_result(ScoreResult(8, ResultKind.STALE, AT))
    finally:
        store.close()


def test_reads_results_and_events(tmp_path: Path) -> None:
    path = tmp_path / "score.db"
    _score_store(path)
    record = read_score_record(str(path))
    assert record is not None and record.skipped == 0
    assert [(r.news_id, r.kind, r.at, r.model) for r in record.results] == [
        (7, "skorlandı", AT, "claude-sonnet"),
        (8, "bayat", AT, None),
    ]
    assert record.results[0].prompt_fingerprint == "pp"
    assert record.results[0].context_fingerprint == "cc"
    assert [(e.news_id, e.coin, e.event_type, e.direction, e.severity) for e in record.events] == [
        (7, "BTC", "hack", "olumsuz", 3)
    ]


def test_read_only_uri(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "score.db"
    _score_store(path)
    news = tmp_path / "news.db"
    NewsStore.open(str(news)).close()
    seen: list[tuple[str, object]] = []
    real: Callable[..., sqlite3.Connection] = sqlite3.connect

    def connect(database: str, **kwargs: object) -> sqlite3.Connection:
        seen.append((database, kwargs.get("timeout")))
        return real(database, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    before = (path.read_bytes(), news.read_bytes())
    assert read_score_record(str(path)) is not None
    assert read_news_sources(str(news)) == {}
    assert [(uri.endswith("?mode=ro"), timeout) for uri, timeout in seen] == [
        (True, 0),
        (True, 0),
    ]
    assert (path.read_bytes(), news.read_bytes()) == before
    assert read_score_record(str(tmp_path / "none.db")) is None
    assert read_news_sources(str(tmp_path / "none.db")) is None
    assert not (tmp_path / "none.db").exists()


def test_bad_row_skipped_counted(tmp_path: Path) -> None:
    path = tmp_path / "score.db"
    _score_store(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO results (news_id, kind, at, rejected) VALUES (9, 'skorlandı', 'bozuk', 0)"
        )
        connection.execute(
            "INSERT INTO results (news_id, kind, at, rejected)"
            " VALUES (10, 'skorlandı', '2026-11-01T12:00:00', 0)"
        )
        connection.execute(
            "INSERT INTO event_scores (news_id, coin, name, event_type, direction, severity,"
            " quote) VALUES (7, 'ETH', 'e', 'hack', 'olumsuz', 'iki', 'q')"
        )
    connection.close()
    record = read_score_record(str(path))
    assert record is not None and record.skipped == 3
    assert [r.news_id for r in record.results] == [7, 8]
    assert [e.coin for e in record.events] == ["BTC"]


def test_unreadable_record_named(tmp_path: Path) -> None:
    path = tmp_path / "score.db"
    path.write_bytes(b"not a database at all, just bytes" * 10)
    with pytest.raises(ScoreStoreError, match="skor kaydı okunamıyor"):
        read_score_record(str(path))
    other = tmp_path / "other.db"
    with sqlite3.connect(other) as connection:
        connection.execute("CREATE TABLE meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.close()
    with pytest.raises(ScoreStoreError, match="biçimi tanınmıyor"):
        read_score_record(str(other))
    with pytest.raises(StoreError, match="biçimi tanınmıyor"):
        read_news_sources(str(other))
    with pytest.raises(StoreError, match="haber kaydı okunamıyor"):
        read_news_sources(str(path))


def test_news_sources_by_record_id(tmp_path: Path) -> None:
    path = tmp_path / "news.db"
    store = NewsStore.open(str(path))
    try:
        store.write(
            "binance",
            [NewsItem("a", None, "t", "", False, AT, AT)],
            SourceState(last_success_at=AT),
        )
        store.write(
            "coindesk",
            [NewsItem("b", None, "u", "", False, AT, AT)],
            SourceState(last_success_at=AT),
        )
    finally:
        store.close()
    assert read_news_sources(str(path)) == {1: "binance", 2: "coindesk"}


def test_reads_while_scorer_holds_the_record(tmp_path: Path) -> None:
    """R-1: skorlayıcının açık bağlantısı (WAL) okumayı beklettirmez."""
    path = tmp_path / "score.db"
    _score_store(path)
    store = ScoreStore.open(str(path), AT)
    try:
        record = read_score_record(str(path))
    finally:
        store.close()
    assert record is not None and len(record.results) == 2
