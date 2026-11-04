"""Spec 0014 AC-11: aynı girdi aynı sonuç; girdi değişmez; `analysis` saf hesap sınırında kalır.

Plan 0014, Risk 8: `boundaries` adımı (R-3c) yalnız proje modüllerini yasaklar. "I/O kütüphanesi
yok", saat ve global durum kuralları burada, kaynak kod üzerinde izin listesiyle sınanır.
"""

import ast
from pathlib import Path

import pytest
from hypothesis import given

from crytobot import analysis
from crytobot.analysis import Candle
from tests.analysis.helpers import INDICATOR_IDS, INDICATORS, Indicator, candle_series

ANALYSIS_DIR = Path(analysis.__file__).parent
ALLOWED_MODULES = {
    "__future__",
    "collections.abc",
    "dataclasses",
    "datetime",
    "enum",
    "math",
    "statistics",
    "typing",
    "crytobot.analysis",
}
CLOCK_CALLS = {"now", "utcnow", "today"}
FORBIDDEN_BUILTINS = {"open", "__import__"}
MUTABLE_VALUES = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)


def _allowed_module(name: str) -> bool:
    return any(name == allowed or name.startswith(f"{allowed}.") for allowed in ALLOWED_MODULES)


def forbidden_imports(source: str) -> list[str]:
    """İzin listesi dışı importlar; fonksiyon içindekiler dahil."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [f"import {a.name}" for a in node.names if not _allowed_module(a.name)]
        elif isinstance(node, ast.ImportFrom) and (
            node.level or node.module is None or not _allowed_module(node.module)
        ):
            found.append(f"from {node.module} import")
    return found


def forbidden_state(source: str) -> list[str]:
    """Saat ve dosya çağrıları, `global` deyimi, modül düzeyinde değişebilir değer."""
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            found.append("global")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr in CLOCK_CALLS:
                found.append(f"{node.func.attr}()")
            elif isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_BUILTINS:
                found.append(f"{node.func.id}()")
    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign) and isinstance(node.value, MUTABLE_VALUES):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [target.id for target in targets if isinstance(target, ast.Name)]
            if names != ["__all__"]:
                found.append(f"{names} = mutable")
    return found


def analysis_sources() -> list[Path]:
    sources = sorted(ANALYSIS_DIR.rglob("*.py"))
    assert {path.name for path in sources} >= {"__init__.py", "_candles.py", "_indicators.py"}
    return sources


def test_analysis_imports_only_allowed_modules() -> None:
    for path in analysis_sources():
        assert forbidden_imports(path.read_text(encoding="utf-8")) == [], path.name


def test_no_clock_or_global_state() -> None:
    for path in analysis_sources():
        assert forbidden_state(path.read_text(encoding="utf-8")) == [], path.name


@pytest.mark.parametrize(
    "source",
    [
        "import socket",
        "import os.path",
        "import pandas",
        "import collections",
        "from time import time",
        "from crytobot.market_data import x",
        "from . import x",
        "def f():\n    import sqlite3",
    ],
)
def test_import_guard_catches_forbidden_code(source: str) -> None:
    assert forbidden_imports(source) != []


@pytest.mark.parametrize(
    "source",
    [
        "datetime.now()",
        "datetime.datetime.utcnow()",
        "date.today()",
        "open('x')",
        "__import__('socket')",
        "def f():\n    global x",
        "CACHE = {}",
        "seen: list[int] = []",
    ],
)
def test_state_guard_catches_forbidden_code(source: str) -> None:
    assert forbidden_state(source) != []


@pytest.mark.parametrize(
    "source",
    [
        "import math",
        "from collections.abc import Sequence",
        "from crytobot.analysis._candles import Candle",
        "candle.open",
        "__all__ = ['x']",
        "NAMES = ('a', 'b')",
        "def f():\n    x = []",
    ],
)
def test_guards_let_allowed_code_through(source: str) -> None:
    assert forbidden_imports(source) == []
    assert forbidden_state(source) == []


@pytest.mark.parametrize("indicator", INDICATORS, ids=INDICATOR_IDS)
@given(candles=candle_series())
def test_same_input_same_result(indicator: Indicator, candles: list[Candle]) -> None:
    assert indicator.compute(candles) == indicator.compute(candles)


@pytest.mark.parametrize("indicator", INDICATORS, ids=INDICATOR_IDS)
@given(candles=candle_series())
def test_input_is_not_changed(indicator: Indicator, candles: list[Candle]) -> None:
    before = list(candles)
    indicator.compute(candles)
    assert len(candles) == len(before)
    assert all(after is original for after, original in zip(candles, before, strict=True))
