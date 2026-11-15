"""Spec 0045 giriş noktası `python -m crytobot calibrate [--final]` (AC-7, R-11; plan Risk 3).

`run` gerçek kodu koşar: gerçek ayar okuması, `load_calibration_config`, veri okuyucu ve dosya
yazıcısı. Spec'in dönemleri sabittir (giriş noktası dönem vermez): burada yalnız ölçüme varmayan
retler sınanır; ölçümün kendisi `tests/app/test_calibration.py`'dedir.
"""

import io
from pathlib import Path

from crytobot.__main__ import COMMANDS, EXIT_REFUSED, USAGE, run

INTERVALS = ("15m", "30m", "1h", "4h", "1d")


def write_config(root: Path, *extra: str) -> Path:
    lines = ["[calibration]"]
    lines += [f'data_{i} = "{(root / f"data-{i}.jsonl").as_posix()}"' for i in INTERVALS]
    lines += ['fee = "0.001"', 'slippage = "0.001"', 'spread = "0.0005"']
    for key, name in (
        ("report_path", "rapor-1.txt"),
        ("settings_path", "ayar-seti.json"),
        ("records_path", "kayit-1.jsonl"),
        ("final_report_path", "rapor-son.txt"),
        ("final_records_path", "kayit-son.jsonl"),
    ):
        lines.append(f'{key} = "{(root / name).as_posix()}"')
    lines += list(extra)
    path = root / "crytobot.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def call(argv: list[str], config: Path) -> tuple[int, str]:
    console = io.StringIO()
    code = run(argv, config_path=config, console=console)
    return code, console.getvalue()


def test_calibrate_commands_are_known() -> None:
    assert ["calibrate"] in COMMANDS and ["calibrate", "--final"] in COMMANDS
    assert "calibrate" in USAGE


def test_final_refused_no_report_exit_1(tmp_path: Path) -> None:
    """AC-7: ayar seti dosyası yoksa ölçüm yok, rapor yok, çıkış 1."""
    config = write_config(
        tmp_path,
        f'settings_sha256 = "{"a" * 64}"',
        'approved_by = "Galip"',
        'approved_at = "2026-11-15T12:00:00+00:00"',
    )
    code, output = call(["calibrate", "--final"], config)
    assert code == EXIT_REFUSED
    assert "kalibrasyon reddedildi: ayar seti dosyası yok: " in output
    assert sorted(path.name for path in tmp_path.iterdir()) == ["crytobot.toml"]


def test_final_without_approval_refused(tmp_path: Path) -> None:
    code, output = call(["calibrate", "--final"], write_config(tmp_path))
    assert code == EXIT_REFUSED
    assert "ayar eksik: calibration.settings_sha256" in output


def test_stage_one_refused_missing_data_exit_1(tmp_path: Path) -> None:
    code, output = call(["calibrate"], write_config(tmp_path))
    assert code == EXIT_REFUSED
    assert "kalibrasyon reddedildi: veri dosyası yok: " in output
    assert sorted(path.name for path in tmp_path.iterdir()) == ["crytobot.toml"]


def test_config_refused_by_name(tmp_path: Path) -> None:
    config = tmp_path / "crytobot.toml"
    config.write_text("[calibration]\n", encoding="utf-8")
    code, output = call(["calibrate"], config)
    assert code == EXIT_REFUSED
    assert output.strip() == "kalibrasyon reddedildi: ayar eksik: calibration.data_15m"
    code, output = call(["calibrate"], tmp_path / "yok.toml")
    assert code == EXIT_REFUSED and "ayar dosyası yok" in output


def test_two_spellings_of_one_file_refused(tmp_path: Path) -> None:
    """Yollar metin olarak farklı ama aynı dosyayı adlandırıyorsa ret (giriş noktası çözer)."""
    config = write_config(tmp_path)
    text = config.read_text(encoding="utf-8")
    same = (tmp_path / "x" / ".." / "rapor-1.txt").as_posix()
    config.write_text(
        text.replace(
            f'records_path = "{(tmp_path / "kayit-1.jsonl").as_posix()}"',
            f'records_path = "{same}"',
        ),
        encoding="utf-8",
    )
    code, output = call(["calibrate"], config)
    assert code == EXIT_REFUSED
    assert "aynı dosyayı adlandıran yol" in output
