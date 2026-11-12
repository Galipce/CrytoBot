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
from crytobot.strategy import StrategySettings

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
    assert isinstance(config.turn.strategy, StrategySettings)
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


@pytest.mark.parametrize(
    ("section", "key"), [("bot", "unknown_key"), ("risk", "api_key"), ("live", None)]
)
def test_unknown_setting_is_refused(section: str, key: str | None) -> None:
    """Bilinmeyen anahtar yok sayılmaz: yazım hatası varsayılana düşmez."""
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
    values[section]["unknown_key"] = "test"
    if history:
        values = with_history(values)
    result = load_config(values, NOW)
    assert result.config is None and result.setting == f"{section}.unknown_key"
    assert result.message == f"bilinmeyen ayar: {section}.unknown_key"


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


# Spec 0026: `[backtest]` backtest koşusunun bölümüdür (0025); bot yükleyicisi adını tanır,
# içine bakmaz. Değerler `[history]` örnekleriyle aynıdır.
BACKTEST_NEAR_NAMES = ["Backtest", "BACKTEST", "bactest", "backtests", "backtest_", "back_test"]


def with_backtest(values: object, value: object = None) -> dict[str, Any]:
    """`backtest` eşlemin başına konur: dosya sırası sonucu değiştirmemeli (0024 plan Risk 3)."""
    assert isinstance(values, dict)
    return {"backtest": {} if value is None else value, **values}


@pytest.mark.parametrize("value", HISTORY_VALUES)
def test_backtest_section_is_passed_unread(value: object) -> None:
    """0026 CB-1, CB-2: sonuç `[backtest]` yokken verilenle aynıdır; değeri mesaja girmez."""
    plain = load_config(document(), NOW)
    result = load_config(with_backtest(document(), value), NOW)
    assert result.config is not None and result.setting is None
    assert result.config == plain.config
    assert result.message == plain.message == "ayarlar geçerli"


def test_backtest_beside_history_is_passed_unread() -> None:
    """0026 CB-1: `[history]` ile birlikte, iki sırada da."""
    plain = load_config(document(), NOW)
    orders = (with_backtest(with_history(document())), with_history(with_backtest(document())))
    for values in orders:
        result = load_config(values, NOW)
        assert result.config is not None and result.config == plain.config
        assert result.message == "ayarlar geçerli"


@pytest.mark.parametrize("name", BACKTEST_NEAR_NAMES)
def test_only_the_exact_backtest_name_is_passed(name: str) -> None:
    """0026 CB-3: büyük/küçük harf ya da benzer ad tanınmaz."""
    values: dict[str, Any] = document()
    values[name] = {}
    result = load_config(values, NOW)
    assert result.config is None and result.setting == name
    assert result.message == f"bilinmeyen ayar: {name}"


@pytest.mark.parametrize("section", list(BASE))
def test_unknown_key_in_each_section_is_refused_beside_backtest(section: str) -> None:
    """0026 PB-1: beş bot bölümünde bilinmeyen anahtar, `[backtest]` varken de."""
    values: dict[str, Any] = document()
    values[section]["unknown_key"] = "test"
    result = load_config(with_backtest(values), NOW)
    assert result.config is None and result.setting == f"{section}.unknown_key"
    assert result.message == f"bilinmeyen ayar: {section}.unknown_key"


@pytest.mark.parametrize("name", ["live", "histroy", "bactest"])
def test_unknown_section_beside_backtest_is_refused(name: str) -> None:
    """0026 PB-2."""
    values: dict[str, Any] = document()
    values[name] = {}
    result = load_config(with_backtest(values), NOW)
    assert result.config is None and result.setting == name
    assert result.message == f"bilinmeyen ayar: {name}"


@pytest.mark.parametrize("name", SETTING_NAMES)
def test_each_missing_setting_is_named_beside_backtest(name: str) -> None:
    """0026 PB-3."""
    result = load_config(with_backtest(document(**{name: None})), NOW)
    assert result.config is None and result.setting == name
    assert result.message == f"ayar eksik: {name}"


