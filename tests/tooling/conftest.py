"""Araç öz-testleri için ortak düzen: projenin geçici kopyası, check.conf adımlarını çalıştırma.

Adım komutları scripts/check.conf'tan okunur (tek kaynak); ``uv run --locked`` öneki atılır ve
araçlar bu sanal ortamın çalıştırılabilirleriyle koşar — kopyada uv yeni ortam (ağ) kurmaz.
"""

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UV_PREFIX = "uv run --locked "
STEP_LINE = re.compile(r"^(?P<name>[^#:]+?)(?:\s*\[fast\])?\s*:\s*(?P<cmd>.+)$")
TIMEOUT_S = 180
SENSITIVE_MODULES = ("risk", "execution", "portfolio")


def check_step(name: str) -> str:
    """scripts/check.conf'taki adımın komutu, ``uv run --locked`` öneki olmadan."""
    for line in (ROOT / "scripts" / "check.conf").read_text(encoding="utf-8").splitlines():
        match = STEP_LINE.match(line.strip())
        if match and match["name"].strip() == name:
            return match["cmd"].replace(UV_PREFIX, "")
    raise LookupError(f"check.conf has no step {name!r}")


@dataclass
class Project:
    root: Path

    def write(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def run_step(self, name: str) -> subprocess.CompletedProcess[str]:
        return self.run(check_step(name))

    def run(self, command: str) -> subprocess.CompletedProcess[str]:
        sh = shutil.which("sh")
        assert sh, "sh is required (Git Bash on Windows)"
        return subprocess.run(
            [sh, "-c", command],
            cwd=self.root,
            env=_isolated_env(self.root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_S,
            check=False,
        )


def _isolated_env(project_root: Path) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("COV_CORE_", "COVERAGE_", "PYTEST_")) and k != "PYTHONPATH"
    }
    venv_bin = str(Path(sys.executable).parent)
    env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")
    # the copy's src must win over the editable install of the real src
    env["PYTHONPATH"] = str(project_root / "src")
    return env


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """pyproject + src + tools'un geçici kopyası, hassas modül testleri ve tek bir geçen test.

    Hassas modüllerin testleri kopyalanır: kopyadaki gerçek kod coverage kapısını kendi
    testleriyle geçer.
    """
    shutil.copy2(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(ROOT / "src", tmp_path / "src", ignore=ignore)
    shutil.copytree(ROOT / "tools", tmp_path / "tools", ignore=ignore)
    (tmp_path / "tests").mkdir()
    for name in ("__init__.py", "conftest.py"):
        shutil.copy2(ROOT / "tests" / name, tmp_path / "tests" / name)
    for module in SENSITIVE_MODULES:
        if (ROOT / "tests" / module).is_dir():
            shutil.copytree(ROOT / "tests" / module, tmp_path / "tests" / module, ignore=ignore)
    copy = Project(tmp_path)
    copy.write("tests/test_ok.py", "def test_ok() -> None:\n    assert True\n")
    return copy
