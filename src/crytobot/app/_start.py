"""Hazırlık ve başlatmanın depo kapıları (spec 0022 R-1, R-3, R-4, R-5, R-9; plan Risk 8, 12).

Depoyu yalnız hazırlık oluşturur, başlatma asla: silinmiş bir depo drawdown durdurmasını sessizce
sıfırlayamaz (BR-6). Her ikisi de yalnız paper'dır; live depo "mod uyuşmuyor" ile reddedilir.
Hazırlık tur atmaz ve borsaya çıkmaz. Depo dosyası hiçbir durumda otomatik silinmez.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from crytobot.execution import PAPER
from crytobot.persistence import StoreOutcome, create_store, load_store, save_store
from crytobot.portfolio import EMPTY_LEDGER, LedgerOutcome, open_ledger

PREPARE_HINT = "önce hazırlık: python -m crytobot prepare"


class PrepareOutcome(Enum):
    PREPARED = "prepared"
    INVALID_BALANCE = "invalid_balance"
    STORE_EXISTS = "store_exists"
    CREATE_FAILED = "create_failed"
    BALANCE_NOT_WRITTEN = "balance_not_written"


@dataclass(frozen=True)
class PrepareResult:
    outcome: PrepareOutcome
    message: str


def prepare_store(store_path: str, opening_balance: Decimal, now: datetime) -> PrepareResult:
    """R-3: depo yoksa paper deposunu oluşturur ve açılış bakiyesini yazar.

    Bakiye depo oluşmadan önce denenir; var olan depoya (okunabilir olsun ya da olmasın) hiçbir şey
    yazılmaz. Oluşturmadan sonra kayıt reddedilirse dosya yerinde kalır (plan Risk 12): başlatma onu
    "defter açılmamış" ile reddeder.
    """
    opened = open_ledger(EMPTY_LEDGER, opening_balance, now)
    if opened.outcome is not LedgerOutcome.OPENED:
        return PrepareResult(PrepareOutcome.INVALID_BALANCE, "açılış bakiyesi geçersiz")
    created = create_store(store_path, PAPER)
    if created.outcome is StoreOutcome.ALREADY_EXISTS:
        return PrepareResult(PrepareOutcome.STORE_EXISTS, "depo zaten var; hiçbir şey yazılmadı")
    if created.state is None:
        message = f"depo oluşturulamadı: {created.message}"
        return PrepareResult(PrepareOutcome.CREATE_FAILED, message)
    state = created.state
    saved = save_store(store_path, state, opened.ledger, state.execution, state.risk)
    if saved.state is None:
        message = f"depo oluştu, açılış bakiyesi yazılamadı: {saved.message}"
        return PrepareResult(PrepareOutcome.BALANCE_NOT_WRITTEN, message)
    return PrepareResult(PrepareOutcome.PREPARED, f"paper deposu hazır: {opened.message}")


class StartOutcome(Enum):
    READY = "ready"
    STORE_MISSING = "store_missing"
    STORE_UNREADABLE = "store_unreadable"
    STORE_BUSY = "store_busy"
    MODE_MISMATCH = "mode_mismatch"
    LEDGER_NOT_OPENED = "ledger_not_opened"


@dataclass(frozen=True)
class StartCheck:
    """`hint` yalnız depo yokken doludur (R-4)."""

    outcome: StartOutcome
    message: str
    hint: str | None


_REFUSALS = {
    StoreOutcome.NOT_FOUND: StartOutcome.STORE_MISSING,
    StoreOutcome.BUSY: StartOutcome.STORE_BUSY,
    StoreOutcome.MODE_MISMATCH: StartOutcome.MODE_MISMATCH,
}


def open_for_start(store_path: str) -> StartCheck:
    """R-4, R-5: depo paper ve defter açıksa `READY`; değilse nedeni adıyla. Hiçbir şey yazmaz."""
    loaded = load_store(store_path, PAPER)
    if loaded.state is None:
        outcome = _REFUSALS.get(loaded.outcome, StartOutcome.STORE_UNREADABLE)
        if outcome is StartOutcome.MODE_MISMATCH:
            message = "depo paper modunda değil; yalnız paper çalışır"
        else:
            message = loaded.message
        hint = PREPARE_HINT if outcome is StartOutcome.STORE_MISSING else None
        return StartCheck(outcome, f"başlatma reddedildi: {message}", hint)
    if loaded.state.ledger.balance is None:
        return StartCheck(
            StartOutcome.LEDGER_NOT_OPENED, "başlatma reddedildi: defter açılmamış", None
        )
    return StartCheck(StartOutcome.READY, "depo hazır", None)


def read_pairs(whitelist: Sequence[str], store_path: str) -> tuple[str, ...]:
    """R-9: beyaz liste ve açık pozisyonların çiftleri, sırayla ve tekrarsız (plan Risk 8).

    Depo yüklenemezse yalnız beyaz liste; depo sorununu tur kendisi bildirir.
    """
    loaded = load_store(store_path, PAPER)
    held: tuple[str, ...] = ()
    if loaded.state is not None:
        held = tuple(position.pair for position in loaded.state.ledger.positions.values())
    return tuple(dict.fromkeys((*whitelist, *held)))
