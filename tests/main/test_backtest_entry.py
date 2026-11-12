"""Spec 0025 giriş noktası `python -m crytobot backtest` (AC-3, AC-4 yol yazımı, AC-10).

`run` gerçek kodu koşar: gerçek ayar yükleyicisi, okuyucu (`read_history`), koşu ve rapor yazıcısı.
Borsa yoktur; saat yalnız raporun üretim anı içindir (spec 0040) ve burada sabittir.
Spec 0042 (plan Risk 8): ayar `holdout_at` taşır; `backtest --final` son değerlendirmedir.
"""

import hashlib
import io
import json
import tomllib
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.__main__ import (
    EXIT_BACKTEST_STOPPED,
    EXIT_FORCED,
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_REPORT_NOT_WRITTEN,
    StoreLock,
    run,
)
from crytobot.app import StopRequest, _backtest, load_backtest_config, run_turn
from crytobot.strategy import StrategySettings
from tests.app.backtest_helpers import at, candles, final_history, history, write_history
from tests.app.helpers import HOUR
from tests.main.test_entry import EXAMPLE, Bot, config_text
from tests.market_data.helpers import BTC, ETH, NOW

SECRETS = {
    "BINANCE_API_KEY": "AKIAKEY0123456789",
    "BINANCE_SECRET": "s3cr3t",
    "API_KEY": "AKIAKEY0123456789",
    "CRYTOBOT_MODE": "live",
}
FLAT = [10] * 8
SHORT_S0 = StrategySettings(1, 2, 3, Decimal(70), 3, Decimal(2), Decimal(2))  # the config's own


class Backtester:
    """Bot'un çalışma dizininde backtest: ayar dosyası ve veri dosyası `root`'ta."""

    def __init__(self, root: Path) -> None:
        self.bot = Bot(root)
        self.root = root
        self.stop = StopRequest()
        self.write_config()
        write_history(self.data, history({BTC: candles(-4, FLAT), ETH: candles(-4, FLAT)}, hours=4))

    @property
    def data(self) -> Path:
        return self.root / "history.jsonl"

    @property
    def report(self) -> Path:
        return self.root / "rapor.txt"

    def write_config(self, **section: str) -> None:
        values = {
            "data_path": f'"{self.data.as_posix()}"',
            "report_path": f'"{self.report.as_posix()}"',
            "split_at": "2026-01-01T02:00:00Z",
            "holdout_at": "2026-01-01T03:00:00Z",
            "spread": '"0.0005"',
            **section,
        }
        rows = "".join(f"{key} = {value}\n" for key, value in values.items())
        # spec 0043 R-4 (plan Risk 4): four candles warm a strategy needing four
        short = {"fast_period": "1", "slow_period": "2", "rsi_period": "3", "atr_period": "3"}
        text = config_text(self.root, candle_count="4", **short) + "\n[backtest]\n" + rows
        self.bot.config_path.write_text(text, encoding="utf-8")

    def run(self, argv: list[str] | None = None) -> tuple[int, str]:
        out = io.StringIO()
        code = run(
            ["backtest"] if argv is None else argv,
            config_path=self.bot.config_path,
            console=out,
            stop=self.stop,
            clock=lambda: NOW,
        )
        return code, out.getvalue()


@pytest.fixture
def tester(tmp_path: Path) -> Backtester:
    return Backtester(tmp_path)


def files(root: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(root.iterdir()) if path.is_file()}


