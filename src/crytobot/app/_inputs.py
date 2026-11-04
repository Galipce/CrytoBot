"""Turun girdileri ve denetimleri (spec 0016 R-4, R-12).

Denetim kuralları kopyalanmaz: `risk` ve `strategy`'nin denetimleri public değil, bilinen iyi
girdilerle public fonksiyonları denenir (plan Risk 8). Mesajlar ham değer taşımaz.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum

from crytobot.analysis import Candle
from crytobot.risk import (
    EMPTY_STATE,
    AccountState,
    ApprovalReason,
    PairRules,
    RiskLimits,
    TradeIntent,
    approve_trade,
    observe,
)
from crytobot.strategy import StrategyError, StrategySettings, propose

_PROBE_PAIR = "PROBE/USDT"
_PROBE_EQUITY = Decimal(10000)
_PROBE_INTENT = TradeIntent(_PROBE_PAIR, "buy", Decimal(100), Decimal(90), Decimal(1000))
_PROBE_RULES = PairRules(Decimal(1), Decimal(0), Decimal(0))


@dataclass(frozen=True)
class TurnSettings:
    """Turun ayarları; hiçbirinin varsayılanı yoktur (R-12). Mod alanı yoktur (R-13)."""

    whitelist: Sequence[str]
    limits: RiskLimits
    strategy: StrategySettings
    fee: Decimal | int
    slippage: Decimal | int
    candle_interval: timedelta
    max_candle_age: timedelta
    max_price_age: timedelta


@dataclass(frozen=True)
class PairMarket:
    """Bir çiftin piyasa verisi. Alanlar doğrulanmadan gelir; `None` eksik veridir (R-4)."""

    candles: Sequence[Candle] | None
    price: Decimal | int | None
    price_at: datetime | None
    rules: PairRules | None
    tick: Decimal | int | None
    spread: Decimal | int | None


class DataIssue(Enum):
    STALE = "stale"
    INVALID = "invalid"


def aware(moment: object) -> bool:
    return isinstance(moment, datetime) and moment.utcoffset() is not None


def _costs_valid(
    limits: RiskLimits, rules: object, fee: object, spread: object, slippage: object, now: datetime
) -> bool:
    """Değerler `approve_trade`'in "geçersiz girdi"sinden geçiyor mu; `limits` denetlendi."""
    if not isinstance(rules, PairRules):
        return False
    state = observe(EMPTY_STATE, now, _PROBE_EQUITY, limits).state
    approval = approve_trade(
        _PROBE_INTENT,
        limits,
        AccountState(_PROBE_EQUITY, _PROBE_EQUITY, 0),
        rules,
        frozenset({_PROBE_PAIR}),
        fee,
        spread,
        slippage,
        state,
        now,
    )
    return approval.reason is not ApprovalReason.INVALID_INPUT


def _strategy_problem(strategy: object) -> str | None:
    if not isinstance(strategy, StrategySettings):
        return "strategy"
    try:
        propose(pair=_PROBE_PAIR, candles=(), position_open=True, tick=1, settings=strategy)
    except StrategyError as error:
        return f"strategy: {error}"
    return None


def _whitelist_valid(whitelist: object) -> bool:
    if not isinstance(whitelist, list | tuple):
        return False
    plain = all(type(pair) is str and pair for pair in whitelist)
    return plain and len(set(whitelist)) == len(whitelist)


def settings_problem(settings: object, now: datetime) -> str | None:
    """R-12: ilk geçersiz ya da eksik ayarın adı; hepsi geçerliyse `None`."""
    if not isinstance(settings, TurnSettings):
        return "settings"
    if not _whitelist_valid(settings.whitelist):
        return "whitelist"
    limits = settings.limits
    if not (
        isinstance(limits, RiskLimits) and observe(EMPTY_STATE, now, _PROBE_EQUITY, limits).accepted
    ):
        return "limits"
    strategy = _strategy_problem(settings.strategy)
    if strategy is not None:
        return strategy
    if not _costs_valid(limits, _PROBE_RULES, settings.fee, 0, 0, now):
        return "fee"
    if not _costs_valid(limits, _PROBE_RULES, 0, 0, settings.slippage, now):
        return "slippage"
    interval = settings.candle_interval
    if not (isinstance(interval, timedelta) and interval > timedelta(0)):
        return "candle_interval"
    for name, age in (
        ("max_candle_age", settings.max_candle_age),
        ("max_price_age", settings.max_price_age),
    ):
        if not (isinstance(age, timedelta) and age >= timedelta(0)):
            return name
    return None


