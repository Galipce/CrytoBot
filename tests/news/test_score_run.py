"""Spec 0051 AC-1, AC-2, AC-3, AC-5, AC-6, AC-9 (plan step 6): skorlama turu — hangi haberler, sıra,
bayat, şema dışı yinelenmez, geçici hata yeniden denenir, kota beklemesi, günlük ve tur sınırı,
parmak izleri, kayıt dosyasında metin yok."""

from datetime import timedelta
from pathlib import Path

import pytest

from crytobot.news import (
    PROMPT_FINGERPRINT,
    ArchiveStore,
    CatalogState,
    RawItem,
    ScoreExit,
    ScoreStore,
    context_fingerprint,
    prepare_archive,
    run_scoring,
)
from tests.news.score_harness import (
    FIXTURES,
    START,
    Harness,
    event,
    events,
    failed,
    ok,
    sha,
)

BINANCE_TITLE = "Binance Will Delist ABC on 2026-12-01"
BINANCE_TEXT = "Binance will delist Alpha Coin (ABC) at 03:00 UTC."
RSS_TITLE = "Ethereum upgrade goes live"
RSS_TEXT = "The Ethereum network completed the upgrade; ETH rose."
MODEL = "claude-sonnet-5-5"


def test_scores_binance_and_rss_with_all_fields(tmp_path: Path) -> None:
    run = Harness(tmp_path)
    run.add("binance", "id:1", BINANCE_TITLE, BINANCE_TEXT, START + timedelta(minutes=1))
    run.add("coindesk", "link:r", RSS_TITLE, RSS_TEXT, START + timedelta(minutes=2))
    run.now = START + timedelta(minutes=3)
    run.replies = [
        ok(
            events(
                event("ABC", "Alpha Coin", "Binance will delist Alpha Coin (ABC)"),
                event("QQQ", "Alpha Coin", "Alpha Coin"),  # no USDT pair: rejected, counted
            )
        ),
        ok(
            events(
                event(
                    "ETH",
                    "Ethereum",
                    "Ethereum upgrade goes live",
                    event_type="ağ yükseltmesi",
                    direction="olumlu",
                    severity=1,
                )
            )
        ),
    ]
    assert run.round()
    assert len(run.prompts) == 2
    report = sha((FIXTURES / "report.txt").read_bytes())
    library = sha((FIXTURES / "library.jsonl").read_bytes())
    fingerprints = (PROMPT_FINGERPRINT, context_fingerprint(report, library))
    first, second = START + timedelta(minutes=3, seconds=1), START + timedelta(minutes=3, seconds=2)
    assert run.rows(
        "SELECT news_id, kind, at, model, prompt_fingerprint, context_fingerprint, rejected"
        " FROM results ORDER BY news_id"
    ) == [
        (1, "skorlandı", first.isoformat(), MODEL, *fingerprints, 1),
        (2, "skorlandı", second.isoformat(), MODEL, *fingerprints, 0),
    ]
    quote = "Binance will delist Alpha Coin (ABC)"
    assert run.rows(
        "SELECT news_id, coin, name, event_type, direction, severity, quote FROM event_scores"
        " ORDER BY id"
    ) == [
        (1, "ABC", "Alpha Coin", "listeden çıkarma", "olumsuz", 2, quote),
        (2, "ETH", "Ethereum", "ağ yükseltmesi", "olumlu", 1, "Ethereum upgrade goes live"),
    ]
    assert run.rows("SELECT news_id, reason, count FROM rejections") == [(1, "USDT çifti yok", 1)]


def test_no_coin_scored_empty(tmp_path: Path) -> None:
    run = Harness(tmp_path)
    run.add("coindesk", "link:x", "Markets are calm", "Nothing happened.", START)
    run.replies = [ok('{"events": []}')]
    assert run.round()
    assert run.rows("SELECT kind, rejected FROM results") == [("skorlandı", 0)]
    assert run.rows("SELECT COUNT(*) FROM event_scores") == [(0,)]


def test_fingerprints_in_result(tmp_path: Path) -> None:
    run = Harness(tmp_path)
    run.add("binance", "id:1", BINANCE_TITLE, BINANCE_TEXT, START)
    run.stop_after_calls = 1  # the loop runs one round, then stops
    store = ScoreStore.open(run.config.store_path, START)
    try:
        assert run_scoring(run.config, store, run.parts()) is ScoreExit.STOPPED
    finally:
        store.close()
    ((prompt_fp, context_fp),) = run.rows(
        "SELECT prompt_fingerprint, context_fingerprint FROM results"
    )
    assert prompt_fp == PROMPT_FINGERPRINT and len(context_fp) == 64
    assert f"prompt={PROMPT_FINGERPRINT} bağlam={context_fp}" in run.lines[0]
    assert run.lines[-1] == "durdu: durdurma isteği tur_sayısı=1"


