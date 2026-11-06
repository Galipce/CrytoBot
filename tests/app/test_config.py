"""Spec 0022 AC-3 (R-2, R-7): ayar eşleminin denetimi; ilk sorunlu ayar `bölüm.anahtar` adıyla.

Eşlem `tomllib`'in verdiği biçimdir. Dosyanın okunması ve "dosya yok / okunamıyor" giriş
noktasındadır (`tests/main`); burada dosyaya ve depoya dokunulmaz.
"""

import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from crytobot.app import SETTING_NAMES, load_config

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
BASE: dict[str, dict[str, Any]] = {
    "bot": {
        "store_path": "bot.db",
        "log_path": "bot.log",
        "turn_interval": "1h",
        "opening_balance": "10000",
    },
    "market": {
        "exchange": "binance",
        "candle_interval": "1h",
        "candle_count": 200,
        "call_timeout": 10,
        "read_budget": 60,
    },
    "turn": {
        "whitelist": ["BTC/USDT", "ETH/USDT"],
        "fee": "0.001",
        "slippage": "0.001",
        "max_candle_age": 900,
        "max_price_age": 120,
    },
    "risk": {
        "per_trade_risk": "0.01",
        "daily_loss_limit": "0.03",
        "max_drawdown": "0.15",
        "max_open_positions": 5,
        "profit_cost_multiple": "2",
    },
    "strategy": {
        "fast_period": 12,
        "slow_period": 26,
        "rsi_period": 14,
        "rsi_threshold": "70",
        "atr_period": 14,
        "k": "2",
        "r": "2",
    },
}


def document(**changes: Any) -> dict[str, dict[str, Any]]:
    """`changes`: `"bölüm.anahtar"` → değer; `None` anahtarı siler."""
    values = copy.deepcopy(BASE)
    for name, value in changes.items():
        section, key = name.split(".")
        if value is None:
            del values[section][key]
        else:
            values[section][key] = value
    return values


def setting_of(values: object) -> str | None:
    result = load_config(values, NOW)
    assert (result.config is None) == (result.setting is not None)
    return result.setting


def test_valid_settings_give_the_whole_config() -> None:
    config = load_config(document(), NOW).config
    assert config is not None
    assert (config.store_path, config.log_path) == ("bot.db", "bot.log")
    assert config.turn_interval == timedelta(hours=1)
    assert config.opening_balance == Decimal(10000)
    assert config.read.candle_interval == config.turn.candle_interval == timedelta(hours=1)
    assert config.read.read_budget == timedelta(seconds=60)
    assert config.turn.whitelist == ("BTC/USDT", "ETH/USDT")
    assert config.turn.limits.max_open_positions == 5
    assert config.turn.strategy.slow_period == 26
    assert config.turn.max_price_age == timedelta(seconds=120)


def test_setting_names_cover_the_document() -> None:
    expected = tuple(f"{s}.{k}" for s, keys in BASE.items() for k in keys)
    assert expected == SETTING_NAMES


@pytest.mark.parametrize("name", SETTING_NAMES)
def test_each_missing_setting_is_named(name: str) -> None:
    """R-2: varsayılan yoktur; eksik ayarın adı söylenir."""
    result = load_config(document(**{name: None}), NOW)
    assert result.config is None and result.setting == name
    assert result.message == f"ayar eksik: {name}"


@pytest.mark.parametrize("section", list(BASE))
def test_missing_or_broken_section_is_named(section: str) -> None:
    values = document()
    del values[section]
    assert setting_of(values) == section
    broken: dict[str, Any] = document()
    broken[section] = "metin"
    assert setting_of(broken) == section


@pytest.mark.parametrize("values", [None, [], "metin"])
def test_document_that_is_not_a_table_is_refused(values: object) -> None:
    assert setting_of(values) == "ayar dosyası"


