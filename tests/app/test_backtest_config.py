"""Spec 0025 AC-4 (R-2; plan Risk 6, 12): backtest ayarları, ilk sorunlu ayar adıyla.

Eşlem `tomllib`'in verdiği biçimdir; dosyanın okunması ve "dosya yok / okunamıyor" giriş
noktasındadır (`tests/main/test_backtest_entry.py`). Burada dosyaya ve depoya dokunulmaz.
Bu dosya `tests/tooling` kopyasına girer: yalnız `tests/app`'ten import eder.
"""

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import load_backtest_config
from tests.app.test_config import document

SPLIT = datetime(2026, 1, 15, tzinfo=UTC)
BACKTEST: dict[str, Any] = {
    "data_path": "history.jsonl",
    "report_path": "rapor.txt",
    "split_at": SPLIT,
    "spread": "0.0005",
}


def backtest_document(**changes: Any) -> dict[str, Any]:
    """`changes`: `"bölüm.anahtar"` → değer (`None` siler); `backtest=None` bölümü siler."""
    section_changes = {k: v for k, v in changes.items() if k.startswith("backtest.")}
    bot_changes = {k: v for k, v in changes.items() if k not in section_changes and k != "backtest"}
    values: dict[str, Any] = document(**bot_changes)
    if "backtest" in changes:
        if changes["backtest"] is not None:
            values["backtest"] = changes["backtest"]
        return values
    section = dict(BACKTEST)
    for name, value in section_changes.items():
        key = name.split(".", 1)[1]
        if value is None:
            section.pop(key, None)
        else:
            section[key] = value
    values["backtest"] = section
    return values


def refused(**changes: Any) -> tuple[str | None, str]:
    result = load_backtest_config(backtest_document(**changes))
    assert result.config is None
    return result.setting, result.message


def test_valid_settings() -> None:
    result = load_backtest_config(backtest_document())
    config = result.config
    assert config is not None, result.message
    assert (config.data_path, config.report_path) == ("history.jsonl", "rapor.txt")
    assert config.split_at == SPLIT
    assert config.spread == Decimal("0.0005")
    assert config.bot.turn.whitelist == ("BTC/USDT", "ETH/USDT")
    assert config.bot.opening_balance == 10000


@pytest.mark.parametrize(
    ("changes", "setting", "message"),
    [
        # the bot's settings first: the turn refuses them here as well
        ({"turn.fee": "-0.1"}, "turn.fee", "ayar geçersiz: turn.fee"),
        ({"risk.per_trade_risk": None}, "risk.per_trade_risk", "ayar eksik: risk.per_trade_risk"),
        ({"strategy.k": "0"}, "strategy.k", "ayar geçersiz: strategy.k"),
        ({"market.candle_count": 0}, "market.candle_count", "ayar geçersiz: market.candle_count"),
        ({"bot.opening_balance": "0"}, "bot.opening_balance", "ayar geçersiz: bot.opening_balance"),
        ({"turn.whitelist": ["BTC/USDT", "BTC/USDT"]}, "turn.whitelist", None),
        ({"bot.turn_interval": "6h", "market.candle_interval": "4h"}, "bot.turn_interval", None),
        ({"backtest": None}, "backtest", "ayar eksik: backtest"),
        ({"backtest": "x"}, "backtest", "ayar geçersiz: backtest"),
        ({"backtest.data_path": None}, "backtest.data_path", "ayar eksik: backtest.data_path"),
        (
            {"backtest.report_path": None},
            "backtest.report_path",
            "ayar eksik: backtest.report_path",
        ),
        ({"backtest.split_at": None}, "backtest.split_at", "ayar eksik: backtest.split_at"),
        ({"backtest.spread": None}, "backtest.spread", "ayar eksik: backtest.spread"),
        ({"backtest.data_path": ""}, "backtest.data_path", "ayar geçersiz: backtest.data_path"),
        ({"backtest.data_path": 7}, "backtest.data_path", None),
        ({"backtest.data_path": "bot.db"}, "backtest.data_path", None),
        ({"backtest.report_path": "history.jsonl"}, "backtest.report_path", None),
        ({"backtest.report_path": "bot.db"}, "backtest.report_path", None),
        ({"backtest.report_path": "bot.log"}, "backtest.report_path", None),
        ({"backtest.report_path": ["r"]}, "backtest.report_path", None),
        ({"backtest.split_at": "2026-01-15T00:00:00Z"}, "backtest.split_at", None),
        ({"backtest.split_at": date(2026, 1, 15)}, "backtest.split_at", None),
        ({"backtest.split_at": datetime(2026, 1, 15)}, "backtest.split_at", None),
        (
            {"backtest.split_at": datetime(2026, 1, 15, 3, tzinfo=timezone(timedelta(hours=3)))},
            "backtest.split_at",
            None,
        ),
        ({"backtest.split_at": SPLIT + timedelta(minutes=30)}, "backtest.split_at", None),
        ({"backtest.spread": "-0.0001"}, "backtest.spread", "ayar geçersiz: backtest.spread"),
        ({"backtest.spread": "1"}, "backtest.spread", None),
        ({"backtest.spread": 1}, "backtest.spread", None),
        ({"backtest.spread": 0.0005}, "backtest.spread", None),
        ({"backtest.spread": "1e-3"}, "backtest.spread", None),
        ({"backtest.spread": True}, "backtest.spread", None),
        # inside 0..1 but past the turn's scale (±999999): the turn's own check refuses it
        ({"backtest.spread": "0." + "0" * 1_000_000 + "1"}, "backtest.spread", None),
        ({"backtest.mode": "live"}, "backtest.mode", "bilinmeyen ayar: backtest.mode"),
    ],
)
def test_refuses_first_bad_setting_by_name(
    changes: dict[str, Any], setting: str, message: str | None
) -> None:
    found, text = refused(**changes)
    assert found == setting
    assert text == (message or f"ayar geçersiz: {setting}")


def test_order_bot_then_keys_then_values_then_unknown() -> None:
    """Plan Risk 12: önce bot, sonra her anahtarın varlığı, sonra değerler, sonra bilinmeyen."""
    assert refused(**{"turn.fee": "x", "backtest.spread": None})[0] == "turn.fee"
    assert refused(**{"backtest.data_path": "", "backtest.spread": None})[0] == "backtest.spread"
    assert refused(**{"backtest.spread": "2", "backtest.data_path": ""})[0] == "backtest.data_path"
    assert refused(**{"backtest.spread": "2", "backtest.x": 1})[0] == "backtest.spread"


def test_zero_spread_and_long_turn_interval_are_valid() -> None:
    result = load_backtest_config(
        backtest_document(**{"backtest.spread": 0, "bot.turn_interval": "4h"})
    )
    assert result.config is not None, result.message
    assert result.config.spread == 0


def test_message_never_holds_the_raw_value() -> None:
    _, message = refused(**{"backtest.report_path": "bot.db"})
    assert "bot.db" not in message
    _, message = refused(**{"backtest.spread": "0.123456789SIR"})
    assert "SIR" not in message


def test_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    load_backtest_config(backtest_document())
    load_backtest_config(backtest_document(**{"backtest.spread": "x"}))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("value", [None, [], "metin", 3])
def test_not_a_mapping(value: Any) -> None:
    result = load_backtest_config(value)
    assert result.config is None and result.setting is not None