def test_before_start_and_archive_never_scored(tmp_path: Path) -> None:
    run = Harness(tmp_path)
    archive = ArchiveStore.open(str(tmp_path / "archive.db"))
    item = prepare_archive(RawItem("77", None, "Binance Will Delist OLD", "", START), START)
    assert item is not None
    archive.write_page(48, "Delisting", [item], CatalogState(48, "Delisting"))
    archive.close()
    run.add("binance", "id:0", "Binance Will Delist EARLY", "x", START - timedelta(seconds=1))
    run.add("binance", "id:1", BINANCE_TITLE, BINANCE_TEXT, START)  # equal to the start: scored
    assert run.round()
    assert len(run.prompts) == 1
    assert BINANCE_TITLE in run.prompts[0]
    assert all("EARLY" not in p and "Delist OLD" not in p for p in run.prompts)
    assert run.rows("SELECT news_id FROM results") == [(2,)]


def test_restart_does_not_rescore(tmp_path: Path) -> None:
    run = Harness(tmp_path)
    run.add("binance", "id:1", BINANCE_TITLE, BINANCE_TEXT, START)
    assert run.round()
    run.now += timedelta(minutes=5)
    assert run.round(started=run.now)  # a restart keeps the first start moment
    assert len(run.prompts) == 1
    assert run.rows("SELECT value FROM meta WHERE name = 'started_at'") == [(START.isoformat(),)]


def test_stale_after_24h_without_call(tmp_path: Path) -> None:
    run = Harness(tmp_path, score={"daily_call_limit": 1})
    run.add("binance", "id:1", BINANCE_TITLE, BINANCE_TEXT, START)
    run.add("coindesk", "link:r", RSS_TITLE, RSS_TEXT, START + timedelta(minutes=1))
    run.now = START + timedelta(
        hours=24, seconds=30
    )  # the first is older than 24 h, not the second
    run.replies = [failed("timeout")]
    assert run.round()
    assert run.rows("SELECT news_id, kind, call_id FROM results") == [(1, "bayat", None)]
    assert len(run.prompts) == 1 and RSS_TITLE in run.prompts[0]
    assert "bayat: haber=1 kaynak=binance çağrı yok" in run.lines
    run.now += timedelta(hours=1)
    assert run.round()  # the second is stale too now: no call, the daily limit is full anyway
    assert len(run.prompts) == 1
    assert run.rows("SELECT news_id, kind FROM results ORDER BY news_id") == [
        (1, "bayat"),
        (2, "bayat"),
    ]


def test_order_by_first_seen(tmp_path: Path) -> None:
    run = Harness(tmp_path)
    run.add("coindesk", "link:late", "Late news", "late", START + timedelta(minutes=9))
    run.add("binance", "id:early", "Early news", "early", START + timedelta(minutes=1))
    run.add("coindesk", "link:mid", "Middle news", "mid", START + timedelta(minutes=5))
    run.now = START + timedelta(minutes=10)
    assert run.round()
    order = [
        next(name for name in ("Early", "Middle", "Late") if f"başlık: {name} news" in prompt)
        for prompt in run.prompts
    ]
    assert order == ["Early", "Middle", "Late"]


def test_schema_reject_not_retried(tmp_path: Path) -> None:
    run = Harness(tmp_path)
    run.add("binance", "id:1", BINANCE_TITLE, BINANCE_TEXT, START)
    run.replies = [ok("```json\n{}\n```")]
    assert run.round()
    assert run.rows("SELECT kind, schema_reason, reply_size FROM results") == [
        ("şema dışı", "çözümlenemiyor", 14)
    ]
    run.now += timedelta(minutes=5)
    assert run.round()
    assert len(run.prompts) == 1
    assert any("sonuç=şema dışı neden=çözümlenemiyor boyut=14" in line for line in run.lines)


