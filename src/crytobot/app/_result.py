"""Turun adı konmuş sonucu (spec 0016 R-11): tur istisna fırlatmaz, ne olduğunu burada söyler."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from crytobot.execution import CloseOrder, Order, OrderOutcome
from crytobot.portfolio import Closure
from crytobot.risk import ApprovalReason
from crytobot.strategy import NoProposalReason


class TurnOutcome(Enum):
    """Tur nasıl bitti. `COMPLETED` dışındakilerde kalan adımlar yapılmamıştır."""

    COMPLETED = "completed"
    INVALID_SETTINGS = "invalid_settings"
    INVALID_TIME = "invalid_time"
    STORE_UNAVAILABLE = "store_unavailable"
    LEDGER_NOT_OPENED = "ledger_not_opened"
    SAVE_REFUSED = "save_refused"
    UNEXPECTED_ERROR = "unexpected_error"


class BuyHalt(Enum):
    """O turda uygulanan durdurma. `DRAWDOWN` yalnız bilgidir: alımı `risk` reddeder (R-8)."""

    STALE_DATA = "stale_data"
    INVALID_DATA = "invalid_data"
    UNKNOWN_ORDERS = "unknown_orders"
    RECONCILIATION = "reconciliation"
    RECONCILIATION_HALT = "reconciliation_halt"
    BALANCE_CHECK_FAILED = "balance_check_failed"
    SAVE_REFUSED = "save_refused"
    HISTORY_IMMUTABLE = "history_immutable"
    OBSERVATION_REJECTED = "observation_rejected"
    DRAWDOWN = "drawdown"
    KILL_SWITCH = "kill_switch"
    STOP_ORDER_FAILED = "stop_order_failed"
    POSITION_BELOW_MINIMUM = "position_below_minimum"


class PairNote(Enum):
    """`app`'in çift başına nedenleri: tekrar koruması (R-3), dolum kapıları (Risk 1, 2, A-1;
    spec 0020 R-2, R-4)."""

    ALREADY_ORDERED = "already_ordered"
    FILL_EXCEEDS_BALANCE = "fill_exceeds_balance"
    RISK_CAP_AT_FILL = "risk_cap_at_fill"
    FILL_OUTSIDE_STOP_TARGET = "fill_outside_stop_target"
    RISK_LIMIT_AT_FILL = "risk_limit_at_fill"
    INSUFFICIENT_EDGE_AT_FILL = "insufficient_edge_at_fill"


@dataclass(frozen=True)
class PairOutcome:
    """Çiftin emir oluşmadan biten sonucu (R-9): "öneri yok", `risk` reddi, emir reddi ya da not."""

    pair: str
    reason: NoProposalReason | ApprovalReason | OrderOutcome | PairNote
    message: str


@dataclass(frozen=True)
class TurnResult:
    """`closes` ve `buys`: bu turda oluşan ya da durumu netleşen emirler; durumlarını taşırlar."""

    outcome: TurnOutcome
    closes: tuple[CloseOrder, ...]
    buys: tuple[Order, ...]
    pairs: tuple[PairOutcome, ...]
    halts: tuple[BuyHalt, ...]
    notice_errors: tuple[str, ...]
    message: str
    closures: tuple[Closure, ...] = ()
    equity: Decimal | None = None
