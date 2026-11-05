"""Mum, fiyat ve emir defteri verisini borsadan çekmek ve saklamak.

Bugün yalnız okuma vardır (spec 0017): `read_market_data`, verilen çiftler için tek geçişte kapanmış
mumları, zaman damgalı son işlem fiyatını, spread'i, fiyat adımını ve çift kurallarını okur. Yalnız
herkese açık veriye erişir, API anahtarı kullanmaz, emir ve hesap işlemi yapamaz. İstisna fırlatmaz:
okunamayan ya da güvenilmeyen alan `None` döner, nedeni `issues`'ta adıyla durur (BR-11); yerine
eski ya da tahmini değer konmaz. Yalnız Binance spot desteklenir. Saklama, döngü ve giriş noktası
yoktur. Borsa yasağı (HTTP 418) `MarketRead.ban` ile bildirilir, bitiş anı `Retry-After`'tan gelir
(spec 0022); yasağı sonraki okumalara taşımak çağıranın işidir. `CANDLE_INTERVALS` kabul edilen mum
aralıklarını, `read_settings_problem` okuma ayarlarının ilk sorununu verir.
"""

from crytobot.market_data._read import read_market_data
from crytobot.market_data._types import (
    CANDLE_INTERVALS,
    InputProblem,
    IssueReason,
    MarketCandle,
    MarketRead,
    MarketRules,
    PairRead,
    ReadBan,
    ReadField,
    ReadIssue,
    ReadSettings,
)
from crytobot.market_data._types import settings_problem as read_settings_problem

__all__: list[str] = [
    "CANDLE_INTERVALS",
    "InputProblem",
    "IssueReason",
    "MarketCandle",
    "MarketRead",
    "MarketRules",
    "PairRead",
    "ReadBan",
    "ReadField",
    "ReadIssue",
    "ReadSettings",
    "read_market_data",
    "read_settings_problem",
]
