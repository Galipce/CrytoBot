"""Spec 0059 AC-1: ayar — ADR 0005 listesi, eksik ve geçersiz alanlar adıyla."""

import tomllib
from pathlib import Path
from typing import Any

import pytest

from crytobot.decide import PREREGISTERED_COINS, load_decide_config

EXAMPLE = Path(__file__).resolve().parents[2] / "crytobot-decide.example.toml"


def document(**changes: Any) -> dict[str, Any]:
    with open(EXAMPLE, "rb") as file:
        data = tomllib.load(file)
    table = data["decide"]
    for key, value in changes.items():
        if value is None:
            table.pop(key)
        else:
            table[key] = value
    return data


def test_example_loads() -> None:
    result = load_decide_config(document())
    assert result.config is not None, result.message
    assert result.config.coins == PREREGISTERED_COINS
    assert result.config.pairs[0] == "BTC/USDT"
    assert result.config.minute_after_close == 5 and result.config.daily_call_limit == 24


@pytest.mark.parametrize(
    "coins",
    [
        list(PREREGISTERED_COINS[:9]),
        [*PREREGISTERED_COINS[:9], "PEPE"],
        [*PREREGISTERED_COINS, "PEPE"],
        [*PREREGISTERED_COINS[:9], "BTC"],
        "BTC",
    ],
)
def test_list_must_match_adr_0005(coins: object) -> None:
    result = load_decide_config(document(coins=coins))
    assert result.config is None
    assert result.message.startswith("ayar geçersiz: decide.coins")


def test_order_is_free() -> None:
    result = load_decide_config(document(coins=list(reversed(PREREGISTERED_COINS))))
    assert result.config is not None


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"coins": None}, "ayar eksik: decide.coins"),
        ({"model": None}, "ayar eksik: decide.model"),
        ({"model": "a b"}, "ayar geçersiz: decide.model"),
        ({"model": "x&calc"}, "ayar geçersiz: decide.model"),
        ({"store_path": None}, "ayar eksik: decide.store_path"),
        ({"log_path": ""}, "ayar geçersiz: decide.log_path"),
        ({"score_path": None}, "ayar eksik: decide.score_path"),
        ({"daily_call_limit": 49}, "ayar geçersiz: decide.daily_call_limit (1…48)"),
        ({"daily_call_limit": True}, "ayar geçersiz: decide.daily_call_limit (1…48)"),
        ({"minute_after_close": 60}, "ayar geçersiz: decide.minute_after_close (0…59)"),
        ({"timeout_s": 0}, "ayar geçersiz: decide.timeout_s (1…3600)"),
        ({"extra": 1}, "bilinmeyen ayar: decide.extra"),
    ],
)
def test_missing_and_invalid_named(changes: dict[str, Any], message: str) -> None:
    result = load_decide_config(document(**changes))
    assert result.config is None
    assert result.message == message


def test_same_paths_refused() -> None:
    data = document()
    data["decide"]["log_path"] = data["decide"]["store_path"]
    assert load_decide_config(data).message == "ayar geçersiz: decide.log_path"


def test_other_section_and_missing_section() -> None:
    assert load_decide_config({**document(), "bot": {}}).message == "bilinmeyen ayar: bot"
    assert load_decide_config({}).message == "ayar eksik: decide"


def test_list_is_adr_0007_twenty_coins() -> None:
    """Spec 0061 CB-1: ADR 0007'nin 20 adı harfiyen; eski on coinlik liste reddedilir."""
    assert PREREGISTERED_COINS == (
        "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK", "TRX",
        "BCH", "LTC", "SUI", "XLM", "HBAR", "DOT", "SHIB", "UNI", "NEAR", "APT",
    )  # fmt: skip
    old = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK", "TRX"]
    result = load_decide_config(document(coins=old))
    assert result.config is None
    assert result.message == "ayar geçersiz: decide.coins (ADR 0005/0007 ön kayıtlı listesi değil)"
