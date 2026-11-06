"""Spec 0023 giriş noktası `python -m crytobot download` (AC-1…AC-4, AC-7; R-1, R-2).

`run` gerçek kodu koşar: gerçek `load_download_config`, `run_download` ve `download_history`;
yalnız saat ve borsa sahtedir (`connect` sahte borsayı verir, ağ yok).
"""

import inspect
import io
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crytobot.__main__ import EXIT_DOWNLOAD_STOPPED, EXIT_FORCED, EXIT_OK, EXIT_REFUSED, run
from crytobot.app import load_download_config
from crytobot.market_data import HistoryRequest, HistoryResult, download_history
from crytobot.market_data._client import CallFailure, ExchangeCallError, PublicExchange
from tests.main.test_entry import EXAMPLE, Bot
from tests.market_data.history_helpers import (
    DOWNLOADED_AT,
    FakeHistoryExchange,
    full_history,
    read_file,
)

SECRETS = {
    "BINANCE_API_KEY": "AKIAKEY0123456789",
    "BINANCE_SECRET": "s3cr3t",
    "BINANCE_API_SECRET": "s3cr3t",
    "API_KEY": "AKIAKEY0123456789",
    "CRYTOBOT_MODE": "live",
}


@dataclass
class Downloader:
    """Bot'un çalışma dizininde indirme: gerçek indirme, sahte borsa ve saat."""

    bot: Bot
    exchange: FakeHistoryExchange = field(
        default_factory=lambda: FakeHistoryExchange(full_history(before=250))
    )
    calls: int = 0
    on_check: Callable[[int], None] | None = None

    @property
    def data(self) -> Path:
        return self.bot.root / "history.jsonl"

    def write_config(self, **changes: str) -> None:
        """Örneğin `[history]` yorumu açılır; yollar ve dönem bu dizine göre değişir."""
        values = {
            "data_path": f'"{self.data.as_posix()}"',
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-03T00:00:00Z",
            **changes,
        }
        self.bot.write_config(**values)
        text = self.bot.config_path.read_text(encoding="utf-8")
        rows = text.splitlines()
        first = rows.index("# [history]")
        history = [row.removeprefix("# ") for row in rows[first:]]
        replaced = []
        for row in history:
            key = row.split("=", 1)[0].strip()
            replaced.append(f"{key} = {values[key]}" if key in values and "=" in row else row)
        text = "\n".join([*rows[:first], *replaced]) + "\n"
        self.bot.config_path.write_text(text, encoding="utf-8")

    def download(
        self, request: HistoryRequest, clock: Callable[[], datetime], stop: Callable[[], bool]
    ) -> HistoryResult:
        self.calls += 1
        checks = 0

        def stop_requested() -> bool:
            nonlocal checks
            checks += 1
            if self.on_check is not None:
                self.on_check(checks)
            return stop()

        def connect() -> PublicExchange:
            return self.exchange

        return download_history(request, clock, stop_requested, connect=connect)

    def run(self, argv: list[str] | None = None) -> tuple[int, str]:
        out = io.StringIO()
        code = run(
            ["download"] if argv is None else argv,
            config_path=self.bot.config_path,
            console=out,
            clock=lambda: DOWNLOADED_AT,
            stop=self.bot.stop,
            download=self.download,
        )
        return code, out.getvalue()


@pytest.fixture
def downloader(tmp_path: Path) -> Downloader:
    loader = Downloader(Bot(tmp_path))
    loader.write_config()
    return loader


def files(root: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(root.iterdir()) if path.is_file()}


def example_with_history() -> str:
    """Örnekteki `[history]` yorumda durur (dönemin varsayılanı yoktur); yorumu açılmış hali."""
    rows = EXAMPLE.read_text(encoding="utf-8").splitlines()
    first = rows.index("# [history]")
    return "\n".join([*rows[:first], *(row.removeprefix("# ") for row in rows[first:])]) + "\n"


def test_example_history_section_is_valid_for_the_download() -> None:
    document = tomllib.loads(example_with_history())
    result = load_download_config(document, datetime(2026, 1, 1, tzinfo=UTC))
    assert result.config is not None, result.message
    assert result.config.data_path == "crytobot-history.jsonl"


