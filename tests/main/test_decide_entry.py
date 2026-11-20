"""Spec 0059 giriş noktası: `decide` ve `decide status` (AC-1, AC-7, AC-8, AC-9)."""

import io
from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from crytobot.__main__ import (
    COMMANDS,
    DECIDE_BUSY,
    DECIDE_H1,
    DECIDE_H4,
    EXIT_FORCED,
    EXIT_OK,
    EXIT_REFUSED,
    USAGE,
    StoreLock,
    make_decide_read,
    run,
)
from crytobot.app import StopRequest
from crytobot.decide import ADR_0005_COINS, CoinData, DecideReply
from crytobot.market_data import MarketCandle, MarketRead, PairRead, ReadSettings
from crytobot.news import EventScore, ResultKind, ScoreResult, ScoreStore
from tests.decide.helpers import BOUNDARY, all_data, reply, wait_entry
from tests.main.test_entry import config_text

START = BOUNDARY + timedelta(minutes=5)


def decide_text(root: Path, **changes: str) -> str:
    values = {
        "store_path": f'"{(root / "decide.db").as_posix()}"',
        "log_path": f'"{(root / "decide.log").as_posix()}"',
        "score_path": f'"{(root / "score.db").as_posix()}"',
        **changes,
    }
    coins = ", ".join(f'"{coin}"' for coin in ADR_0005_COINS)
    rows = [f"coins = [{coins}]", 'model = "claude-sonnet-5-5"']
    rows += [f"{key} = {value}" for key, value in values.items()]
    return "[decide]\n" + "\n".join(rows) + "\n"


class World:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.now = START
        self.calls: list[str] = []
        self.reads: list[datetime] = []
        self.bot_config = root / "crytobot.toml"
        self.bot_config.write_text(config_text(root), encoding="utf-8")
        self.decide_config = root / "crytobot-decide.toml"
        self.decide_config.write_text(decide_text(root), encoding="utf-8")
        self.stop = StopRequest()
        self.on_call: object = None

    def call(self, model: str, system: str, prompt: str, timeout_s: float) -> DecideReply:
        self.calls.append(prompt)
        if callable(self.on_call):
            self.on_call(self)
        return DecideReply("ok", reply(*(wait_entry(coin) for coin in ADR_0005_COINS)))

    def forbidden_call(self, model: str, system: str, prompt: str, timeout_s: float) -> DecideReply:
        raise AssertionError("no LLM call expected")

    def read(self, coins: tuple[str, ...], boundary: datetime) -> Mapping[str, CoinData | None]:
        self.reads.append(boundary)
        return all_data(boundary)

    def forbidden_read(
        self, coins: tuple[str, ...], boundary: datetime
    ) -> Mapping[str, CoinData | None]:
        raise AssertionError("no market read expected")

    def wait(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)
        self.stop.request("SIGINT")  # one turn, then a clean stop

    def run(self, *command: str, forbidden: bool = False) -> tuple[int, str]:
        out = io.StringIO()
        self.stop = StopRequest()
        code = run(
            list(command),
            config_path=self.bot_config,
            news_config_path=self.root / "crytobot-news.toml",
            events_config_path=self.root / "crytobot-events.toml",
            forward_config_path=self.root / "crytobot-forward.toml",
            decide_config_path=self.decide_config,
            console=out,
            clock=lambda: self.now,
            stop=self.stop,
            wait=self.wait,
            decide_call=self.forbidden_call if forbidden else self.call,
            decide_read=self.forbidden_read if forbidden else self.read,
        )
        return code, out.getvalue()


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_commands_listed() -> None:
    assert ["decide"] in COMMANDS and ["decide", "status"] in COMMANDS
    assert ["decide", "extra"] not in COMMANDS
    assert "decide" in USAGE


