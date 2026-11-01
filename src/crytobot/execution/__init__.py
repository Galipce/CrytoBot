"""Onaylı emirleri borsaya (live) / simülatöre (paper, backtest) iletmek, emir durumunu izlemek.

Bugün yalnızca paper mod vardır (spec 0006): `place_order`, `risk`'in onayladığı bir öneriden
(`TradeApproval.intent`) simülatörde anında dolan bir piyasa alımı oluşturur. Öneri kimliği
`clientOrderId`'yi belirler (`cb-` + kimlik); aynı kimlik ikinci bir emir oluşturmaz. Miktar
yuvarlanmaz: adımın katı değilse ya da asgarilerin altındaysa istek reddedilir. Durumu bilinmeyen
bir emir varken (güvenli mod, BR-11) yeni emir oluşmaz; `query_order` durumu netleştirir, güvenli
moda giriş ve çıkış birer `Notification` üretir.
"""

from crytobot.execution._orders import (
    CLIENT_ID_PREFIX,
    EMPTY_EXECUTION,
    PAPER,
    ExecutionState,
    Notification,
    NotificationKind,
    Order,
    OrderOutcome,
    OrderRequest,
    OrderResult,
    QueryOutcome,
    QueryResult,
    place_order,
    query_order,
)
from crytobot.execution._paper import OrderStatus, PaperExchange

__all__: list[str] = [
    "CLIENT_ID_PREFIX",
    "EMPTY_EXECUTION",
    "PAPER",
    "ExecutionState",
    "Notification",
    "NotificationKind",
    "Order",
    "OrderOutcome",
    "OrderRequest",
    "OrderResult",
    "OrderStatus",
    "PaperExchange",
    "QueryOutcome",
    "QueryResult",
    "place_order",
    "query_order",
]
