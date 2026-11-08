"""Spec 0022 giriş noktası `python -m crytobot prepare|start` (AC-1…AC-3, AC-7, AC-11…AC-13).

`run` gerçek kodu koşar; yalnız saat, bekleme ve okumanın borsası sahtedir: okuma gerçek
`read_market_data`'dır, `connect` sahte borsayı verir (ağ yok, `tests/market_data/helpers.py`).
"""

import io
import signal
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import crytobot.__main__ as entry
from crytobot.__main__ import (
    EXIT_FORCED,
    EXIT_LOG_FAILED,
    EXIT_OK,
    EXIT_READ_REFUSED,
    EXIT_REFUSED,
    Output,
    StoreLock,
    install_signals,
    make_wait,
    run,
    stop_signals,
)
from crytobot.app import TRIAL_MARK, ForcedStop, StopRequest, load_config
from crytobot.market_data import InputProblem, MarketRead, ReadSettings, read_market_data
from crytobot.persistence import create_store, load_store
from tests.app.loop_fakes import Clock
from tests.market_data.helpers import NOW, FakeExchange

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "crytobot.example.toml"
PUBLIC_CALLS = {"markets", "klines", "ticker"}


def config_text(root: Path, **changes: str) -> str:
    """Örnek dosya; depo ve kayıt yolu `root`'ta. `changes`: anahtar → TOML değeri."""
    text = EXAMPLE.read_text(encoding="utf-8")
    values = {
        "store_path": f'"{(root / "bot.db").as_posix()}"',
        "log_path": f'"{(root / "bot.log").as_posix()}"',
        **changes,
    }
    lines = []
    for row in text.splitlines():
        key = row.split("=", 1)[0].strip()
        lines.append(f"{key} = {values[key]}" if key in values and "=" in row else row)
    return "\n".join(lines) + "\n"


class SpyExchange(FakeExchange):
    """Okumanın borsada dokunduğu her açık adı kaydeder."""

    def __init__(self) -> None:
        super().__init__()
        object.__setattr__(self, "touched", [])

    def __getattribute__(self, name: str) -> Any:
        if not name.startswith("_") and name not in {"touched", "calls", "kline_requests"}:
            object.__getattribute__(self, "touched").append(name)
        return object.__getattribute__(self, name)


