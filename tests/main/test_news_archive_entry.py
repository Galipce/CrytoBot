"""Spec 0047 giriş noktası `python -m crytobot news archive` ve `news archive status` (AC-4, AC-5,
AC-8, AC-9, AC-10).

`run` gerçek kodu koşar: gerçek ayar yükleyici, yol çakışması, kilit, depo, çalıştırma ve durum;
yalnız saat, bekleme ve getirme sahtedir (ağ yok).
"""

import io
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from crytobot import __main__ as entry
from crytobot.__main__ import (
    ARCHIVE_BUSY,
    COMMANDS,
    EXIT_FORCED,
    EXIT_LOG_FAILED,
    EXIT_OK,
    EXIT_REFUSED,
    USAGE,
    StoreLock,
    run,
)
from crytobot.app import ForcedStop, StopRequest
from crytobot.news import ARCHIVE_EMPTY, Fetched, load_archive_config
from tests.main.test_entry import config_text
from tests.main.test_news_entry import EXAMPLE, news_text
from tests.news.test_archive_run import START, A, B, Binance, articles

EXIT_STOPPED = 4


def archive_text(root: Path, **changes: str) -> str:
    values = {
        "archive_store_path": f'"{(root / "archive.db").as_posix()}"',
        "archive_log_path": f'"{(root / "archive.log").as_posix()}"',
        **changes,
    }
    return news_text(root, **values)


@dataclass
class Archiver:
    root: Path
    binance: Binance = field(
        default_factory=lambda: Binance(
            {A: ("Listing", articles(1, 70)), B: ("Delisting", articles(2, 5))}
        )
    )
    now: datetime = START
    requests: list[str] = field(default_factory=list)
    on_fetch: Callable[[int], Fetched | None] | None = None
    stop: StopRequest = field(default_factory=StopRequest)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.bot_config.write_text(config_text(self.root), encoding="utf-8")
        self.write(archive_text(self.root))

    @property
    def bot_config(self) -> Path:
        return self.root / "crytobot.toml"

    @property
    def news_config(self) -> Path:
        return self.root / "crytobot-news.toml"

    @property
    def store(self) -> Path:
        return self.root / "archive.db"

    @property
    def log(self) -> Path:
        return self.root / "archive.log"

    def write(self, text: str) -> None:
        self.news_config.write_text(text, encoding="utf-8")

    def clock(self) -> datetime:
        return self.now

    def wait(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)

    def fetch(self, url: str, _max_bytes: int, _stopped: Callable[[], bool]) -> Fetched:
        self.requests.append(url)
        self.now += timedelta(seconds=1)
        if self.on_fetch is not None:
            replaced = self.on_fetch(len(self.requests) - 1)
            if replaced is not None:
                return replaced
        return Fetched(body=self.binance.body(url))

    def run(self, *command: str) -> tuple[int, str]:
        out = io.StringIO()
        self.stop = StopRequest()
        code = run(
            list(command),
            config_path=self.bot_config,
            news_config_path=self.news_config,
            console=out,
            clock=self.clock,
            stop=self.stop,
            wait=self.wait,
            news_fetch=lambda *_: pytest.fail("the collector's fetch is never used"),
            archive_fetch=self.fetch,
        )
        return code, out.getvalue()


@pytest.fixture
def archiver(tmp_path: Path) -> Archiver:
    return Archiver(tmp_path)


def test_example_archive_config_is_valid() -> None:
    with EXAMPLE.open("rb") as file:
        result = load_archive_config(tomllib.load(file))
    assert result.config is not None, result.message
    assert result.config.request_gap_s == 1
    assert result.config.url.startswith("https://www.binance.com/")


def test_commands_listed() -> None:
    assert ["news", "archive"] in COMMANDS and ["news", "archive", "status"] in COMMANDS
    assert "archive" in USAGE
    assert ["news", "archive", "extra"] not in COMMANDS


def test_archive_fills_and_exits_0(archiver: Archiver) -> None:
    code, console = archiver.run("news", "archive")
    assert code == EXIT_OK
    assert " arşiv arşiv katalog=Listing yeni=70 tekrar=0 geçersiz=0 " in console
    log = archiver.log.read_text(encoding="utf-8")
    assert log.splitlines()[-1].endswith(" arşiv arşiv: tamam")
    assert not (archiver.root / "bot.db").exists()
    assert not (archiver.root / "news.db").exists()  # the forward store is never opened


