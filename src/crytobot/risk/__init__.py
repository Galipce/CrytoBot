"""Her işlem önerisini iş kurallarına göre onaylamak/reddetmek, pozisyon boyutlamak.

Risk limitleri config'in `[risk]` tablosundan okunur: `per_trade_risk`, `daily_loss_limit`,
`max_drawdown` (kasaya oran, `0.01` = %1) ve `max_open_positions` (tam sayı).
Sabit üst sınırlar: `HARD_CAPS`. Alım önerileri `approve_trade` ile onaylanır: stop zorunlu, miktar
risk bütçesi ve serbest bakiyeyle sınırlı, borsa adımına aşağı yuvarlanmış.
"""

from crytobot.risk._approval import (
    AccountState,
    ApprovalReason,
    PairRules,
    TradeApproval,
    TradeIntent,
    approve_trade,
)
from crytobot.risk._limits import (
    DEFAULT_LIMITS,
    HARD_CAPS,
    ChangeDecision,
    Channel,
    LimitChange,
    LoadedLimits,
    RejectReason,
    RiskConfigError,
    RiskError,
    RiskLimits,
    decide_change,
    load_limits,
)

__all__: list[str] = [
    "DEFAULT_LIMITS",
    "HARD_CAPS",
    "AccountState",
    "ApprovalReason",
    "ChangeDecision",
    "Channel",
    "LimitChange",
    "LoadedLimits",
    "PairRules",
    "RejectReason",
    "RiskConfigError",
    "RiskError",
    "RiskLimits",
    "TradeApproval",
    "TradeIntent",
    "approve_trade",
    "decide_change",
    "load_limits",
]