@dataclass
class Bot:
    """Bir çalışma dizini: ayar dosyası, sahte saat ve borsa. `stop_on_read`: n'inci okumada
    durdurma istenir (tur biter, sonra çıkılır)."""

    root: Path
    clock: Clock = field(default_factory=lambda: Clock(NOW))
    exchange: SpyExchange = field(default_factory=SpyExchange)
    stop_on_read: int | None = 2
    stop_twice: bool = False
    reads: int = 0
    stop: StopRequest = field(default_factory=StopRequest)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.write_config()

    @property
    def config_path(self) -> Path:
        return self.root / "crytobot.toml"

    @property
    def store(self) -> Path:
        return self.root / "bot.db"

    @property
    def log(self) -> Path:
        return self.root / "bot.log"

    def write_config(self, **changes: str) -> None:
        self.config_path.write_text(config_text(self.root, **changes), encoding="utf-8")

    def read(self, pairs: tuple[str, ...], settings: ReadSettings) -> MarketRead:
        self.reads += 1
        if self.reads == self.stop_on_read:
            self.stop.request("SIGINT")
            if self.stop_twice:
                self.stop.request("SIGINT")
        return read_market_data(pairs, settings, self.clock, connect=lambda: self.exchange)

    def wait(self, seconds: float) -> None:
        self.clock.advance(seconds)

    def run(self, *command: str, console: Any = None, trial: bool = True) -> tuple[int, str]:
        cmd = list(command)
        if cmd == ["start"] and trial:
            cmd = ["start", "--trial"]
        out = io.StringIO() if console is None else console
        self.stop = StopRequest()  # a new process: its own stop request and read count
        self.reads = 0
        code = run(
            cmd,
            config_path=self.config_path,
            console=out,
            clock=self.clock,
            stop=self.stop,
            read=self.read,
            wait=self.wait,
        )
        return code, out.getvalue() if isinstance(out, io.StringIO) else ""

    def log_lines(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines()


def event_lines(text: str, event: str) -> list[str]:
    return [row for row in text.splitlines() if row.split(" ", 2)[1:2] == [event]]


@pytest.fixture
def bot(tmp_path: Path) -> Bot:
    return Bot(tmp_path)


def test_example_config_is_valid() -> None:
    """Repodaki örnek dosya bütün ayarları taşır ve geçerlidir."""
    with EXAMPLE.open("rb") as file:
        result = load_config(tomllib.load(file), NOW)
    assert result.config is not None, result.message


def test_real_config_is_ignored_by_git() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "crytobot.toml" in ignored


def test_start_writes_summaries_to_console_and_log(bot: Bot) -> None:
    """AC-1: hazırlık, sonra başlatma: ilk tur hemen, ikincisi saat başında; özetler iki yerde."""
    assert bot.run("prepare")[0] == EXIT_OK
    code, console = bot.run("start")
    assert code == EXIT_OK
    summaries = event_lines(console, "tur")
    assert len(summaries) == 2
    assert "an=2026-11-05T14:44:20+00:00" in summaries[0]
    assert "an=2026-11-05T15:00:00+00:00" in summaries[1]
    assert all("sonuç=completed" in row for row in summaries)
    log = bot.log_lines()
    assert event_lines("\n".join(log), "tur") == summaries
    assert event_lines(console, "durdurma")[0].endswith(
        "durdu: neden=durdurma isteği (SIGINT) son_tur=completed tur_sayısı=2"
    )


def test_history_section_passes_prepare_and_start(bot: Bot) -> None:
    """Spec 0024 CB-4: `[history]` eklenmiş gerçek dosya giriş noktasından geçer."""
    text = config_text(bot.root) + '\n[history]\nmode = "live"\nbilinmeyen = 1\n'
    bot.config_path.write_text(text, encoding="utf-8")
    code, prepared = bot.run("prepare")
    assert code == EXIT_OK
    code, started = bot.run("start")
    assert code == EXIT_OK
    assert event_lines(started, "tur")
    for output in (prepared, started, "\n".join(bot.log_lines())):
        assert "bilinmeyen ayar" not in output


def test_backtest_section_passes_prepare_and_start(bot: Bot) -> None:
    """Spec 0026 CB-5: `[backtest]` eklenmiş gerçek dosya giriş noktasından geçer."""
    text = config_text(bot.root) + '\n[backtest]\nmode = "live"\nbilinmeyen = 1\n'
    bot.config_path.write_text(text, encoding="utf-8")
    code, prepared = bot.run("prepare")
    assert code == EXIT_OK
    code, started = bot.run("start")
    assert code == EXIT_OK
    assert event_lines(started, "tur")
    for output in (prepared, started, "\n".join(bot.log_lines())):
        assert "bilinmeyen ayar" not in output


def test_trial_mark_on_start_and_every_summary(bot: Bot) -> None:
    """AC-12, R-14: başlatma çıktısı, kayıttaki başlatma satırı ve her tur özeti."""
    bot.run("prepare")
    _, console = bot.run("start")
    log = "\n".join(bot.log_lines())
    for text in (console, log):
        (start,) = event_lines(text, "başlatma")
        assert TRIAL_MARK in start
        summaries = event_lines(text, "tur")
        assert summaries and all(TRIAL_MARK in row for row in summaries)


def test_prepare_twice_is_refused(bot: Bot) -> None:
    assert bot.run("prepare")[0] == EXIT_OK
    before = bot.store.read_bytes()
    code, console = bot.run("prepare")
    assert code == EXIT_REFUSED and "depo zaten var" in console
    assert bot.store.read_bytes() == before
    assert bot.reads == 0


def test_prepare_makes_no_turn_and_no_read(bot: Bot) -> None:
    """R-3: hazırlık tur atmaz ve borsaya çıkmaz."""
    assert bot.run("prepare")[0] == EXIT_OK
    assert bot.reads == 0 and bot.exchange.touched == []
    state = load_store(bot.store, "paper").state
    assert state is not None and state.execution.orders == {}


def test_start_without_store_names_it_and_suggests_prepare(bot: Bot) -> None:
    code, console = bot.run("start")
    assert code == EXIT_REFUSED
    assert "başlatma reddedildi: depo yok; önce hazırlık: python -m crytobot prepare" in console
    assert not bot.store.exists() and bot.reads == 0


@pytest.mark.parametrize("kind", ["missing", "unreadable", "huge", "invalid", "not_utf8"])
def test_missing_or_unreadable_config_touches_nothing(bot: Bot, kind: str) -> None:
    """AC-3: bot başlamaz, sorun adıyla söylenir; borsaya, depoya ve kayda dokunulmaz."""
    expected = {
        "missing": "ayar dosyası yok: crytobot.toml",
        "unreadable": "ayar dosyası okunamıyor: crytobot.toml",
        "huge": "ayar dosyası okunamıyor: crytobot.toml",
        "invalid": "bot başlamadı: ayar geçersiz: market.read_budget",
        "not_utf8": "ayar dosyası okunamıyor: crytobot.toml",
    }[kind]
    if kind == "missing":
        bot.config_path.unlink()
    elif kind == "unreadable":
        bot.config_path.write_text("[bot\nstore_path = ", encoding="utf-8")
    elif kind == "huge":  # Python 3.12 refuses a 4300+ digit integer (Known traps)
        bot.write_config(read_budget="1" * 5000)
    elif kind == "invalid":
        bot.write_config(read_budget="3600")
    else:
        bot.config_path.write_bytes(b'[bot]\nstore_path = "\xff\xfe"\n')
    for command in ("prepare", "start"):
        code, console = bot.run(command)
        assert code == EXIT_REFUSED
        assert expected in console
        assert "1111" not in console
    assert sorted(path.name for path in bot.root.iterdir()) == (
        [] if kind == "missing" else ["crytobot.toml"]
    )
    assert bot.reads == 0


def test_usage_on_unknown_command(bot: Bot) -> None:
    for argv in ([], ["live"], ["start", "--live"], ["prepare", "start"]):
        out = io.StringIO()
        assert run(argv, config_path=bot.config_path, console=out) == EXIT_REFUSED
        assert "kullanım: python -m crytobot prepare|start" in out.getvalue()
    assert not bot.store.exists()


def test_keys_in_environment_change_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-2, R-1: ortamda anahtar ve mod varken çıktı aynıdır; hesap ya da emir çağrısı yok."""
    plain = Bot(tmp_path / "plain")
    plain.run("prepare")
    _, without = plain.run("start")
    for name, value in {
        "BINANCE_API_KEY": "AKIAKEY0123456789",
        "BINANCE_SECRET": "s3cr3t",
        "BINANCE_API_SECRET": "s3cr3t",
        "API_KEY": "AKIAKEY0123456789",
        "CRYTOBOT_MODE": "live",
        "MODE": "live",
    }.items():
        monkeypatch.setenv(name, value)
    keys = Bot(tmp_path / "keys")
    keys.run("prepare")
    _, with_keys = keys.run("start")
    assert with_keys.replace(keys.root.as_posix(), plain.root.as_posix()) == without
    assert "s3cr3t" not in with_keys and "AKIA" not in with_keys
    assert keys.exchange.calls == plain.exchange.calls
    assert set(keys.exchange.touched) <= PUBLIC_CALLS


def test_entry_never_reads_the_environment() -> None:
    """R-1: giriş noktası ve `app` ortam değişkeni okumaz (kaynakta `environ`/`getenv` yok)."""
    sources = [Path(entry.__file__), *(Path(entry.__file__).parent / "app").glob("*.py")]
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert "environ" not in text and "getenv" not in text, path.name


def test_only_public_calls_reach_the_exchange(bot: Bot) -> None:
    """AC-2: sahte borsa yalnız herkese açık üç çağrıyı görür: emir ve hesap çağrısı yoktur."""
    bot.run("prepare")
    bot.run("start")
    assert bot.exchange.touched
    assert set(bot.exchange.touched) <= PUBLIC_CALLS


def test_live_store_is_refused_by_the_entry(bot: Bot) -> None:
    created = create_store(bot.store, "live")
    assert created.state is not None
    code, console = bot.run("start")
    assert code == EXIT_REFUSED and "paper modunda değil" in console
    assert bot.reads == 0


def test_second_start_on_same_store_is_refused(bot: Bot) -> None:
    """AC-7, R-6: aynı depoyu tutan süreç varken ikinci başlatma ve hazırlık reddedilir."""
    assert bot.run("prepare")[0] == EXIT_OK
    before = bot.store.read_bytes()
    held = StoreLock(str(bot.store))
    assert held.acquire() is None
    try:
        for command in ("start", "prepare"):
            code, console = bot.run(command)
            assert code == EXIT_REFUSED
            assert "reddedildi: depo başka bir bot sürecinde kullanılıyor" in console
        assert bot.reads == 0 and bot.store.read_bytes() == before
    finally:
        held.release()
    assert bot.run("start")[0] == EXIT_OK  # released: the next start runs


def test_lock_is_released_after_each_run(bot: Bot) -> None:
    bot.run("prepare")
    bot.run("start")
    lock = StoreLock(str(bot.store))
    assert lock.acquire() is None
    lock.release()


def test_lock_in_a_missing_folder_is_named(tmp_path: Path) -> None:
    bot = Bot(tmp_path)
    bot.write_config(store_path=f'"{(tmp_path / "yok" / "bot.db").as_posix()}"')
    code, console = bot.run("prepare")
    assert code == EXIT_REFUSED and "kilit dosyası açılamıyor" in console


@pytest.fixture
def restore_signals() -> Iterator[None]:
    saved = {sig: signal.getsignal(sig) for sig in stop_signals()}
    yield
    for sig, handler in saved.items():
        signal.signal(sig, handler)


@pytest.mark.usefixtures("restore_signals")
def test_platform_signals_reach_the_loop() -> None:
    """AC-11, R-12: Ctrl+C her yerde, Windows'ta Ctrl+Break, Unix'te SIGTERM; ikincisi zorlar."""
    import sys

    if sys.platform == "win32":  # an if block: mypy narrows the platform here, not in a ternary
        expected = {signal.SIGINT, signal.SIGBREAK}
    else:
        expected = {signal.SIGINT, signal.SIGTERM}
    assert set(stop_signals()) == expected
    for sig in stop_signals():
        stop = StopRequest()
        install_signals(stop)
        handler = signal.getsignal(sig)
        assert callable(handler)
        handler(sig, None)
        assert stop.requested and stop.source == sig.name
        with pytest.raises(ForcedStop):
            handler(sig, None)


def test_wait_returns_soon_after_a_stop_request() -> None:
    """Plan Risk 6: bekleme ≤1 s'lik parçalardır; istekten sonra en geç bir parça."""
    stop = StopRequest()
    now = [0.0]
    pieces: list[float] = []

    def sleep(seconds: float) -> None:
        pieces.append(seconds)
        now[0] += seconds
        if len(pieces) == 3 and not stop.requested:
            stop.request("SIGINT")

    make_wait(stop, sleep, lambda: now[0])(3600.0)
    assert pieces == [1.0, 1.0, 1.0]
    pieces.clear()
    make_wait(StopRequest(), sleep, lambda: now[0])(2.5)
    assert pieces == [1.0, 1.0, 0.5]


def test_read_refusal_exits_with_its_code(bot: Bot, monkeypatch: pytest.MonkeyPatch) -> None:
    bot.run("prepare")
    monkeypatch.setattr(bot, "read", lambda *_: MarketRead((), None, InputProblem.CLOCK))
    code, console = bot.run("start")
    assert code == EXIT_READ_REFUSED
    assert "okuma reddedildi: clock" in console


def test_second_stop_during_a_turn_exits_with_130(bot: Bot) -> None:
    bot.run("prepare")
    bot.stop_on_read, bot.stop_twice = 1, True
    code, console = bot.run("start")
    assert code == EXIT_FORCED
    assert "neden=zorla durdurma" in console


def test_unwritable_log_goes_to_console_and_stops(bot: Bot) -> None:
    """AC-13, R-15: kayıt dosyası yazılamıyor: satırlar konsolda, bot tur atmadan durur."""
    assert bot.run("prepare")[0] == EXIT_OK
    folder = bot.root / "kayıt-klasörü"
    folder.mkdir()
    bot.write_config(log_path=f'"{folder.as_posix()}"')
    code, console = bot.run("start")
    assert code == EXIT_LOG_FAILED
    assert event_lines(console, "başlatma") and TRIAL_MARK in console
    assert "kayıt dosyası yazılamıyor: bot durdu" in console
    assert event_lines(console, "tur") == [] and bot.reads == 0


def test_unwritable_log_during_prepare_is_named(bot: Bot) -> None:
    folder = bot.root / "kayıt"
    folder.mkdir()
    bot.write_config(log_path=f'"{folder.as_posix()}"')
    code, console = bot.run("prepare")
    assert code == EXIT_LOG_FAILED
    assert "hazırlık paper deposu hazır" in console
    assert "kayıt dosyası yazılamıyor" in console


def test_console_without_turkish_characters_does_not_crash(bot: Bot) -> None:
    """AC-13, R-13: konsol basamadığı karakteri yer tutucuyla yazar; kayıt UTF-8 tam metindir."""
    bot.run("prepare")
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="ascii", errors="strict")
    code, _ = bot.run("start", console=console)
    console.flush()
    assert code == EXIT_OK
    shown = raw.getvalue().decode("ascii")
    assert "ba?lad?" in shown and "?" in shown
    log = bot.log.read_bytes().decode("utf-8")
    assert "başladı" in log and TRIAL_MARK in log


