"""Pozisyonlar, bakiye mutabakatı, kâr/zarar defteri.

Bugün yalnızca paper alımların defteri vardır (spec 0007): `open_ledger` boş defteri bir başlangıç
yatırmasıyla açar, `record_fill` dolan her alımı silinmez bir kayıt ve ayrı bir pozisyon olarak
yazar ve bedelini USDT bakiyesinden düşer. Bakiye negatife düşmez; aynı `clientOrderId` ikinci bir
kayıt doğurmaz. `account_state` defterden serbest bakiyeyi, açık pozisyonları ve çift başına güncel
fiyatla değerlenmiş kasayı türetir: `risk`'in hesap girdisi (`AccountState`'e `app` çevirir).
"""

from crytobot.portfolio._close import Close, CloseOutcome, CloseResult, close_position
from crytobot.portfolio._ledger import (
    BUY,
    EMPTY_LEDGER,
    AccountSnapshot,
    CloseReason,
    Closure,
    Entry,
    EntryKind,
    Fill,
    Ledger,
    LedgerOutcome,
    LedgerResult,
    Position,
    SnapshotOutcome,
    SnapshotResult,
    account_state,
    open_ledger,
    record_fill,
)

__all__: list[str] = [
    "BUY",
    "EMPTY_LEDGER",
    "AccountSnapshot",
    "Close",
    "CloseOutcome",
    "CloseReason",
    "CloseResult",
    "Closure",
    "Entry",
    "EntryKind",
    "Fill",
    "Ledger",
    "LedgerOutcome",
    "LedgerResult",
    "Position",
    "SnapshotOutcome",
    "SnapshotResult",
    "account_state",
    "close_position",
    "open_ledger",
    "record_fill",
]