def test_no_key_read_no_network_files_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-3: anahtar ortamda olsa da davranış aynı; ağ yok (pytest-socket); depo, kayıt ve veri
    dosyası bayt bayt değişmez."""
    plain = Backtester(tmp_path / "anahtarsiz")
    code, quiet = plain.run()
    assert code == EXIT_OK, quiet

    keyed = Backtester(tmp_path / "anahtarli")
    assert keyed.bot.run("prepare")[0] == EXIT_OK  # a real bot store and log next to it
    before = files(keyed.root)
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    code, console = keyed.run()
    assert code == EXIT_OK, console
    after = files(keyed.root)
    assert after.pop("rapor.txt") == plain.report.read_bytes()
    assert after == before
    for value in SECRETS.values():
        assert value not in console
    assert console.replace(str(keyed.report.as_posix()), "R") == quiet.replace(
        str(plain.report.as_posix()), "R"
    )


def test_console_lines_carry_no_time_stamp(tester: Backtester) -> None:
    """R-12: koşuya saat verilmez; satırlar `backtest` ya da rapor metniyle başlar."""
    code, console = tester.run()
    assert code == EXIT_OK
    rows = console.splitlines()
    assert rows[0].startswith("backtest başladı: dönem=2026-01-01T00:00:00+00:00")
    assert "CrytoBot backtest raporu" in rows
    assert rows[-1] == f"backtest tamam: rapor dosyası {tester.report.as_posix()}"
    assert tester.report.read_text(encoding="utf-8") in console


def test_report_carries_the_entry_clock_and_its_fingerprint(tester: Backtester) -> None:
    """Spec 0040 CB-1, CB-2: giriş noktası saati verir; konsoldaki parmak izi dosyanınkidir."""
    code, console = tester.run()
    assert code == EXIT_OK
    report = tester.report.read_bytes()
    assert f"üretim anı: {NOW.isoformat()}\n".encode() in report
    rows = console.splitlines()
    assert rows[-2] == f"rapor parmak izi: {hashlib.sha256(report).hexdigest()}"


def test_completes_while_bot_holds_lock(tester: Backtester) -> None:
    """AC-3: aynı depoyla çalışan bir botun kilidi varken koşu tamamlanır."""
    assert tester.bot.run("prepare")[0] == EXIT_OK
    lock = StoreLock(str(tester.bot.store))
    assert lock.acquire() is None
    try:
        code, console = tester.run()
    finally:
        lock.release()
    assert code == EXIT_OK, console
    assert tester.report.exists()


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("missing", "backtest reddedildi: ayar dosyası yok: crytobot.toml"),
        ("unreadable", "backtest reddedildi: ayar dosyası okunamıyor: crytobot.toml"),
        ("invalid", "backtest reddedildi: ayar geçersiz: backtest.spread"),
        ("bot", "backtest reddedildi: ayar geçersiz: turn.fee"),
    ],
)
def test_missing_or_unreadable_config_writes_nothing(
    tester: Backtester, kind: str, expected: str
) -> None:
    """AC-4: hiçbir şey yazılmaz, ilk sorunlu ayar adıyla; ham değer yazılmaz."""
    if kind == "missing":
        tester.bot.config_path.unlink()
    elif kind == "unreadable":
        tester.bot.config_path.write_bytes(b"[bot\n\xff")
    elif kind == "invalid":
        tester.write_config(spread='"0.1SIR"')
    else:
        text = tester.bot.config_path.read_text(encoding="utf-8")
        tester.bot.config_path.write_text(text.replace('fee = "0.001"', 'fee = "-1"'), "utf-8")
    before = files(tester.root)
    code, console = tester.run()
    assert code == EXIT_REFUSED
    assert console == expected + "\n"
    assert files(tester.root) == before
    assert "SIR" not in console


@pytest.mark.parametrize(
    ("key", "spelled", "setting"),
    [
        ("report_path", "sub/../bot.db", "backtest.report_path"),
        ("report_path", "./bot.log", "backtest.report_path"),
        ("report_path", "sub/../history.jsonl", "backtest.report_path"),
        ("data_path", "./bot.db", "backtest.data_path"),
    ],
)
def test_report_path_spelled_as_store_is_refused(
    tester: Backtester, key: str, spelled: str, setting: str
) -> None:
    """AC-4, R-2: başka yazımla aynı dosya da reddedilir (çözülmüş yolla)."""
    (tester.root / "sub").mkdir()
    tester.write_config(**{key: f'"{(tester.root / spelled).as_posix()}"'})
    before = files(tester.root)
    code, console = tester.run()
    assert code == EXIT_REFUSED
    assert console == f"backtest reddedildi: ayar geçersiz: {setting}\n"
    assert files(tester.root) == before


@pytest.fixture
def stores(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Koşunun geçici depo yolları (`run_turn`'ün gördüğü)."""
    seen: list[str] = []
    real = run_turn  # the same function `_backtest` calls

    def spy(**kwargs: Any) -> Any:
        seen.append(str(kwargs["store_path"]))
        return real(**kwargs)

    monkeypatch.setattr(_backtest, "run_turn", spy)
    yield seen


def test_temporary_store_is_removed(tester: Backtester, stores: list[str]) -> None:
    assert tester.run()[0] == EXIT_OK
    assert stores and not Path(stores[0]).parent.exists()
    assert sorted(path.name for path in tester.root.iterdir()) == [
        "crytobot.toml",
        "history.jsonl",
        "rapor.txt",
    ]


