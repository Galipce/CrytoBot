"""LLM paper ölçümünün ayarı ve ön kayıtlı sabitleri (spec 0060 R-1, AC-1, C-1...C-8, G-1...G-9).

`crytobot-llm-paper.toml`'un `[llm_paper]` bölümünde yalnız yollar ve istek aralığı vardır. Ölçüm
anları, süre, tohum, tekrar sayısı, eşikler, kasa, maliyet ve risk ayarları spec'te ön kayıtlıdır ve
burada sabittir: ayarda verilirse ret (adıyla). Bot ayarı sonradan değişse de ölçüm değişmez. Yollar
zorunlu ve birbirinden farklıdır; çözülmüş karşılaştırma giriş noktasındadır. İlk sorun adıyla
söylenir, ham değer yazılmaz.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crytobot.risk import RiskLimits

SECTION = "llm_paper"
# spec 0061 CB-5 / G-1 (ADR 0007, 20 coins): a fixed 00:00 UTC after the new code is deployed;
# the exact moment is written at ship (spec 0060's 2026-11-20T03:00Z period is superseded)
MEASUREMENT_START = datetime(2026, 11, 22, tzinfo=UTC)
MEASUREMENT_DAYS = 90
MEASUREMENT_SPAN = timedelta(days=MEASUREMENT_DAYS)
MEASUREMENT_END = MEASUREMENT_START + MEASUREMENT_SPAN
# C-5: matched random entries
RANDOM_SEED = 60
RANDOM_REPEATS = 1000
# C-7 and R-7: the pre-registered verdict
MIN_CLOSED_TRADES = 30
MIN_PROFIT_FACTOR = Decimal("1.2")
MAX_DRAWDOWN = Decimal("0.15")
RANDOM_PERCENTILE = 95
MAX_BAD_DECISIONS = Decimal("0.20")
# C-2, C-3, C-4: the same as the ADR 0004 S0 run
OPENING_BALANCE = Decimal("100")
FEE = Decimal("0.001")
SLIPPAGE = Decimal("0.001")
SPREAD = Decimal("0")  # no spread data in a replay; the slippage covers it (plan Risk 4)
MAX_HOLD = timedelta(days=7)
LIMITS = RiskLimits(
    per_trade_risk=Decimal("0.01"),
    daily_loss_limit=Decimal("0.03"),
    max_drawdown=Decimal("0.15"),
    max_open_positions=5,
    profit_cost_multiple=Decimal("2"),
)
QUOTE = "USDT"
MIN_GAP_S = 1

_PATH_KEYS = (
    "decide_store_path",
    "s0_store_path",
    "price_store_path",
    "rules_path",
    "report_path",
    "trades_path",
)
_KEYS = (*_PATH_KEYS, "request_gap_s")
# names of the pre-registered numbers: given in the file they are refused by name (AC-1)
PREREGISTERED_KEYS = (
    "start",
    "end",
    "days",
    "seed",
    "repeats",
    "min_trades",
    "min_profit_factor",
    "max_drawdown",
    "percentile",
    "opening_balance",
    "fee",
    "slippage",
    "spread",
    "per_trade_risk",
    "daily_loss_limit",
    "max_open_positions",
    "profit_cost_multiple",
    "max_hold_days",
)


@dataclass(frozen=True)
class LlmPaperConfig:
    decide_store_path: str
    s0_store_path: str
    price_store_path: str
    rules_path: str
    report_path: str
    trades_path: str
    request_gap_s: int

    @property
    def outputs(self) -> tuple[str, ...]:
        return (self.price_store_path, self.rules_path, self.report_path, self.trades_path)


@dataclass(frozen=True)
class LlmPaperConfigResult:
    config: LlmPaperConfig | None
    message: str


class _Problem(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _name(key: str) -> str:
    return f"{SECTION}.{key}"


def _path(table: Mapping[object, object], key: str, taken: list[str]) -> str:
    if key not in table:
        raise _Problem(f"ayar eksik: {_name(key)}")
    value = table[key]
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 2048
        or any(not char.isprintable() for char in value)
        or value in taken
    ):
        raise _Problem(f"ayar geçersiz: {_name(key)}")
    taken.append(value)
    return value


def _section(document: Mapping[object, object]) -> LlmPaperConfig:
    for name in document:
        if name != SECTION:
            raise _Problem(f"bilinmeyen ayar: {name}")
    table = document.get(SECTION)
    if table is None:
        raise _Problem(f"ayar eksik: {SECTION}")
    if not isinstance(table, Mapping):
        raise _Problem(f"ayar geçersiz: {SECTION}")
    for key in table:
        if key in PREREGISTERED_KEYS:
            raise _Problem(f"ön kayıtlı, ayarlanamaz: {_name(str(key))} (spec 0060)")
        if key not in _KEYS:
            raise _Problem(f"bilinmeyen ayar: {_name(str(key))}")
    taken: list[str] = []
    decide, s0, prices, rules, report, trades = (_path(table, key, taken) for key in _PATH_KEYS)
    gap = table.get("request_gap_s", MIN_GAP_S)
    if type(gap) is not int or not MIN_GAP_S <= gap <= 60:
        raise _Problem(f"ayar geçersiz: {_name('request_gap_s')}")
    return LlmPaperConfig(decide, s0, prices, rules, report, trades, gap)


def load_llm_paper_config(document: object) -> LlmPaperConfigResult:
    """`[llm_paper]` geçerliyse ayar; değilse ilk sorunun adını veren mesaj."""
    if not isinstance(document, Mapping):
        return LlmPaperConfigResult(None, f"ayar geçersiz: {SECTION}")
    try:
        config = _section(document)
    except _Problem as problem:
        return LlmPaperConfigResult(None, problem.message)
    return LlmPaperConfigResult(config, "ayarlar geçerli")
