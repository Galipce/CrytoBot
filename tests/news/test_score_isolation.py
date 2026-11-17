"""Spec 0051 AC-7 (R-7, R-8): skorlayıcı bot deposunu ve bot kaydını açmaz, haber kaydına yazmaz;
skorlayıcı okurken toplayıcının haber yazması sürer, toplayıcı yazarken skorlayıcı okur."""

import hashlib
from datetime import timedelta
from pathlib import Path

from crytobot.__main__ import EXIT_OK
from crytobot.news import NewsItem, ScoreReply, SourceState, read_forward
from tests.main.test_entry import Bot
from tests.main.test_news_score_entry import START, Scorer


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_bot_store_never_opened(tmp_path: Path) -> None:
    bot = Bot(tmp_path)
    assert bot.run("prepare")[0] == EXIT_OK
    scorer = Scorer(tmp_path)
    scorer.bot_config.write_text(bot.config_path.read_text(encoding="utf-8"), encoding="utf-8")
    scorer.add("binance", "id:1", "Binance Will Delist ABC", "t", START)
    scorer.news.close()
    before = {path.name: digest(path) for path in tmp_path.iterdir() if path.is_file()}
    assert scorer.run("news", "score")[0] == EXIT_OK
    assert len(scorer.prompts) == 1
    after = {path.name: digest(path) for path in tmp_path.iterdir() if path.is_file()}
    for name in ("bot.db", "bot.log", "news.db", "prices.db", "crytobot.toml"):
        assert after[name] == before[name], name  # bot, news and price records untouched
    added = sorted(set(after) - set(before))
    assert [name for name in added if not name.startswith("news.db-")] == [
        "score.db",
        "score.db.lock",
        "score.log",
    ]  # the read-only news connection may leave its WAL index; nothing else is new


def test_collector_writes_while_scorer_reads(tmp_path: Path) -> None:
    scorer = Scorer(tmp_path)
    scorer.add("binance", "id:1", "Binance Will Delist ABC", "t", START)
    written: list[bool] = []

    def call(model: str, system: str, prompt: str, timeout_s: float) -> ScoreReply:
        # the collector writes a new item while the scorer is mid-round, reading the record
        written.extend(
            scorer.news.write(
                "coindesk",
                [NewsItem("link:new", None, "New", "n", False, None, START + timedelta(minutes=1))],
                SourceState(),
            )
        )
        return ScoreReply("ok", '{"events": []}', False, 1.0, True)

    scorer.call = call  # type: ignore[method-assign]
    assert scorer.run("news", "score")[0] == EXIT_OK
    assert written == [True]

    # and the scorer reads while the collector holds an open write transaction
    connection = scorer.news._connection
    connection.execute("BEGIN IMMEDIATE")
    try:
        items = read_forward(str(tmp_path / "news.db"), START)
    finally:
        connection.execute("ROLLBACK")
    assert items is not None and [item.title for item in items] == [
        "Binance Will Delist ABC",
        "New",
    ]