@pytest.mark.parametrize(("name", "value"), INVALID)
def test_each_invalid_setting_is_named_beside_backtest(name: str, value: object) -> None:
    """0026 PB-3."""
    result = load_config(with_backtest(document(**{name: value})), NOW)
    assert result.config is None and result.setting == name
    assert result.message == f"ayar geçersiz: {name}"


@pytest.mark.parametrize("section", list(BASE))
def test_missing_or_broken_section_is_named_beside_backtest(section: str) -> None:
    """0026 PB-3."""
    values = document()
    del values[section]
    result = load_config(with_backtest(values), NOW)
    assert result.setting == section and result.message == f"ayar eksik: {section}"
    broken: dict[str, Any] = document()
    broken[section] = "metin"
    result = load_config(with_backtest(broken), NOW)
    assert result.setting == section and result.message == f"ayar geçersiz: {section}"


def test_only_backtest_misses_bot() -> None:
    """0026 PB-3: botun bölümleri `[backtest]`'ten önce denetlenir."""
    result = load_config({"backtest": {"mode": "live"}}, NOW)
    assert result.config is None and result.setting == "bot"
    assert result.message == "ayar eksik: bot"


def test_first_problem_in_file_order_is_named_beside_backtest() -> None:
    """0026 PB-3 (0022/AC-3)."""
    values = document(**{"turn.fee": "x", "risk.max_drawdown": "x", "strategy.k": None})
    assert setting_of(with_backtest(values)) == "turn.fee"


def test_bot_mode_defaults_to_paper_and_accepts_live() -> None:
    """Spec 0033: [bot] altında mode opsiyoneldir (varsayılan 'paper', 'live' kabul edilir)."""
    res_def = load_config(document(), NOW)
    assert res_def.config is not None and res_def.config.mode == "paper"
    res_live = load_config(document(**{"bot.mode": "live"}), NOW)
    assert res_live.config is not None and res_live.config.mode == "live"
    res_paper = load_config(document(**{"bot.mode": "paper"}), NOW)
    assert res_paper.config is not None and res_paper.config.mode == "paper"
    res_bad = load_config(document(**{"bot.mode": "invalid"}), NOW)
    assert res_bad.config is None and res_bad.setting == "bot.mode"
    assert res_bad.message == "ayar geçersiz: bot.mode"


# --- spec 0043 R-1, R-4 (AC-1, AC-8; plan Risk 3, 4) ---

S1_KEYS = {**BASE["strategy"], "trend_period": 150}
S2_KEYS = {"breakout_period": 55, "atr_period": 14, "k": "2", "r": "2"}
S3_KEYS = {"rsi_period": 14, "rsi_threshold": "35", "atr_period": 14, "k": "1.5", "r": "2"}
CANDIDATE_KEYS: dict[str, dict[str, Any]] = {
    "S0": dict(BASE["strategy"]),
    "S1": S1_KEYS,
    "S2": S2_KEYS,
    "S3": S3_KEYS,
}


def chosen(
    name: str, keys: dict[str, Any] | None = None, *, candle_count: int = 200
) -> dict[str, dict[str, Any]]:
    """Seçilen adayın tam anahtar kümesiyle belge; `keys`'te `None` anahtarı siler."""
    values = document(**{"market.candle_count": candle_count})
    strategy: dict[str, Any] = {"name": name, **CANDIDATE_KEYS[name], **(keys or {})}
    values["strategy"] = {key: value for key, value in strategy.items() if value is not None}
    return values


