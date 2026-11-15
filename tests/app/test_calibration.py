"""Spec 0045 AC-7, AC-9 (app): ayarlar, veri denetimi, onay kapısı, yazım; iki koşu bayt eşit.

Veri dosyaları gerçek biçimde (sürüm 2) yazılır ve gerçek okuyucuyla okunur. Dönemler kısadır
(`PERIODS`, 4 gün): 15m'de 384 mum; spec'in dönemleri yalnız giriş noktasının varsayılanıdır.
Bu dosya `tests/tooling` kopyasına da girer: başka test paketinden import etmez.
"""

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import (
    CalibrationConfig,
    CalibrationOutcome,
    CalibrationParts,
    StopRequest,
    load_calibration_config,
    run_calibration,
    run_calibration_final,
)
from crytobot.backtest import report_exists, write_report
from crytobot.calibration import Period
from crytobot.market_data import read_history

D0 = datetime(2024, 1, 1, tzinfo=UTC)
DAY = timedelta(days=1)
PAIRS = ("BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT")
STEPS = {
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": DAY,
}
PERIODS = (
    Period("ayarlama", D0 + DAY, D0 + 2.5 * DAY, PAIRS[:1]),
    Period("çapraz sınama", D0 + DAY, D0 + 2.5 * DAY, PAIRS[1:]),
    Period("görülmemiş", D0 + 3 * DAY, D0 + 4 * DAY, PAIRS),
)
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
DOWNLOADED = datetime(2026, 11, 12, 1, 0, tzinfo=UTC)


def _ms(moment: datetime) -> int:
    return int((moment - datetime(1970, 1, 1, tzinfo=UTC)) / timedelta(milliseconds=1))


def _candles(step: timedelta, seed: int, skip: set[int]) -> list[list[object]]:
    rows: list[list[object]] = []
    price = 100.0
    count = int(4 * DAY / step)
    for index in range(count):
        wave = 100 * (1 + 0.04 * math.sin(2 * math.pi * index / (7 + seed)))
        close = wave * (1 + 0.003 * math.sin(index * (seed + 1.7)))
        high, low = max(price, close) * 1.002, min(price, close) * 0.998
        volume = 90.0 if index % 97 == 50 else 1.0 + index % 4
        if index not in skip:
            moment = _ms(D0 + index * step)
            rows.append(
                [moment, *(f"{value:.8f}" for value in (price, high, low, close)), f"{volume:.2f}"]
            )
        price = close
    return rows


def write_data(
    path: Path,
    interval: str,
    *,
    version: int = 2,
    pairs: tuple[str, ...] = PAIRS,
    skip: Callable[[str], set[int]] = lambda _: set(),
) -> Path:
    header = {
        "format": "crytobot-history",
        "version": version,
        "exchange": "binance",
        "candle_interval": interval,
        "start": D0.isoformat(),
        "end": (D0 + 4 * DAY).isoformat(),
        "warmup_start": D0.isoformat(),
        "downloaded_at": DOWNLOADED.isoformat(),
        "pairs": [
            {
                "pair": pair,
                "market_id": pair.replace("/", ""),
                "tick": "0.00000001",
                "amount_step": "0.001",
                "min_amount": "0.001",
                "min_notional": "5",
            }
            for pair in pairs
        ],
    }
    lines: list[object] = [header]
    counts: dict[str, int] = {}
    for seed, pair in enumerate(pairs):
        rows = _candles(STEPS[interval], seed, skip(pair))
        counts[pair] = len(rows)
        lines += [[pair, *(row if version == 2 else row[:5])] for row in rows]
    lines.append({"complete": True, "counts": counts})
    text = "".join(json.dumps(line, separators=(",", ":")) + "\n" for line in lines)
    path.write_bytes(text.encode("utf-8"))
    return path


