"""Spec 0045 AC-10, R-11: kalibrasyon botun dosyalarına dokunmaz; yalnız kendi çıktılarını yazar.

Bot gibi bir çalışma dizini kurulur (çalışan ayar, depo, kökteki veri ve rapor dosyaları); iki
aşama koşulur; öncesi/sonrası SHA-256 ve dizindeki dosya kümesi karşılaştırılır.
"""

import hashlib
from pathlib import Path

from crytobot.app import CalibrationOutcome, run_calibration, run_calibration_final
from tests.app.test_calibration import (
    NOW,
    PERIODS,
    STEPS,
    Console,
    config_of,
    parts,
    write_data,
)

BOT_FILES = {
    "crytobot.toml": b'[bot]\nmode = "paper"\n',
    "bot.db": b"SQLite format 3\x00 not really",
    "crytobot-history-2026.jsonl": b'{"format":"crytobot-history"}\n',
    "crytobot-history-2026-4h.jsonl": b"{}\n",
    "crytobot-backtest-2026.txt": b"rapor\n",
    "crytobot-backtest-2026-4h.txt": b"rapor 4h\n",
}


def digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_no_bot_files_touched(tmp_path: Path) -> None:
    for name, content in BOT_FILES.items():
        (tmp_path / name).write_bytes(content)
    work = tmp_path / "eval"
    work.mkdir()
    for interval in STEPS:
        write_data(work / f"data-{interval}.jsonl", interval)
    before = digests(tmp_path)

    console = Console()
    assert run_calibration(config_of(work), parts(console), periods=PERIODS).outcome is (
        CalibrationOutcome.COMPLETED
    )
    settings = hashlib.sha256((work / "ayar-seti.json").read_bytes()).hexdigest()
    approved = config_of(
        work, settings_sha256=settings, approved_by="Galip", approved_at=NOW.isoformat()
    )
    assert run_calibration_final(approved, parts(console), periods=PERIODS).outcome is (
        CalibrationOutcome.COMPLETED
    )

    after = digests(tmp_path)
    assert {name: after[name] for name in before} == before  # nothing changed
    assert sorted(set(after) - set(before)) == [
        "eval/ayar-seti.json",
        "eval/kayit-1.jsonl",
        "eval/kayit-son.jsonl",
        "eval/rapor-1.txt",
        "eval/rapor-son.txt",
    ]
