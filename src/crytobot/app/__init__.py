"""Bileşim kökü: modülleri bağlar, zamanlayıcı/döngü.

`run_turn` (spec 0016): verilen piyasa verisi, ayarlar, depo yolu, zaman, paper simülatörü ve
bildirim alıcısıyla tek paper turu. Sıra: depoyu yükle → bilinmeyen emirleri sorgula → kasayı gözle
→ stop ve hedef kapanışları → kasayı gözle → beyaz liste sırasıyla alım; her adım kaydedilir.
Belirsiz durumda alım durur, kapanış sürer, bildirim gider (BR-11). Tur istisna fırlatmaz ve her
zaman paper'dır. `to_turn_market` bir piyasa okumasının sonucunu tur girdisine çevirir (spec 0017).

Döngü (spec 0022): `load_config` ayar eşlemini denetler (varsayılan yok, ilk sorunlu ayar adıyla),
`prepare_store` paper deposunu açılış bakiyesiyle oluşturur (başlatma depoyu asla oluşturmaz),
`open_for_start` depoyu başlatma için denetler, `run_loop` turları UTC aralık sınırlarında atar.
Gerçek etkiler (saat, bekleme, piyasa okuması, çıktı, durdurma isteği) `LoopParts` ile verilir:
`app` saat çağırmaz, borsaya kendi başına çıkmaz, yalnız kendisine verilen okumayı çağırır. Borsa
yasağı süresince okuma yapılmaz. Her başlatma bir deneme koşusudur (`TRIAL_MARK`, BR-10). Giriş
noktası `python -m crytobot`'tur.

İndirme (spec 0023): `load_download_config` aynı ayar dosyasından botun ayarlarını ve `[history]`
bölümünü (veri dosyası yolu, dönem) denetler; `run_download` geçmiş veri indirmesini `DownloadParts`
ile verilen saat, indirme işlevi, çıktı ve durdurma isteğiyle yapar. Depoya, kilide ve kayıt
dosyasına dokunmaz.
"""

from crytobot.app._backtest_config import (
    BacktestConfig,
    BacktestConfigResult,
    load_backtest_config,
)
from crytobot.app._config import SETTING_NAMES, BotConfig, ConfigResult, load_config
from crytobot.app._download import (
    DownloadConfig,
    DownloadConfigResult,
    DownloadExit,
    DownloadParts,
    load_download_config,
    run_download,
)
from crytobot.app._events import TRIAL_MARK, line
from crytobot.app._inputs import PairMarket, TurnSettings
from crytobot.app._loop import (
    MAX_WAIT_S,
    ExitReason,
    ForcedStop,
    LogWriteError,
    LoopExit,
    LoopParts,
    StopRequest,
    run_loop,
)
from crytobot.app._market import to_turn_market
from crytobot.app._notices import NoticeKind, TurnMemory, TurnNotice
from crytobot.app._result import BuyHalt, PairNote, PairOutcome, TurnOutcome, TurnResult
from crytobot.app._start import (
    PREPARE_HINT,
    PrepareOutcome,
    PrepareResult,
    StartCheck,
    StartOutcome,
    open_for_start,
    prepare_store,
    read_pairs,
)
from crytobot.app._turn import run_turn

__all__: list[str] = [
    "MAX_WAIT_S",
    "PREPARE_HINT",
    "SETTING_NAMES",
    "TRIAL_MARK",
    "BacktestConfig",
    "BacktestConfigResult",
    "BotConfig",
    "BuyHalt",
    "ConfigResult",
    "DownloadConfig",
    "DownloadConfigResult",
    "DownloadExit",
    "DownloadParts",
    "ExitReason",
    "ForcedStop",
    "LogWriteError",
    "LoopExit",
    "LoopParts",
    "NoticeKind",
    "PairMarket",
    "PairNote",
    "PairOutcome",
    "PrepareOutcome",
    "PrepareResult",
    "StartCheck",
    "StartOutcome",
    "StopRequest",
    "TurnMemory",
    "TurnNotice",
    "TurnOutcome",
    "TurnResult",
    "TurnSettings",
    "line",
    "load_backtest_config",
    "load_config",
    "load_download_config",
    "open_for_start",
    "prepare_store",
    "read_pairs",
    "run_download",
    "run_loop",
    "run_turn",
    "to_turn_market",
]
