"""AC-4: modül düzeni docs/architecture.md tablosuyla birebir aynıdır."""

import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "src" / "crytobot"
MODULE_ROW = re.compile(r"^\|\s*`(?P<name>[a-z_]+)`\s*\|")


def documented_modules() -> set[str]:
    text = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    section = text.split("## Modules / components and ownership", 1)[1].split("\n## ", 1)[0]
    return {m["name"] for line in section.splitlines() if (m := MODULE_ROW.match(line))}


def package_modules() -> set[str]:
    return {p.parent.name for p in PACKAGE_DIR.glob("*/__init__.py")}


def test_modules_match_architecture_table() -> None:
    documented = documented_modules()
    assert len(documented) == 14
    assert package_modules() == documented


@pytest.mark.parametrize("name", sorted(documented_modules()))
def test_every_module_importable_with_public_interface(name: str) -> None:
    module = importlib.import_module(f"crytobot.{name}")
    assert isinstance(module.__all__, list)
    assert module.__doc__ and module.__doc__.strip()
