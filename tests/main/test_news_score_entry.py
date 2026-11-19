"""Spec 0051 giriş noktası `news score` ve `news score status` (AC-6, AC-8, AC-9).

`run` gerçek kodu koşar: gerçek ayar yükleyici, yol denetimi, bağlam ve parmak izleri, fiyat
deposundan borsa bilgisi, kilit, kayıt ve tur; yalnız saat, bekleme ve LLM çağrısı sahtedir.
"""

import hashlib
import io
import json
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from crytobot.__main__ import (
    COMMANDS,
    EXIT_OK,
    EXIT_REFUSED,
    SCORE_BUSY,
    USAGE,
    StoreLock,
    run,
)
from crytobot.app import StopRequest
from crytobot.market_data import PairInfo, PriceStore
from crytobot.news import (
    NewsItem,
    NewsStore,
    ScoreConfig,
    ScoreReply,
    SourceState,
    load_score_config,
)
from tests.main.test_entry import config_text

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "news" / "fixtures" / "score"
START = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)
PERMISSION_ROWS = (
    'ai_permission_by = "Test"',
    "ai_permission_on = 2026-11-17",
    'ai_permission_basis = "test koşulu"',
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def toml_value(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)  # TOML basic strings and integers


@dataclass
class Scorer:
    """Bir çalışma dizini: bot ayarı, haber ayarı ([news] + [score]), events ayarı ve fiyat
    deposu, haber kaydı, sahte saat, bekleme ve LLM."""

    root: Path
    now: datetime = START
    replies: list[ScoreReply] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    stop: StopRequest = field(default_factory=StopRequest)
    score: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.bot_config.write_text(config_text(self.root), encoding="utf-8")
        self.write_news()
        prices = self.root / "prices.db"
        self.events_config.write_text(
            f"[events]\nprice_store_path = {toml_value(prices.as_posix())}\n", encoding="utf-8"
        )
        store = PriceStore.open(str(prices))
        store.save_pairs([PairInfo("ABC", "ABCUSDT", "TRADING")], START - timedelta(days=1))
        store.close()
        self.news = NewsStore.open(str(self.root / "news.db"))

    @property
    def bot_config(self) -> Path:
        return self.root / "crytobot.toml"

    @property
    def news_config(self) -> Path:
        return self.root / "crytobot-news.toml"

    @property
    def events_config(self) -> Path:
        return self.root / "crytobot-events.toml"

    @property
    def score_table(self) -> dict[str, Any]:
        table: dict[str, Any] = {
            "store_path": (self.root / "score.db").as_posix(),
            "log_path": (self.root / "score.log").as_posix(),
            "model": "claude-sonnet-5-5",
            "calibration_report_path": (FIXTURES / "report.txt").as_posix(),
            "calibration_report_sha256": sha(FIXTURES / "report.txt"),
            "library_path": (FIXTURES / "library.jsonl").as_posix(),
            "library_sha256": sha(FIXTURES / "library.jsonl"),
        }
        for key, value in self.score.items():
            if value is None:
                table.pop(key, None)
            else:
                table[key] = value
        return table

    def write_news(self) -> None:
        rows = [
            "[news]",
            f"store_path = {toml_value((self.root / 'news.db').as_posix())}",
            f"log_path = {toml_value((self.root / 'news.log').as_posix())}",
            f"archive_store_path = {toml_value((self.root / 'archive.db').as_posix())}",
            f"archive_log_path = {toml_value((self.root / 'archive.log').as_posix())}",
            "",
            "[[news.sources]]",
            'name = "binance"',
            'type = "binance-duyuru"',
            'url = "https://example.org/b"',
            *PERMISSION_ROWS,
            "",
            "[[news.sources]]",
            'name = "coindesk"',
            'type = "rss"',
            'url = "https://example.org/r"',
            *PERMISSION_ROWS,
            "",
            "[score]",
            *(f"{key} = {toml_value(value)}" for key, value in self.score_table.items()),
        ]
        self.news_config.write_text("\n".join(rows) + "\n", encoding="utf-8")

    @property
    def config(self) -> ScoreConfig:
        with self.news_config.open("rb") as file:
            result = load_score_config(tomllib.load(file))
        assert result.config is not None, result.message
        return result.config

    def add(self, source: str, key: str, title: str, text: str, seen: datetime) -> None:
        self.news.write(
            source, [NewsItem(key, None, title, text, False, None, seen)], SourceState()
        )

    def call(self, model: str, system: str, prompt: str, timeout_s: float) -> ScoreReply:
        self.prompts.append(prompt)
        self.now += timedelta(seconds=1)
        if self.replies:
            return self.replies.pop(0)
        return ScoreReply("ok", '{"events": []}', False, 1.0, True)

    def forbidden_call(self, model: str, system: str, prompt: str, timeout_s: float) -> ScoreReply:
        raise AssertionError("no LLM call expected")

    def wait(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)
        self.stop.request("SIGINT")  # one round, then a clean stop

    def run(self, *command: str) -> tuple[int, str]:
        out = io.StringIO()
        self.stop = StopRequest()
        code = run(
            list(command),
            config_path=self.bot_config,
            news_config_path=self.news_config,
            events_config_path=self.events_config,
            console=out,
            clock=lambda: self.now,
            stop=self.stop,
            wait=self.wait,
            score_call=self.call,
        )
        return code, out.getvalue()


@pytest.fixture
def scorer(tmp_path: Path) -> Scorer:
    return Scorer(tmp_path)


def test_commands_listed() -> None:
    assert ["news", "score"] in COMMANDS and ["news", "score", "status"] in COMMANDS
    assert "[score]" in USAGE
    assert ["news", "score", "extra"] not in COMMANDS


def test_scores_and_logs(scorer: Scorer) -> None:
    scorer.add("binance", "id:1", "Binance Will Delist ABC", "Binance will delist ABC.", START)
    scorer.replies = [
        ScoreReply(
            "ok",
            json.dumps(
                {
                    "events": [
                        {
                            "coin": "ABC",
                            "name": "ABC",
                            "event_type": "listeden çıkarma",
                            "direction": "olumsuz",
                            "severity": 3,
                            "quote": "Binance will delist ABC.",
                        }
                    ]
                }
            ),
            False,
            2.0,
            True,
        )
    ]
    code, console = scorer.run("news", "score")
    assert code == EXIT_OK
    assert len(scorer.prompts) == 1
    log = (scorer.root / "score.log").read_text(encoding="utf-8")
    assert "skor başladı: model=claude-sonnet-5-5 aralık=5dk" in log
    assert "usdt_çifti=1" in log
    assert "çağrı: haber=1 kaynak=binance süre=2.0s sonuç=skorlandı skor=1 klasör=boş" in log
    assert log.splitlines()[-1].endswith("skor durdu: durdurma isteği tur_sayısı=1")
    assert "Binance will delist ABC." not in log  # no news text in the log
    code, console = scorer.run("news", "score", "status")
    assert code == EXIT_OK
    assert "haber: skorlandı=1 şema_dışı=0 bayat=0 bekleyen=0" in console
    assert "olumsuz/3=1" in console


def refuse(scorer: Scorer, *command: str) -> str:
    code, console = scorer.run(*(command or ("news", "score")))
    assert code == EXIT_REFUSED
    assert scorer.prompts == []
    assert not (scorer.root / "score.db").exists()  # nothing written to the record
    assert not (scorer.root / "score.log").exists()
    return console.strip().splitlines()[-1]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"store_path": "news.db"}, "ayar geçersiz: score.store_path"),
        ({"store_path": "sub/../news.db"}, "ayar geçersiz: score.store_path"),
        ({"store_path": "archive.db"}, "ayar geçersiz: score.store_path"),
        ({"store_path": "bot.db"}, "ayar geçersiz: score.store_path"),
        ({"store_path": "prices.db"}, "ayar geçersiz: score.store_path"),
        ({"log_path": "news.log"}, "ayar geçersiz: score.log_path"),
        ({"log_path": "sub/../bot.log"}, "ayar geçersiz: score.log_path"),
        ({"log_path": "archive.log"}, "ayar geçersiz: score.log_path"),
        ({"log_path": "score.db"}, "ayar geçersiz: score.log_path"),
        ({"model": None}, "ayar eksik: score.model"),
        ({"interval_minutes": 0}, "ayar geçersiz: score.interval_minutes (1…1440)"),
        ({"daily_call_limit": 1001}, "ayar geçersiz: score.daily_call_limit (1…1000)"),
    ],
)
def test_refusals_named(scorer: Scorer, changes: dict[str, Any], message: str) -> None:
    for key, value in changes.items():
        if isinstance(value, str) and key.endswith("_path") and not value.startswith("/"):
            changes[key] = (scorer.root / value).as_posix()
    scorer.score = changes
    scorer.write_news()
    assert refuse(scorer) == f"news score: reddedildi: {message}"