def test_example_without_history_names_the_missing_section() -> None:
    """Örnek olduğu gibi kopyalanırsa indirme dönemi uydurmaz: bölüm eksik denir."""
    with EXAMPLE.open("rb") as file:
        result = load_download_config(tomllib.load(file), datetime(2026, 1, 1, tzinfo=UTC))
    assert result.config is None and result.message == "ayar eksik: history"


def test_download_writes_the_file_and_prints_the_summary(downloader: Downloader) -> None:
    """AC-1: dosya ve çift başına özet; çıkış 0."""
    code, console = downloader.run()
    assert code == EXIT_OK, console
    data = read_file(downloader.data)
    assert data.complete["counts"] == {"BTC/USDT": 48 + 200, "ETH/USDT": 48 + 200}
    summaries = [row for row in console.splitlines() if row.split(" ", 2)[1] == "özet"]
    assert summaries == [
        f"{DOWNLOADED_AT.isoformat()} özet {pair} ilk=2025-12-23T16:00:00+00:00"
        " son=2026-01-02T23:00:00+00:00 mum=248 boşluk=0"
        for pair in ("BTC/USDT", "ETH/USDT")
    ]
    assert console.splitlines()[-1].endswith(
        f"indirme tamam: dosya={downloader.data.as_posix()} çift=2"
    )


def test_backtest_section_passes_the_download(downloader: Downloader) -> None:
    """Spec 0026 CB-5: `[backtest]` eklenmiş dosyayla indirme ayarları kabul eder."""
    with downloader.bot.config_path.open("a", encoding="utf-8") as file:
        file.write('\n[backtest]\nmode = "live"\nbilinmeyen = 1\n')
    code, console = downloader.run()
    assert code == EXIT_OK, console
    assert downloader.data.is_file()
    assert "bilinmeyen ayar" not in console