def test_turn_logged_and_status(world: World) -> None:
    code, _ = world.run("decide")
    assert code == EXIT_OK
    assert len(world.calls) == 1 and world.reads == [BOUNDARY]
    log = (world.root / "decide.log").read_text(encoding="utf-8")
    assert "karar başladı: model=claude-sonnet-5-5 coin=10 dakika=5" in log
    assert "karar tur: an=2026-11-20T10:00:00+00:00 sonuç=ok çağrı=var al=0 bekle=10" in log
    assert log.splitlines()[-1].endswith("karar durdu: durdurma isteği tur_sayısı=1")
    code, console = world.run("decide", "status", forbidden=True)
    assert code == EXIT_OK
    assert "bugünkü çağrı (UTC 2026-11-20): 1/24" in console
    assert "  BTC: bekle (2026-11-20T10:00:00+00:00)" in console


def test_status_no_network_no_llm(world: World) -> None:
    code, console = world.run("decide", "status", forbidden=True)
    assert code == EXIT_OK
    assert console.strip().endswith("henüz tur yok")
    assert not (world.root / "decide.db").exists()


@pytest.mark.parametrize(
    ("key", "target"),
    [
        ("store_path", "bot.db"),
        ("store_path", "bot.log"),
        ("store_path", "crytobot.toml"),
        ("store_path", "score.db"),
        ("log_path", "bot.db"),
        ("log_path", "decide.db"),
        ("log_path", "./sub/../decide.db"),
        ("score_path", "decide.log"),
    ],
)
def test_path_collisions_refused_no_call(world: World, key: str, target: str) -> None:
    (world.root / "sub").mkdir(exist_ok=True)
    world.decide_config.write_text(
        decide_text(world.root, **{key: f'"{(world.root / target).as_posix()}"'}),
        encoding="utf-8",
    )
    code, console = world.run("decide", forbidden=True)
    assert code == EXIT_REFUSED
    assert console.strip().startswith("decide: reddedildi: ayar geçersiz: decide.")
    assert not (world.root / "decide.log").exists()


def test_news_and_shadow_paths_refused(world: World) -> None:
    news = world.root / "crytobot-news.toml"
    news.write_text(
        f'[news]\nstore_path = "{(world.root / "news.db").as_posix()}"\n', encoding="utf-8"
    )
    world.decide_config.write_text(
        decide_text(world.root, store_path=f'"{(world.root / "news.db").as_posix()}"'),
        encoding="utf-8",
    )
    code, console = world.run("decide", forbidden=True)
    assert (code, console.strip()) == (
        EXIT_REFUSED,
        "decide: reddedildi: ayar geçersiz: decide.store_path",
    )


@pytest.mark.parametrize(
    ("score", "key", "message"),
    [
        ('calibration_report_path = "{root}/report.txt"', "store_path", "decide.store_path"),
        ('library_path = "{root}/library.jsonl"', "log_path", "decide.log_path"),
        ('store_path = "{root}/other-score.db"', None, "decide.score_path"),
    ],
)
def test_score_paths_guarded(world: World, score: str, key: str | None, message: str) -> None:
    """Review round 1 L-3: skorlayıcının bağlam dosyaları korunur; skor yolu haber ayarındakidir."""
    root = world.root.as_posix()
    line_ = score.format(root=root)
    (world.root / "crytobot-news.toml").write_text(f"[score]\n{line_}\n", encoding="utf-8")
    if key is not None:
        target = line_.split("=", 1)[1].strip()
        world.decide_config.write_text(decide_text(world.root, **{key: target}), encoding="utf-8")
    code, console = world.run("decide", forbidden=True)
    assert code == EXIT_REFUSED
    assert console.strip() == f"decide: reddedildi: ayar geçersiz: {message}"


def test_matching_score_path_accepted(world: World) -> None:
    (world.root / "crytobot-news.toml").write_text(
        f'[score]\nstore_path = "{(world.root / "score.db").as_posix()}"\n', encoding="utf-8"
    )
    code, _ = world.run("decide")
    assert code == EXIT_OK


def test_wrong_list_refused(world: World) -> None:
    text = decide_text(world.root).replace('"TON"', '"PEPE"')
    world.decide_config.write_text(text, encoding="utf-8")
    code, console = world.run("decide", forbidden=True)
    assert code == EXIT_REFUSED
    assert "ayar geçersiz: decide.coins (ADR 0005 ön kayıtlı listesi değil)" in console


