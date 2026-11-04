"""Spec 0015 AC-10: aynı girdi aynı sonuç; girdi değişmez; gelecek yok; saf hesap sınırı (BR-1).

Plan 0015, Risk 10: `boundaries` adımı yalnız `execution` ve `persistence`'ı yasaklar. Saat, ağ,
`market_data` ve global durum burada, kaynak kod üzerinde izin listesiyle sınanır.
"""

import ast
import inspect
from dataclasses import fields
from decimal import ROUND_UP, Context, Decimal, Inexact, Overflow, Rounded, localcontext
from pathlib import Path

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from crytobot import strategy
from crytobot.analysis import Candle
from crytobot.risk import TradeIntent
from crytobot.strategy import StrategySettings, propose
from tests.analysis.helpers import candle_series, from_closes
from tests.analysis.test_purity import forbidden_state
from tests.strategy.helpers import CROSS, PAIR, make_settings, run

STRATEGY_DIR = Path(strategy.__file__).parent
ALLOWED_MODULES = {
    "collections.abc",
    "dataclasses",
    "decimal",
    "enum",
    "typing",
    "crytobot.analysis",
    "crytobot.risk",
    "crytobot.strategy",
}
PRICES = st.floats(min_value=1.0, max_value=1000.0)


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


def strategy_sources() -> list[Path]:
    sources = sorted(STRATEGY_DIR.rglob("*.py"))
    assert {path.name for path in sources} >= {"__init__.py", "_inputs.py", "_proposal.py"}
    return sources


def decide(candles: list[Candle]) -> object:
    return propose(
        pair=PAIR,
        candles=candles,
        position_open=False,
        tick=Decimal("0.01"),
        settings=make_settings(),
    )


def test_purity_example_is_a_proposal() -> None:
    """Aşağıdaki iki testin sabit örneği öneri yolundan geçer; üreteç o yola ulaşmaz."""
    assert isinstance(decide(from_closes(CROSS)), TradeIntent)


@given(candles=candle_series())
@example(candles=from_closes(CROSS))
def test_same_input_same_result(candles: list[Candle]) -> None:
    assert decide(candles) == decide(candles)


@given(candles=candle_series())
@example(candles=from_closes(CROSS))
def test_input_is_not_changed(candles: list[Candle]) -> None:
    before = list(candles)
    decide(candles)
    assert len(candles) == len(before)
    assert all(after is original for after, original in zip(candles, before, strict=True))


@given(later=st.lists(PRICES, min_size=1, max_size=8))
def test_longer_series_call_leaves_no_state(later: list[float]) -> None:
    """Durum tutulmaz: uzun seriyi görmüş çağrı, sonraki kısa serinin kararını değiştirmez.

    İndikatörlerin gelecek mumdan etkilenmediğini `tests/analysis/test_no_look_ahead.py` sınar.
    """
    first = from_closes((*CROSS, *later))
    expected = decide(from_closes(CROSS))
    assert isinstance(expected, TradeIntent)
    decide(first)
    assert decide(first[: len(CROSS)]) == expected
    assert decide(from_closes(CROSS)) == expected


def test_result_ignores_caller_decimal_context() -> None:
    expected = run(CROSS, k=Decimal("1.2345678901234567"), tick=Decimal("0.00000001"))
    strict = Context(prec=2, Emax=2, Emin=-2, rounding=ROUND_UP, traps=[Inexact, Rounded, Overflow])
    with localcontext(strict):
        result = run(CROSS, k=Decimal("1.2345678901234567"), tick=Decimal("0.00000001"))
    assert result == expected
    assert repr(result) == repr(expected)


def test_no_profit_input_in_signature() -> None:
    """BR-1: kâr hedefi, gerçekleşen kâr-zarar ve işlem sıklığı girdi değildir."""
    assert set(inspect.signature(propose).parameters) == {
        "pair",
        "candles",
        "position_open",
        "tick",
        "settings",
    }
    assert {field.name for field in fields(StrategySettings)} == {
        "fast_period",
        "slow_period",
        "rsi_period",
        "rsi_threshold",
        "atr_period",
        "k",
        "r",
    }


def test_strategy_imports_only_allowed_modules() -> None:
    for path in strategy_sources():
        assert forbidden_imports(path.read_text(encoding="utf-8")) == [], path.name


def test_no_clock_or_global_state() -> None:
    for path in strategy_sources():
        assert forbidden_state(path.read_text(encoding="utf-8")) == [], path.name


@pytest.mark.parametrize(
    "source",
    [
        "import socket",
        "import crytobot.execution",
        "from crytobot.market_data import x",
        "from crytobot.persistence import x",
        "from time import time",
        "from . import x",
        "def f():\n    import sqlite3",
    ],
)
def test_import_guard_catches_forbidden_code(source: str) -> None:
    assert forbidden_imports(source) != []


@pytest.mark.parametrize(
    "source",
    [
        "from decimal import Decimal",
        "from crytobot.risk import TradeIntent",
        "from crytobot.strategy._inputs import check_inputs",
    ],
)
def test_import_guard_lets_allowed_code_through(source: str) -> None:
    assert forbidden_imports(source) == []
