"""Spec 0060 giriş noktası: `llm-paper download` ve `llm-paper report` (AC-1, AC-2, AC-10)."""

import io
import json
from datetime import timedelta
from pathlib import Path

import pytest

from crytobot.__main__ import EXIT_OK, EXIT_REFUSED, USAGE, run
from crytobot.app import StopRequest
from crytobot.app._llm_paper_config import MEASUREMENT_START
from crytobot.decide import (
    PREREGISTERED_COINS,
    PROMPT_FINGERPRINT,
    DecideStore,
    Decision,
    Status,
    Turn,
)
from crytobot.market_data import DownloadOutcome, DownloadRun, PairInfo, PriceStore, StoredCandle
from tests.main.test_entry import config_text

START = MEASUREMENT_START
HOUR = timedelta(hours=1)
NOW = START + 10 * HOUR + timedelta(minutes=20)
RULES = json.dumps(
    {
        "at": START.isoformat(),
        "pairs": {
            coin: {"amount_step": "0.0001", "min_amount": "0.0001", "min_notional": "5"}
            for coin in PREREGISTERED_COINS
        },
    }
)


def llm_text(root: Path, **changes: str) -> str:
    values = {
        "decide_store_path": "decide.db",
        "s0_store_path": "paper.db",
        "price_store_path": "prices.db",
        "rules_path": "rules.json",
        "report_path": "report.txt",
        "trades_path": "trades.jsonl",
        **changes,
    }
    rows = [f'{key} = "{(root / value).as_posix()}"' for key, value in values.items()]
    return "[llm_paper]\n" + "\n".join(rows) + "\n"