def table(folder: Path, **changes: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        **{f"data_{interval}": str(folder / f"data-{interval}.jsonl") for interval in STEPS},
        "fee": "0.001",
        "slippage": "0.001",
        "spread": "0.0005",
        "report_path": str(folder / "rapor-1.txt"),
        "settings_path": str(folder / "ayar-seti.json"),
        "records_path": str(folder / "kayit-1.jsonl"),
        "final_report_path": str(folder / "rapor-son.txt"),
        "final_records_path": str(folder / "kayit-son.jsonl"),
    }
    values.update(changes)
    return {key: value for key, value in values.items() if value is not None}


def config_of(folder: Path, **changes: object) -> CalibrationConfig:
    result = load_calibration_config({"calibration": table(folder, **changes)})
    assert result.config is not None, result.message
    return result.config


def digest(path: str) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def read_bytes(path: str) -> bytes | None:
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def fixed(moment: datetime) -> Callable[[], datetime]:
    return lambda: moment


class Console(list[str]):
    def __call__(self, text: str) -> None:
        self.append(text)


def parts(
    console: Console, clock: Callable[[], datetime] = lambda: NOW, **changes: Any
) -> CalibrationParts:
    made = CalibrationParts(
        read_history,
        digest,
        read_bytes,
        report_exists,
        write_report,
        console,
        StopRequest(),
        clock,
    )
    return replace(made, **changes)


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    for interval in STEPS:
        write_data(tmp_path / f"data-{interval}.jsonl", interval)
    return tmp_path


def leftovers(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir() if not path.name.startswith("data-"))


# --- the settings -------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("x", "ayar geçersiz: calibration"),
        ({}, "ayar eksik: calibration"),
        ({"calibration": 3}, "ayar geçersiz: calibration"),
    ],
)
def test_section_missing_or_not_a_table(document: object, message: str) -> None:
    assert load_calibration_config(document).message == message


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"data_1h": None}, "ayar eksik: calibration.data_1h"),
        ({"final_records_path": None}, "ayar eksik: calibration.final_records_path"),
        ({"data_4h": ""}, "ayar geçersiz: calibration.data_4h"),
        ({"data_4h": 4}, "ayar geçersiz: calibration.data_4h"),
        ({"report_path": "same"}, "ayar geçersiz: calibration.settings_path"),
        ({"fee": 0.001}, "ayar geçersiz: calibration.fee"),
        ({"fee": "1"}, "ayar geçersiz: calibration.fee"),
        ({"spread": "-0.1"}, "ayar geçersiz: calibration.spread"),
        ({"fee": "0.6", "slippage": "0.4"}, "ayar geçersiz: calibration.slippage"),
        ({"extra": 1}, "bilinmeyen ayar: calibration.extra"),
        ({"approved_by": "Galip"}, "ayar eksik: calibration.settings_sha256"),
        (
            {
                "settings_sha256": "x",
                "approved_by": "G",
                "approved_at": "2026-11-15T12:00:00+00:00",
            },
            "ayar geçersiz: calibration.settings_sha256",
        ),
        (
            {
                "settings_sha256": "a" * 64,
                "approved_by": " ",
                "approved_at": "2026-11-15T12:00:00+00:00",
            },
            "ayar geçersiz: calibration.approved_by",
        ),
        (
            {"settings_sha256": "a" * 64, "approved_by": "G", "approved_at": "2026-11-15T12:00:00"},
            "ayar geçersiz: calibration.approved_at",
        ),
        (
            {"settings_sha256": "a" * 64, "approved_by": "G", "approved_at": "dün"},
            "ayar geçersiz: calibration.approved_at",
        ),
    ],
)
def test_settings_refused_by_name(tmp_path: Path, changes: dict[str, object], message: str) -> None:
    if changes.get("report_path") == "same":
        changes = {"report_path": "x.txt", "settings_path": "x.txt"}
    result = load_calibration_config({"calibration": table(tmp_path, **changes)})
    assert (result.config, result.message) == (None, message)


def test_settings_accept_approval(tmp_path: Path) -> None:
    config = config_of(
        tmp_path,
        settings_sha256="AB" * 32,
        approved_by=" Galip ",
        approved_at="2026-11-15T15:00:00+03:00",
    )
    assert config.approval is not None
    assert config.approval.settings_sha256 == "ab" * 32
    assert config.approval.approved_by == "Galip"
    assert config.approval.approved_at == NOW
    assert config.costs.spread == Decimal("0.0005")


