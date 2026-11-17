"""Spec 0051 AC-2, AC-5, AC-8 (plan step 3, Risk 6): skor kaydı yalnız eklenir; başlangıç anı bir
kez yazılır; haberin tek sonucu vardır; günlük çağrı sayısı ve kota anı yeniden açılışta korunur.
Haber kaydı yalnız okunur (`read_forward`)."""

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from crytobot.news import NewsItem, NewsStore, SourceState
from crytobot.news._score_store import (
    CallEnd,
    EventScore,
    ResultKind,
    ScoreResult,
    ScoreStore,
    ScoreStoreError,
    read_score_snapshot,
)
from crytobot.news._store import read_forward

START = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)
SCORE = EventScore("BTC", "Bitcoin", "spot listeleme", "olumlu", 2, "Bitcoin listed")


def scored(news_id: int, at: datetime = START) -> ScoreResult:
    return ScoreResult(
        news_id,
        ResultKind.SCORED,
        at,
        "claude-sonnet-5-5",
        "p" * 64,
        "c" * 64,
        (SCORE,),
        (("alıntı birebir değil", 2),),
    )


def test_append_only(tmp_path: Path) -> None:
    path = str(tmp_path / "score.db")
    store = ScoreStore.open(path, START)
    call = store.begin_call(1, START)
    store.write_result(scored(1), call, CallEnd("ok", 1.5, START))
    store.end_call(store.begin_call(2, START), CallEnd("timeout", 120.0, START))
    with pytest.raises(ScoreStoreError):  # one result per news
        store.write_result(scored(1, START + timedelta(hours=1)))
    store.close()

    with sqlite3.connect(path) as connection:
        for table, column in [
            ("meta", "value"),
            ("calls", "news_id"),
            ("call_ends", "outcome"),
            ("results", "kind"),
            ("event_scores", "coin"),
            ("rejections", "count"),
        ]:
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                connection.execute(f"UPDATE {table} SET {column} = {column}")
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                connection.execute(f"DELETE FROM {table}")

    again = ScoreStore.open(path, START + timedelta(days=3))
    assert again.started_at == START  # written once
    assert again.resulted() == frozenset({1})
    again.close()


def test_counts_survive_reopen(tmp_path: Path) -> None:
    path = str(tmp_path / "score.db")
    store = ScoreStore.open(path, START)
    for minute in range(3):
        at = START + timedelta(minutes=minute)
        store.end_call(store.begin_call(minute, at), CallEnd("unknown", 1.0, at))
    store.begin_call(9, START + timedelta(minutes=5))  # killed mid-call: counted, no end
    quota = START + timedelta(minutes=6)
    store.end_call(store.begin_call(10, quota), CallEnd("quota", 1.0, quota))
    store.close()

    again = ScoreStore.open(path, START)
    assert again.calls_on(START.date()) == 5
    assert again.calls_on(START.date() + timedelta(days=1)) == 0
    assert again.last_quota_at() == quota
    again.close()


def test_snapshot(tmp_path: Path) -> None:
    path = str(tmp_path / "score.db")
    assert read_score_snapshot(path, START.date()) is None
    assert not Path(path).exists()  # status creates nothing
    store = ScoreStore.open(path, START)
    store.write_result(scored(1), store.begin_call(1, START), CallEnd("ok", 1.0, START))
    later = START + timedelta(minutes=1)
    store.write_result(
        ScoreResult(2, ResultKind.SCHEMA, later, "m", "p", "c", schema_reason="çözümlenemiyor"),
        store.begin_call(2, later),
        CallEnd("ok", 1.0, later),
    )
    store.write_result(ScoreResult(3, ResultKind.STALE, later))
    store.close()
    snapshot = read_score_snapshot(path, date(2026, 11, 17))
    assert snapshot is not None
    assert snapshot.results == {"skorlandı": 1, "şema dışı": 1, "bayat": 1}
    assert snapshot.scores == {("olumlu", 2): 1}
    assert snapshot.rejections == {"alıntı birebir değil": 2}
    assert snapshot.calls_today == 2
    assert snapshot.last_scored_at == START
    assert snapshot.last_error == "şema dışı"


def test_not_a_score_record(tmp_path: Path) -> None:
    path = tmp_path / "other.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO meta VALUES ('format', '9')")
    with pytest.raises(ScoreStoreError, match="biçimi tanınmıyor"):
        ScoreStore.open(str(path), START)
    with pytest.raises(ScoreStoreError):
        read_score_snapshot(str(path), START.date())


def item(key: str, seen: datetime) -> NewsItem:
    return NewsItem(key, None, f"title {key}", f"text {key}", False, None, seen)


def test_read_forward_since_and_order(tmp_path: Path) -> None:
    path = str(tmp_path / "news.db")
    assert read_forward(path, START) is None
    assert not Path(path).exists()
    store = NewsStore.open(path)
    store.write(
        "rss",
        [
            item("late", START + timedelta(minutes=5)),
            item("before", START - timedelta(microseconds=1)),
            item("exact", START),
            item("frac", START + timedelta(microseconds=500)),
        ],
        SourceState(),
    )
    store.write("binance", [item("same", START)], SourceState())
    items = read_forward(path, START)
    store.close()
    assert items is not None
    assert [each.title for each in items] == [
        "title exact",
        "title same",
        "title frac",
        "title late",
    ]
    assert {each.source for each in items} == {"rss", "binance"}
