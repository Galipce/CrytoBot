"""Durum bildirimleri (spec 0016 R-10): süren durum için yalnız giriş ve çıkış.

Hafıza kalıcı değildir: `TurnMemory` süreç belleğidir, yeni nesne yeniden başlatmadır (plan Risk 5).
Bildirimin tek kaynağı budur; `execution`'ın `Notification`'ı iletilmez (plan Risk 11).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class NoticeKind(Enum):
    INVALID_TIME = "invalid_time"
    STORE_UNAVAILABLE = "store_unavailable"
    LEDGER_NOT_OPENED = "ledger_not_opened"
    STALE_DATA = "stale_data"
    INVALID_DATA = "invalid_data"
    SAFE_MODE = "safe_mode"
    RECONCILIATION = "reconciliation"
    SAVE_REFUSED = "save_refused"
    HISTORY_IMMUTABLE = "history_immutable"
    OBSERVATION_REJECTED = "observation_rejected"
    CLOSE_REFUSED = "close_refused"
    UNEXPECTED_ERROR = "unexpected_error"
    DRAWDOWN_HALT = "drawdown_halt"
    DAILY_LOSS_LIMIT = "daily_loss_limit"


# Absence ends only these: every completed turn evaluates them. Any other state ends with `clear`
# or `evaluated`, so what a turn did not evaluate gets no exit (R-10)
_EVALUATED_EVERY_TURN = frozenset(
    {
        NoticeKind.STALE_DATA,
        NoticeKind.INVALID_DATA,
        NoticeKind.RECONCILIATION,
        NoticeKind.CLOSE_REFUSED,
        NoticeKind.UNEXPECTED_ERROR,
    }
)
# about the account, not a pair: evaluated only when the ledger is asked for the equity
_ACCOUNT_INVALID_DATA = (NoticeKind.INVALID_DATA, "")


def _ended_by_absence(key: tuple[NoticeKind, str]) -> bool:
    return key[0] in _EVALUATED_EVERY_TURN and key != _ACCOUNT_INVALID_DATA


@dataclass(frozen=True)
class TurnNotice:
    """`entering`: durum başladı (`True`) ya da bitti (`False`). `subject`: çift ya da kimlik."""

    kind: NoticeKind
    subject: str
    entering: bool
    at: object
    message: str


@dataclass
class TurnMemory:
    """Süreç belleği: süren durumlar ve "geçmiş değiştirilemez" durdurması (R-6, R-10)."""

    active: set[tuple[NoticeKind, str]] = field(default_factory=set)
    history_halted: bool = False
    retry_after: float | None = None


class Notices:
    """Bir turun bildirimleri: durumları hafızayla karşılaştırır, geçişleri alıcıya iletir."""

    def __init__(self, memory: TurnMemory, sink: Callable[[TurnNotice], None], now: object) -> None:
        self._memory = memory
        self._sink = sink
        self._now = now
        self._touched: set[tuple[NoticeKind, str]] = set()
        self._evaluated: set[tuple[NoticeKind, str]] = set()
        self.errors: list[str] = []

    def _send(self, key: tuple[NoticeKind, str], entering: bool, message: str) -> None:
        try:
            self._sink(TurnNotice(key[0], key[1], entering, self._now, message))
        except Exception as error:  # R-10: the flow goes on; the text could hold a secret
            self.errors.append(type(error).__name__)

    def enter(self, kind: NoticeKind, subject: str, message: str) -> None:
        """Durum sürüyor; hafızada yoksa giriş bildirimi."""
        key = (kind, subject)
        self._touched.add(key)
        if key not in self._memory.active:
            self._memory.active.add(key)
            self._send(key, True, message)

    def clear(self, kind: NoticeKind, subject: str = "") -> None:
        """Durum bitti; hafızadaysa çıkış bildirimi."""
        key = (kind, subject)
        self._touched.discard(key)
        if key in self._memory.active:
            self._memory.active.remove(key)
            self._send(key, False, f"{kind.value}: durum düzeldi")

    def keep(self, kind: NoticeKind, subject: str = "") -> None:
        """Durum bu tur değerlendirilmedi: varsa sürüyor sayılır, çıkış üretilmez (R-10)."""
        key = (kind, subject)
        if key in self._memory.active:
            self._touched.add(key)

    def evaluated(self, kind: NoticeKind, subject: str = "") -> None:
        """Durum bu tur değerlendirildi; tur tamamlanırsa bitmiş sayılır, erken biterse sürer."""
        self._evaluated.add((kind, subject))

    def settle(self) -> None:
        """Tamamlanan turda, değerlendirilip bu tur görülmeyen durumlar bitmiştir. Erken biten
        turda çağrılmaz; değerlendirilmeyene çıkış yok (Risk 11, review round 2 F-2)."""
        unseen = self._memory.active - self._touched
        ended = {key for key in unseen if _ended_by_absence(key) or key in self._evaluated}
        for kind, subject in sorted(ended, key=lambda key: (key[0].value, key[1])):
            self.clear(kind, subject)
