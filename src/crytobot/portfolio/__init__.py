"""Pozisyonlar, bakiye mutabakatı, kâr/zarar defteri.

Bugün yalnızca paper alımların defteri vardır (spec 0007): `open_ledger` boş defteri bir başlangıç
yatırmasıyla açar, `record_fill` dolan her alımı silinmez bir kayıt ve ayrı bir pozisyon olarak
yazar ve bedelini USDT bakiyesinden düşer. Bakiye negatife düşmez; aynı `clientOrderId` ikinci bir
kayıt doğurmaz.
"""

from crytobot.portfolio._ledger import (
    BUY,
    EMPTY_LEDGER,
    Entry,
    EntryKind,
    Fill,
    Ledger,
    LedgerOutcome,
    LedgerResult,
    Position,
    open_ledger,
    record_fill,
)

__all__: list[str] = [
    "BUY",
    "EMPTY_LEDGER",
    "Entry",
    "EntryKind",
    "Fill",
    "Ledger",
    "LedgerOutcome",
    "LedgerResult",
    "Position",
    "open_ledger",
    "record_fill",
]
