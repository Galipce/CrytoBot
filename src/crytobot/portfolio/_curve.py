"""Gerçekleşmiş kasa eğrisi ve kapanmış işlem sayısı (spec 0038 CB-4, plan A-1).

Defterin sahibi bu modüldür: BR-10'un paper eşikleri net sonucu ve düşüşü yalnız gerçekleşmiş
kapanışlardan ister; `app` gerçekleşen kâr/zararı kendisi okumaz (R-14). Açık pozisyonun
gerçekleşmemiş sonucu eğriye girmez; kısmi kapanışın gerçekleşen kısmı girer (plan Risk 3).
"""

from decimal import Decimal, DecimalException, localcontext

from crytobot.portfolio._ledger import EntryKind, Ledger
from crytobot.portfolio._numbers import BOUNDED


def realized_curve(ledger: Ledger) -> tuple[Decimal, ...]:
    """Açılış bakiyesi, sonra her kapanıştan sonraki gerçekleşmiş kasa, kapanma sırasıyla.

    Defter açılmamışsa ya da toplam 60 basamağa sığmıyorsa boş: eğri hesaplanamıyor."""
    if not ledger.entries or ledger.entries[0].kind is not EntryKind.OPENING:
        return ()
    equity = ledger.entries[0].usdt
    curve = [equity]
    try:
        with localcontext(BOUNDED):
            for closure in ledger.closures.values():
                equity += closure.realized
                curve.append(equity)
    except DecimalException:
        return ()
    return tuple(curve)


def closed_trades(ledger: Ledger) -> int:
    """Tamamen kapanmış alım sayısı: kapanışı olan ve artık açık olmayan her alım bir işlemdir
    (hedef, stop ya da sinyal kapanışı fark etmez); kısmi kapanışlar tek işlemdir."""
    closed = {closure.position.client_order_id for closure in ledger.closures.values()}
    return len(closed - set(ledger.positions))
