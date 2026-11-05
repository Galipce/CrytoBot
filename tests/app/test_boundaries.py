"""Spec 0016 AC-13: sınırlar: düz `dict` (B-16), kâr girdisi yok (BR-1), izin verilen importlar.

`boundaries` adımı yalnız `execution` ve `persistence` kuralını sınar; ağ, `market_data` ve saat
burada, kaynak kod üzerinde izin listesiyle sınanır (0015 plan Risk 10'un aynısı).

Spec 0019: `market_data`'nın yalnız kökü import edilir, alt modülleri edilmez (CB-1, PB-2). Okuma
işlevi hiçbir biçimde kullanılamaz, adı `app` kaynağında geçemez (CB-2, CB-3): `app` borsaya çıkmaz.
"""

import ast
import dataclasses
import inspect
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot import app
from crytobot.app import PairMarket, TurnSettings, _buys, _closes, _session, run_turn
from crytobot.portfolio import account_state, exit_decisions
from tests.app.helpers import BTC, LATER, bot_with_position, pair_market

APP_DIR = Path(app.__file__).parent
ALLOWED_MODULES = {
    "collections.abc",
    "dataclasses",
    "datetime",
    "decimal",
    "enum",
    "hashlib",
    "crytobot.analysis",
    "crytobot.app",
    "crytobot.execution",
    "crytobot.persistence",
    "crytobot.portfolio",
    "crytobot.risk",
    "crytobot.strategy",
}
ROOT_ONLY_MODULES = {"crytobot.market_data"}
MARKET_READER = "read_market_data"
CLOCK_CALLS = {"now", "utcnow", "today", "time", "monotonic"}


def files_naming_reader(root: Path) -> list[str]:
    """Düz metin arar: yorum, docstring ve metin değerleri de kapsamdadır (0019 CB-3)."""
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if MARKET_READER in path.read_text(encoding="utf-8")
    )


def _allowed(name: str) -> bool:
    if name in ROOT_ONLY_MODULES:
        return True
    return any(name == allowed or name.startswith(f"{allowed}.") for allowed in ALLOWED_MODULES)


def forbidden_imports(source: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [f"import {a.name}" for a in node.names if not _allowed(a.name)]
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module is None or not _allowed(node.module):
                found.append(f"from {node.module}")
            elif node.module in ROOT_ONLY_MODULES:
                found += [
                    f"from {node.module} import {a.name}"
                    for a in node.names
                    if a.name in (MARKET_READER, "*")
                ]
        elif isinstance(node, ast.Attribute) and node.attr == MARKET_READER:
            found.append(f".{MARKET_READER}")
    return found


def forbidden_state(source: str) -> list[str]:
    """Saat çağrısı ve `global` deyimi: saat ve durum çağrıyla gelir (R-1)."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Global):
            found.append("global")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in CLOCK_CALLS
        ):
            found.append(f"{node.func.attr}()")
    return found


def test_app_gives_plain_dict_prices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B-16: `account_state` ve `exit_decisions`'a yalnız düz `dict` gider."""
    seen: list[type] = []

    def account_spy(ledger: Any, prices: Any) -> Any:
        seen.append(type(prices))
        return account_state(ledger, prices)

    def exit_spy(ledger: Any, prices: Any) -> Any:
        seen.append(type(prices))
        return exit_decisions(ledger, prices)

    monkeypatch.setattr(_session, "account_state", account_spy)
    monkeypatch.setattr(_buys, "account_state", account_spy)
    monkeypatch.setattr(_closes, "exit_decisions", exit_spy)

    bot = bot_with_position(tmp_path / "s.db")
    bot.turn({BTC: pair_market(price=Decimal(7), price_at=LATER)}, now=LATER)

    assert len(seen) >= 3 and set(seen) == {dict}


def test_no_profit_input_in_signature() -> None:
    """R-14, BR-1: kâr hedefi, kâr-zarar ve işlem sıklığı turun girdisi değildir."""
    names = set(inspect.signature(run_turn).parameters)
    names |= {field.name for field in dataclasses.fields(TurnSettings)}
    names |= {field.name for field in dataclasses.fields(PairMarket)}
    words = ("profit", "pnl", "realized", "target", "goal", "frequency")
    assert not {name for name in names if any(word in name for word in words)}


def test_decisions_do_not_read_realized_profit() -> None:
    """R-14: defterin `realized` alanı `app` kaynağında okunmaz."""
    for path in APP_DIR.glob("*.py"):
        assert ".realized" not in path.read_text(encoding="utf-8"), path.name


def test_app_imports_only_allowed_modules() -> None:
    for path in APP_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert forbidden_imports(source) == [], path.name
        assert forbidden_state(source) == [], path.name


@pytest.mark.parametrize(
    "source",
    [
        "import ccxt",
        "import socket",
        "from crytobot.reporting import x",
        "from crytobot.control import x",
        "from . import x",
        "def f():\n    import sqlite3",
    ],
)
def test_import_guard_catches_forbidden_code(source: str) -> None:
    assert forbidden_imports(source) != []


@pytest.mark.parametrize(
    "source",
    [
        "import crytobot.market_data",
        "from crytobot.market_data import MarketRead",
        "from crytobot.market_data import x",
    ],
)
def test_import_guard_accepts_market_data_root(source: str) -> None:
    """0019 CB-1: `market_data` kökü `app`'e açıktır."""
    assert forbidden_imports(source) == []


@pytest.mark.parametrize(
    ("source", "finding"),
    [
        (
            "from crytobot.market_data import read_market_data",
            "from crytobot.market_data import read_market_data",
        ),
        (
            "from crytobot.market_data import read_market_data as r",
            "from crytobot.market_data import read_market_data",
        ),
        ("from crytobot.market_data import *", "from crytobot.market_data import *"),
        (
            "import crytobot.market_data\ncrytobot.market_data.read_market_data",
            ".read_market_data",
        ),
        ("import crytobot.market_data as m\nm.read_market_data", ".read_market_data"),
    ],
)
def test_import_guard_rejects_market_data_reader(source: str, finding: str) -> None:
    """0019 CB-2: bulgu okuma işlevini adlandırır; kökün yasak olmasından gelen ret sayılmaz."""
    assert forbidden_imports(source) == [finding]


@pytest.mark.parametrize(
    "source",
    [
        "from crytobot.market_data._client import x",
        "import crytobot.market_data._client",
        "from crytobot import market_data",
    ],
)
def test_import_guard_rejects_market_data_internals(source: str) -> None:
    """0019 PB-2 (plan Risk 2): kök kuralı önek kuralı değildir, alt modül yolu geçmez."""
    assert forbidden_imports(source) != []


def test_app_source_never_names_market_data_reader() -> None:
    """0019 CB-3: gerçek `app` klasöründe okuma işlevinin adı geçmez."""
    assert files_naming_reader(APP_DIR) == []


@pytest.mark.parametrize(
    ("relative", "content"),
    [
        ("yorum.py", "# read_market_data\n"),
        ("belge.py", '"""read_market_data"""\n'),
        ("metin.py", 'AD = "read_market_data"\n'),
        ("alt/kume/dosya.py", "x = read_market_data\n"),
    ],
)
def test_reader_name_scan_covers_every_python_file(
    tmp_path: Path, relative: str, content: str
) -> None:
    """0019 CB-3: sonradan eklenen her dosya kapsamdadır; adı geçmeyen dosya bulunmaz."""
    (tmp_path / "temiz.py").write_text("x = 1\n", encoding="utf-8")
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    assert files_naming_reader(tmp_path) == [relative]
