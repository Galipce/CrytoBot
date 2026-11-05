"""Okumanın girdi ve sonuç tipleri, girdi denetimi (spec 0017 R-1, R-15; plan Risk 8, 10)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum

SUPPORTED_EXCHANGE = "binance"
MAX_CANDLE_COUNT = 1000
# Epoch-aligned, fixed-length intervals only: 3d and 1w are not aligned, 1M has no fixed length
# (plan Risk 8). The text is what Binance's klines endpoint expects.
CANDLE_INTERVALS: dict[timedelta, str] = {
    timedelta(minutes=1): "1m",
    timedelta(minutes=3): "3m",
    timedelta(minutes=5): "5m",
    timedelta(minutes=15): "15m",
    timedelta(minutes=30): "30m",
    timedelta(hours=1): "1h",
    timedelta(hours=2): "2h",
    timedelta(hours=4): "4h",
    timedelta(hours=6): "6h",
    timedelta(hours=8): "8h",
    timedelta(hours=12): "12h",
    timedelta(days=1): "1d",
}


class MarketDataError(Exception):
    """Modülün iç hatalarının tabanı; `read_market_data` dışına çıkmaz (R-3)."""


class ReadField(Enum):
    CANDLES = "candles"
    PRICE = "price"
    PRICE_AT = "price_at"
    SPREAD = "spread"
    TICK = "tick"
    RULES = "rules"


class IssueReason(Enum):
    """Eksik ya da güvenilmeyen alanın adı konmuş nedeni; ham yanıt metni taşımaz (R-11)."""

    BUDGET_ENDED = "budget_ended"
    CALL_TIMED_OUT = "call_timed_out"
    NETWORK = "network"
    RATE_LIMITED = "rate_limited"
    BAD_SYMBOL = "bad_symbol"
    EXCHANGE_ERROR = "exchange_error"
    MALFORMED_RESPONSE = "malformed_response"
    UNEXPECTED = "unexpected"
    NOT_LISTED = "not_listed"
    NOT_USDT = "not_usdt"
    NOT_SPOT = "not_spot"
    NOT_TRADING = "not_trading"
    TICK_NOT_REPORTED = "tick_not_reported"
    RULE_NOT_REPORTED = "rule_not_reported"
    NO_CANDLES = "no_candles"
    TOO_MANY_CANDLES = "too_many_candles"
    HIGH_BELOW_LOW = "high_below_low"
    PRICE_OUTSIDE_RANGE = "price_outside_range"
    NOT_POSITIVE = "not_positive"
    NOT_A_NUMBER = "not_a_number"
    DUPLICATE_TIME = "duplicate_time"
    TIME_OUT_OF_ORDER = "time_out_of_order"
    TIME_OFF_INTERVAL = "time_off_interval"
    CANDLE_GAP = "candle_gap"
    NO_LAST_PRICE = "no_last_price"
    NO_STAMP = "no_stamp"
    CLOCK_DRIFT = "clock_drift"
    PRICE_FINER_THAN_TICK = "price_finer_than_tick"
    NO_BID = "no_bid"
    NO_ASK = "no_ask"
    BID_ABOVE_ASK = "bid_above_ask"
    SPREAD_TOO_WIDE = "spread_too_wide"


class InputProblem(Enum):
    """Borsaya çağrı gitmeden reddedilen girdinin adı (R-15)."""

    SETTINGS = "settings"
    EXCHANGE = "exchange"
    CANDLE_INTERVAL = "candle_interval"
    CANDLE_COUNT = "candle_count"
    CALL_TIMEOUT = "call_timeout"
    READ_BUDGET = "read_budget"
    PAIRS = "pairs"
    PAIR_NOT_TEXT = "pair_not_text"
    PAIR_DUPLICATE = "pair_duplicate"
    CLOCK = "clock"


@dataclass(frozen=True, slots=True)
class ReadSettings:
    """Okumanın ayarları; hiçbirinin varsayılanı yoktur (R-15)."""

    exchange: str
    candle_interval: timedelta
    candle_count: int
    call_timeout: timedelta
    read_budget: timedelta


@dataclass(frozen=True, slots=True)
class MarketCandle:
    """Kapanmış bir mum; değerler borsanın bildirdiği metinle birebir aynıdır (R-9)."""

    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True, slots=True)
class MarketRules:
    """Çiftin borsa kuralları; bildirilmeyen değer 0 sayılmaz, kurallar eksik döner (R-14)."""

    amount_step: Decimal
    min_amount: Decimal
    min_notional: Decimal


@dataclass(frozen=True, slots=True)
class ReadIssue:
    field: ReadField
    reason: IssueReason


@dataclass(frozen=True, slots=True)
class PairRead:
    """Bir çiftin okuması: eksik alan `None`, nedeni `issues`'tadır."""

    pair: str
    candles: tuple[MarketCandle, ...] | None
    price: Decimal | None
    price_at: datetime | None
    spread: Decimal | None
    tick: Decimal | None
    rules: MarketRules | None
    issues: tuple[ReadIssue, ...]


@dataclass(frozen=True, slots=True)
class MarketRead:
    """Okumanın sonucu: `pairs` istek sırasıyla; ret: `pairs` boş, `input_problem` dolu.

    `read_at` okumanın son saat değeridir, `run_turn`'ün `now`'ı odur (plan Risk 4). Yalnız saat
    reddinde değil her retde `None`'dır; bu değerle `run_turn` `INVALID_TIME` döner.
    """

    pairs: tuple[PairRead, ...]
    read_at: datetime | None
    input_problem: InputProblem | None


def _positive_duration(value: object) -> bool:
    return isinstance(value, timedelta) and value > timedelta(0)


def settings_problem(settings: object) -> InputProblem | None:
    """İlk geçersiz ya da eksik ayarın adı; hepsi geçerliyse `None`."""
    if not isinstance(settings, ReadSettings):
        return InputProblem.SETTINGS
    exchange: object = settings.exchange
    if type(exchange) is not str or exchange != SUPPORTED_EXCHANGE:
        return InputProblem.EXCHANGE
    interval: object = settings.candle_interval
    if not (isinstance(interval, timedelta) and interval in CANDLE_INTERVALS):
        return InputProblem.CANDLE_INTERVAL
    count: object = settings.candle_count
    if not (type(count) is int and 1 <= count <= MAX_CANDLE_COUNT):
        return InputProblem.CANDLE_COUNT
    if not _positive_duration(settings.call_timeout):
        return InputProblem.CALL_TIMEOUT
    if not _positive_duration(settings.read_budget):
        return InputProblem.READ_BUDGET
    return None


def pairs_problem(pairs: object) -> InputProblem | None:
    """Liste, metin ve tekrar denetimi; çiftin borsadaki durumu `_pairs`'tadır (R-14)."""
    if not isinstance(pairs, list | tuple):
        return InputProblem.PAIRS
    named: Sequence[object] = pairs
    if not all(type(pair) is str and pair for pair in named):
        return InputProblem.PAIR_NOT_TEXT
    if len(set(named)) != len(named):
        return InputProblem.PAIR_DUPLICATE
    return None
