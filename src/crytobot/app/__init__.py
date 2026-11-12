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
"""

from crytobot.app._backtest import BacktestExit, BacktestOutcome, BacktestParts, run_backtest
from crytobot.app._backtest_config import (
    BacktestConfig,
    BacktestConfigResult,
    load_backtest_config,
)
from crytobot.app._config import (
    MAINNET,
    SETTING_NAMES,
    TESTNET,
    TESTNET_PAPER_REFUSAL,
    BotConfig,
    ConfigResult,
    NetworkResult,
    load_config,
    load_network,
)
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
from crytobot.app._events import TESTNET_SKIPPED, TRIAL_MARK, line, network_note_text
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
    bind_live_network,
    create_live_exchange,
    open_for_start,
    prepare_live_store,
    prepare_store,
    read_pairs,
    record_start,
    store_network_problem,
)
from crytobot.app._turn import run_turn

__all__: list[str] = [
    "MAINNET",
    "MAX_WAIT_S",
    "PREPARE_HINT",
    "SETTING_NAMES",
    "TESTNET",
    "TESTNET_PAPER_REFUSAL",
    "TESTNET_SKIPPED",
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
    "ForcedStop",
    "KillRequest",
    "LogWriteError",
    "LoopExit",
    "LoopParts",
    "NetworkResult",
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
    "bind_live_network",
    "check_paper_proof",
    "check_stage_gate",
    "create_live_exchange",
    "engage_kill_switch",
    "get_dashboard_status",
    "line",
    "load_backtest_config",
    "load_config",
    "load_download_config",
    "load_network",
    "load_stage_config",
    "network_note_text",
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
    "run_loop",
    "run_turn",
    "store_network_problem",
    "to_turn_market",
]
