"""Her işlem önerisini iş kurallarına göre onaylamak/reddetmek, pozisyon boyutlamak.

Risk limitleri config'in `[risk]` tablosundan okunur: `per_trade_risk`, `daily_loss_limit`,
`max_drawdown` (kasaya oran, `0.01` = %1), `max_open_positions` (tam sayı) ve
`profit_cost_multiple` (kâr/maliyet katı). Sabit üst sınırlar: `HARD_CAPS`; katın alt sınırı:
`HARD_FLOOR_MULTIPLE`. Alım önerileri `approve_trade` ile onaylanır: stop zorunlu, miktar
risk bütçesi ve serbest bakiyeyle sınırlı, borsa adımına aşağı yuvarlanmış.
Kasa `observe` ile `RiskState`'e gözlenir (gün başı, zirve, drawdown durdurması); onay bu
durumu ister ve günlük zarar ya da drawdown limitinde reddeder; durdurmayı yalnızca CLI `resume`
ile kaldırır. Önerinin hedefe kadar beklenen kârı, efektif maliyetin (komisyon + spread +
slippage) katını geçmiyorsa öneri reddedilir. Onay sonucu karara bağladığı öneriyi değiştirmeden
taşır (`TradeApproval.intent`); `execution` emri yalnızca o öneriden oluşturur.
Açık pozisyonun stop ya da hedefte kapanışı yeni işlem değildir (spec 0009): `approve_close`
talebi yalnızca biçimine bakarak onaylar — hiçbir giriş limiti, beyaz liste ya da kill switch
kapanışı engellemez; `execution` satışı yalnızca bu onaydan oluşturur (BR-9).
"""

from crytobot.risk._approval import (
    AccountState,
    ApprovalReason,
    PairRules,
    TradeApproval,
    TradeIntent,
    approve_trade,
)
from crytobot.risk._close import (
    CLOSE_REASONS,
    CloseApproval,
    CloseRefusal,
    CloseRequest,
    approve_close,
    close_request_problems,
)
from crytobot.risk._limits import (
    DEFAULT_LIMITS,
    HARD_CAPS,
    HARD_FLOOR_MULTIPLE,
    ChangeDecision,
    Channel,
    HardCaps,
    LimitChange,
    LoadedLimits,
    RejectReason,
    RiskConfigError,
    RiskError,
    RiskLimits,
    decide_change,
    load_limits,
)
from crytobot.risk._tracking import (
    EMPTY_STATE,
    RiskState,
    StateUpdate,
    TrackingReason,
    observe,
    resume,
)

__all__: list[str] = [
    "CLOSE_REASONS",
    "DEFAULT_LIMITS",
    "EMPTY_STATE",
    "HARD_CAPS",
    "HARD_FLOOR_MULTIPLE",
    "AccountState",
    "ApprovalReason",
    "ChangeDecision",
    "Channel",
    "CloseApproval",
    "CloseRefusal",
    "CloseRequest",
    "HardCaps",
    "LimitChange",
    "LoadedLimits",
    "PairRules",
    "RejectReason",
    "RiskConfigError",
    "RiskError",
    "RiskLimits",
    "RiskState",
    "StateUpdate",
    "TrackingReason",
    "TradeApproval",
    "TradeIntent",
    "approve_close",
    "approve_trade",
    "close_request_problems",
    "decide_change",
    "load_limits",
    "observe",
    "resume",
]
