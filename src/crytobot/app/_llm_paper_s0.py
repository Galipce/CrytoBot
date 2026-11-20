"""ADR 0004 S0 koşusunun pencereye düşen işlemleri (spec 0060 G-9, AC-8; plan Risk 9).

Paper deposu 0038'deki gibi salt okunur açılır (`load_store(..., readonly=True)`); yazılmaz,
kilitlenmez. Girişi `[başlangıç, bitiş)` içinde olan kapanmış işlemler ve açık pozisyonlar sayılır.
Depo yoksa, okunamıyorsa ya da defter açılmamışsa `None` ("S0 yok").
"""

from datetime import datetime
from decimal import Decimal

from crytobot.app._llm_paper_report import S0Summary
from crytobot.persistence import StoreOutcome, load_store
from crytobot.portfolio import realized_opened_between


def read_s0_summary(path: str, start: datetime, end: datetime) -> S0Summary | None:
    try:
        loaded = load_store(path, "paper", readonly=True)
    except Exception:  # an unreadable store is "S0 yok", never a stopped report
        return None
    if loaded.outcome is not StoreOutcome.LOADED or loaded.state is None:
        return None
    ledger = loaded.state.ledger
    results = realized_opened_between(ledger, start, end)
    gains = sum((value for value in results if value > 0), Decimal(0))
    losses = sum((-value for value in results if value < 0), Decimal(0))
    opened = sum(start <= p.opened_at < end for p in ledger.positions.values())
    return S0Summary(
        len(results),
        opened,
        sum(results, Decimal(0)),
        None if losses == 0 else gains / losses,
    )
