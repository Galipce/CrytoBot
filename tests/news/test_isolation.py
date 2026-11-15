"""Spec 0046 AC-8 (R-1): toplayıcı çalışırken paper botunun turu, toplayıcı hiç yokmuş gibi aynı
sonucu verir; toplayıcı bot deposuna ve bot kaydına yazmaz."""

import hashlib
import sqlite3
from pathlib import Path

from crytobot.__main__ import EXIT_OK, StoreLock
from tests.main.test_entry import Bot
from tests.main.test_news_entry import Collector


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path) -> list[str]:
    with sqlite3.connect(path) as connection:
        return list(connection.iterdump())


def paper_turns(bot: Bot) -> str:
    assert bot.run("prepare")[0] == EXIT_OK
    code, console = bot.run("start")
    assert code == EXIT_OK
    return console.replace(str(bot.root), "<root>").replace(bot.root.as_posix(), "<root>")


def test_paper_turn_same_with_collector(tmp_path: Path) -> None:
    alone = paper_turns(Bot(tmp_path / "alone"))

    root = tmp_path / "beside"
    collector = Collector(root)
    assert collector.run("news")[0] == EXIT_OK  # a round before the bot starts
    news_lock = StoreLock(str(collector.store.resolve()))  # the collector is "running"
    assert news_lock.acquire() is None
    try:
        beside = paper_turns(Bot(root))
    finally:
        news_lock.release()

    assert beside == alone
    assert dump(tmp_path / "alone" / "bot.db") == dump(root / "bot.db")
    log = (root / "bot.log").read_text(encoding="utf-8")
    assert "haber" not in log


def test_bot_store_bytes_unchanged(tmp_path: Path) -> None:
    bot = Bot(tmp_path)
    assert bot.run("prepare")[0] == EXIT_OK
    store, log = digest(bot.store), digest(bot.log)
    files = sorted(path.name for path in tmp_path.iterdir())
    collector = Collector(tmp_path)
    collector.bot_config.write_text(bot.config_path.read_text(encoding="utf-8"), encoding="utf-8")
    collector.stop_after_rounds = 2
    assert collector.run("news")[0] == EXIT_OK
    assert (digest(bot.store), digest(bot.log)) == (store, log)
    added = sorted(set(path.name for path in tmp_path.iterdir()) - set(files))
    # WAL and shared-memory files go with the last connection
    assert added == ["crytobot-news.toml", "news.db", "news.db.lock", "news.log"]
