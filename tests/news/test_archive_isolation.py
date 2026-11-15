"""Spec 0047 AC-9 (R-1): arşiv komutu çalışırken paper botunun turu ve ileriye dönük toplayıcının
turu, komut hiç yokmuş gibi aynı sonucu verir; komut bot deposuna ve ileriye dönük haber kaydına
yazmaz."""

from pathlib import Path

from crytobot.__main__ import EXIT_OK, StoreLock
from tests.main.test_entry import Bot
from tests.main.test_news_archive_entry import Archiver
from tests.main.test_news_entry import Collector
from tests.news.test_isolation import digest, dump, paper_turns


def archive_running(root: Path) -> StoreLock:
    """Bir arşiv çalıştırması yapılmış ve arşiv komutu "çalışıyor" (kilidi tutuluyor)."""
    archiver = Archiver(root)
    assert archiver.run("news", "archive")[0] == EXIT_OK
    lock = StoreLock(str(archiver.store.resolve()))
    assert lock.acquire() is None
    return lock


def plain(console: str, root: Path) -> str:
    return console.replace(str(root), "<root>").replace(root.as_posix(), "<root>")


def test_paper_turn_same_with_archive(tmp_path: Path) -> None:
    alone = paper_turns(Bot(tmp_path / "alone"))

    root = tmp_path / "beside"
    lock = archive_running(root)
    try:
        beside = paper_turns(Bot(root))
    finally:
        lock.release()

    assert beside == alone
    assert dump(tmp_path / "alone" / "bot.db") == dump(root / "bot.db")
    assert "arşiv" not in (root / "bot.log").read_text(encoding="utf-8")


def test_collector_round_same_with_archive(tmp_path: Path) -> None:
    alone_root = tmp_path / "alone"
    code, alone = Collector(alone_root).run("news")
    assert code == EXIT_OK

    root = tmp_path / "beside"
    lock = archive_running(root)
    try:
        code, beside = Collector(root).run("news")
    finally:
        lock.release()

    assert code == EXIT_OK
    assert plain(beside, root) == plain(alone, alone_root)
    assert dump(alone_root / "news.db") == dump(root / "news.db")
    alone_log = (alone_root / "news.log").read_text(encoding="utf-8")
    assert plain((root / "news.log").read_text(encoding="utf-8"), root) == plain(
        alone_log, alone_root
    )


def test_bot_and_forward_store_bytes_unchanged(tmp_path: Path) -> None:
    bot = Bot(tmp_path)
    assert bot.run("prepare")[0] == EXIT_OK
    collector = Collector(tmp_path)
    collector.bot_config.write_text(bot.config_path.read_text(encoding="utf-8"), encoding="utf-8")
    assert collector.run("news")[0] == EXIT_OK
    watched = [bot.store, bot.log, tmp_path / "news.db", tmp_path / "news.log"]
    before = [digest(path) for path in watched]
    files = sorted(path.name for path in tmp_path.iterdir())

    archiver = Archiver(tmp_path)
    archiver.bot_config.write_text(bot.config_path.read_text(encoding="utf-8"), encoding="utf-8")
    assert archiver.run("news", "archive")[0] == EXIT_OK
    assert archiver.run("news", "archive", "status")[0] == EXIT_OK

    assert [digest(path) for path in watched] == before
    added = sorted(set(path.name for path in tmp_path.iterdir()) - set(files))
    # WAL and shared-memory files go with the last connection
    assert added == ["archive.db", "archive.db.lock", "archive.log"]