@pytest.mark.parametrize("name", list(CANDIDATE_KEYS))
def test_each_candidate_is_selected_with_its_keys(name: str) -> None:
    config = load_config(chosen(name), NOW).config
    assert config is not None
    strategy = config.turn.strategy
    assert strategy.name == name
    expected = {
        key: Decimal(value) if isinstance(value, str) else value
        for key, value in CANDIDATE_KEYS[name].items()
    }
    assert dict(strategy.parameters()) == expected


def test_no_name_is_s0() -> None:
    """R-1: ad yoksa S0 (bugünkü davranış); açık `name = "S0"` aynı ayarı verir."""
    implicit = load_config(document(), NOW).config
    explicit = load_config(chosen("S0"), NOW).config
    assert implicit is not None and explicit is not None
    assert isinstance(implicit.turn.strategy, StrategySettings)
    assert implicit == explicit


@pytest.mark.parametrize("value", ["S4", "s0", "", 0, None, ["S1"], True])
def test_unknown_strategy_name_refused(value: object) -> None:
    """AC-1: bilinmeyen ad `ayar geçersiz: strategy.name`, anahtarlardan önce."""
    values = document()
    values["strategy"]["name"] = value
    result = load_config(values, NOW)
    assert (result.config, result.setting) == (None, "strategy.name")
    assert result.message == "ayar geçersiz: strategy.name"
    del values["strategy"]["fast_period"]  # the name is judged before the keys
    assert load_config(values, NOW).message == "ayar geçersiz: strategy.name"


@pytest.mark.parametrize(
    ("name", "key"),
    [(name, key) for name, keys in CANDIDATE_KEYS.items() for key in keys],
)
def test_selected_strategy_missing_key_refused(name: str, key: str) -> None:
    """AC-1: seçilen adayın eksik anahtarı `ayar eksik: strategy.<alan>`."""
    result = load_config(chosen(name, {key: None}), NOW)
    assert (result.config, result.setting) == (None, f"strategy.{key}")
    assert result.message == f"ayar eksik: strategy.{key}"


@pytest.mark.parametrize(
    ("name", "key"),
    [("S0", "trend_period"), ("S2", "fast_period"), ("S2", "rsi_threshold"), ("S3", "slow_period")],
)
def test_key_of_another_candidate_refused(name: str, key: str) -> None:
    """Plan Risk 3: seçilen adayın kullanmadığı anahtar etkisiz kalmaz, reddedilir."""
    result = load_config(chosen(name, {key: 20}), NOW)
    assert (result.config, result.setting) == (None, f"strategy.{key}")
    assert result.message == f"bilinmeyen ayar: strategy.{key}"


@pytest.mark.parametrize(
    ("name", "key", "value"),
    [
        ("S1", "trend_period", 0),
        ("S1", "trend_period", "100"),
        ("S2", "breakout_period", -1),
        ("S2", "k", 2.5),
        ("S3", "rsi_threshold", "101"),
        ("S3", "atr_period", "14"),
    ],
)
def test_selected_strategy_invalid_key_refused(name: str, key: str, value: object) -> None:
    result = load_config(chosen(name, {key: value}), NOW)
    assert (result.config, result.setting) == (None, f"strategy.{key}")
    assert result.message == f"ayar geçersiz: strategy.{key}"


@pytest.mark.parametrize(
    ("name", "keys", "needed"),
    [
        ("S0", {}, 27),
        ("S1", {"trend_period": 150}, 150),
        ("S2", {"breakout_period": 100}, 101),
        ("S3", {}, 200),
    ],
)
def test_candle_count_warmup_boundary(name: str, keys: dict[str, Any], needed: int) -> None:
    """AC-8: en uzun göstergeye tam yeten mum sayısı kabul, bir eksiği
    `ayar geçersiz: market.candle_count`."""
    assert load_config(chosen(name, keys, candle_count=needed), NOW).config is not None
    result = load_config(chosen(name, keys, candle_count=needed - 1), NOW)
    assert (result.config, result.setting) == (None, "market.candle_count")
    assert result.message == "ayar geçersiz: market.candle_count"