def test_status_makes_no_request(archiver: Archiver) -> None:
    """AC-8: durum ağa çıkmaz, kilit almaz, çıkış 0; boş arşivde bunu söyler."""
    code, console = archiver.run("news", "archive", "status")
    assert (code, console.strip()) == (EXIT_OK, f"{ARCHIVE_EMPTY} boyut=0 bayt")
    assert not archiver.store.exists()
    assert archiver.run("news", "archive")[0] == EXIT_OK
    archiver.requests.clear()
    lock = StoreLock(str(archiver.store.resolve()))  # an archive command is running
    assert lock.acquire() is None
    try:
        code, console = archiver.run("news", "archive", "status")
    finally:
        lock.release()
    assert code == EXIT_OK
    assert archiver.requests == []
    assert console.splitlines()[0].startswith("katalog=Listing kayıt=70 bildirilen=70 fark=0 ")
    assert "arşiv: kayıt=75 " in console and "ileriye dönük kayıt yok" in console


def test_status_unreadable_archive_refused(archiver: Archiver) -> None:
    archiver.store.write_bytes(b"not a database" * 100)
    code, console = archiver.run("news", "archive", "status")
    assert (code, console.strip()) == (EXIT_REFUSED, "news archive: reddedildi: arşiv okunamıyor")


