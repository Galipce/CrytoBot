"""Mum, fiyat ve emir defteri verisini borsadan çekmek ve saklamak.

Bugün yalnız okuma vardır (spec 0017): `read_market_data`, verilen çiftler için tek geçişte kapanmış
mumları, zaman damgalı son işlem fiyatını, spread'i, fiyat adımını ve çift kurallarını okur. Yalnız
herkese açık veriye erişir, API anahtarı kullanmaz, emir ve hesap işlemi yapamaz. İstisna fırlatmaz:
okunamayan ya da güvenilmeyen alan `None` döner, nedeni `issues`'ta adıyla durur (BR-11); yerine
eski ya da tahmini değer konmaz. Yalnız Binance spot desteklenir. Saklama, döngü ve giriş noktası
yoktur.
"""

from crytobot.market_data._read import read_market_data
from crytobot.market_data._types import (
    InputProblem,
    IssueReason,
    MarketCandle,
    MarketRead,
    MarketRules,
    PairRead,
    ReadField,
    ReadIssue,
    ReadSettings,
)

__all__: list[str] = [
    "InputProblem",
    "IssueReason",
    "MarketCandle",
    "MarketRead",
    "MarketRules",
    "PairRead",
    "ReadField",
    "ReadIssue",
    "ReadSettings",
    "read_market_data",
]
