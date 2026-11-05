"""AC-10: doğrudan bağımlılıklar yalnızca onaylı araçlar ve runtime'da ccxt'dir.

Kaynak: spec 0001, R-8; spec 0018 (Supersedes: 0001/AC-10).
"""

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
APPROVED_RUNTIME = ["ccxt"]


def requirement_name(requirement: str) -> str:
    return re.split(r"[\s<>=!~;\[]", requirement, maxsplit=1)[0].lower().replace("_", "-")


def test_only_approved_dev_dependencies() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "optional-dependencies" not in pyproject["project"]
    groups = pyproject["dependency-groups"]
    assert set(groups) == {"dev"}
    assert {requirement_name(r) for r in groups["dev"]} == APPROVED_DEV_TOOLS


def test_lockfile_direct_dependencies_are_only_approved_dev_tools() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    (project,) = [p for p in lock["package"] if p["name"] == "crytobot"]
    assert "optional-dependencies" not in project
    assert set(project["dev-dependencies"]) == {"dev"}
    assert {d["name"] for d in project["dev-dependencies"]["dev"]} == APPROVED_DEV_TOOLS


def test_runtime_dependency_is_only_ccxt() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = sorted(requirement_name(r) for r in pyproject["project"]["dependencies"])
    assert declared == APPROVED_RUNTIME

    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    (project,) = [p for p in lock["package"] if p["name"] == "crytobot"]
    locked = sorted(d["name"] for d in project.get("dependencies", []))
    assert locked == APPROVED_RUNTIME


def test_lockfile_pins_every_package_with_hashes() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    registry = [p for p in lock["package"] if "registry" in p["source"]]
    assert "ccxt" in {p["name"] for p in registry}
    for package in registry:
        files = [*package.get("wheels", []), *filter(None, [package.get("sdist")])]
        assert package["version"], package["name"]
        assert files, package["name"]
        assert all(f["hash"].startswith("sha256:") for f in files), package["name"]
