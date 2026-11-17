"""Spec 0051 AC-9 (plan step 6, 7): durum komutu R-9'un bütün kalemlerini gösterir; kayıt yokken
"henüz skor yok" der; ağa, LLM'e ve kilide dokunmaz."""

import io
from datetime import timedelta
from pathlib import Path

from crytobot.__main__ import EXIT_OK, StoreLock, run
from crytobot.news import (
    NO_SCORES,
    read_forward,
    read_score_snapshot,
    score_status_lines,
)
from tests.main.test_news_score_entry import Scorer
from tests.news.score_harness import START, Harness, event, events, failed, ok


def test_all_items(tmp_path: Path) -> None:
    run_ = Harness(tmp_path)
    for index in range(4):
        run_.add(
            "coindesk", f"link:{index}", f"News ABC {index}", "Binance will delist ABC.", START
        )
    run_.add("binance", "id:stale", "Old", "t", START)
    run_.replies = [
        ok(
            events(
                event("ABC", "ABC", "Binance will delist ABC."),
                event("XYZ", "XYZ", "not in the text"),
                event("ABC", "ABC", "Binance will delist ABC."),
            )
        ),
        ok("not json"),
        failed("timeout"),
    ]
    run_.now = START + timedelta(minutes=1)
    assert run_.round()  # scored, schema, timeout
    config = run_.config
    snapshot = read_score_snapshot(config.store_path, run_.now.date())
    lines = score_status_lines(config, snapshot, read_forward(config.news.store_path, START))
    assert lines == [
        f"skor kaydı: {config.store_path} model=claude-sonnet-5-5",
        f"başlangıç anı: {START.isoformat()}",
        "haber: skorlandı=1 şema_dışı=1 bayat=0 bekleyen=3",
        "olay skoru: toplam=1 olumlu/1=0 olumlu/2=0 olumlu/3=0 olumsuz/1=0 olumsuz/2=1"
        " olumsuz/3=0 belirsiz/1=0 belirsiz/2=0 belirsiz/3=0",
        "reddedilen olay skoru: toplam=2 alıntı birebir değil=1 yinelenen coin=1",
        "bugünkü çağrı (UTC): 3/200",
        f"son başarılı skor: {(START + timedelta(minutes=1, seconds=1)).isoformat()}",
        "son hata: timeout",
    ]
    missing = score_status_lines(config, snapshot, None)
    assert missing[2].endswith("bekleyen=bilinmiyor (haber kaydı yok)")


def test_no_record(tmp_path: Path) -> None:
    config = Harness(tmp_path).config
    assert read_score_snapshot(config.store_path, START.date()) is None
    assert score_status_lines(config, None, ()) == [
        f"skor kaydı: {config.store_path} model=claude-sonnet-5-5",
        NO_SCORES,
    ]
    assert not Path(config.store_path).exists()


def test_status_no_call_no_lock(tmp_path: Path) -> None:
    scorer = Scorer(tmp_path)
    scorer.replies = [ok(events())]
    scorer.add("binance", "id:1", "Binance Will Delist ABC", "t", START)
    assert scorer.run("news", "score")[0] == EXIT_OK
    calls = len(scorer.prompts)
    lock = StoreLock(str(Path(scorer.config.store_path).resolve()))
    assert lock.acquire() is None  # a scorer "runs"
    try:
        console = io.StringIO()
        code = run(
            ["news", "score", "status"],
            config_path=scorer.bot_config,
            console=console,
            clock=lambda: START + timedelta(hours=1),
            news_config_path=scorer.news_config,
            events_config_path=scorer.events_config,
            score_call=scorer.forbidden_call,
        )
    finally:
        lock.release()
    assert code == EXIT_OK
    assert len(scorer.prompts) == calls  # no LLM call
    assert "haber: skorlandı=1 şema_dışı=0 bayat=0 bekleyen=0" in console.getvalue()
