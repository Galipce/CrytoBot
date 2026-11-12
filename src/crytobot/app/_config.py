"""Ayar dosyasının eşlemi → `BotConfig` (spec 0022 R-2, R-3, R-7; plan Risk 4).

Hiçbir ayarın varsayılanı yoktur, bilinmeyen anahtar ve bölüm reddedilir. İstisnalar
`[history]` (spec 0024) ve `[backtest]` (spec 0026) bölümleridir: adları tam olarak tanınır ve
değerlerine bakılmadan geçilir; içlerini indirme (0023) ve backtest (0025) yükleyicileri denetler.
Sorun ayarın `bölüm.anahtar` adıyla söylenir; ham değer
mesaja yazılmaz. Önce her ayarın varlığı ve biçimi, sonra anlamı
denetlenir, ikisi de dosya sırasıyla. Para ve oranlar metin (`"0.01"`) ya da tam sayıdır, `float`
kabul edilmez; süreler saniye, aralıklar Binance metni (`"1h"`). Limit alanları sabit bir
iskeletin içinde tek tek denenir: iskelet yalnız denetim içindir, değer olarak kullanılmaz. Sonra
`settings_problem` ve okumanın denetimi bütüne bakar. Denetim kuralları kopyalanmaz.

Spec 0043 R-1 (plan Risk 3): `[strategy] name` isteğe bağlıdır ("S0"…"S3", yoksa S0 ve bugünkü
davranış); bölümün anahtarları seçilen adayınkilerdir. Bilinmeyen ad `ayar geçersiz: strategy.name`,
adayın eksik anahtarı `ayar eksik: strategy.<alan>`, adaya ait olmayan anahtar `bilinmeyen ayar:
strategy.<alan>` (etkisiz bir ayara güvenilmesin). `SETTING_NAMES` S0'ın şemasıdır. R-4: mum sayısı
adayın `required_candles`'ından azsa `ayar geçersiz: market.candle_count`.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from crytobot.app._inputs import TurnSettings, settings_problem
from crytobot.market_data import CANDLE_INTERVALS, ReadSettings, read_settings_problem
from crytobot.portfolio import EMPTY_LEDGER, LedgerOutcome, open_ledger
from crytobot.risk import DEFAULT_LIMITS, EMPTY_STATE, RiskLimits, observe
from crytobot.strategy import (
    InvalidInputError,
    Settings,
    StrategyError,
    StrategySettings,
    candidate,
    candidate_parameters,
    propose,
    required_candles,
)

_PROBE_EQUITY = Decimal(10000)
_PROBE_PAIR = "PROBE/USDT"
# Known-good strategy for judging the other sections alone; never a value of the bot
_PROBE_STRATEGY = StrategySettings(1, 2, 2, Decimal(70), 2, Decimal(2), Decimal(2))
_INTERVALS_BY_TEXT = {text: interval for interval, text in CANDLE_INTERVALS.items()}
_DIGITS = frozenset("0123456789")
# Specs 0024, 0026, 0028, 0029, 0033: their contents are judged by loaders
# (0023, 0025, 0028, 0029, 0032/0033); the bot never reads them; matched by exact name only
_PASSED_SECTIONS = frozenset({"history", "backtest", "stage", "reporting", "dashboard", "exchange"})


@dataclass(frozen=True)
class BotConfig:
    """Botun bütün ayarları."""

    store_path: str
    log_path: str
    turn_interval: timedelta
    opening_balance: Decimal
    read: ReadSettings
    turn: TurnSettings
    mode: str = "paper"


@dataclass(frozen=True)
class ConfigResult:
    """`config` yalnız her ayar geçerliyse doludur; değilse `setting` ilk sorunlu ayarın adıdır."""

    config: BotConfig | None
    setting: str | None
    message: str


class _Bad(Exception):
    """Bir ayar geçersiz; yalnız `app` içinde, `load_config` dışına çıkmaz."""


def _text(value: object) -> str:
    if type(value) is not str or not value:
        raise _Bad
    return value


def _interval(value: object) -> timedelta:
    interval = _INTERVALS_BY_TEXT.get(_text(value))
    if interval is None:
        raise _Bad
    return interval


def _seconds(value: object) -> timedelta:
    if type(value) is not int or value < 0:
        raise _Bad
    try:
        return timedelta(seconds=value)
    except OverflowError:
        raise _Bad from None


def _whole(value: object) -> int:
    if type(value) is not int:
        raise _Bad
    return value


def _plain_decimal(text: str) -> bool:
    body = text[1:] if text.startswith("-") else text
    whole, _, fraction = body.partition(".")
    return bool(whole) and set(whole) <= _DIGITS and set(fraction) <= _DIGITS


def _number(value: object) -> Decimal | int:
    """Tam sayı ya da düz ondalık metin; `float`, `bool`, `1e3`, `NaN` ve `1_000` reddedilir."""
    if type(value) is int:
        return value
    text = _text(value)
    if not _plain_decimal(text) or text.endswith("."):
        raise _Bad
    try:
        return Decimal(text)
    except InvalidOperation:  # pragma: no cover - a plain decimal text always converts
        raise _Bad from None


def _whitelist(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _Bad
    return tuple(value)  # each pair is judged by the turn's own check


def _mode(value: object) -> str:
    if type(value) is not str or value not in ("paper", "live"):
        raise _Bad
    return value


_Parse = Callable[[object], object]

# File order: the first problem named is the first in this order (plan Risk 4)
_SCHEMA: tuple[tuple[str, tuple[tuple[str, _Parse], ...]], ...] = (
    (
        "bot",
        (
            ("store_path", _text),
            ("log_path", _text),
            ("turn_interval", _interval),
            ("opening_balance", _number),
        ),
    ),
    (
        "market",
        (
            ("exchange", _text),
            ("candle_interval", _interval),
            ("candle_count", _whole),
            ("call_timeout", _seconds),
            ("read_budget", _seconds),
        ),
    ),
    (
        "turn",
        (
            ("whitelist", _whitelist),
            ("fee", _number),
            ("slippage", _number),
            ("max_candle_age", _seconds),
            ("max_price_age", _seconds),
        ),
    ),
    (
        "risk",
        (
            ("per_trade_risk", _number),
            ("daily_loss_limit", _number),
            ("max_drawdown", _number),
            ("max_open_positions", _whole),
            ("profit_cost_multiple", _number),
        ),
    ),
    (
        "strategy",
        (
            ("fast_period", _whole),
            ("slow_period", _whole),
            ("rsi_period", _whole),
            ("rsi_threshold", _number),
            ("atr_period", _whole),
            ("k", _number),
            ("r", _number),
        ),
    ),
)

SETTING_NAMES: tuple[str, ...] = tuple(
    f"{section}.{key}" for section, keys in _SCHEMA for key, _ in keys
)


class _Problem(Exception):
    def __init__(self, setting: str, message: str) -> None:
        super().__init__(setting)
        self.setting = setting
        self.message = message


def _missing(name: str) -> _Problem:
    return _Problem(name, f"ayar eksik: {name}")


def _invalid(name: str) -> _Problem:
    return _Problem(name, f"ayar geçersiz: {name}")


_STRATEGY_SECTION = "strategy"
_DEFAULT_STRATEGY = StrategySettings.name
_NUMBERS = frozenset({"rsi_threshold", "k", "r"})  # the rest are periods, whole numbers


def _strategy_keys(table: Mapping[object, object]) -> tuple[tuple[str, _Parse], ...]:
    """R-1: seçilen adayın anahtarları; ad yoksa S0. Ad denetimi anahtarlardan öncedir."""
    name = table.get("name", _DEFAULT_STRATEGY)
    keys = candidate_parameters(name) if type(name) is str else None
    if keys is None:
        raise _invalid(f"{_STRATEGY_SECTION}.name")
    return tuple((key, _number if key in _NUMBERS else _whole) for key in keys)


def _parse(document: object) -> dict[str, object]:
    if not isinstance(document, Mapping):
        raise _invalid("ayar dosyası")
    values: dict[str, object] = {}
    for section, schema_keys in _SCHEMA:
        table = document.get(section)
        if table is None:
            raise _missing(section)
        if not isinstance(table, Mapping):
            raise _invalid(section)
        keys = schema_keys
        if section == _STRATEGY_SECTION:
            keys = _strategy_keys(table)
            values["strategy.name"] = table.get("name", _DEFAULT_STRATEGY)
        for key, parse in keys:
            name = f"{section}.{key}"
            if key not in table:
                raise _missing(name)
            try:
                values[name] = parse(table[key])
            except _Bad:
                raise _invalid(name) from None
        known = {key for key, _ in keys}
        if section == "bot":
            known.add("mode")
        if section == _STRATEGY_SECTION:
            known.add("name")
        for key in table:
            if key not in known:
                raise _Problem(f"{section}.{key}", f"bilinmeyen ayar: {section}.{key}")
    bot_table = document.get("bot")
    mode = "paper"
    if isinstance(bot_table, Mapping) and "mode" in bot_table:
        try:
            mode = _mode(bot_table["mode"])
        except _Bad:
            raise _invalid("bot.mode") from None
    values["bot.mode"] = mode
    for section in document:
        if section in _PASSED_SECTIONS:
            continue
        if section not in {name for name, _ in _SCHEMA}:
            raise _Problem(str(section), f"bilinmeyen ayar: {section}")
    return values


def _limits(values: Mapping[str, object], now: datetime) -> RiskLimits:
    names = (
        "per_trade_risk",
        "daily_loss_limit",
        "max_drawdown",
        "max_open_positions",
        "profit_cost_multiple",
    )
    for key in names:
        probe = replace(DEFAULT_LIMITS, **{key: values[f"risk.{key}"]})  # type: ignore[arg-type]
        if not observe(EMPTY_STATE, now, _PROBE_EQUITY, probe).accepted:
            raise _invalid(f"risk.{key}")
    return RiskLimits(*(values[f"risk.{key}"] for key in names))  # type: ignore[arg-type]


def _strategy(values: Mapping[str, object]) -> Settings:
    """Seçilen adayın ayarı (R-1); anlamı `propose`'un kendi denetimiyle, alan adıyla."""
    kind = candidate(values["strategy.name"])
    keys = candidate_parameters(values["strategy.name"])
    assert kind is not None and keys is not None  # the name was judged by `_parse`
    strategy = kind(**{key: values[f"strategy.{key}"] for key in keys})  # type: ignore[arg-type]
    try:
        propose(pair=_PROBE_PAIR, candles=(), position_open=True, tick=1, settings=strategy)
    except InvalidInputError as error:
        raise _invalid(f"strategy.{error.name}") from None
    except StrategyError:  # pragma: no cover - settings fail only by name
        raise _invalid("strategy") from None
    return strategy


