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

Paper kanıtı (spec 0038): paper başlatması `record_start` ile depoya kanıtlı ya da deneme kaydı
bırakır, döngü her tamamlanan turun anını işaretler; `check_paper_proof` `start --live`'da paper
kanıt deposunu salt okunur denetler (kayıtlar, eşikler, onay sırası).

İndirme (spec 0023): `load_download_config` aynı ayar dosyasından botun ayarlarını ve `[history]`
bölümünü (veri dosyası yolu, dönem) denetler; `run_download` geçmiş veri indirmesini `DownloadParts`
ile verilen saat, indirme işlevi, çıktı ve durdurma isteğiyle yapar. Depoya, kilide ve kayıt
dosyasına dokunmaz.

Backtest (spec 0025): `load_backtest_config` botun ayarlarını ve `[backtest]` bölümünü (veri ve
rapor dosyası yolu, ayrım anı, spread) denetler; `run_backtest` veri dosyasındaki dönemin her tur
anında paper turunun aynısını simüle saatle atar ve raporu yazar. Okuma, rapor dosyası, konsol,
durdurma isteği ve geçici depo yolu `BacktestParts` ile gelir; bot deposuna, kilide ve kayıt
dosyasına dokunulmaz, ağa çıkılmaz.

Son değerlendirme (spec 0042): varsayılan backtest yalnız örneklem içini koşar ve yazar;
`run_evaluation` adayları aynı koşullarla örneklem içinde seçer, seçileni örneklem dışı ve saklı
dönemde sabit eşiklerle değerlendirir ve tek son değerlendirme raporu yazar. Aşama kapısı yalnız bu
raporu ve onun strateji adını kabul eder.

Aday stratejiler (spec 0043): `[strategy] name` S0…S3'ten birini seçer (yoksa S0). Son
değerlendirme `final_configs` ile `[backtest] final_data`'nın iki aralığını (1h, 4h) ve her
aralıkta sabit R-3 ızgarasını (`CANDIDATE_GRIDS`) sınar; aşama kapısı rapordaki adayın adını,
bütün parametrelerini ve aralığını çalışan ayarla karşılaştırır.
"""

from crytobot.app._backtest import BacktestExit, BacktestOutcome, BacktestParts, run_backtest
from crytobot.app._backtest_config import (
    FINAL_INTERVALS,
    BacktestConfig,
    BacktestConfigResult,
    FinalConfigsResult,
    final_configs,
    load_backtest_config,
)
from crytobot.app._config import SETTING_NAMES, BotConfig, ConfigResult, load_config
from crytobot.app._control import (
    ControlResult,
    engage_kill_switch,
    query_status,
    request_stop,
    resume_operations,
)
from crytobot.app._dashboard import get_dashboard_status
from crytobot.app._download import (
    DownloadConfig,
    DownloadConfigResult,
    DownloadExit,
    DownloadParts,
    load_download_config,
    run_download,
)
from crytobot.app._evaluation import run_evaluation
from crytobot.app._events import TRIAL_MARK, line
from crytobot.app._grid import CANDIDATE_GRIDS
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
from crytobot.app._paper_proof import PaperProof, PaperProofResult, check_paper_proof
from crytobot.app._result import BuyHalt, PairNote, PairOutcome, TurnOutcome, TurnResult
from crytobot.app._session import KillRequest
from crytobot.app._stage import (
    StageConfig,
    StageConfigResult,
    StageGateResult,
    check_stage_gate,
    load_stage_config,
)
from crytobot.app._start import (
    PREPARE_HINT,
    PrepareOutcome,
    PrepareResult,
    StartCheck,
    StartOutcome,
    create_live_exchange,
    open_for_start,
    prepare_live_store,
    prepare_store,
    read_pairs,
    record_start,
)
from crytobot.app._turn import run_turn

__all__: list[str] = [
    "CANDIDATE_GRIDS",
    "FINAL_INTERVALS",
    "MAX_WAIT_S",
    "PREPARE_HINT",
    "SETTING_NAMES",
    "TRIAL_MARK",
    "BacktestConfig",
    "BacktestConfigResult",
    "BacktestExit",
    "BacktestOutcome",
    "BacktestParts",
    "BotConfig",
    "BuyHalt",
    "ConfigResult",
    "ControlResult",
    "DownloadConfig",
    "DownloadConfigResult",
    "DownloadExit",
    "DownloadParts",
    "ExitReason",
    "FinalConfigsResult",
    "ForcedStop",
    "KillRequest",
    "LogWriteError",
    "LoopExit",
    "LoopParts",
    "NoticeKind",
    "PairMarket",
    "PairNote",
    "PairOutcome",
    "PaperProof",
    "PaperProofResult",
    "PrepareOutcome",
    "PrepareResult",
    "StageConfig",
    "StageConfigResult",
    "StageGateResult",
    "StartCheck",
    "StartOutcome",
    "StopRequest",
    "TurnMemory",
    "TurnNotice",
    "TurnOutcome",
    "TurnResult",
    "TurnSettings",
    "check_paper_proof",
    "check_stage_gate",
    "create_live_exchange",
    "engage_kill_switch",
    "final_configs",
    "get_dashboard_status",
    "line",
    "load_backtest_config",
    "load_config",
    "load_download_config",
    "load_stage_config",
    "open_for_start",
    "prepare_live_store",
    "prepare_store",
    "query_status",
    "read_pairs",
    "record_start",
    "request_stop",
    "resume_operations",
    "run_backtest",
    "run_download",
    "run_evaluation",
    "run_loop",
    "run_turn",
    "to_turn_market",
]
