"""AC-10: doğrudan bağımlılıklar yalnızca onaylı geliştirme araçlarıdır (spec 0001, R-8)."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPROVED_DEV_TOOLS = {
    "hypothesis",
    "import-linter",
    "mypy",
    "pytest",
    "pytest-cov",
    "pytest-socket",
    "ruff",
}


def requirement_name(requirement: str) -> str:
    return re.split(r"[\s<>=!~;\[]", requirement, maxsplit=1)[0].lower().replace("_", "-")


def test_only_approved_dev_dependencies() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dependencies"] == []
    groups = pyproject["dependency-groups"]
    assert set(groups) == {"dev"}
    assert {requirement_name(r) for r in groups["dev"]} == APPROVED_DEV_TOOLS