def test_keys_ignored_store_and_log_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-2, R-1: ortamda anahtar varken çıktı aynıdır; depo ve kayıt bayt bayt aynı, kilit yok."""
    outputs: list[str] = []
    for name, with_keys in (("plain", False), ("keys", True)):
        if with_keys:
            for key, value in SECRETS.items():
                monkeypatch.setenv(key, value)
        loader = Downloader(Bot(tmp_path / name))
        loader.write_config()
        assert loader.bot.run("prepare")[0] == EXIT_OK
        before = files(loader.bot.root)
        code, console = loader.run()
        assert code == EXIT_OK
        after = files(loader.bot.root)
        assert set(after) - set(before) == {"history.jsonl"}
        assert {name: after[name] for name in before} == before
        assert {call.split(" ")[0] for call in loader.exchange.calls} == {"markets", "klines"}
        outputs.append(
            console.replace(loader.bot.root.as_posix(), "<root>").replace(
                str(loader.bot.root), "<root>"
            )
        )
    assert outputs[0] == outputs[1]
    assert "s3cr3t" not in outputs[1] and "AKIA" not in outputs[1]


@pytest.mark.parametrize("kind", ["missing", "unreadable"])
def test_missing_or_unreadable_config_downloads_nothing(downloader: Downloader, kind: str) -> None:
    """AC-3: ayar dosyası yok ya da okunamıyor: ağa çıkılmaz, dosya yazılmaz."""
    if kind == "missing":
        downloader.bot.config_path.unlink()
        expected = "ayar dosyası yok: crytobot.toml"
    else:
        downloader.bot.config_path.write_text("[history\nstart = ", encoding="utf-8")
        expected = "ayar dosyası okunamıyor: crytobot.toml"
    code, console = downloader.run()
    assert code == EXIT_REFUSED and expected in console
    assert downloader.calls == 0 and not downloader.data.exists()


@pytest.mark.parametrize(
    ("changes", "setting"),
    [
        ({"end": "2026-07-01T00:00:00Z"}, "history.end"),  # after the download moment
        ({"start": "2026-01-01T00:30:00Z"}, "history.start"),
        ({"end": "2026-01-01T00:00:00Z"}, "history.end"),
        ({"start": "2026-01-01T00:00:00"}, "history.start"),
        ({"read_budget": "3600"}, "market.read_budget"),
    ],
)
def test_invalid_setting_downloads_nothing(
    downloader: Downloader, changes: dict[str, str], setting: str
) -> None:
    """AC-3: ilk sorunlu ayar adıyla; indirme çağrılmaz."""
    downloader.write_config(**changes)
    code, console = downloader.run()
    assert code == EXIT_REFUSED
    assert f"indirme başlamadı: ayar geçersiz: {setting}" in console
    assert downloader.calls == 0 and not downloader.data.exists()


@pytest.mark.parametrize("target", ["bot.db", "bot.log"])
def test_data_path_naming_the_store_or_log_another_way_is_refused(
    downloader: Downloader, target: str
) -> None:
    """R-1: başka yazımla da depo ya da kayıt dosyası olamaz (çözümlenmiş yol)."""
    other = f'"{(downloader.bot.root / "x" / ".." / target).as_posix()}"'
    downloader.write_config(data_path=other)
    code, console = downloader.run()
    assert code == EXIT_REFUSED
    assert "indirme başlamadı: ayar geçersiz: history.data_path" in console
    assert downloader.calls == 0


def test_existing_data_file_is_refused_and_kept(downloader: Downloader) -> None:
    """AC-4: var olan dosya bayt bayt aynı kalır; borsaya çağrı gitmez."""
    downloader.data.write_bytes(b"old data")
    code, console = downloader.run()
    assert code == EXIT_DOWNLOAD_STOPPED
    assert "veri dosyası zaten var" in console
    assert downloader.data.read_bytes() == b"old data" and downloader.exchange.calls == []


def test_ban_stops_with_its_code_and_names_the_end(downloader: Downloader) -> None:
    """AC-7: 418 sonrası istek gitmez, çıkış 4, bitiş anı yazılır; dosya kalmaz."""
    downloader.exchange.fail = {2: ExchangeCallError(CallFailure.BANNED, 60.0)}
    code, console = downloader.run()
    assert code == EXIT_DOWNLOAD_STOPPED
    assert "borsa yasağı (HTTP 418), bitiş 2026-06-01T12:01:00+00:00" in console
    assert len(downloader.exchange.calls) == 2
    assert sorted(path.name for path in downloader.bot.root.iterdir()) == ["crytobot.toml"]


def test_unexpected_error_is_named_by_type_without_its_text(downloader: Downloader) -> None:
    downloader.exchange.fail = {3: RuntimeError("AKIAKEY0123456789 s3cr3t")}
    code, console = downloader.run()
    assert code == EXIT_DOWNLOAD_STOPPED
    assert "beklenmeyen hata: RuntimeError" in console
    assert "s3cr3t" not in console and "AKIA" not in console
    assert not downloader.data.exists()


def test_stop_request_mid_download_exits_with_its_code(downloader: Downloader) -> None:
    """AC-7, R-8: ilk istek: indirme sıradaki çağrıdan önce durur; dosya kalmaz."""
    downloader.on_check = lambda n: downloader.bot.stop.request("SIGINT") if n == 3 else None
    code, console = downloader.run()
    assert code == EXIT_DOWNLOAD_STOPPED
    assert "indirme durdu: durdurma isteği" in console
    assert sorted(path.name for path in downloader.bot.root.iterdir()) == ["crytobot.toml"]


def test_second_stop_request_exits_with_130_and_leaves_no_file(downloader: Downloader) -> None:
    """R-8: ikinci istek `ForcedStop`'tur: satır yazılır, `.part` silinir, çıkış 130."""

    def twice(check: int) -> None:
        if check == 3:
            downloader.bot.stop.request("SIGINT")
            downloader.bot.stop.request("SIGINT")

    downloader.on_check = twice
    code, console = downloader.run()
    assert code == EXIT_FORCED
    assert "indirme durdu: zorla durdurma" in console
    assert sorted(path.name for path in downloader.bot.root.iterdir()) == ["crytobot.toml"]


def test_usage_names_the_download_command(downloader: Downloader) -> None:
    for argv in (["download", "--live"], ["indir"]):
        code, console = downloader.run(argv)
        assert code == EXIT_REFUSED
        assert "kullanım: python -m crytobot prepare|start|download" in console
    assert downloader.calls == 0


def test_real_download_function_is_the_default() -> None:
    assert inspect.signature(run).parameters["download"].default is download_history