INVALID = [
    ("bot.store_path", ""),
    ("bot.store_path", 5),
    ("bot.log_path", ["a"]),
    ("bot.log_path", "bot.db"),  # the log would write into the store
    ("bot.turn_interval", 3600),
    ("bot.opening_balance", 10000.0),
    ("bot.opening_balance", "0"),
    ("bot.opening_balance", 0),
    ("bot.opening_balance", "-5"),
    ("bot.opening_balance", "on bin"),
    ("bot.opening_balance", "1e4"),
    ("bot.opening_balance", "NaN"),
    ("bot.opening_balance", "1_000"),
    ("bot.opening_balance", " 100"),
    ("bot.opening_balance", "100."),
    ("bot.opening_balance", ".5"),
    ("bot.opening_balance", True),
    ("bot.opening_balance", "1" * 29),  # past the ledger's 28 digits
    ("bot.opening_balance", "1." + "0" * 27 + "1"),  # 29 significant digits
    ("market.exchange", "kraken"),
    ("market.exchange", 1),
    ("market.candle_interval", "1w"),
    ("market.candle_count", 0),
    ("market.candle_count", 1001),
    ("market.candle_count", "200"),
    ("market.candle_count", True),
    ("market.call_timeout", 0),
    ("market.call_timeout", 1.5),
    ("market.call_timeout", -1),
    ("market.call_timeout", 10**30),  # past the calendar
    ("market.read_budget", 0),
    ("turn.whitelist", "BTC/USDT"),
    ("turn.whitelist", ["BTC/USDT", "BTC/USDT"]),
    ("turn.whitelist", ["BTC/USDT", 5]),
    ("turn.whitelist", [""]),
    ("turn.fee", 0.001),
    ("turn.fee", "-0.001"),
    ("turn.fee", "1"),
    ("turn.slippage", "abc"),
    ("turn.slippage", "-1"),
    ("turn.max_candle_age", -1),
    ("turn.max_candle_age", "900"),
    ("turn.max_price_age", 1.0),
    ("risk.per_trade_risk", "0.5"),  # past the hard cap
    ("risk.per_trade_risk", 0.01),
    ("risk.daily_loss_limit", "0"),
    ("risk.max_drawdown", "1"),
    ("risk.max_open_positions", 0),
    ("risk.max_open_positions", "5"),
    ("risk.profit_cost_multiple", "0.5"),  # below the hard floor
    ("strategy.fast_period", 0),
    ("strategy.fast_period", 26),  # not below slow
    ("strategy.slow_period", "26"),
    ("strategy.rsi_period", -1),
    ("strategy.rsi_threshold", "101"),
    ("strategy.rsi_threshold", 70.0),
    ("strategy.atr_period", 0),
    ("strategy.k", "0"),
    ("strategy.r", "-2"),
]


@pytest.mark.parametrize(("name", "value"), INVALID)
def test_each_invalid_setting_is_named(name: str, value: object) -> None:
    """R-2: turun ve okumanın bugün reddettiği her ayar; mesaj ham değeri taşımaz."""
    result = load_config(document(**{name: value}), NOW)
    assert result.config is None and result.setting == name
    assert result.message == f"ayar geçersiz: {name}"


def test_every_setting_has_an_invalid_case() -> None:
    assert {name for name, _ in INVALID} == set(SETTING_NAMES)


def test_huge_number_is_named_without_its_digits() -> None:
    """Known traps: 4300 basamaktan uzun `int` metne çevrilmez."""
    for name in ("bot.opening_balance", "risk.max_open_positions", "strategy.fast_period"):
        huge = 10**5000 + 1 if name == "bot.opening_balance" else 10**5000
        result = load_config(document(**{name: huge}), NOW)
        assert result.setting == name
        assert "0000" not in result.message


@pytest.mark.parametrize(("section", "key"), [("bot", "mode"), ("risk", "api_key"), ("live", None)])
def test_unknown_setting_is_refused(section: str, key: str | None) -> None:
    """Bilinmeyen anahtar yok sayılmaz: yazım hatası varsayılana düşmez, mod anahtarı yoktur."""
    values: dict[str, Any] = document()
    if key is None:
        values[section] = {}
        expected = section
    else:
        values[section][key] = "paper"
        expected = f"{section}.{key}"
    result = load_config(values, NOW)
    assert result.config is None and result.setting == expected
    assert result.message == f"bilinmeyen ayar: {expected}"


@pytest.mark.parametrize("interval", ["45m", "1w", "3d", "1M", "60m", "", "1H"])
def test_turn_interval_must_be_an_accepted_candle_interval(interval: str) -> None:
    """R-7: okumanın kabul etmediği aralık R-2 ile reddedilir."""
    assert setting_of(document(**{"bot.turn_interval": interval})) == "bot.turn_interval"


def test_turn_interval_shorter_than_candle_interval_is_refused() -> None:
    values = document(**{"bot.turn_interval": "30m", "market.read_budget": 60})
    assert setting_of(values) == "bot.turn_interval"


@pytest.mark.parametrize("interval", ["1h", "4h", "1d"])
def test_turn_interval_at_or_above_candle_interval_is_accepted(interval: str) -> None:
    config = load_config(document(**{"bot.turn_interval": interval}), NOW).config
    assert config is not None and config.turn_interval >= config.read.candle_interval


@pytest.mark.parametrize(("budget", "refused"), [(3600, True), (7200, True), (3599, False)])
def test_read_budget_must_be_shorter_than_turn_interval(budget: int, refused: bool) -> None:
    """R-2: okuma bütçesi tur aralığından kısa olmak zorundadır."""
    setting = setting_of(document(**{"market.read_budget": budget}))
    assert setting == ("market.read_budget" if refused else None)


