"""Spec 0017 AC-2, plan Risk 9: `ccxt` yalnız `market_data/_client.py`'de import edilir."""

import ast
from pathlib import Path

import crytobot

SRC = Path(crytobot.__file__).parent
ALLOWED = {SRC / "market_data" / "_client.py"}


def _imports_ccxt(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(
            alias.name.split(".")[0] == "ccxt" for alias in node.names
        ):
            return True
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.split(".")[0] == "ccxt"
        ):
            return True
    return False


def test_ccxt_imported_only_by_client() -> None:
    importing = {
        path for path in SRC.rglob("*.py") if _imports_ccxt(path.read_text(encoding="utf-8"))
    }
    assert importing == ALLOWED


def test_the_scan_sees_each_import_form() -> None:
    assert _imports_ccxt("import ccxt")
    assert _imports_ccxt("import ccxt.async_support")
    assert _imports_ccxt("from ccxt import binance")
    assert _imports_ccxt("def f():\n    import ccxt")
    assert not _imports_ccxt("import ccxtra")
