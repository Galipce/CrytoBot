"""Her işlem önerisini iş kurallarına göre onaylamak/reddetmek, pozisyon boyutlamak.

Risk limitleri config'in `[risk]` tablosundan okunur: `per_trade_risk`, `daily_loss_limit`,
`max_drawdown` (kasaya oran, `0.01` = %1) ve `max_open_positions` (tam sayı).
Sabit üst sınırlar: `HARD_CAPS`.
"""

from crytobot.risk._limits import (
    DEFAULT_LIMITS,
    HARD_CAPS,
    LoadedLimits,
    RejectReason,
    RiskConfigError,
    RiskError,
    RiskLimits,
    load_limits,
)

__all__: list[str] = [
    "DEFAULT_LIMITS",
    "HARD_CAPS",
    "LoadedLimits",
    "RejectReason",
    "RiskConfigError",
    "RiskError",
    "RiskLimits",
    "load_limits",
]