def test_forced_stop_leaves_no_report(tester: Backtester, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-10, R-13: ikinci durdurma isteği ikinci turda: çıkış 130, rapor yok, `.part` yok,
    geçici dizin silinmiş."""
    seen: list[str] = []
    real = run_turn  # the same function `_backtest` calls

    def second_turn_forced(**kwargs: Any) -> Any:
        seen.append(str(kwargs["store_path"]))
        if len(seen) == 2:
            tester.stop.request("SIGINT")
            tester.stop.request("SIGINT")  # ForcedStop
        return real(**kwargs)

    monkeypatch.setattr(_backtest, "run_turn", second_turn_forced)
    code, console = tester.run()
    assert code == EXIT_FORCED
    assert console.splitlines()[-1] == "backtest durdu: zorla durdurma; rapor yazılmadı"
    assert "CrytoBot backtest raporu" not in console
    assert sorted(path.name for path in tester.root.iterdir()) == ["crytobot.toml", "history.jsonl"]
    assert not Path(seen[0]).parent.exists()


def test_untrusted_data_exits_with_stopped(tester: Backtester) -> None:
    rows = [json.loads(row) for row in tester.data.read_text(encoding="utf-8").splitlines()]
    rows[2] = [*rows[2][:3], "1", "2", rows[2][5]]
    tester.data.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    code, console = tester.run()
    assert code == EXIT_BACKTEST_STOPPED
    assert "güvenilmeyen veri: BTC/USDT (high_below_low)" in console
    assert not tester.report.exists()


def test_report_file_failure_exits_with_report_on_console(tester: Backtester) -> None:
    missing = tester.root / "yok" / "rapor.txt"
    tester.write_config(report_path=f'"{missing.as_posix()}"')
    code, console = tester.run()
    assert code == EXIT_REPORT_NOT_WRITTEN
    assert "CrytoBot backtest raporu" in console
    assert "rapor dosyası yazılamadı" in console
    assert not missing.parent.exists()


def test_existing_report_is_refused(tester: Backtester) -> None:
    tester.report.write_text("eski", encoding="utf-8")
    code, console = tester.run()
    assert code == EXIT_REFUSED
    assert "rapor dosyası var" in console
    assert tester.report.read_text(encoding="utf-8") == "eski"


def test_usage_names_the_backtest_command(tester: Backtester) -> None:
    code, console = tester.run(["backtest", "--live"])
    assert code == EXIT_REFUSED
    assert "kullanım: python -m crytobot prepare|start|download|backtest" in console
    assert not tester.report.exists()


def example_with_backtest() -> str:
    """Örnekteki `[backtest]` yorumda durur; yorumu açılmış hali (bölümün satırları)."""
    rows = EXAMPLE.read_text(encoding="utf-8").splitlines()
    first = rows.index("# [backtest]")
    last = next(i for i in range(first, len(rows)) if not rows[i].startswith("# "))
    opened = [row.removeprefix("# ") for row in rows[first:last]]
    return "\n".join([*rows[:first], *opened, *rows[last:]]) + "\n"


def test_example_backtest_section_is_valid() -> None:
    result = load_backtest_config(tomllib.loads(example_with_backtest()))
    assert result.config is not None, result.message
    assert result.config.report_path == "crytobot-backtest.txt"
    assert result.config.split_at == at(0).replace(year=2025, month=11, day=22)
    assert result.config.holdout_at == at(0).replace(year=2025, month=11, day=26)


def test_example_without_backtest_names_the_missing_section() -> None:
    with EXAMPLE.open("rb") as file:
        result = load_backtest_config(tomllib.load(file))
    assert result.config is None and result.message == "ayar eksik: backtest"


def write_final(tester: Backtester, **section: str) -> None:
    """Spec 0043 R-5 (plan Risk 1, 5): `final_data` iki aralığın dosyasını verir; ayrım anları 1h
    ve 4h sınırında. Dosyalar 200 mumluk ısınma taşır (`final_history`)."""
    paths = {text: tester.root / f"history-{text}.jsonl" for text in ("1h", "4h")}
    for text, hours in (("1h", 1), ("4h", 4)):
        write_history(paths[text], final_history(hours * HOUR, lambda _index: 10, (BTC, ETH)))
    table = ", ".join(f'"{text}" = "{path.as_posix()}"' for text, path in paths.items())
    values = {
        "split_at": "2026-01-01T08:00:00Z",
        "holdout_at": "2026-01-01T12:00:00Z",
        "final_data": f"{{ {table} }}",
    }
    tester.write_config(**{**values, **section})


@pytest.fixture
def small_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    """R-3 ızgarası 72 kombinasyonla ~15 s sürer (plan Risk 9, `tests/app/test_evaluation_grid.py`);
    giriş noktası testleri yolu sınar: aralık başına fixture'ın tek kısa stratejisi."""
    from crytobot.app import _evaluation

    monkeypatch.setattr(_evaluation, "CANDIDATE_GRIDS", ((SHORT_S0,),))


def test_final_writes_a_final_report_with_the_same_exit_codes(
    tester: Backtester, small_grid: None
) -> None:
    """Spec 0042 AC-1, AC-6: `backtest --final` son değerlendirme raporu yazar (burada 30 işlem
    yok: "aday yok"); parmak izi satırı ve çıkış kodu varsayılanla aynı yoldan. Spec 0043 R-5:
    tek değerlendirme 1h ve 4h'yi birlikte sınar."""
    write_final(tester)
    code, console = tester.run(["backtest", "--final"])
    assert code == EXIT_OK, console
    report = tester.report.read_text(encoding="utf-8")
    assert report.splitlines()[0] == "CrytoBot backtest raporu — son değerlendirme"
    assert "sınanan kombinasyon: 2\n" in report
    assert "paper adayı: aday yok\n" in report
    assert "== aday: S0 1h ==\n" in report and "== aday: S0 4h ==\n" in report
    assert report.count("sonuç: geçmedi: örneklem içi işlem yetersiz (0 < 30)\n") == 2
    rows = console.splitlines()
    assert rows[0] == "backtest son değerlendirme başladı: aday=2 kombinasyon=2"
    assert rows[-2] == (
        f"rapor parmak izi: {hashlib.sha256(tester.report.read_bytes()).hexdigest()}"
    )
    code, console = tester.run(["backtest", "--final"])
    assert code == EXIT_REFUSED and "rapor dosyası var" in console


def test_final_without_final_data_refused(tester: Backtester) -> None:
    """Spec 0043 R-5: `--final` iki aralığın dosyasını ister; varsayılan koşu istemez."""
    code, console = tester.run(["backtest", "--final"])
    assert code == EXIT_REFUSED
    assert console == "backtest reddedildi: ayar eksik: backtest.final_data\n"
    assert not tester.report.exists()
    assert tester.run()[0] == EXIT_OK


def test_final_data_naming_the_store_refused(tester: Backtester) -> None:
    """Veri yolu bot deposunu başka yazımla da adlandıramaz (`_same_file`)."""
    write_final(tester)
    text = tester.bot.config_path.read_text(encoding="utf-8")
    other = (tester.root / "history-4h.jsonl").as_posix()
    store = (tester.root / "." / "bot.db").as_posix()
    tester.bot.config_path.write_text(text.replace(other, store), encoding="utf-8")
    code, console = tester.run(["backtest", "--final"])
    assert code == EXIT_REFUSED
    assert "ayar geçersiz: backtest.final_data" in console


def test_default_backtest_console_shows_in_sample_only(tester: Backtester) -> None:
    """Spec 0042 AC-1: varsayılan koşu örneklem içi dönemi söyler; sonrası yazılmaz."""
    code, console = tester.run()
    assert code == EXIT_OK
    assert console.splitlines()[0] == (
        "backtest başladı: dönem=2026-01-01T00:00:00+00:00..2026-01-01T02:00:00+00:00"
        " (örneklem içi) çift=2 tur=2"
    )
    assert "örneklem dışı" not in console
    assert "saklı dönem" not in console and "tüm koşu" not in console


def test_holdout_outside_the_data_is_refused_before_any_turn(
    tester: Backtester, small_grid: None
) -> None:
    """Spec 0042 AC-2: saklı dönem başı veri dönemini aşarsa ret, rapor yok, çıkış 1."""
    tester.write_config(holdout_at="2026-01-01T04:00:00Z")
    code, console = tester.run(["backtest"])
    assert code == EXIT_REFUSED
    assert "ayar geçersiz: backtest.holdout_at" in console
    assert not tester.report.exists()
    write_final(tester, holdout_at="2026-01-01T16:00:00Z")  # spec 0043: the final data's end
    code, console = tester.run(["backtest", "--final"])
    assert code == EXIT_REFUSED
    assert "ayar geçersiz: backtest.holdout_at" in console
    assert not tester.report.exists()
