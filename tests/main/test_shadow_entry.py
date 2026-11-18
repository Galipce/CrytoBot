"""Spec 0052 giriş noktası: paper `start` `[shadow]` ile satır yazar, `shadow status` gösterir
(AC-1, AC-7, AC-10; plan step 5, Risk 6).

`run` gerçek kodu koşar (gerçek ayar yükleyici, yol denetimi, kilit, döngü, gerçek görünüm ve
yazıcı); yalnız saat, bekleme ve okumanın borsası sahtedir (`tests/main/test_entry.py`'nin
düzeneği).
"""

import io
import json
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import crytobot.__main__ as entry
from crytobot.__main__ import EXIT_OK, EXIT_REFUSED, StoreLock, run
from crytobot.app import StopRequest, load_shadow_config
from tests.main.test_backtest_entry import Backtester
from tests.main.test_entry import Bot, config_text, event_lines
from tests.main.test_live_paper_proof_entry import SpyClient, live_dir, start_live


def toml(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


@dataclass
class ShadowBot(Bot):
    """`Bot` + haber ayar dosyası ve `[shadow]` bölümü; `run` haber ayarının yolunu da verir."""

    def __post_init__(self) -> None:
        super().__post_init__()
        self.shadow: dict[str, str] = {
            "record_path": self.path("shadow.jsonl"),
            "score_path": self.path("score.db"),
            "news_path": self.path("news.db"),
        }
        self.extra = ""
        self.write_all()

    def path(self, name: str) -> str:
        return (self.root / name).as_posix()

    @property
    def news_config(self) -> Path:
        return self.root / "crytobot-news.toml"

    @property
    def record(self) -> Path:
        return self.root / "shadow.jsonl"

    def write_all(self, *, section: bool = True, mode: str | None = None) -> None:
        changes = {} if mode is None else {"mode": toml(mode)}
        text = config_text(self.root, **changes)
        if mode is not None and "mode =" not in text:
            text = text.replace("[bot]\n", f"[bot]\nmode = {toml(mode)}\n", 1)
        if section:
            text += "\n[shadow]\n" + "".join(f"{k} = {toml(v)}\n" for k, v in self.shadow.items())
        self.config_path.write_text(text + self.extra, encoding="utf-8")
        self.news_config.write_text(
            "[news]\n"
            f"store_path = {toml(self.path('collector.db'))}\n"
            f"log_path = {toml(self.path('collector.log'))}\n"
            f"archive_store_path = {toml(self.path('archive.db'))}\n"
            f"archive_log_path = {toml(self.path('archive.log'))}\n"
            "[score]\n"
            f"store_path = {toml(self.path('scorer.db'))}\n"
            f"log_path = {toml(self.path('scorer.log'))}\n",
            encoding="utf-8",
        )

    def run(self, *command: str, console: Any = None, trial: bool = True) -> tuple[int, str]:
        cmd = list(command)
        if cmd == ["start"] and trial:
            cmd = ["start", "--trial"]
        out = io.StringIO()
        self.stop = StopRequest()
        self.reads = 0
        code = run(
            cmd,
            config_path=self.config_path,
            news_config_path=self.news_config,
            console=out,
            clock=self.clock,
            stop=self.stop,
            read=self.read,
            wait=self.wait,
        )
        return code, out.getvalue()

    def files(self) -> dict[str, bytes]:
        """Dizindeki her dosya; kilit dosyasının yalnız varlığı (tutulan kilit okunamaz)."""
        return {
            path.name: b"" if path.suffix == ".lock" else path.read_bytes()
            for path in sorted(self.root.iterdir())
        }


@pytest.fixture
def bot(tmp_path: Path) -> ShadowBot:
    return ShadowBot(tmp_path / "work")


def rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_trial_start_writes_rows_and_status_shows_them(bot: ShadowBot) -> None:
    assert bot.run("prepare")[0] == EXIT_OK
    code, console = bot.run("start")
    assert code == EXIT_OK
    assert len(event_lines(console, "tur")) == 2
    written = rows(bot.record)
    assert [row["pair"] for row in written] == ["BTC/USDT", "ETH/USDT"] * 2
    assert {(row["state"], row["reason"]) for row in written} == {("filtre yok", "skor kaydı yok")}
    assert not (bot.root / "score.db").exists() and not (bot.root / "news.db").exists()
    code, console = bot.run("shadow", "status")
    assert code == EXIT_OK
    lines = console.strip().splitlines()
    assert lines[0] == f"gölge kayıt: {bot.shadow['record_path']}"
    assert "tur sayısı: 2" in lines
    btc = "BTC/USDT: bastırılırdı=0 bastırılmazdı=0 bastırılmazdı — eksik bilgi=0 filtre yok=2"
    assert btc in lines
    assert "filtre yok nedenleri: skor kaydı yok=4" in lines
    assert lines[-1] == "son kayıt hatası: yok"


def test_no_section_writes_nothing(bot: ShadowBot) -> None:
    bot.write_all(section=False)
    assert bot.run("prepare")[0] == EXIT_OK
    code, console = bot.run("start")
    assert code == EXIT_OK
    assert len(event_lines(console, "tur")) == 2
    assert not bot.record.exists()
    code, console = bot.run("shadow", "status")
    assert code == EXIT_REFUSED
    assert console.strip() == "shadow status: reddedildi: ayar eksik: shadow"


COLLISIONS = [
    ("record_path", "bot.db", "shadow.record_path"),
    ("record_path", "sub/../bot.db", "shadow.record_path"),
    ("record_path", "bot.log", "shadow.record_path"),
    ("record_path", "paper.db", "shadow.record_path"),  # [stage] paper_store_path
    ("record_path", "score.db", "shadow.record_path"),
    ("record_path", "news.db", "shadow.record_path"),
    ("record_path", "crytobot.toml", "shadow.record_path"),
    ("record_path", "crytobot-news.toml", "shadow.record_path"),
    ("record_path", "collector.db", "shadow.record_path"),
    ("record_path", "collector.log", "shadow.record_path"),
    ("record_path", "archive.db", "shadow.record_path"),
    ("record_path", "archive.log", "shadow.record_path"),
    ("record_path", "scorer.db", "shadow.record_path"),
    ("record_path", "scorer.log", "shadow.record_path"),
    ("score_path", "bot.db", "shadow.score_path"),
    ("score_path", "./bot.db", "shadow.score_path"),
    ("news_path", "bot.db", "shadow.news_path"),
]


@pytest.mark.parametrize(("key", "name", "setting"), COLLISIONS)
def test_path_collisions_refused_nothing_written(
    bot: ShadowBot, key: str, name: str, setting: str
) -> None:
    bot.extra = f"\n[stage]\npaper_store_path = {toml(bot.path('paper.db'))}\n"
    bot.write_all()
    assert bot.run("prepare")[0] == EXIT_OK
    bot.shadow[key] = bot.path(name)
    bot.write_all()
    before = bot.files()
    code, console = bot.run("start")
    assert code == EXIT_REFUSED
    assert console.strip().splitlines()[-1].endswith(f"bot başlamadı: ayar geçersiz: {setting}")
    assert bot.files() == before  # no lock, no log line, no record
    assert bot.reads == 0


def test_missing_shadow_key_refused_by_name(bot: ShadowBot) -> None:
    assert bot.run("prepare")[0] == EXIT_OK
    del bot.shadow["news_path"]
    bot.write_all()
    before = bot.files()
    code, console = bot.run("start")
    assert code == EXIT_REFUSED
    assert console.strip().endswith("bot başlamadı: ayar eksik: shadow.news_path")
    assert bot.files() == before


def spy_loader(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    calls: list[object] = []
    real = load_shadow_config

    def spy(document: object) -> Any:
        calls.append(document)
        return real(document)

    monkeypatch.setattr(entry, "load_shadow_config", spy)
    return calls


def colliding_section(root: Path) -> str:
    """`record_path` deponun kendisi: paper başlatma bunu reddeder (R-8); okunursa tuzak çalışır."""
    paths = {
        "record_path": (root / "bot.db").as_posix(),
        "score_path": (root / "score.db").as_posix(),
        "news_path": (root / "news.db").as_posix(),
    }
    return "\n[shadow]\n" + "".join(f"{k} = {toml(v)}\n" for k, v in paths.items())


def untimed(console: str) -> list[str]:
    """Gerçek saatle koşan satırların zaman damgası atılır."""
    return [row.split(" ", 1)[-1] for row in console.splitlines()]


def test_live_start_ignores_shadow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-7 (fix-1, M-1): live başlatma bütün kapılardan geçer; bölüm okunmaz, çakışma reddetmez."""
    calls = spy_loader(monkeypatch)
    config, _paper = live_dir(tmp_path)
    plain = config.read_text(encoding="utf-8")
    code, without = start_live(config, SpyClient(), stopped=True)
    assert code == EXIT_OK, without
    assert " başlatma başladı:" in without
    config.write_text(plain + colliding_section(tmp_path), encoding="utf-8")
    code, with_section = start_live(config, SpyClient(), stopped=True)
    assert code == EXIT_OK, with_section
    assert untimed(with_section) == untimed(without)
    assert calls == []
    assert "gölge" not in (tmp_path / "bot.log").read_text(encoding="utf-8")


def test_backtest_ignores_shadow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-7 (fix-1, M-1): geçerli ayarla koşan backtest; bölüm varken konsol ve rapor aynı."""
    calls = spy_loader(monkeypatch)
    tester = Backtester(tmp_path)
    plain = tester.run()
    assert plain[0] == EXIT_OK, plain[1]
    report = tester.report.read_bytes()
    tester.report.unlink()  # an existing report is never overwritten
    text = tester.bot.config_path.read_text(encoding="utf-8")
    tester.bot.config_path.write_text(text + colliding_section(tmp_path), encoding="utf-8")
    assert tester.run() == plain
    assert tester.report.read_bytes() == report
    assert calls == []


def test_status_no_lock_no_network(bot: ShadowBot, monkeypatch: pytest.MonkeyPatch) -> None:
    code, console = bot.run("shadow", "status")
    assert (code, console.strip()) == (EXIT_OK, "henüz gölge kayıt yok")
    assert not bot.record.exists()
    good = {
        "version": "1",
        "turn_at": "2026-11-18T12:00:00+00:00",
        "pair": "BTC/USDT",
        "state": "bastırılırdı",
        "reason": "olumsuz olay",
        "technical_buy": "var",
    }
    bot.record.write_text(
        json.dumps(good, ensure_ascii=False) + '\n{"version": "1", "tu', encoding="utf-8"
    )
    bot.log.write_text(
        "2026-11-18T12:00:02+00:00 hata döngü hatası: gölge kayıt PermissionError\n",
        encoding="utf-8",
    )

    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network")

    monkeypatch.setattr(socket, "socket", no_network)
    lock = StoreLock(str(bot.store))
    assert lock.acquire() is None  # a running bot holds the store
    before = bot.files()
    try:
        code, console = bot.run("shadow", "status")
    finally:
        lock.release()
    assert code == EXIT_OK
    lines = console.strip().splitlines()
    assert "tur sayısı: 1" in lines
    buys = "teknik al: toplam=1 bastırılırdı=1 bastırılmazdı=0 bastırılmazdı — eksik bilgi=0"
    assert f"{buys} filtre yok=0" in lines
    assert "bozuk satır=1" in lines
    assert lines[-1] == "son kayıt hatası: PermissionError"
    assert bot.files() == before  # read only