def test_first_problem_in_file_order_is_named() -> None:
    values = document(**{"turn.fee": "x", "risk.max_drawdown": "x", "strategy.k": None})
    assert setting_of(values) == "turn.fee"


def test_zero_ages_are_accepted() -> None:
    values = document(**{"turn.max_candle_age": 0, "turn.max_price_age": 0})
    assert setting_of(values) is None


# Spec 0024: `[history]` indirmenin bölümüdür (0023); bot yükleyicisi adını tanır, içine bakmaz.
HISTORY_VALUES: list[object] = [
    {},
    {"mode": "live"},
    {"start": "dün", "pairs": 5},
    {"alt": {"x": 1}},
    "metin",
    5,
    [1, 2],
]
NEAR_NAMES = ["History", "HISTORY", "histroy", "historyy", "history_"]


def with_history(values: object, value: object = None) -> dict[str, Any]:
    """`history` eşlemin başına konur: dosya sırası sonucu değiştirmemeli (plan Risk 3)."""
    assert isinstance(values, dict)
    return {"history": {} if value is None else value, **values}


@pytest.mark.parametrize("value", HISTORY_VALUES)
def test_history_section_is_passed_unread(value: object) -> None:
    """CB-1, CB-2: sonuç `[history]` yokken verilenle aynıdır; değeri mesaja ve ayarlara girmez."""
    plain = load_config(document(), NOW)
    result = load_config(with_history(document(), value), NOW)
    assert result.config is not None and result.setting is None
    assert result.config == plain.config
    assert result.message == plain.message == "ayarlar geçerli"


@pytest.mark.parametrize("name", NEAR_NAMES)
def test_only_the_exact_history_name_is_passed(name: str) -> None:
    """CB-3: büyük/küçük harf ya da benzer ad tanınmaz."""
    values: dict[str, Any] = document()
    values[name] = {}
    result = load_config(values, NOW)
    assert result.config is None and result.setting == name
    assert result.message == f"bilinmeyen ayar: {name}"


@pytest.mark.parametrize("history", [False, True])
@pytest.mark.parametrize("section", list(BASE))
def test_unknown_key_in_each_section_is_refused(section: str, history: bool) -> None:
    """PB-1: beş bot bölümünde bilinmeyen anahtar, `[history]` olsun olmasın."""
    values: dict[str, Any] = document()
    values[section]["mode"] = "live"
    if history:
        values = with_history(values)
    result = load_config(values, NOW)
    assert result.config is None and result.setting == f"{section}.mode"
    assert result.message == f"bilinmeyen ayar: {section}.mode"


@pytest.mark.parametrize("name", ["live", "histroy"])
def test_unknown_section_beside_history_is_refused(name: str) -> None:
    """PB-2."""
    values: dict[str, Any] = document()
    values[name] = {}
    result = load_config(with_history(values), NOW)
    assert result.config is None and result.setting == name
    assert result.message == f"bilinmeyen ayar: {name}"


@pytest.mark.parametrize("name", SETTING_NAMES)
def test_each_missing_setting_is_named_beside_history(name: str) -> None:
    """PB-3."""
    result = load_config(with_history(document(**{name: None})), NOW)
    assert result.config is None and result.setting == name
    assert result.message == f"ayar eksik: {name}"


@pytest.mark.parametrize(("name", "value"), INVALID)
def test_each_invalid_setting_is_named_beside_history(name: str, value: object) -> None:
    """PB-3."""
    result = load_config(with_history(document(**{name: value})), NOW)
    assert result.config is None and result.setting == name
    assert result.message == f"ayar geçersiz: {name}"


@pytest.mark.parametrize("section", list(BASE))
def test_missing_or_broken_section_is_named_beside_history(section: str) -> None:
    """PB-3."""
    values = document()
    del values[section]
    result = load_config(with_history(values), NOW)
    assert result.setting == section and result.message == f"ayar eksik: {section}"
    broken: dict[str, Any] = document()
    broken[section] = "metin"
    result = load_config(with_history(broken), NOW)
    assert result.setting == section and result.message == f"ayar geçersiz: {section}"


def test_only_history_misses_bot() -> None:
    """PB-3: botun bölümleri `[history]`'den önce denetlenir."""
    result = load_config({"history": {"mode": "live"}}, NOW)
    assert result.config is None and result.setting == "bot"
    assert result.message == "ayar eksik: bot"


def test_first_problem_in_file_order_is_named_beside_history() -> None:
    """PB-3 (0022/AC-3)."""
    values = document(**{"turn.fee": "x", "risk.max_drawdown": "x", "strategy.k": None})
    assert setting_of(with_history(values)) == "turn.fee"
