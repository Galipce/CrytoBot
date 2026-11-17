"""Spec 0048 AC-11 (R-11): işlem davranışı değişmez. Çalışma dizininde bot ayarı, haber ayarı,
bot deposu, kaynak kayıtlar (arşiv, ileriye dönük kayıt) vardır; iki komut koşulur; öncesi/sonrası
SHA-256 ve dosya kümesi karşılaştırılır. Paper turu koşudan önce ve sonra aynı sonucu verir."""

import hashlib
from decimal import Decimal
from pathlib import Path

from tests.app.helpers import BTC, LATER, bot_with_position, pair_market
from tests.app.test_events_run import World


def digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_configs_sources_bot_store_sha256_unchanged(tmp_path: Path) -> None:
    world = World(tmp_path)
    (tmp_path / "bot.db").write_bytes(b"SQLite format 3\x00 the bot store")
    (tmp_path / "bot.log").write_text("bot log\n", encoding="utf-8")
    (tmp_path / "crytobot-events.toml").touch()
    world.write_events()
    before = digests(tmp_path)
    assert {"crytobot.toml", "crytobot-news.toml", "archive.db", "news.db", "bot.db"} <= set(before)

    assert world.run("events", "download") == 0, world.text
    assert world.run("events", "measure") == 0, world.text

    after = digests(tmp_path)
    assert {name: after[name] for name in before} == before
    assert sorted(set(after) - set(before)) == [
        "out/library.jsonl",
        "out/prices.db",
        "out/prices.db.lock",
        "out/report.txt",
        "out/report.txt.lock",
    ]


def test_paper_turn_same(tmp_path: Path) -> None:
    def turn(path: Path) -> object:
        path.parent.mkdir(parents=True)
        bot = bot_with_position(path)
        result = bot.turn({BTC: pair_market(price=Decimal(7), price_at=LATER)}, now=LATER)
        return (result.outcome, result.buys, result.closes, result.halts, result.message)

    before = turn(tmp_path / "before" / "s.db")
    world = World(tmp_path / "events")
    assert world.run("events", "download") == 0, world.text
    assert world.run("events", "measure") == 0, world.text
    assert turn(tmp_path / "after" / "s.db") == before
