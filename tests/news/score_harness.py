"""Skorlayıcı testlerinin ortak düzeneği: haber kaydı, ayar, bağlam, sahte saat ve sahte LLM."""

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from crytobot.news import (
    NewsItem,
    NewsStore,
    ScoreConfig,
    ScoreParts,
    ScoreReply,
    ScoreStore,
    SourceState,
    load_context,
    load_score_config,
    run_score_round,
)

FIXTURES = Path(__file__).parent / "fixtures" / "score"
START = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)
PAIRS = frozenset({"ABC", "XYZ", "BTC", "ETH"})


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ok(text: str) -> ScoreReply:
    return ScoreReply("ok", text, False, 1.5, True)


def failed(outcome: str) -> ScoreReply:
    return ScoreReply(outcome, None, False, 2.0, True)


def events(*items: dict[str, Any]) -> str:
    return json.dumps({"events": list(items)}, ensure_ascii=False)


def event(coin: str, name: str, quote: str, **changes: object) -> dict[str, Any]:
    item: dict[str, Any] = {
        "coin": coin,
        "name": name,
        "event_type": "listeden çıkarma",
        "direction": "olumsuz",
        "severity": 2,
        "quote": quote,
    }
    item.update(changes)
    return item


def score_document(root: Path, **score: object) -> dict[str, Any]:
    report = (FIXTURES / "report.txt").read_bytes()
    library = (FIXTURES / "library.jsonl").read_bytes()
    table: dict[str, Any] = {
        "store_path": str(root / "score.db"),
        "log_path": str(root / "score.log"),
        "model": "claude-sonnet-5-5",
        "calibration_report_path": str(FIXTURES / "report.txt"),
        "calibration_report_sha256": sha(report),
        "library_path": str(FIXTURES / "library.jsonl"),
        "library_sha256": sha(library),
    }
    table.update(score)
    return {
        "news": {
            "store_path": str(root / "news.db"),
            "log_path": str(root / "news.log"),
            "sources": [
                {"name": "binance", "type": "binance-duyuru", "url": "https://example.org/b"},
                {"name": "coindesk", "type": "rss", "url": "https://example.org/r"},
            ],
        },
        "score": table,
    }


Reply = ScoreReply | Callable[[str], ScoreReply]


@dataclass
class Harness:
    root: Path
    score: dict[str, object] = field(default_factory=dict)
    now: datetime = START
    replies: list[Reply] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    stop_after_calls: int | None = None
    call_seconds: float = 1.0

    def __post_init__(self) -> None:
        self.news = NewsStore.open(str(self.root / "news.db"))

    @property
    def config(self) -> ScoreConfig:
        result = load_score_config(score_document(self.root, **self.score))
        assert result.config is not None, result.message
        return result.config

    def add(self, source: str, key: str, title: str, text: str, seen: datetime) -> None:
        self.news.write(
            source, [NewsItem(key, None, title, text, False, None, seen)], SourceState()
        )

    def call(self, model: str, system: str, prompt: str, timeout_s: float) -> ScoreReply:
        assert (model, timeout_s) == (self.config.model, float(self.config.timeout_s))
        self.prompts.append(prompt)
        self.now += timedelta(seconds=self.call_seconds)
        reply = self.replies.pop(0) if self.replies else ok(events())
        return reply(prompt) if callable(reply) else reply

    def parts(self) -> ScoreParts:
        report = (FIXTURES / "report.txt").read_bytes()
        library = (FIXTURES / "library.jsonl").read_bytes()
        context = load_context(report, sha(report), library, sha(library))
        return ScoreParts(
            lambda: self.now,
            lambda seconds: None,
            self.stopped,
            self.call,
            self.lines.append,
            context,
            PAIRS,
            START - timedelta(days=1),
        )

    def stopped(self) -> bool:
        return self.stop_after_calls is not None and len(self.prompts) >= self.stop_after_calls

    def round(self, started: datetime | None = None) -> bool:
        """Kayıt her turda yeniden açılır: yeniden başlatma gibi."""
        store = ScoreStore.open(self.config.store_path, started or START)
        try:
            return run_score_round(self.config, store, self.parts())
        finally:
            store.close()

    def rows(self, sql: str) -> list[tuple[Any, ...]]:
        with sqlite3.connect(self.config.store_path) as connection:
            return [tuple(row) for row in connection.execute(sql).fetchall()]