def test_news_record_and_exchange_info_missing(scorer: Scorer) -> None:
    scorer.news.close()
    for suffix in ("", "-wal", "-shm"):
        (scorer.root / f"news.db{suffix}").unlink(missing_ok=True)
    assert refuse(scorer).startswith("news score: reddedildi: haber kaydı yok:")
    NewsStore.open(str(scorer.root / "news.db")).close()
    scorer.events_config.write_text("[events]\n", encoding="utf-8")
    assert refuse(scorer).startswith("news score: reddedildi: borsa bilgisi yok")
    empty = scorer.root / "empty-prices.db"
    PriceStore.open(str(empty)).close()  # a store without a snapshot
    scorer.events_config.write_text(
        f"[events]\nprice_store_path = {toml_value(empty.as_posix())}\n", encoding="utf-8"
    )
    assert refuse(scorer) == "news score: reddedildi: borsa bilgisi yok (önce events download)"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"calibration_report_sha256": "0" * 64},
            "bağlam dosyasının parmak izi uyuşmuyor: score.calibration_report_sha256",
        ),
        (
            {"library_sha256": "0" * 64},
            "bağlam dosyasının parmak izi uyuşmuyor: score.library_sha256",
        ),
        (
            {"calibration_report_path": "missing.txt"},
            "bağlam dosyası yok: score.calibration_report_path",
        ),
        ({"library_path": "missing.jsonl"}, "bağlam dosyası yok: score.library_path"),
    ],
)
def test_context_fingerprint_mismatch_or_missing_refused(
    scorer: Scorer, changes: dict[str, Any], message: str
) -> None:
    for key, value in changes.items():
        if key.endswith("_path"):
            changes[key] = (scorer.root / value).as_posix()
    scorer.score = changes
    scorer.write_news()
    assert refuse(scorer) == f"news score: reddedildi: {message}"