class World:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.bot = root / "crytobot.toml"
        self.bot.write_text(config_text(root), encoding="utf-8")
        self.config = root / "crytobot-llm-paper.toml"
        self.config.write_text(llm_text(root), encoding="utf-8")
        self.needs: list[object] = []
        self.network = False

    def rules(self) -> tuple[str, None] | tuple[None, str]:
        return RULES, None

    def download(self, needs, store: PriceStore, parts, gap):  # type: ignore[no-untyped-def]
        self.needs.append(needs)
        store.save_pairs([PairInfo(c, f"{c}USDT", "TRADING") for c in PREREGISTERED_COINS], NOW)
        for need in needs:
            candles = []
            moment = need.start
            while moment < need.end:
                ms = int(moment.timestamp() * 1000)
                low = "99" if moment == START + HOUR and need.coin == "SOL" else "104"
                candles.append(StoredCandle(ms, "105", "106", low, "105"))
                moment += HOUR
            store.save_span(f"{need.coin}USDT", need.start, need.end, candles, "test", NOW)
        store.record_run(DownloadRun(NOW, NOW, 0.1, 1, NOW.replace(minute=0)))
        return DownloadOutcome.COMPLETE

    def forbidden_download(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("no network expected")

    def run(self, *command: str, offline: bool = False) -> tuple[int, str]:
        out = io.StringIO()
        code = run(
            ["llm-paper", *command],
            config_path=self.bot,
            news_config_path=self.root / "crytobot-news.toml",
            events_config_path=self.root / "crytobot-events.toml",
            forward_config_path=self.root / "crytobot-forward.toml",
            decide_config_path=self.root / "crytobot-decide.toml",
            llm_paper_config_path=self.config,
            console=out,
            clock=lambda: NOW,
            stop=StopRequest(),
            wait=lambda seconds: None,
            events_download=self.forbidden_download if offline else self.download,
            llm_paper_rules=(lambda: (_ for _ in ()).throw(AssertionError("network")))
            if offline
            else self.rules,
        )
        return code, out.getvalue()

    def decide(self) -> None:
        store = DecideStore.open(str(self.root / "decide.db"))
        buy = Decision("SOL", Status.BUY, 99.0, 100.0, 95.0, 120.0, 4, 3, ("a",), action="al")
        wait = Decision("ETH", Status.WAIT, reasons=("b",), action="bekle")
        store.write(Turn(START, "m", PROMPT_FINGERPRINT, "f", "ok", True, (buy, wait)))
        store.close()


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_commands_in_usage() -> None:
    assert "llm-paper" in USAGE


def test_download_needs_and_rerun(world: World) -> None:
    code, console = world.run("download")
    assert code == EXIT_OK, console
    needs = world.needs[0]
    assert {n.coin for n in needs} == set(PREREGISTERED_COINS)  # type: ignore[attr-defined]
    assert all(n.start == START - HOUR and n.end == NOW.replace(minute=0) for n in needs)  # type: ignore[attr-defined]
    assert json.loads((world.root / "rules.json").read_text(encoding="utf-8"))["pairs"]["SOL"]
    assert "llm-paper download: tamam" in console


def test_download_error_named(world: World) -> None:
    world.rules = lambda: (None, "bağlanamadı")  # type: ignore[method-assign]
    code, console = world.run("download")
    assert code == EXIT_REFUSED
    assert "llm-paper download: durdu: borsa kuralları okunamadı: bağlanamadı" in console


def test_report_offline_lockless_inputs_unchanged(world: World) -> None:
    world.decide()
    assert world.run("download")[0] == EXIT_OK
    inputs = [
        world.root / name for name in ("decide.db", "prices.db", "rules.json", "crytobot.toml")
    ]
    before = [path.read_bytes() for path in inputs]
    code, console = world.run("report", offline=True)
    assert code == EXIT_OK, console
    assert "llm-paper report: hüküm: ölçüm sürüyor" in console
    assert [path.read_bytes() for path in inputs] == before
    report = (world.root / "report.txt").read_text(encoding="utf-8")
    assert "al=1 claude_bekle=1" in report and "S0 yok" in report
    rows = [
        json.loads(line)
        for line in (world.root / "trades.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["coin"] == "SOL" and rows[0]["status"] == "açık"
    assert not (world.root / "bot.db").exists()


def test_report_without_record_refused(world: World) -> None:
    code, console = world.run("report", offline=True)
    assert code == EXIT_REFUSED and "karar kaydı yok" in console


def test_report_without_prices_refused(world: World) -> None:
    world.decide()
    code, console = world.run("report", offline=True)
    assert code == EXIT_REFUSED and "önce llm-paper download" in console


def test_future_report_moment_refused(world: World) -> None:
    world.decide()
    code, console = world.run("report", "--at", (NOW + HOUR).isoformat(), offline=True)
    assert code == EXIT_REFUSED and "rapor anı gelecekte" in console


@pytest.mark.parametrize(
    ("key", "target"),
    [
        ("report_path", "decide.db"),
        ("trades_path", "bot.db"),
        ("price_store_path", "paper.db"),
        ("rules_path", "crytobot.toml"),
        ("trades_path", "./sub/../report.txt"),
    ],
)
def test_path_collisions_refused(world: World, key: str, target: str) -> None:
    (world.root / "sub").mkdir(exist_ok=True)
    world.config.write_text(llm_text(world.root, **{key: target}), encoding="utf-8")
    code, console = world.run("report", offline=True)
    assert code == EXIT_REFUSED
    assert console.strip().startswith("llm-paper report: reddedildi: ayar geçersiz: llm_paper.")


def test_preregistered_key_refused(world: World) -> None:
    world.config.write_text(llm_text(world.root) + "seed = 1\n", encoding="utf-8")
    code, console = world.run("report", offline=True)
    assert (code, console.strip()) == (
        EXIT_REFUSED,
        "llm-paper report: reddedildi: ön kayıtlı, ayarlanamaz: llm_paper.seed (spec 0060)",
    )


def test_outputs_atomic(world: World) -> None:
    world.decide()
    world.run("download")
    world.run("report", offline=True)
    leftovers = [p.name for p in world.root.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
    first = (world.root / "trades.jsonl").read_bytes()
    world.run("report", offline=True)
    assert (world.root / "trades.jsonl").read_bytes() == first  # the same inputs, the same file


def test_bad_command(world: World) -> None:
    code, console = world.run("extra")
    assert code == EXIT_REFUSED and console.strip() == USAGE