@pytest.mark.parametrize("outcome", ["timeout", "no_session", "unknown"])
def test_transient_retried_next_round(tmp_path: Path, outcome: str) -> None:
    run = Harness(tmp_path)
    run.add("binance", "id:1", BINANCE_TITLE, BINANCE_TEXT, START)
    run.add("coindesk", "link:r", RSS_TITLE, RSS_TEXT, START + timedelta(minutes=1))
    run.now = START + timedelta(minutes=2)
    run.replies = [failed(outcome)]
    assert run.round()
    assert len(run.prompts) == 1  # the round ends at the failure: no hammering
    assert run.rows("SELECT COUNT(*) FROM results") == [(0,)]
    assert run.rows("SELECT outcome FROM call_ends") == [(outcome,)]
    assert f"hata={outcome}" in run.lines[-1]
    run.now += timedelta(minutes=5)
    assert run.round()
    assert len(run.prompts) == 3  # the same news first, then the next
    assert BINANCE_TITLE in run.prompts[1]
    assert run.rows("SELECT news_id, kind FROM results ORDER BY news_id") == [
        (1, "skorlandı"),
        (2, "skorlandı"),
    ]


def test_quota_wait(tmp_path: Path) -> None:
    run = Harness(tmp_path)
    run.add("binance", "id:1", BINANCE_TITLE, BINANCE_TEXT, START)
    run.replies = [failed("quota")]
    assert run.round()
    quota_at = run.now
    for minutes in (5, 30, 59):
        run.now = quota_at + timedelta(minutes=minutes)
        assert run.round()
        assert len(run.prompts) == 1, minutes
    assert "durum=kota beklemesi" in run.lines[-1]
    run.now = quota_at + timedelta(minutes=60)
    assert run.round()
    assert len(run.prompts) == 2
    assert run.rows("SELECT kind FROM results") == [("skorlandı",)]


def test_daily_limit_survives_restart(tmp_path: Path) -> None:
    run = Harness(tmp_path, score={"daily_call_limit": 2})
    for index in range(4):
        run.add("coindesk", f"link:{index}", f"News {index}", "t", START + timedelta(minutes=index))
    run.now = START.replace(hour=23, minute=50)
    run.replies = [failed("unknown"), ok(events())]
    assert run.round()  # the failure ends the round: 1 call
    assert run.round()  # restart: 1 more call; the limit counts failures too
    assert len(run.prompts) == 2
    assert run.round()
    assert len(run.prompts) == 2
    assert "durum=günlük sınır dolu" in run.lines[-1]
    run.now = START.replace(day=18, hour=0, minute=0, second=1)  # the next UTC day
    assert run.round()
    assert len(run.prompts) == 4  # 2 more, then the limit again
    assert "durum=günlük sınır dolu" in run.lines[-1]


def test_round_limit(tmp_path: Path) -> None:
    run = Harness(tmp_path, score={"max_calls_per_round": 2})
    for index in range(3):
        run.add("coindesk", f"link:{index}", f"News {index}", "t", START + timedelta(minutes=index))
    run.now = START + timedelta(minutes=5)
    assert run.round()
    assert len(run.prompts) == 2
    assert "bekleyen=3 çağrı=2 skorlandı=2" in run.lines[-1]
    assert "durum=tur sınırı" in run.lines[-1]
    assert run.round()
    assert len(run.prompts) == 3


def test_stop_between_calls_and_stopped_call(tmp_path: Path) -> None:
    run = Harness(tmp_path)
    for index in range(3):
        run.add("coindesk", f"link:{index}", f"News {index}", "t", START + timedelta(minutes=index))
    run.now = START + timedelta(minutes=5)
    run.stop_after_calls = 1
    assert not run.round()
    assert len(run.prompts) == 1
    run.stop_after_calls = None
    run.replies = [failed("stopped")]
    assert not run.round()  # a stopped call ends the round as stopped and writes no result
    assert run.rows("SELECT news_id FROM results") == [(1,)]
    assert run.rows("SELECT outcome FROM call_ends ORDER BY call_id") == [("ok",), ("stopped",)]


def test_log_has_no_text_prompt_or_reply(tmp_path: Path) -> None:
    run = Harness(tmp_path)
    body = "UNIQUE-BODY-TEXT Binance will delist Alpha Coin (ABC)"
    run.add("binance", "id:1", "UNIQUE-TITLE Binance Will Delist ABC", body, START)
    run.add("coindesk", "link:r", "UNIQUE-TITLE-2", "UNIQUE-BODY-2", START)
    run.replies = [
        ok(events(event("ABC", "Alpha Coin", "Binance will delist Alpha Coin (ABC)"))),
        ok("UNIQUE-REPLY not json"),
    ]
    assert run.round()
    log = "\n".join(run.lines)
    for needle in ("UNIQUE", "Alpha Coin", "TALİMAT", "VERİ", "events"):
        assert needle not in log
    assert "çağrı: haber=1 kaynak=binance süre=1.5s sonuç=skorlandı skor=1 klasör=boş" in log
    assert "çağrı: haber=2 kaynak=coindesk süre=1.5s sonuç=şema dışı neden=çözümlenemiyor" in log