def _price_value_valid(price: object) -> bool:
    if isinstance(price, bool) or not isinstance(price, Decimal | int):
        return False
    number = Decimal(price)
    return number.is_finite() and number > 0


def price_issue(data: object, settings: TurnSettings, now: datetime) -> DataIssue | None:
    """R-4: fiyat bayat ya da geçersiz mi; yaşı azami yaşa eşit olan tazedir."""
    if not isinstance(data, PairMarket) or not _price_value_valid(data.price):
        return DataIssue.INVALID
    at = data.price_at
    if not aware(at):
        return DataIssue.INVALID
    assert isinstance(at, datetime)  # checked above
    if at > now:
        return DataIssue.INVALID
    return DataIssue.STALE if now - at > settings.max_price_age else None


def _candle_issue(
    pair: str, data: PairMarket, settings: TurnSettings, now: datetime
) -> DataIssue | None:
    """`propose(position_open=True)` öneri üretmez, seriyi ve tick'i denetler (plan Risk 6)."""
    candles = data.candles
    try:
        propose(
            pair=pair,
            candles=candles,  # type: ignore[arg-type]  # the check is propose's
            position_open=True,
            tick=data.tick,  # type: ignore[arg-type]
            settings=settings.strategy,
        )
    except StrategyError:
        return DataIssue.INVALID
    assert candles is not None  # None is not a series: refused above
    if not candles:
        return DataIssue.INVALID  # missing data; a short series is INSUFFICIENT_HISTORY (Risk 7)
    try:
        closed_at = candles[-1].open_time + settings.candle_interval
    except OverflowError:  # an extreme date (B-9)
        return DataIssue.INVALID
    if closed_at > now:
        return DataIssue.INVALID
    return DataIssue.STALE if now - closed_at > settings.max_candle_age else None


def data_issue(pair: str, data: object, settings: TurnSettings, now: datetime) -> DataIssue | None:
    """R-4: çiftin verisi bayat ya da geçersiz mi. Geçersiz, bayatın önündedir."""
    if not isinstance(data, PairMarket):
        return DataIssue.INVALID
    issues = (
        price_issue(data, settings, now),
        _candle_issue(pair, data, settings, now),
    )
    if DataIssue.INVALID in issues or not _costs_valid(
        settings.limits, data.rules, 0, data.spread, 0, now
    ):
        return DataIssue.INVALID
    return DataIssue.STALE if DataIssue.STALE in issues else None


@dataclass(frozen=True)
class DataReport:
    """`prices`: fiyatı taze çiftler, düz `dict` (B-16). `issues`: sorunlu çiftler, sırayla."""

    prices: dict[str, Decimal | int]
    issues: dict[str, DataIssue]


def read_market(
    market: Mapping[str, object], pairs: Sequence[str], settings: TurnSettings, now: datetime
) -> DataReport:
    """Çiftler: beyaz liste ve açık pozisyonlar. Okumanın yan etkisi yoktur, emirden önce biter."""
    prices: dict[str, Decimal | int] = {}
    issues: dict[str, DataIssue] = {}
    for pair in pairs:
        data = market.get(pair)
        issue = data_issue(pair, data, settings, now)
        if issue is not None:
            issues[pair] = issue
        if isinstance(data, PairMarket) and price_issue(data, settings, now) is None:
            assert data.price is not None  # checked by price_issue
            prices[pair] = data.price
    return DataReport(prices, issues)
