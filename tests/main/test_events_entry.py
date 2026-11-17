"""Spec 0048 giriş noktası `python -m crytobot events download` ve `events measure` (AC-9, AC-10;
plan Risk 2, 10): retler ağa ve dosyaya dokunmadan, adıyla, çıkış 1; ikinci koşu reti; çıkış
kodları.

`run` gerçek kodu koşar: ayar yükleyiciler, yol çakışması, kilit, depo ve iki koşu; indirme gerçek
`download_event_prices`'tır, yalnız borsa, monoton saat ve bekleme sahtedir (`World`).
"""

from collections.abc import Sequence
from pathlib import Path

import pytest

from crytobot.__main__ import (
    COMMANDS,
    EVENTS_BUSY,
    EVENTS_REPORT_BUSY,
    EXIT_FORCED,
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_REPORT_NOT_WRITTEN,
    USAGE,
    StoreLock,
    repo_root,
)
from crytobot.app import ForcedStop
from crytobot.market_data import DownloadOutcome, EventPriceParts, PriceNeed, PriceStore
from tests.app.test_events_run import World

EXIT_STOPPED = 4


def listing(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


def test_events_commands_are_known() -> None:
    assert ["events", "download"] in COMMANDS and ["events", "measure"] in COMMANDS
    assert "events" in USAGE and "[download] [measure]" in USAGE
    root = repo_root()
    assert root is not None and (root / "pyproject.toml").is_file()


@pytest.mark.parametrize("command", ["download", "measure"])
@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"model_cutoff": ""}, "ayar eksik: events.model_cutoff"),
        ({"model_cutoff": '"2025-02-30"'}, "ayar geçersiz: events.model_cutoff"),
        ({"request_gap_s": "0"}, "ayar geçersiz: events.request_gap_s"),
        ({"price_store_path": '"{root}/archive.db"'}, "ayar geçersiz: events.price_store_path"),
        ({"report_path": '"{root}/news.db"'}, "ayar geçersiz: events.report_path"),
        ({"library_path": '"{root}/news.log"'}, "ayar geçersiz: events.library_path"),
        ({"library_path": '"{root}/archive.log"'}, "ayar geçersiz: events.library_path"),
        ({"report_path": '"{root}/bot.db"'}, "ayar geçersiz: events.report_path"),
        ({"report_path": '"{root}/bot.log"'}, "ayar geçersiz: events.report_path"),
        ({"report_path": '"{root}/./out/../out/prices.db"'}, "ayar geçersiz: events.report_path"),
        ({"library_path": '"{root}/crytobot.toml"'}, "ayar geçersiz: events.library_path"),
        (
            {"price_store_path": '"{repo}/events-prices.db"'},
            "ayar geçersiz: events.price_store_path",
        ),
    ],
)
def test_refusals_no_request_no_file(
    tmp_path: Path, command: str, change: dict[str, str], message: str
) -> None:
    world = World(tmp_path)
    root, repo = tmp_path.as_posix(), (repo_root() or Path("/")).as_posix()
    world.write_events(**{key: value.format(root=root, repo=repo) for key, value in change.items()})
    before = listing(tmp_path)

    assert world.run("events", command) == EXIT_REFUSED
    assert world.text == f"events {command}: reddedildi: {message}\n"
    assert (world.downloads, world.exchange.calls) == (0, [])
    assert listing(tmp_path) == before


@pytest.mark.parametrize("command", ["download", "measure"])
def test_archive_missing_or_configs_unreadable_refused(tmp_path: Path, command: str) -> None:
    world = World(tmp_path)
    (tmp_path / "archive.db").unlink()
    before = listing(tmp_path)
    assert world.run("events", command) == EXIT_REFUSED
    assert world.text == f"events {command}: reddedildi: arşiv yok: {root(tmp_path)}/archive.db\n"
    (tmp_path / "crytobot-events.toml").unlink()
    assert world.run("events", command) == EXIT_REFUSED
    assert "ayar dosyası yok: crytobot-events.toml" in world.text
    world.write_events()
    (tmp_path / "crytobot-news.toml").write_text("[news]\nstore_path = 3\n", encoding="utf-8")
    assert world.run("events", command) == EXIT_REFUSED
    assert world.text.startswith(f"events {command}: reddedildi: ")
    (tmp_path / "crytobot-news.toml").unlink()
    assert world.run("events", command) == EXIT_REFUSED
    assert "ayar dosyası yok: crytobot-news.toml" in world.text
    assert world.downloads == 0 and set(listing(tmp_path)) <= set(before) | {"crytobot-events.toml"}


def root(path: Path) -> str:
    return path.as_posix()


@pytest.mark.parametrize("command", ["download", "measure"])
def test_second_run_refused(tmp_path: Path, command: str) -> None:
    world = World(tmp_path)
    lock = StoreLock(str(world.prices.resolve()))
    assert lock.acquire() is None
    try:
        assert world.run("events", command) == EXIT_REFUSED
        assert world.text == f"events {command}: reddedildi: {EVENTS_BUSY}\n"
    finally:
        lock.release()
    assert world.downloads == 0 and not world.prices.exists()


def test_report_lock_refused(tmp_path: Path) -> None:
    world = World(tmp_path)
    assert world.run("events", "download") == EXIT_OK, world.text
    lock = StoreLock(str(world.report.resolve()))
    assert lock.acquire() is None
    try:
        assert world.run("events", "measure") == EXIT_REFUSED
        assert world.text == f"events measure: reddedildi: {EVENTS_REPORT_BUSY}\n"
    finally:
        lock.release()
    assert not world.report.exists()


class Planned(World):
    """İndirme adımının sonucu testten gelir."""

    outcome: DownloadOutcome | None = None
    raise_forced: bool = False

    def download(
        self, needs: Sequence[PriceNeed], store: PriceStore, parts: EventPriceParts, gap: float
    ) -> DownloadOutcome:
        self.downloads += 1
        if self.raise_forced:
            raise ForcedStop
        assert self.outcome is not None
        return self.outcome


@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        (DownloadOutcome.COMPLETE, EXIT_OK),
        (DownloadOutcome.FAILED, EXIT_REFUSED),
        (DownloadOutcome.STOPPED, EXIT_STOPPED),
    ],
)
def test_download_exit_codes(tmp_path: Path, outcome: DownloadOutcome, code: int) -> None:
    world = Planned(tmp_path)
    world.outcome = outcome
    assert world.run("events", "download") == code
    assert world.downloads == 1


def test_forced_stop_exit_130_lock_released(tmp_path: Path) -> None:
    world = Planned(tmp_path)
    world.raise_forced = True
    assert world.run("events", "download") == EXIT_FORCED
    lock = StoreLock(str(world.prices.resolve()))
    assert lock.acquire() is None
    lock.release()


def test_measure_exit_codes(tmp_path: Path) -> None:
    world = World(tmp_path)
    assert world.run("events", "measure") == EXIT_REFUSED
    assert "fiyat verisi yok:" in world.text and not world.prices.exists()
    assert world.run("events", "download") == EXIT_OK, world.text
    missing = tmp_path / "missing" / "library.jsonl"  # the writer cannot create the file
    world.write_events(library_path=f'"{missing.as_posix()}"')
    assert world.run("events", "measure") == EXIT_REPORT_NOT_WRITTEN
    assert "kütüphane yazılamadı" in world.text and not world.report.exists()