def test_second_scorer_refused(scorer: Scorer) -> None:
    lock = StoreLock(str((scorer.root / "score.db").resolve()))
    assert lock.acquire() is None
    try:
        assert refuse(scorer) == f"news score: reddedildi: {SCORE_BUSY}"
    finally:
        lock.release()


def test_status_without_record(scorer: Scorer) -> None:
    code, console = scorer.run("news", "score", "status")
    assert code == EXIT_OK
    assert console.strip().splitlines()[-1] == "henüz skor yok"
    assert not (scorer.root / "score.db").exists()


def test_future_permission_date_refused(scorer: Scorer) -> None:
    """Spec 0055 CB-1: izin tarihi UTC bugünden sonraysa skorlayıcı ve durumu reddeder; çağrı ve
    kayıt yok."""
    scorer.now = START - timedelta(days=1)
    message = "news score: reddedildi: ayar geçersiz: news.sources[1].ai_permission_on (gelecekte)"
    assert refuse(scorer) == message
    assert refuse(scorer, "news", "score", "status") == message


@pytest.mark.parametrize("binance_permitted", [True, False])
def test_examples_only_with_permitted_binance(scorer: Scorer, binance_permitted: bool) -> None:
    """Spec 0055 CB-3 (VERIFY F-1): giriş noktası örnek bayrağını ayardan kurar. İzinli
    `binance-duyuru` yoksa (yalnız izinli `rss` varken de) gerçek prompt örneksizdir; varsa
    kütüphane örnekleri gelir."""
    source = "binance"
    if not binance_permitted:
        text = scorer.news_config.read_text(encoding="utf-8")
        permitted = 'url = "https://example.org/b"\n' + "\n".join(PERMISSION_ROWS) + "\n"
        assert permitted in text
        scorer.news_config.write_text(
            text.replace(permitted, 'url = "https://example.org/b"\nenabled = false\n'),
            encoding="utf-8",
        )
        source = "coindesk"  # an rss source that is permitted
    scorer.add(source, "id:1", "Binance Will Delist ABC", "Binance will delist ABC.", START)
    code, _ = scorer.run("news", "score")
    assert code == EXIT_OK
    (prompt,) = scorer.prompts
    assert ("NEW4" in prompt) is binance_permitted
    assert ("(örnek yok)" in prompt) is not binance_permitted


def test_examples_with_permitted_stream(scorer: Scorer) -> None:
    """Spec 0056 AC-9: izinli `binance-akış` kaynağı da Binance duyurusudur: gerçek promptta
    kütüphane örnekleri gelir."""
    text = scorer.news_config.read_text(encoding="utf-8")
    old = 'type = "binance-duyuru"\nurl = "https://example.org/b"'
    assert old in text
    scorer.news_config.write_text(
        text.replace(old, 'type = "binance-akış"\nurl = "wss://example.org/b"'), encoding="utf-8"
    )
    scorer.add("binance", "id:akış:1:abc", "Binance Will Delist ABC", "Binance will delist.", START)
    code, _ = scorer.run("news", "score")
    assert code == EXIT_OK
    (prompt,) = scorer.prompts
    assert "NEW4" in prompt and "(örnek yok)" not in prompt


def test_closed_stream_no_examples(scorer: Scorer) -> None:
    """Review I-2 (AC-9 olumsuz kolu): akış kaynağı kapalı ve izinli `binance-duyuru` yokken, yalnız
    izinli rss varken prompt örneksizdir."""
    text = scorer.news_config.read_text(encoding="utf-8")
    old = 'type = "binance-duyuru"\nurl = "https://example.org/b"\n' + "\n".join(PERMISSION_ROWS)
    assert old in text
    scorer.news_config.write_text(
        text.replace(old, 'type = "binance-akış"\nurl = "wss://example.org/b"\nenabled = false'),
        encoding="utf-8",
    )
    scorer.add("coindesk", "id:1", "Binance Will Delist ABC", "Binance will delist ABC.", START)
    code, _ = scorer.run("news", "score")
    assert code == EXIT_OK
    (prompt,) = scorer.prompts
    assert "NEW4" not in prompt and "(örnek yok)" in prompt
