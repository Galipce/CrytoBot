"""Pozisyonlar, bakiye mutabakatı, kâr/zarar defteri.

Paper alımların ve kapanışlarının defteri (spec 0007, 0008): `open_ledger` boş defteri bir
başlangıç yatırmasıyla açar, `record_fill` dolan her alımı silinmez bir kayıt ve ayrı bir pozisyon
olarak yazar ve bedelini USDT bakiyesinden düşer. `exit_decisions` güncel fiyatlarla stop'a ya da
hedefe ulaşan açık pozisyonları belirler (defteri değiştirmez); `close_position` dolan kapanış
satışını yazar: pozisyon tamamen kapanır, satış geliri bakiyeye eklenir, komisyonlar dahil net
kâr/zarar gerçekleşir. Bakiye negatife düşmez; alım ve kapanış aynı kimlik alanını paylaşır, aynı
`clientOrderId` ikinci bir kayıt doğurmaz. `account_state` defterden serbest bakiyeyi, açık
pozisyonları, çift başına güncel fiyatla değerlenmiş kasayı ve gerçekleşen kâr/zarar toplamını
türetir: `risk`'in hesap girdisi (`AccountState`'e `app` çevirir).
"""

from crytobot.portfolio._close import (
    Close,
    CloseOutcome,
    CloseResult,
    Decision,
    DecisionOutcome,
    DecisionResult,
    close_position,
    exit_decisions,
)
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
from crytobot.portfolio._replay import ledger_problems

__all__: list[str] = [
    "BUY",
    "EMPTY_LEDGER",
    "AccountSnapshot",
    "Close",
    "CloseOutcome",
    "CloseReason",
    "CloseResult",
    "Closure",
    "Decision",
    "DecisionOutcome",
    "DecisionResult",
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
    "exit_decisions",
    "ledger_problems",
    "open_ledger",
    "record_fill",
]