def test_missing_config_refused(world: World) -> None:
    world.decide_config.unlink()
    code, console = world.run("decide", forbidden=True)
    assert (code, console.strip()) == (
        EXIT_REFUSED,
        "decide: reddedildi: ayar dosyası yok: crytobot-decide.toml",
    )


def test_second_decide_refused(world: World) -> None:
    lock = StoreLock(str((world.root / "decide.db").resolve()))
    assert lock.acquire() is None
    try:
        code, console = world.run("decide", forbidden=True)
        assert (code, console.strip()) == (EXIT_REFUSED, f"decide: reddedildi: {DECIDE_BUSY}")
    finally:
        lock.release()


def test_stop_and_forced_stop(world: World) -> None:
    def force(current: World) -> None:
        current.stop.request("SIGINT")
        current.stop.request("SIGINT")

    world.on_call = force
    code, _ = world.run("decide")
    assert code == EXIT_FORCED
    world.on_call = None
    world.now = START + timedelta(minutes=1)
    code, console = world.run("decide", "status", forbidden=True)
    assert console.strip().endswith("henüz tur yok")  # no half turn
    code, _ = world.run("decide")  # the lock was released
    assert code == EXIT_OK


def test_bot_store_untouched(world: World) -> None:
    code, _ = world.run("decide")
    assert code == EXIT_OK
    assert not (world.root / "bot.db").exists() and not (world.root / "bot.log").exists()


def _market(pairs: tuple[str, ...], settings: ReadSettings, end: datetime) -> MarketRead:
    found = []
    for index, pair in enumerate(pairs):
        if pair == "TON/USDT":  # unreadable pair
            found.append(PairRead(pair, None, None, None, None, None, None, ()))
            continue
        base = Decimal(10 * (index + 1))
        count, span = settings.candle_count, settings.candle_interval
        candles = tuple(
            MarketCandle(
                end - span * (count - i), base, base * Decimal("1.01"), base * Decimal("0.99"), base
            )
            for i in range(count)
        )
        found.append(PairRead(pair, candles, base, end, None, Decimal("0.01"), None, ()))
    return MarketRead(tuple(found), end, None)


def test_real_read_wiring(tmp_path: Path) -> None:
    score = ScoreStore.open(str(tmp_path / "score.db"), BOUNDARY - timedelta(days=2))
    event = EventScore("SOL", "Solana", "listeye alma", "olumlu", 2, "quote")
    score.write_result(
        ScoreResult(1, ResultKind.SCORED, BOUNDARY - timedelta(hours=2), scores=(event,))
    )
    old = EventScore("SOL", "Solana", "hack", "olumsuz", 3, "quote")
    score.write_result(
        ScoreResult(2, ResultKind.SCORED, BOUNDARY - timedelta(hours=30), scores=(old,))
    )
    score.close()
    settings: list[ReadSettings] = []

    def market(pairs: tuple[str, ...], read_settings: ReadSettings) -> MarketRead:
        settings.append(read_settings)
        return _market(pairs, read_settings, BOUNDARY)

    lines: list[str] = []
    read = make_decide_read(lambda: START, str(tmp_path / "score.db"), lines.append, market)
    data = read(ADR_0005_COINS, BOUNDARY)
    assert settings == [DECIDE_H1, DECIDE_H4]
    assert DECIDE_H1.candle_count == 250 and DECIDE_H4.candle_count == 40
    assert data["TON"] is None
    sol = data["SOL"]
    assert sol is not None and len(sol.h1) == 250 and sol.tick == Decimal("0.01")
    assert [e.event_type for e in sol.events] == ["listeye alma"]  # only the last 24 hours
    assert lines == []
    missing = make_decide_read(lambda: START, str(tmp_path / "none.db"), lines.append, market)
    assert missing(ADR_0005_COINS, BOUNDARY)["SOL"] is not None
    assert lines == ["skor kaydı okunamadı ya da yok: olay skorsuz tur"]
    assert not (tmp_path / "none.db").exists()
