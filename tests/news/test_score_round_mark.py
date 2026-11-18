"""Spec 0052 AC-6 (plan step 2, Risk 2, 3): skorlayıcı her turun anını ve turun başındaki engelini
skor kaydına yazar — çağrı yapmayan turda da; tur aralığı 15 dakikayı aşan ayarla başlamayı adıyla
reddeder, tam 15 kabul edilir. İz yalnız eklenir; 0051'de açılmış kayıtta tablo yeniden açılışta
oluşur. 0051'in testleri değişmeden geçer (aynı düzenek)."""

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from crytobot.news import load_score_config
from crytobot.news._score_store import ScoreStore
from tests.main.test_news_score_entry import Scorer, refuse
from tests.news.test_score_run import START, Harness, failed, score_document


def marks(run: Harness) -> list[tuple[str, str | None]]:
    return [(str(at), held) for at, held in run.rows("SELECT at, held FROM rounds ORDER BY id")]


def test_round_mark_without_calls_quota_wait(tmp_path: Path) -> None:
    run = Harness(tmp_path)
    run.add("binance", "id:1", "News ABC", "t", START)
    run.replies = [failed("quota")]
    assert run.round()
    quota_at = run.now
    run.now = quota_at + timedelta(minutes=5)
    assert run.round()
    assert len(run.prompts) == 1  # the second round made no call
    assert marks(run) == [(START.isoformat(), None), (run.now.isoformat(), "kota beklemesi")]


def test_round_mark_without_calls_daily_limit(tmp_path: Path) -> None:
    run = Harness(tmp_path, score={"daily_call_limit": 1})
    for index in range(2):
        run.add("coindesk", f"link:{index}", f"News {index}", "t", START)
    run.now = START + timedelta(minutes=1)
    assert run.round()
    first = run.now - timedelta(seconds=run.call_seconds)  # the mark is the round's start
    run.now = START + timedelta(minutes=6)
    assert run.round()
    assert len(run.prompts) == 1
    assert marks(run) == [
        (first.isoformat(), None),
        (run.now.isoformat(), "günlük sınır dolu"),
    ]


def test_round_mark_without_calls_nothing_pending(tmp_path: Path) -> None:
    run = Harness(tmp_path)
    for minutes in (1, 6):
        run.now = START + timedelta(minutes=minutes)
        assert run.round()
    assert run.prompts == []
    assert marks(run) == [
        ((START + timedelta(minutes=1)).isoformat(), None),
        ((START + timedelta(minutes=6)).isoformat(), None),
    ]


def test_round_mark_before_news_read(tmp_path: Path) -> None:
    """Haber kaydı okunamasa da iz yazılmıştır: turun ilk işi."""
    run = Harness(tmp_path)
    run.news.close()
    for suffix in ("", "-wal", "-shm"):
        (tmp_path / f"news.db{suffix}").unlink(missing_ok=True)
    with pytest.raises(Exception, match="haber kaydı yok"):
        run.round()
    assert marks(run) == [(START.isoformat(), None)]


def test_rounds_append_only_and_added_to_old_record(tmp_path: Path) -> None:
    path = tmp_path / "score.db"
    store = ScoreStore.open(str(path), START)
    store.mark_round(START, None)
    store.close()
    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE rounds SET held = 'x'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM rounds")
        # a 0051 record: no rounds table yet
        connection.execute("DROP TRIGGER rounds_no_update")
        connection.execute("DROP TRIGGER rounds_no_delete")
        connection.execute("DROP TABLE rounds")
    again = ScoreStore.open(str(path), START + timedelta(days=1))
    assert again.started_at == START
    again.mark_round(START + timedelta(days=1), "kota beklemesi")
    again.close()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT held FROM rounds").fetchall() == [("kota beklemesi",)]


def test_interval_over_15_refused_15_accepted(tmp_path: Path) -> None:
    accepted = load_score_config(score_document(tmp_path, interval_minutes=15))
    assert accepted.config is not None and accepted.config.interval_minutes == 15
    refused = load_score_config(score_document(tmp_path, interval_minutes=16))
    assert refused.config is None
    assert refused.message == "ayar geçersiz: score.interval_minutes (en çok 15)"
    # 0051's range message is unchanged (plan 0052 Risk 2)
    assert load_score_config(score_document(tmp_path, interval_minutes=0)).message == (
        "ayar geçersiz: score.interval_minutes (1…1440)"
    )


def test_scorer_start_refused_over_15(tmp_path: Path) -> None:
    scorer = Scorer(tmp_path / "work")
    scorer.score = {"interval_minutes": 16}
    scorer.write_news()
    assert refuse(scorer) == (
        "news score: reddedildi: ayar geçersiz: score.interval_minutes (en çok 15)"
    )