# --- data checks (AC-7) ---------------------------------------------------------------------------
def _stage(folder: Path, **changes: object) -> tuple[CalibrationOutcome, Console]:
    console = Console()
    exit_ = run_calibration(config_of(folder, **changes), parts(console), periods=PERIODS)
    return exit_.outcome, console


def test_refused_pair_without_candles_in_period(folder: Path) -> None:
    """AC-7: bir çiftin bir aralıkta bir dönemde hiç mumu yoksa ölçüm yok, ret, dosya yok."""
    unseen = set(range(int(3 * DAY / STEPS["4h"]), int(4 * DAY / STEPS["4h"])))
    write_data(
        folder / "data-4h.jsonl", "4h", skip=lambda pair: unseen if pair == "SOL/USDT" else set()
    )
    outcome, console = _stage(folder)
    assert outcome is CalibrationOutcome.REFUSED
    assert console[-1] == "kalibrasyon reddedildi: veri eksik: SOL/USDT 4h görülmemiş"
    assert leftovers(folder) == []
    assert not any("aralık" in line for line in console)  # no measurement started


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda f: (f / "data-1h.jsonl").unlink(), "veri dosyası yok: "),
        (lambda f: (f / "data-1h.jsonl").write_text("{", encoding="utf-8"), "veri dosyası bozuk"),
        (
            lambda f: write_data(f / "data-1h.jsonl", "4h"),
            "veri dosyası uyumsuz: mum aralığı 1h değil",
        ),
        (lambda f: write_data(f / "data-1h.jsonl", "1h", version=1), "hacim yok (sürüm 1)"),
        (lambda f: write_data(f / "data-1h.jsonl", "1h", pairs=PAIRS[:4]), "çift yok (XRP/USDT)"),
    ],
)
def test_refused_data_named(folder: Path, make: Callable[[Path], object], message: str) -> None:
    make(folder)
    outcome, console = _stage(folder)
    assert outcome is CalibrationOutcome.REFUSED
    assert message in console[-1]
    assert leftovers(folder) == []


def test_refused_data_not_covering_the_periods(folder: Path) -> None:
    later = (PERIODS[0], PERIODS[1], replace(PERIODS[2], end=D0 + 5 * DAY))
    console = Console()
    exit_ = run_calibration(config_of(folder), parts(console), periods=later)
    assert exit_.outcome is CalibrationOutcome.REFUSED
    assert "dönemleri kapsamıyor" in console[-1]


def test_refused_when_an_output_exists(folder: Path) -> None:
    (folder / "kayit-1.jsonl").write_text("eski", encoding="utf-8")
    outcome, console = _stage(folder)
    assert outcome is CalibrationOutcome.REFUSED
    assert console[-1].endswith("kayit-1.jsonl; üzerine yazılmaz")
    assert leftovers(folder) == ["kayit-1.jsonl"]


def test_refused_when_digest_fails(folder: Path) -> None:
    console = Console()
    exit_ = run_calibration(
        config_of(folder), parts(console, digest=lambda _: None), periods=PERIODS
    )
    assert exit_.outcome is CalibrationOutcome.REFUSED
    assert "veri dosyası okunamıyor" in console[-1]


# --- stage 1 and the final run --------------------------------------------------------------------
@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Console]:
    """1. aşama modül başına bir kez; testler kopyasıyla çalışır."""
    where = tmp_path_factory.mktemp("stage-one")
    for interval in STEPS:
        write_data(where / f"data-{interval}.jsonl", interval)
    console = Console()
    exit_ = run_calibration(config_of(where), parts(console), periods=PERIODS)
    assert exit_.outcome is CalibrationOutcome.COMPLETED, console
    return where, console


@pytest.fixture
def stage_one(prepared: tuple[Path, Console], tmp_path: Path) -> tuple[Path, Console]:
    where, console = prepared
    for path in where.iterdir():
        (tmp_path / path.name).write_bytes(path.read_bytes())
    return tmp_path, console