def test_second_archive_refused(archiver: Archiver, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-9: aynı arşive ikinci arşiv komutu — başka yazımla da — reddedilir, istek gitmez."""
    monkeypatch.chdir(archiver.root)
    lock = StoreLock(str(archiver.store.resolve()))
    assert lock.acquire() is None
    try:
        for spelling in (f'"{archiver.store.as_posix()}"', '"./archive.db"'):
            archiver.write(archive_text(archiver.root, archive_store_path=spelling))
            code, console = archiver.run("news", "archive")
            assert (code, console.strip()) == (
                EXIT_REFUSED,
                f"news archive: reddedildi: {ARCHIVE_BUSY}",
            )
        assert archiver.requests == []
        assert not archiver.log.exists()
    finally:
        lock.release()


def test_archive_runs_beside_collector_and_bot_locks(archiver: Archiver) -> None:
    """R-1: toplayıcı ve bot çalışırken de çalışır (kilitleri ayrıdır)."""
    locks = [StoreLock(str(archiver.root / name)) for name in ("news.db", "bot.db")]
    for lock in locks:
        assert lock.acquire() is None
    try:
        assert archiver.run("news", "archive")[0] == EXIT_OK
    finally:
        for lock in locks:
            lock.release()


@pytest.mark.parametrize(
    ("changes", "key"),
    [
        ({"archive_store_path": "bot.db"}, "archive_store_path"),
        ({"archive_store_path": "./bot.log"}, "archive_store_path"),
        ({"archive_store_path": "sub/../news.db"}, "archive_store_path"),
        ({"archive_store_path": "./news.log"}, "archive_store_path"),
        ({"archive_log_path": "./bot.db"}, "archive_log_path"),
        ({"archive_log_path": "bot.log"}, "archive_log_path"),
        ({"archive_log_path": "./news.db"}, "archive_log_path"),
        ({"archive_log_path": "./news.log"}, "archive_log_path"),
        ({"archive_log_path": "./archive.db"}, "archive_log_path"),
    ],
)
def test_path_collisions_refused_no_request(
    archiver: Archiver, monkeypatch: pytest.MonkeyPatch, changes: dict[str, str], key: str
) -> None:
    """AC-10: arşiv ya da kaydı ileriye dönük kayıt, onun kaydı, bot deposu, bot kaydı ya da
    birbirleriyse (başka yazımla da) ağa ve dosyaya dokunmadan ret."""
    monkeypatch.chdir(archiver.root)
    (archiver.root / "sub").mkdir()
    archiver.bot_config.write_text(
        config_text(archiver.root, store_path='"bot.db"', log_path='"bot.log"'), encoding="utf-8"
    )
    archiver.write(
        archive_text(
            archiver.root,
            store_path='"news.db"',
            log_path='"news.log"',
            **{
                "archive_store_path": '"archive.db"',
                **{name: f'"{value}"' for name, value in changes.items()},
            },
        )
    )
    before = sorted(path.name for path in archiver.root.iterdir())
    for command in (("news", "archive"), ("news", "archive", "status")):
        code, console = archiver.run(*command)
        assert (code, console.strip()) == (
            EXIT_REFUSED,
            f"news archive: reddedildi: ayar geçersiz: news.{key}",
        )
    assert archiver.requests == []
    assert sorted(path.name for path in archiver.root.iterdir()) == before


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"archive_request_gap_s": "0"}, "ayar geçersiz: news.archive_request_gap_s"),
        (
            {"archive_url": '"http://www.binance.com/x"'},
            "ayar geçersiz: news.archive_url (https değil)",
        ),
    ],
)
def test_invalid_config_refused_at_entry(
    archiver: Archiver, changes: dict[str, str], message: str
) -> None:
    archiver.write(archive_text(archiver.root, **changes))
    code, console = archiver.run("news", "archive")
    assert (code, console.strip()) == (EXIT_REFUSED, f"news archive: reddedildi: {message}")
    assert archiver.requests == [] and not archiver.store.exists()


def test_missing_or_unreadable_file_refused(archiver: Archiver) -> None:
    archiver.news_config.unlink()
    code, console = archiver.run("news", "archive")
    expected = "news archive: reddedildi: ayar dosyası yok: crytobot-news.toml"
    assert (code, console.strip()) == (EXIT_REFUSED, expected)
    archiver.write("[news\n")
    code, console = archiver.run("news", "archive", "status")
    expected = "news archive: reddedildi: ayar dosyası okunamıyor: crytobot-news.toml"
    assert (code, console.strip()) == (EXIT_REFUSED, expected)


def test_missing_archive_key_refused_but_collector_unaffected(archiver: Archiver) -> None:
    rows = [
        row
        for row in archive_text(archiver.root).splitlines()
        if not row.startswith("archive_store_path")
    ]
    archiver.write("\n".join(rows) + "\n")
    code, console = archiver.run("news", "archive")
    expected = "news archive: reddedildi: ayar eksik: news.archive_store_path"
    assert (code, console.strip()) == (EXIT_REFUSED, expected)


def test_stop_exits_4(archiver: Archiver) -> None:
    """AC-4: Ctrl+C ile durma çıkış 4; yazılmışlar kalır."""

    def stop_on_second_page(index: int) -> Fetched | None:
        if index == 2:
            archiver.stop.request("SIGINT")
        return None

    archiver.on_fetch = stop_on_second_page
    code, console = archiver.run("news", "archive")
    assert code == EXIT_STOPPED
    assert console.splitlines()[-1].endswith(" arşiv arşiv: eksik (2 katalog)")
    archiver.on_fetch = None
    assert archiver.run("news", "archive")[0] == EXIT_OK
    assert [url for url in archiver.requests if "pageNo=1&" in url and f"catalogId={A}" in url] == [
        archiver.requests[1]
    ]


def test_forced_stop_exits_130(archiver: Archiver) -> None:
    """AC-4: ikinci Ctrl+C çıkış 130."""

    def forced(index: int) -> Fetched | None:
        if index == 2:
            raise ForcedStop
        return None

    archiver.on_fetch = forced
    assert archiver.run("news", "archive")[0] == EXIT_FORCED
    lock = StoreLock(str(archiver.store.resolve()))
    assert lock.acquire() is None  # released on the way out
    lock.release()


def test_source_error_exits_1(archiver: Archiver) -> None:
    archiver.on_fetch = lambda index: Fetched(error="http_429") if index == 1 else None
    code, console = archiver.run("news", "archive")
    assert code == EXIT_REFUSED
    assert " hata=http_429" in console


def test_log_unwritable_exits_3(archiver: Archiver) -> None:
    (archiver.root / "logdir").mkdir()
    archiver.write(
        archive_text(archiver.root, archive_log_path=f'"{(archiver.root / "logdir").as_posix()}"')
    )
    code, console = archiver.run("news", "archive")
    assert code == EXIT_LOG_FAILED
    assert "kayıt dosyası yazılamıyor: arşiv durdu" in console


def test_unopenable_store_refused(archiver: Archiver) -> None:
    archiver.store.write_bytes(b"not a database" * 100)
    code, console = archiver.run("news", "archive")
    assert code == EXIT_REFUSED
    assert "reddedildi: arşiv açılamıyor" in console
    assert archiver.requests == []


def test_no_telegram_at_entry(archiver: Archiver, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-5, G-8: Telegram ayarlı olsa da arşiv bildirim kurmaz."""

    def never(*_args: object, **_kwargs: object) -> None:
        pytest.fail("the archive never builds a reporter")

    monkeypatch.setattr(entry, "ReportingService", never)
    monkeypatch.setattr(entry, "load_reporting_config", never)
    archiver.on_fetch = lambda index: Fetched(error="timeout") if index == 1 else None
    assert archiver.run("news", "archive")[0] == EXIT_REFUSED
    archiver.on_fetch = None
    assert archiver.run("news", "archive")[0] == EXIT_OK
