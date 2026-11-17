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

Dönem boşlukları (spec 0044): `period_gaps` bir çiftin dönemdeki boşluklarını (`CandleGap`)
indirme özetinin `boşluk=` kuralıyla verir; `has_candle` dönemde mum olup olmadığını söyler. Saftır.

Olay fiyatları (spec 0048): `download_event_prices` istenen coin aralıklarının 1h mumlarını genel
piyasa verisinden, vermezse herkese açık geçmiş veri arşivinden (`data.binance.vision`) anahtarsız
indirip ayrı bir SQLite deposuna (`PriceStore`) yazar: tek istek, istekler arası en az ayardaki
süre, ilk kaynak hatasında durur, yeniden çalıştırma yalnız eksikleri ister. `read_prices` depoyu
ağsız okur; `missing_spans` depoda olmayan parçaları verir.
"""

from crytobot.market_data._event_prices import (
    REQUEST_TIMEOUT_S,
    DownloadOutcome,
    EventPriceParts,
    PriceNeed,
    download_event_prices,
    missing_spans,
)
from crytobot.market_data._gaps import CandleGap, has_candle, period_gaps
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
from crytobot.market_data._price_store import (
    DownloadRun,
    PairInfo,
    PriceData,
    PriceStore,
    PriceStoreError,
    StoredCandle,
    StoredSpan,
    read_prices,
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
from crytobot.market_data._vision import (
    VisionFetched,
    VisionHop,
    fetch_month,
    month_url,
    parse_month,
)

__all__: list[str] = [
    "CANDLE_INTERVALS",
    "REQUEST_TIMEOUT_S",
    "CandleGap",
    "DownloadOutcome",
    "DownloadRun",
    "EventPriceParts",
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
    "PairInfo",
    "PairRead",
    "PairSummary",
    "PriceData",
    "PriceNeed",
    "PriceStore",
    "PriceStoreError",
    "ReadBan",
    "ReadField",
    "ReadIssue",
    "ReadSettings",
    "StoredCandle",
    "StoredSpan",
    "VisionFetched",
    "VisionHop",
    "download_event_prices",
    "download_history",
    "fetch_month",
    "has_candle",
    "missing_spans",
    "month_url",
    "parse_month",
    "period_gaps",
    "read_history",
    "read_market_data",
    "read_prices",
    "read_settings_problem",
]
