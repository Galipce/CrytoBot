"""Mum, fiyat ve emir defteri verisini borsadan çekmek ve saklamak.

Bugün yalnız okuma vardır (spec 0017): `read_market_data`, verilen çiftler için tek geçişte kapanmış
mumları, zaman damgalı son işlem fiyatını, spread'i, fiyat adımını ve çift kurallarını okur. Yalnız
herkese açık veriye erişir, API anahtarı kullanmaz, emir ve hesap işlemi yapamaz. İstisna fırlatmaz:
okunamayan ya da güvenilmeyen alan `None` döner, nedeni `issues`'ta adıyla durur (BR-11); yerine
eski ya da tahmini değer konmaz. Yalnız Binance spot desteklenir. Saklama, döngü ve giriş noktası
yoktur. Borsa yasağı (HTTP 418) `MarketRead.ban` ile bildirilir, bitiş anı `Retry-After`'tan gelir
(spec 0022); yasağı sonraki okumalara taşımak çağıranın işidir. `CANDLE_INTERVALS` kabul edilen mum
aralıklarını, `read_settings_problem` okuma ayarlarının ilk sorununu verir.

Geçmiş veri (spec 0023): `download_history`, verilen çiftlerin bir dönemdeki kapanmış mumlarını
(ısınma mumları dahil), kurallarını ve fiyat adımını herkese açık uçlardan anahtarsız indirip tek
bir veri dosyasına (JSON Lines) yazar. Her çağrı bir kez yapılır; ilk hata, güvenilmeyen veri ya
da durdurma isteği indirmeyi durdurur ve tamamlanmış görünen dosya bırakmaz. Var olan dosyanın
üzerine yazılmaz. İstisna fırlatmaz: sonuç `HistoryResult`'tır (özetler ya da `HistoryStop`).

Backtest girdisi (spec 0025): `read_history` veri dosyasını bütünüyle okur ve denetler. Sonuç ya
`HistoryData`'dır ya da adı konmuş bir sorun (`HistoryReadProblem`: yok, okunamıyor, bozuk,
tamamlanmamış, güvenilmeyen veri). 0017'nin mum denetimleri aynen uygulanır; boşluk doldurulmaz.
"""

from crytobot.market_data._history import (
    HistoryRequest,
    HistoryResult,
    HistoryStop,
    HistoryStopReason,
    PairSummary,
    download_history,
)
from crytobot.market_data._history_read import (
    HistoryData,
    HistoryPair,
    HistoryRead,
    HistoryReadProblem,
    read_history,
)
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
    "HistoryData",
    "HistoryPair",
    "HistoryRead",
    "HistoryReadProblem",
    "HistoryRequest",
    "HistoryResult",
    "HistoryStop",
    "HistoryStopReason",
    "InputProblem",
    "IssueReason",
    "MarketCandle",
    "MarketRead",
    "MarketRules",
    "PairRead",
    "PairSummary",
    "ReadBan",
    "ReadField",
    "ReadIssue",
    "ReadSettings",
    "download_history",
    "read_history",
    "read_market_data",
    "read_settings_problem",
]