def test_stage_one_writes_settings_report_and_records(stage_one: tuple[Path, Console]) -> None:
    folder, console = stage_one
    assert leftovers(folder) == ["ayar-seti.json", "kayit-1.jsonl", "rapor-1.txt"]
    sha = hashlib.sha256((folder / "ayar-seti.json").read_bytes()).hexdigest()
    assert any(
        line.startswith(f"kalibrasyon ayar seti parmak izi: {sha} (")
        and line.endswith("ayar-seti.json)")
        for line in console
    )
    report = (folder / "rapor-1.txt").read_text(encoding="utf-8")
    assert f"(ayar seti parmak izi: {sha})" in report.splitlines()[1]
    assert "görülmemiş birleşik" not in report
    assert [line for line in console if line.startswith("kalibrasyon aralık")] == [
        f"kalibrasyon aralık {interval}" for interval in STEPS
    ]


def _approve(
    folder: Path, sha: str | None = None, at: str = "2026-11-15T12:00:00+00:00"
) -> CalibrationConfig:
    real = hashlib.sha256((folder / "ayar-seti.json").read_bytes()).hexdigest()
    return config_of(folder, settings_sha256=sha or real, approved_by="Galip", approved_at=at)


def test_final_measures_three_periods_and_verdicts(stage_one: tuple[Path, Console]) -> None:
    folder, _ = stage_one
    console = Console()
    exit_ = run_calibration_final(
        _approve(folder), parts(console, clock=lambda: NOW), periods=PERIODS
    )
    assert exit_.outcome is CalibrationOutcome.COMPLETED, console
    report = (folder / "rapor-son.txt").read_text(encoding="utf-8")
    assert "ayar seti onayı: Galip, 2026-11-15T12:00:00+00:00" in report
    assert sum(line.startswith("hüküm: ") for line in report.splitlines()) == 40
    assert any(line.startswith("kalibrasyon hüküm: ") for line in console)
    assert (folder / "kayit-son.jsonl").exists()


def test_final_refused_missing_settings_file(stage_one: tuple[Path, Console]) -> None:
    folder, _ = stage_one
    config = _approve(folder)
    (folder / "ayar-seti.json").unlink()
    console = Console()
    exit_ = run_calibration_final(config, parts(console), periods=PERIODS)
    assert exit_.outcome is CalibrationOutcome.REFUSED
    assert console[-1].startswith("kalibrasyon reddedildi: ayar seti dosyası yok: ")
    assert not (folder / "rapor-son.txt").exists()


def test_final_refused_without_approval(stage_one: tuple[Path, Console]) -> None:
    folder, _ = stage_one
    console = Console()
    exit_ = run_calibration_final(config_of(folder), parts(console), periods=PERIODS)
    assert exit_.outcome is CalibrationOutcome.REFUSED
    assert console[-1] == "kalibrasyon reddedildi: ayar eksik: calibration.settings_sha256"


def test_final_refused_fingerprint_mismatch(stage_one: tuple[Path, Console]) -> None:
    folder, _ = stage_one
    console = Console()
    exit_ = run_calibration_final(_approve(folder, sha="0" * 64), parts(console), periods=PERIODS)
    assert exit_.outcome is CalibrationOutcome.REFUSED
    assert "ayar seti parmak izi onayla tutmuyor" in console[-1]
    assert not (folder / "rapor-son.txt").exists() and not (folder / "kayit-son.jsonl").exists()


def test_final_refused_approval_moment(stage_one: tuple[Path, Console]) -> None:
    folder, _ = stage_one
    for at in ("2026-11-15T11:59:59+00:00", "2026-11-15T12:00:01+00:00"):
        console = Console()
        # the settings were generated at NOW; the clock reads NOW: before and after are refused
        exit_ = run_calibration_final(_approve(folder, at=at), parts(console), periods=PERIODS)
        assert exit_.outcome is CalibrationOutcome.REFUSED
        assert "onay anı geçersiz" in console[-1]
    assert not (folder / "rapor-son.txt").exists()