def test_log_is_appended_never_rewritten(bot: Bot) -> None:
    bot.run("prepare")
    bot.run("start")
    first = bot.log.read_bytes()
    bot.run("start")
    assert bot.log.read_bytes().startswith(first)
    assert len(event_lines(bot.log.read_text(encoding="utf-8"), "başlatma")) == 2


def test_log_path_naming_the_store_another_way_never_writes_into_the_store(bot: Bot) -> None:
    """R-05 reproduction, review round 1 L-3 (QA, VERIFY 0022): `bot.log_path` is compared with
    `bot.store_path` only as text, so `<root>/./bot.db` passes and log lines are appended into
    the SQLite store file. Whatever the fix (refuse the setting, or keep the files apart), no
    log line may ever land in the store file (persistence, sensitive area)."""
    bot.write_config(log_path=f'"{bot.root.as_posix()}/./bot.db"')
    for command in ("prepare", "start"):
        bot.run(command)
    if bot.store.exists():
        data = bot.store.read_bytes()
        assert "hazırlık".encode() not in data  # prepare's line
        assert TRIAL_MARK.encode() not in data  # start's line and every turn summary


@pytest.mark.parametrize("command", ["prepare", "start"])
def test_log_path_naming_the_store_another_way_is_refused(bot: Bot, command: str) -> None:
    """Review round 3 L-2: `./bot.db` names the store; the setting is refused before anything is
    touched — no store, no `.lock`, no log file, only the console line."""
    bot.write_config(log_path=f'"{bot.root.as_posix()}/./bot.db"')
    code, console = bot.run(command)
    assert code == EXIT_REFUSED
    assert "bot başlamadı: ayar geçersiz: bot.log_path" in console
    assert sorted(path.name for path in bot.root.iterdir()) == ["crytobot.toml"]


def test_output_without_log_writes_only_the_console() -> None:
    out = io.StringIO()
    Output(out)("satır")
    assert out.getvalue() == "satır\n"