def _read(values: Mapping[str, object], turn_interval: timedelta) -> ReadSettings:
    read = ReadSettings(
        values["market.exchange"],  # type: ignore[arg-type]
        values["market.candle_interval"],  # type: ignore[arg-type]
        values["market.candle_count"],  # type: ignore[arg-type]
        values["market.call_timeout"],  # type: ignore[arg-type]
        values["market.read_budget"],  # type: ignore[arg-type]
    )
    problem = read_settings_problem(read)
    if problem is not None:
        raise _invalid(f"market.{problem.value}")
    if read.read_budget >= turn_interval:  # R-2: a read never runs into the next boundary
        raise _invalid("market.read_budget")
    return read


def _turn(values: Mapping[str, object], now: datetime) -> TurnSettings:
    turn = TurnSettings(
        values["turn.whitelist"],  # type: ignore[arg-type]
        DEFAULT_LIMITS,
        _PROBE_STRATEGY,
        values["turn.fee"],  # type: ignore[arg-type]
        values["turn.slippage"],  # type: ignore[arg-type]
        values["market.candle_interval"],  # type: ignore[arg-type]
        values["turn.max_candle_age"],  # type: ignore[arg-type]
        values["turn.max_price_age"],  # type: ignore[arg-type]
    )
    problem = settings_problem(turn, now)
    if problem is not None:  # every other name was judged above, these are the turn's own
        raise _invalid(f"turn.{problem}")
    return turn


