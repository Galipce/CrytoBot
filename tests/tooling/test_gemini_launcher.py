"""Spec 0027 AC-5, AC-6: scripts/gemini-devam.ps1 agy'yi bulur ve Gemini'yi depo kökünde açar.

Başlatıcı ``-Prova`` ile çalışır: Gemini açılmaz, bulunan yol, çalışma klasörü ve argümanlar
yazılır. Kabuk Windows PowerShell (burada) ya da pwsh'tir (CI); ikisi de yoksa test başarısız olur.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "gemini-devam.ps1"
TIMEOUT_S = 120
SKIP_PERMISSIONS = ("--dangerously-skip-permissions", "--mode", "--sandbox")


def _powershell() -> str:
    shell = shutil.which("powershell") or shutil.which("pwsh")
    assert shell, "Windows PowerShell or pwsh is required for the launcher tests"
    return shell


def _launch(
    tmp_path: Path, path_dirs: list[Path], profile: Path
) -> subprocess.CompletedProcess[str]:
    """Başlatıcıyı depo dışından, yalnızca verilen PATH ve kullanıcı klasörüyle çalıştırır."""
    system = [Path(os.environ["SYSTEMROOT"]) / "System32"] if sys.platform == "win32" else []
    env = {
        **os.environ,
        "PATH": os.pathsep.join(str(p) for p in [*path_dirs, *system]),
        "USERPROFILE": str(profile),
    }
    return subprocess.run(
        [
            _powershell(),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-Prova",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT_S,
        check=False,
    )


def _fake_agy(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    agy = directory / name
    agy.write_bytes(b"")
    agy.chmod(0o755)
    return agy


def _field(stdout: str, label: str) -> str:
    lines = [line[len(label) :] for line in stdout.splitlines() if line.startswith(label)]
    assert len(lines) == 1, stdout
    return lines[0]


@pytest.fixture
def empty_path(tmp_path: Path) -> Path:
    directory = tmp_path / "empty-path"
    directory.mkdir()
    return directory


def test_finds_fallback_when_not_on_path(tmp_path: Path, empty_path: Path) -> None:
    """AC-5: agy not on PATH → %USERPROFILE%\\.gemini\\bin\\agy.exe, opened at the repo root."""
    profile = tmp_path / "profile"
    agy = _fake_agy(profile / ".gemini" / "bin", "agy.exe")

    result = _launch(tmp_path, [empty_path], profile)

    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(_field(result.stdout, "agy: ")) == agy
    assert Path(_field(result.stdout, "Çalışma klasörü: ")).resolve() == ROOT


def test_prefers_path(tmp_path: Path) -> None:
    """Req. 5: PATH first, the fallback only after it."""
    profile = tmp_path / "profile"
    _fake_agy(profile / ".gemini" / "bin", "agy.exe")
    on_path = _fake_agy(tmp_path / "bin", "agy.exe" if sys.platform == "win32" else "agy")

    result = _launch(tmp_path, [tmp_path / "bin"], profile)

    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(_field(result.stdout, "agy: ")) == on_path


def test_arguments_open_interactively_in_default_permission_mode(
    tmp_path: Path, empty_path: Path
) -> None:
    """AC-5 / Req. 5, 6: one -i opening instruction, no option that skips permissions."""
    profile = tmp_path / "profile"
    _fake_agy(profile / ".gemini" / "bin", "agy.exe")

    result = _launch(tmp_path, [empty_path], profile)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _field(result.stdout, "Argüman 1: ") == "-i"
    instruction = _field(result.stdout, "Argüman 2: ")
    assert "Argüman 3: " not in result.stdout
    for option in SKIP_PERMISSIONS:
        assert option not in result.stdout
    assert '"' not in instruction
    for needed in (
        "AGENTS.md",
        "specs/active/",
        "Status",
        "Approved by / on",
        "bitmemiş ilk adım",
        "git status",
        ".claude/handoff.local.md",
        "eski",
        "aktif iş yok",
        "/analyze",
        "/anew-plan",
        "Onayım gelene kadar",
    ):
        assert needed in instruction, needed


def test_missing_agy_stops_with_turkish_message(tmp_path: Path, empty_path: Path) -> None:
    """AC-6: neither place → Gemini is not opened, both places and a hint are named, exit ≠ 0."""
    profile = tmp_path / "profile"
    profile.mkdir()

    result = _launch(tmp_path, [empty_path], profile)

    assert result.returncode != 0
    assert "agy: " not in result.stdout
    assert "bulunamadı; Gemini açılmadı" in result.stderr
    assert "1. PATH (agy komutu)" in result.stderr
    assert f"2. {profile / '.gemini' / 'bin' / 'agy.exe'}" in result.stderr
    assert "Kurulum ipucu:" in result.stderr


def test_script_starts_with_utf8_bom() -> None:
    """Windows PowerShell 5.1 reads a BOM-less script as ANSI and garbles the Turkish text."""
    assert SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf")
