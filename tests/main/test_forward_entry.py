"""Spec 0053 giriş noktası `python -m crytobot forward download` ve `forward report [--at <an>]`
(AC-9, AC-10; plan Risk 7, 8, 10): retler hiçbir dosyaya dokunmadan, adıyla, çıkış 1; rapor ağsız,
LLM'siz ve kilitsiz; okunan kayıtlar bayt bayt aynı kalır.

`run` gerçek kodu koşar (`tests/app/test_forward_run.py`'nin `World`'ü): ayar yükleyiciler, yol
çakışması, kilit, depo ve iki koşu; yalnız borsa, monoton saat ve bekleme sahtedir.
"""

from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import pytest

from crytobot.__main__ import (
    COMMANDS,
    EXIT_FORCED,
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_REPORT_NOT_WRITTEN,
    FORWARD_AT_INVALID,
    FORWARD_BUSY,
    USAGE,
    StoreLock,
)
from crytobot.app import ForcedStop
from crytobot.market_data import DownloadOutcome, EventPriceParts, PriceNeed, PriceStore
from crytobot.news import ScoreStore
from tests.app.test_forward_run import NOW, REPORT_AT, World

EXIT_STOPPED = 4


def listing(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


def test_forward_commands_are_known() -> None:
    assert ["forward", "download"] in COMMANDS and ["forward", "report"] in COMMANDS
    assert "|forward" in USAGE and "[report] [--at YYYY-MM-DDTHH:MM:SSZ]" in USAGE
    assert "[download] [measure]" in USAGE


@pytest.mark.parametrize(
    ("argv", "text"),
    [
        (["forward"], USAGE),
        (["forward", "measure"], USAGE),
        (["forward", "report", "--at"], USAGE),
        (["forward", "download", "--at", "2026-11-18T12:00:00Z"], USAGE),
        (["forward", "report", "--at", "2026-11-18T12:00:00"], FORWARD_AT_INVALID),
        (["forward", "report", "--at", "dün"], FORWARD_AT_INVALID),
    ],
)
def test_usage_and_report_time_refused(tmp_path: Path, argv: list[str], text: str) -> None:
    world = World(tmp_path)
    before = listing(tmp_path)
    assert world.run(*argv) == EXIT_REFUSED
    expected = text if text == USAGE else f"forward report: reddedildi: {text}"
    assert world.text == f"{expected}\n"
    assert listing(tmp_path) == before


def test_future_report_time_refused(tmp_path: Path) -> None:
    world = World(tmp_path)
    later = (NOW + timedelta(seconds=1)).isoformat()
    assert world.run("forward", "report", "--at", later) == EXIT_REFUSED
    assert world.text == "forward report: reddedildi: rapor anı gelecekte\n"
    assert not world.report.exists() and not world.samples.exists()


COLLISIONS = [
    ("report_path", "score.db"),
    ("report_path", "score.log"),
    ("report_path", "shadow.jsonl"),
    ("samples_path", "news.db"),
    ("samples_path", "news.log"),
    ("report_path", "archive.db"),
    ("samples_path", "archive.log"),
    ("report_path", "bot.db"),
    ("samples_path", "bot.log"),
    ("report_path", "paper.db"),
    ("report_path", "crytobot.toml"),
    ("samples_path", "crytobot-news.toml"),
    ("report_path", "crytobot-forward.toml"),
    ("samples_path", "out/report.txt"),
    ("report_path", "out/prices.db"),
    ("price_store_path", "score.db"),
    ("price_store_path", "./out/../news.db"),
]


@pytest.mark.parametrize("command", ["download", "report"])
@pytest.mark.parametrize(("key", "target"), COLLISIONS)
def test_output_path_collisions_refused_nothing_written(
    tmp_path: Path, command: str, key: str, target: str
) -> None:
    world = World(tmp_path)
    world.write_bot(stage=f'"{(tmp_path / "paper.db").as_posix()}"')
    world.write_forward(**{key: f'"{(tmp_path / target).as_posix()}"'})
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    assert world.run("forward", command) == EXIT_REFUSED
    assert world.text == f"forward {command}: reddedildi: ayar geçersiz: forward.{key}\n"
    assert (world.downloads, world.exchange.calls) == (0, [])
    after = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before


@pytest.mark.parametrize("command", ["download", "report"])
def test_config_refusals_named(tmp_path: Path, command: str) -> None:
    world = World(tmp_path)
    (tmp_path / "crytobot-forward.toml").unlink()
    assert world.run("forward", command) == EXIT_REFUSED
    assert world.text == f"forward {command}: reddedildi: ayar dosyası yok: crytobot-forward.toml\n"
    world.write_forward(samples_path="")
    assert world.run("forward", command) == EXIT_REFUSED
    assert world.text == f"forward {command}: reddedildi: ayar eksik: forward.samples_path\n"
    world.write_forward()
    news = (tmp_path / "crytobot-news.toml").read_text(encoding="utf-8")
    (tmp_path / "crytobot-news.toml").write_text(news.split("[score]")[0], encoding="utf-8")
    assert world.run("forward", command) == EXIT_REFUSED
    assert world.text.startswith(f"forward {command}: reddedildi: ayar eksik: score")
    (tmp_path / "crytobot-news.toml").unlink()
    assert world.run("forward", command) == EXIT_REFUSED
    assert "ayar dosyası yok: crytobot-news.toml" in world.text
    (tmp_path / "crytobot-news.toml").write_text(news, encoding="utf-8")
    (tmp_path / "crytobot.toml").write_text("[bot]\n", encoding="utf-8")
    assert world.run("forward", command) == EXIT_REFUSED
    assert world.text.startswith(f"forward {command}: reddedildi: bot ayarı: ")
    (tmp_path / "crytobot.toml").unlink()
    assert world.run("forward", command) == EXIT_REFUSED
    assert "ayar dosyası yok: crytobot.toml" in world.text
    world.write_bot()
    text = (tmp_path / "crytobot.toml").read_text(encoding="utf-8")
    (tmp_path / "crytobot.toml").write_text(text + "extra = 1\n", encoding="utf-8")
    assert world.run("forward", command) == EXIT_REFUSED
    assert world.text == f"forward {command}: reddedildi: bilinmeyen ayar: shadow.extra\n"
    assert world.downloads == 0 and not world.prices.exists() and not world.report.exists()


def test_no_score_record_writes_no_verdict(tmp_path: Path) -> None:
    world = World(tmp_path, scores=False, shadow=False)
    assert world.run("forward", "report", "--at", REPORT_AT.isoformat()) == EXIT_OK, world.text
    text = world.report.read_text(encoding="utf-8")
    assert "hüküm: hüküm yok: skor yok — kalan 90 gün, 30 örnek" in text
    assert world.samples.read_text(encoding="utf-8").count("\n") == 1


def test_report_no_network_no_llm_no_lock(tmp_path: Path) -> None:
    """R-1: rapor borsaya, arşive ve LLM'e çıkmaz; fiyat deposunun kilidi tutulurken de koşar."""
    world = World(tmp_path)
    assert world.run("forward", "download") == EXIT_OK, world.text
    calls, downloads = list(world.exchange.calls), world.downloads
    lock = StoreLock(str(world.prices.resolve()))
    assert lock.acquire() is None
    try:
        assert world.run("forward", "report", "--at", REPORT_AT.isoformat()) == EXIT_OK
    finally:
        lock.release()
    assert (world.exchange.calls, world.downloads) == (calls, downloads)
    assert "forward report: hüküm: " in world.text


def test_report_while_score_and_bot_locked(tmp_path: Path) -> None:
    world = World(tmp_path)
    assert world.run("forward", "download") == EXIT_OK, world.text
    locks = [
        StoreLock(str((tmp_path / name).resolve())) for name in ("score.db", "bot.db", "news.db")
    ]
    for lock in locks:
        assert lock.acquire() is None
    scorer = ScoreStore.open(str(tmp_path / "score.db"), NOW)
    try:
        assert world.run("forward", "report", "--at", REPORT_AT.isoformat()) == EXIT_OK
    finally:
        scorer.close()
        for lock in locks:
            lock.release()
    assert world.report.is_file()


def test_inputs_byte_identical_after_report(tmp_path: Path) -> None:
    world = World(tmp_path)
    assert world.run("forward", "download") == EXIT_OK, world.text
    inputs = [
        tmp_path / name
        for name in (
            "score.db",
            "news.db",
            "shadow.jsonl",
            "crytobot.toml",
            "crytobot-news.toml",
            "crytobot-forward.toml",
        )
    ] + [world.prices]
    before = [path.read_bytes() for path in inputs]
    assert world.run("forward", "report", "--at", REPORT_AT.isoformat()) == EXIT_OK
    assert world.run("forward", "report") == EXIT_OK
    assert [path.read_bytes() for path in inputs] == before
    assert not (tmp_path / "bot.db").exists() and not (tmp_path / "bot.log").exists()


def test_download_lock_refused(tmp_path: Path) -> None:
    world = World(tmp_path)
    lock = StoreLock(str(world.prices.resolve()))
    assert lock.acquire() is None
    try:
        assert world.run("forward", "download") == EXIT_REFUSED
        assert world.text == f"forward download: reddedildi: {FORWARD_BUSY}\n"
    finally:
        lock.release()
    assert world.downloads == 0 and not world.prices.exists()


class Planned(World):
    outcome: DownloadOutcome = DownloadOutcome.STOPPED
    forced: bool = False

    def download(
        self, needs: Sequence[PriceNeed], store: PriceStore, parts: EventPriceParts, gap: float
    ) -> DownloadOutcome:
        self.downloads += 1
        if self.forced:
            raise ForcedStop
        return self.outcome


def test_download_exit_codes(tmp_path: Path) -> None:
    world = Planned(tmp_path)
    assert world.run("forward", "download") == EXIT_STOPPED
    world.outcome = DownloadOutcome.FAILED
    assert world.run("forward", "download") == EXIT_REFUSED
    world.forced = True
    assert world.run("forward", "download") == EXIT_FORCED
    assert world.downloads == 3


def test_unreadable_inputs_refused(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.shadow_path.unlink()
    world.shadow_path.mkdir()
    assert world.run("forward", "report") == EXIT_REFUSED
    assert world.text == "forward report: reddedildi: gölge kayıt okunamıyor\n"
    world.shadow_path.rmdir()
    (tmp_path / "score.db").unlink()
    (tmp_path / "score.db").write_bytes(b"not a database" * 20)
    assert world.run("forward", "report") == EXIT_REFUSED
    assert world.text == "forward report: reddedildi: skor kaydı okunamıyor\n"
    assert not world.report.exists()


def test_report_not_written_exit_6(tmp_path: Path) -> None:
    world = World(tmp_path, scores=False, shadow=False)
    world.write_forward(samples_path=f'"{(tmp_path / "none" / "s.jsonl").as_posix()}"')
    assert world.run("forward", "report") == EXIT_REPORT_NOT_WRITTEN
    assert "forward report: durdu: örnek dosyası yazılamadı: " in world.text
    assert not (tmp_path / "none").exists()
