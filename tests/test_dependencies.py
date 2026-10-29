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
    assert "optional-dependencies" not in pyproject["project"]
    groups = pyproject["dependency-groups"]
    assert set(groups) == {"dev"}
    assert {requirement_name(r) for r in groups["dev"]} == APPROVED_DEV_TOOLS


def test_lockfile_direct_dependencies_are_only_approved_dev_tools() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    (project,) = [p for p in lock["package"] if p["name"] == "crytobot"]
    assert project.get("dependencies", []) == []
    assert "optional-dependencies" not in project
    assert set(project["dev-dependencies"]) == {"dev"}
    assert {d["name"] for d in project["dev-dependencies"]["dev"]} == APPROVED_DEV_TOOLS