def _config(values: Mapping[str, object], now: datetime) -> BotConfig:
    store_path, log_path = values["bot.store_path"], values["bot.log_path"]
    if log_path == store_path:
        raise _invalid("bot.log_path")
    turn_interval = values["bot.turn_interval"]
    assert isinstance(turn_interval, timedelta)  # parsed above
    if turn_interval < values["market.candle_interval"]:  # type: ignore[operator]
        raise _invalid("bot.turn_interval")  # R-7
    balance = values["bot.opening_balance"]
    assert isinstance(balance, Decimal | int)  # parsed above
    if open_ledger(EMPTY_LEDGER, balance, now).outcome is not LedgerOutcome.OPENED:
        raise _invalid("bot.opening_balance")  # R-3: the ledger's own digit limits
    read = _read(values, turn_interval)
    turn = _turn(values, now)
    strategy = _strategy(values)
    if read.candle_count < required_candles(strategy):  # spec 0043 R-4: the longest indicator
        raise _invalid("market.candle_count")
    turn = replace(turn, limits=_limits(values, now), strategy=strategy)
    if settings_problem(turn, now) is not None:  # pragma: no cover - each part passed alone
        raise _invalid("turn")
    mode = str(values.get("bot.mode", "paper"))
    return BotConfig(
        str(store_path),
        str(log_path),
        turn_interval,
        Decimal(balance),
        read,
        turn,
        mode=mode,
    )


def load_config(document: object, now: datetime) -> ConfigResult:
    """R-2: ayar eşlemi geçerliyse `BotConfig`; değilse ilk sorunlu ayarın adı. Dokunmaz, okumaz.

    `now` yalnız denetimlerin zamanıdır (defter ve risk denetimi zaman ister).
    """
    try:
        config = _config(_parse(document), now)
    except _Problem as problem:
        return ConfigResult(None, problem.setting, problem.message)
    return ConfigResult(config, None, "ayarlar geçerli")