def test_final_refused_changed_costs_or_data(stage_one: tuple[Path, Console]) -> None:
    folder, _ = stage_one
    console = Console()
    changed = replace(_approve(folder), costs=replace(_approve(folder).costs, spread=Decimal(0)))
    assert run_calibration_final(changed, parts(console), periods=PERIODS).outcome is (
        CalibrationOutcome.REFUSED
    )
    assert "maliyet ayar setinden farklı" in console[-1]
    write_data(
        folder / "data-1d.jsonl", "1d", skip=lambda pair: {0} if pair == "BTC/USDT" else set()
    )
    console = Console()
    assert run_calibration_final(_approve(folder), parts(console), periods=PERIODS).outcome is (
        CalibrationOutcome.REFUSED
    )
    assert "veri dosyası ayar setinden farklı: 1d" in console[-1]


def test_final_refused_corrupt_settings(stage_one: tuple[Path, Console]) -> None:
    folder, _ = stage_one
    (folder / "ayar-seti.json").write_bytes(b"\xff{")
    sha = hashlib.sha256(b"\xff{").hexdigest()
    console = Console()
    exit_ = run_calibration_final(_approve(folder, sha=sha), parts(console), periods=PERIODS)
    assert exit_.outcome is CalibrationOutcome.REFUSED
    assert "ayar seti dosyası bozuk (json)" in console[-1]


def test_two_runs_byte_identical_except_generated_at(
    folder: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """AC-9: aynı girdilerle iki koşu: rapor ve kayıtlar üretim anı satırı dışında bayt eşit."""
    other = tmp_path_factory.mktemp("second")
    for interval in STEPS:
        (other / f"data-{interval}.jsonl").write_bytes(
            (folder / f"data-{interval}.jsonl").read_bytes()
        )
    later = NOW + timedelta(hours=2)
    results = []
    for where, moment in ((folder, NOW), (other, later)):
        console = Console()
        config = replace(config_of(where), data=config_of(folder).data)  # the very same data files
        exit_ = run_calibration(config, parts(console, clock=fixed(moment)), periods=PERIODS)
        assert exit_.outcome is CalibrationOutcome.COMPLETED
        results.append(
            (
                (where / "rapor-1.txt").read_text(encoding="utf-8").splitlines(),
                (where / "kayit-1.jsonl").read_text(encoding="utf-8").splitlines(),
            )
        )
    (report_a, records_a), (report_b, records_b) = results
    assert [i for i, (a, b) in enumerate(zip(report_a, report_b, strict=True)) if a != b] == [1]
    assert report_a[1].startswith("üretim anı: ") and report_b[1].startswith("üretim anı: ")
    assert records_a[1:] == records_b[1:] and records_a[0] != records_b[0]


# --- stop, write failures, unexpected errors ------------------------------------------------------
def test_stop_request_stops_before_the_next_interval(folder: Path) -> None:
    console = Console()
    made = parts(console)
    made.stop.request()
    exit_ = run_calibration(config_of(folder), made, periods=PERIODS)
    assert exit_.outcome is CalibrationOutcome.STOPPED
    assert console[-1] == "kalibrasyon durdu: durdurma isteği"
    assert leftovers(folder) == []


def test_write_failure_named(folder: Path) -> None:
    console = Console()
    exit_ = run_calibration(
        config_of(folder), parts(console, write_file=lambda *_: False), periods=PERIODS
    )
    assert exit_.outcome is CalibrationOutcome.NOT_WRITTEN
    assert console[-1].startswith("kalibrasyon durdu: ayar seti yazılamadı: ")


def test_unexpected_error_named_by_type(folder: Path) -> None:
    def broken(_: str) -> Any:
        raise KeyError("sır")

    console = Console()
    exit_ = run_calibration(config_of(folder), parts(console, read=broken), periods=PERIODS)
    assert exit_.outcome is CalibrationOutcome.STOPPED
    assert console[-1] == "kalibrasyon durdu: beklenmeyen hata: KeyError"
