"""Giriş noktası: `python -m crytobot prepare|start|download|backtest|calibrate|news|events|forward`
(spec 0022, 0023, 0025, 0045, 0046, 0047, 0048, 0051, 0053).

Karar içermez: kararların hepsi `app`'tedir. Burada yalnız gerçek etkiler bağlanır: ayar dosyası
(`tomllib`, çalışma dizinindeki `crytobot.toml`), gerçek UTC saati, ≤1 s'lik parçalarla bekleme,
sinyaller, tek süreç kilidi, konsol ve kayıt dosyası yazıcısı, piyasa okuması. Yalnız paper vardır;
mod seçeneği, API anahtarı ve ortam değişkeni okunmaz.

`download` (spec 0023) geçmiş veriyi aynı ayar dosyasının `[history]` bölümüne göre indirir. Kilit
alınmaz, depo ve kayıt dosyası açılmaz: çıktı yalnız konsoladır, çalışan bir paper botu etkilenmez.

`backtest` (spec 0025) veri dosyasıyla, aynı ayar dosyasının `[backtest]` bölümüne göre koşar. Ağa
çıkılmaz, saat verilmez, kilit alınmaz; bot deposu ve kayıt dosyası açılmaz. Turların durumu
`tempfile` ile açılan geçici bir dizindeki depodadır ve dizin her çıkışta silinir (zorla durdurma
dahil; süreç öldürülürse işletim sisteminin geçici dizininde kalır, bir daha okunmaz). Konsol
satırları zaman damgası taşımaz. Spec 0042: `backtest` yalnız örneklem içini koşar ve yazar;
`backtest --final` son değerlendirmedir (`run_evaluation`): örneklem dışı ve saklı dönem yalnız
orada hesaplanır; aynı çıkış kodları. Spec 0043 R-5 (plan Risk 1): `--final` `[backtest]
final_data`'nın iki aralığını (1h, 4h) ve her aralıkta R-3 ızgarasını tek raporda sınar.

`calibrate` (spec 0045) aynı ayar dosyasının `[calibration]` bölümüne göre beş veri dosyasıyla
indikatör kalibrasyonunun 1. aşamasını (ayarlama, çapraz sınama → ayar seti, rapor, kayıtlar);
`calibrate --final` onaylı ayar setiyle son ölçümü koşar. Ağa çıkılmaz, kilit alınmaz, bot deposu,
kayıt dosyası ve çalışan ayar değişmez; yalnız ayardaki çıktı yolları yazılır (üzerine yazılmaz).
Yollar çözülmüş hâlleriyle de birbirinden farklı olmalıdır. Çıkış kodları backtest'inkiyle aynıdır.

`news` (spec 0046) haber toplayıcısıdır: ayar ayrı dosyadadır (`crytobot-news.toml`, plan A-2), bot
ayarı yalnız `[bot]` yollarının karşılaştırması ve Telegram ayarı için okunur. Kararlar `news`'tedir
(`run_collection`; `app` aracısız, plan Risk 1); burada gerçek saat, ≤1 s'lik bekleme, sinyaller,
haber kaydının mutlak yolunun kilidi (`<haber kaydı>.lock`, bot kilidinden ayrı), konsol ve haberin
kendi kayıt dosyası, HTTPS getirme ve `reporting` bağlanır. Bot deposu açılmaz. `news status` ağa
çıkmaz, kilit almaz; depo yoksa oluşturmaz. Çıkış: 0 temiz durma ya da durum, 1 ret (ayar, kilit,
okunamayan ya da yazılamayan kayıt), 3 kayıt dosyası yazılamıyor, 130 zorla durma.

`news archive` (spec 0047) geçmiş Binance duyurularını arşive doldurur; ayar aynı haber ayar
dosyasının `archive_` anahtarlarıdır (plan Risk 1). Ayar → yol çakışması → arşiv deposunun mutlak
yolunun kilidi (`<arşiv>.lock`; toplayıcının ve botun kilidinden ayrı) → depo sırası; arşivin kendi
kayıt dosyası, gerçek saat, monoton saat, ≤1 s'lik bekleme ve HTTPS getirme bağlanır. Telegram
bağlanmaz, bot deposu ve ileriye dönük haber kaydı açılmaz. `news archive status` ağa çıkmaz, kilit
almaz, iki depoyu yalnız okur. Çıkış: 0 arşiv tamam ya da durum, 1 ret ya da kaynak hatası, 3 kayıt
dosyası yazılamıyor, 4 durdurma isteğiyle durdu, 130 zorla durma.

`events download` ve `events measure` (spec 0048) geçmiş olay örnek kütüphanesini kurar: ayar ayrı
dosyadadır (`crytobot-events.toml`, plan Risk 2); kaynak kayıtların yolları ve türleri haber ayar
dosyasından, bot deposu ve kayıt yolu bot ayarından yalnız okunur. Sıra: iki ayar → çıktı yollarının
çakışması (çözülmüş yollarla: kaynak kayıtlar, kayıt dosyaları, bot deposu, ayar dosyaları,
birbirleri, deponun çalışma ağacı) → arşiv var mı → fiyat deposunun mutlak yolunun kilidi (iki
komut için tek; `measure` raporun kilidini de alır) → koşu. Bütün retler ağa ve dosyaya dokunmadan.
Kaynak kayıtlar `news`'le okunup etiketlenir ve `calibration`'ın tipine çevrilir (`app` `news`'i
import etmez). `download` genel piyasa verisine ve herkese açık geçmiş veri arşivine çıkar;
`measure` ağa çıkmaz, rapor ve kütüphane üzerine yazılmaz. Telegram bağlanmaz, bot deposu açılmaz.
Çıkış: 0 tamam, 1 ret ya da kaynak hatası, 4 durdurma isteğiyle durdu, 6 çıktı yazılamadı, 130
zorla durma.

`news score` (spec 0051) LLM olay skorlayıcısıdır, gölge modda: ayar haber ayar dosyasının
`[score]` bölümüdür. Sıra: ayar → yolların çakışması (çözülmüş yollarla: haber kaydı, arşiv, bot
deposu, bütün kayıt dosyaları, fiyat deposu, bağlam dosyaları) → haber kaydı var mı → bağlam
dosyaları ve parmak izleri → borsa bilgisi (`crytobot-events.toml`'un fiyat deposundan USDT
çiftleri, yalnız okunur; plan Risk 2) → skor kaydının mutlak yolunun kilidi (`<skor kaydı>.lock`;
bot, toplayıcı ve arşiv kilitlerinden ayrı) → döngü. Bütün retler kayda dokunmadan. LLM çağrısı
`llm`'in `claude -p` alt sürecidir (`claude` PATH'te aranır); kararlar `news`'tedir. Bot deposu
açılmaz, Telegram bağlanmaz. `news score status` ağa ve LLM'e çıkmaz, kilit almaz, kayıtları yalnız
okur. Çıkış: 0 temiz durma ya da durum, 1 ret ya da okunamayan/yazılamayan kayıt, 3 kayıt dosyası
yazılamıyor, 130 zorla durma.

Çıkış kodları: 0 temiz durma, hazırlık, indirme ya da backtest tamam, 1 başlatma, hazırlık, indirme
ya da backtest reddi (ayarlar, veri dosyası, rapor dosyası var), 2 okuma reddiyle durma, 3 kayıt
dosyası yazılamıyor, 4 indirme durdu, 5 backtest durdu, 6 backtest tamam ama rapor dosyası
yazılamadı (rapor konsolda), 130 zorla durma.

Gölge filtre kaydı (spec 0052): paper `start` (`--trial` ve kanıtlı) bot ayarının `[shadow]`
bölümünü okur; bölüm yoksa davranış bugünküdür. Gölge kaydın yolu bot deposu, bot kayıt dosyası,
paper kanıt deposu, skor ve haber kaydı, bot ayar dosyası ve varsayılan haber ayarının kayıtları ve
kayıt dosyalarıyla (çözülmüş yollarla) aynı olamaz; skor ve haber kaydı bot deposu olamaz. Ret kayıt
dosyası açılmadan, kilit alınmadan, konsola. Her turda skor ve haber kaydı `news`'le yalnız okunur
ve `app`'in tipine (`PairFilter`) çevrilir; satırlar JSON Lines olarak yalnız eklenir (plan A-1).
`start --live` ve `backtest` `[shadow]`'u okumaz. `shadow status` ağa ve LLM'e çıkmaz, kilit almaz,
gölge kaydı ve bot kayıt dosyasını yalnız okur.

`forward download` ve `forward report [--at <an>]` (spec 0053) ileriye dönük ölçüm raporudur: ayar
ayrı dosyadadır (`crytobot-forward.toml`, plan Risk 6); skor ve haber kaydının yolları ve kaynak
türleri haber ayarından (`[score]`, `[news]`), beyaz liste, `[shadow]` ve bot yolları bot ayarından
okunur. Sıra: üç ayar → çıktı yollarının çakışması (çözülmüş yollarla: skor, gölge, haber kaydı,
arşiv, kayıt dosyaları, bot deposu, paper kanıt deposu, ayar dosyaları, birbirleri; plan Risk 10) →
koşu. Bütün retler hiçbir dosyaya dokunmadan. Kayıtlar `news`'le yalnız okunur (`mode=ro`), gölge
kaydın JSON satırları burada çözülür, hepsi `calibration`'ın tipine çevrilir (`app` `news`'i import
etmez). `download` fiyat deposunun mutlak yolunu kilitler ve 0048'in indirme adımını koşar;
`report` ağa ve LLM'e çıkmaz, kilit almaz; rapor ve örnek dosyası geçici dosya + `os.replace` ile
atomik üzerine yazılır (plan Risk 7). `--at` saat dilimli ISO an ister, gelecekteki an reddedilir.
Çıkış: 0 tamam, 1 ret ya da kaynak hatası, 4 durdurma isteğiyle durdu, 6 çıktı yazılamadı, 130 zorla
durma.
"""

import hashlib
import json
import os
import shutil
import signal
import sys
import tempfile
import threading
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import FrameType
from typing import IO, TextIO

from crytobot.analysis import Candle
from crytobot.app import (
    BacktestConfig,
    BacktestOutcome,
    BacktestParts,
    BotConfig,
    CalibrationConfig,
    CalibrationOutcome,
    CalibrationParts,
    DownloadConfig,
    DownloadParts,
    EventDownloadParts,
    EventInputs,
    EventMeasureParts,
    EventsConfig,
    EventsOutcome,
    ExitReason,
    ForcedStop,
    ForwardConfig,
    ForwardDownloadParts,
    ForwardOutcome,
    ForwardReportParts,
    ForwardSources,
    KillRequest,
    LogWriteError,
    LoopParts,
    PairFilter,
    PaperProof,
    PrepareOutcome,
    ShadowConfig,
    ShadowParts,
    StartOutcome,
    StopRequest,
    check_paper_proof,
    check_stage_gate,
    create_live_exchange,
    engage_kill_switch,
    final_configs,
    get_dashboard_status,
    last_shadow_error,
    line,
    load_backtest_config,
    load_calibration_config,
    load_config,
    load_download_config,
    load_events_config,
    load_forward_config,
    load_shadow_config,
    load_stage_config,
    open_for_start,
    prepare_live_store,
    prepare_store,
    query_status,
    record_start,
    request_stop,
    resume_operations,
    run_backtest,
    run_calibration,
    run_calibration_final,
    run_download,
    run_evaluation,
    run_events_download,
    run_events_measure,
    run_forward_download,
    run_forward_report,
    run_loop,
    shadow_status_lines,
)
from crytobot.backtest import read_report, report_exists, write_report
from crytobot.calibration import (
    EventAnnouncement,
    ForwardEvent,
    ForwardInputs,
    ScoredNews,
    ShadowTurn,
)
from crytobot.control import (
    clear_kill_flag,
    clear_stop_flag,
    is_lock_held,
    kill_flag_set,
    set_kill_flag,
    set_stop_flag,
    stop_flag_path,
)
from crytobot.dashboard import (
    PortBusyError,
    create_server,
    load_dashboard_config,
)
from crytobot.decide import (
    QUOTE,
    CoinData,
    DecideConfig,
    DecideExit,
    DecideParts,
    DecideReply,
    DecideStore,
    DecideStoreError,
    EventNote,
    decide_status_lines,
    load_decide_config,
    read_decide_snapshot,
    run_decide,
)
from crytobot.llm import ClaudeRequest, call_claude
from crytobot.market_data import (
    DownloadOutcome,
    EventPriceParts,
    HistoryRequest,
    HistoryResult,
    MarketRead,
    PriceData,
    PriceNeed,
    PriceStore,
    PriceStoreError,
    ReadSettings,
    download_event_prices,
    download_history,
    read_history,
    read_market_data,
    read_pairs,
    read_prices,
)
from crytobot.news import (
    BINANCE_KINDS,
    EVENT_TYPES,
    STREAM_KIND,
    ArchiveConfig,
    ArchiveOutcome,
    ArchiveParts,
    ArchiveStore,
    ArchiveStoreError,
    CoinFilter,
    CollectionExit,
    CollectParts,
    Connection,
    ContextError,
    Fetched,
    NewsConfig,
    NewsSource,
    NewsStore,
    PermissionCheck,
    ScoreCall,
    ScoreConfig,
    ScoreContext,
    ScoreExit,
    ScoreParts,
    ScoreReply,
    ScoreStore,
    ScoreStoreError,
    SecretsError,
    StoreError,
    StreamKeys,
    StreamParts,
    StreamRunner,
    Verdict,
    archive_status_lines,
    base_of,
    fetch_restrictions,
    fetch_server_time,
    fetch_source,
    judge_permissions,
    load_archive_config,
    load_context,
    load_news_config,
    load_score_config,
    load_stream_keys,
    open_stream,
    permission_in_future,
    read_filter_view,
    read_forward,
    read_library_sources,
    read_news_sources,
    read_score_record,
    read_score_snapshot,
    read_snapshot,
    redact,
    run_archive,
    run_collection,
    run_scoring,
    score_status_lines,
    status_lines,
    title_pattern,
)
from crytobot.reporting import ReportingService, load_reporting_config

CONFIG_FILE = "crytobot.toml"
NEWS_CONFIG_FILE = "crytobot-news.toml"
EVENTS_CONFIG_FILE = "crytobot-events.toml"
FORWARD_CONFIG_FILE = "crytobot-forward.toml"
DECIDE_CONFIG_FILE = "crytobot-decide.toml"
USAGE = (
    "kullanım: python -m crytobot "
    "prepare|start|download|backtest|calibrate|status|kill-switch|resume|stop|dashboard|news|events"
    "|shadow|forward|decide"
    " [--live] [--trial] [--final] [archive] [score] [status] [download] [measure]"
    " [report] [--at YYYY-MM-DDTHH:MM:SSZ]"
)
COMMANDS = (
    ["prepare"],
    ["prepare", "--live"],
    ["start"],
    ["start", "--live"],
    ["start", "--trial"],
    ["download"],
    ["backtest"],
    ["backtest", "--final"],
    ["calibrate"],
    ["calibrate", "--final"],
    ["status"],
    ["kill-switch"],
    ["kill-switch", "on"],
    ["resume"],
    ["stop"],
    ["dashboard"],
    ["news"],
    ["news", "status"],
    ["news", "archive"],
    ["news", "archive", "status"],
    ["news", "score"],
    ["news", "score", "status"],
    ["events", "download"],
    ["events", "measure"],
    ["shadow", "status"],
    ["forward", "download"],
    ["forward", "report"],
    ["decide"],
    ["decide", "status"],
)
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_READ_REFUSED = 2
EXIT_LOG_FAILED = 3
EXIT_DOWNLOAD_STOPPED = 4
EXIT_BACKTEST_STOPPED = 5
EXIT_REPORT_NOT_WRITTEN = 6
EXIT_FORCED = 130
_EXIT_CODES = {
    ExitReason.STOPPED: EXIT_OK,
    ExitReason.READ_REFUSED: EXIT_READ_REFUSED,
    ExitReason.LOG_FAILED: EXIT_LOG_FAILED,
    ExitReason.FORCED: EXIT_FORCED,
    ExitReason.BANNED: EXIT_REFUSED,
}
_BACKTEST_EXIT_CODES = {
    BacktestOutcome.COMPLETED: EXIT_OK,
    BacktestOutcome.REFUSED: EXIT_REFUSED,
    BacktestOutcome.STOPPED: EXIT_BACKTEST_STOPPED,
    BacktestOutcome.REPORT_NOT_WRITTEN: EXIT_REPORT_NOT_WRITTEN,
}
_CALIBRATION_EXIT_CODES = {
    CalibrationOutcome.COMPLETED: EXIT_OK,
    CalibrationOutcome.REFUSED: EXIT_REFUSED,
    CalibrationOutcome.STOPPED: EXIT_BACKTEST_STOPPED,
    CalibrationOutcome.NOT_WRITTEN: EXIT_REPORT_NOT_WRITTEN,
}
_LOG_FAILED = "kayıt dosyası yazılamıyor: bot durdu"
_DIGEST_CHUNK = 1 << 20
_PIECE_S = 1.0

Clock = Callable[[], datetime]
Read = Callable[[tuple[str, ...], ReadSettings], MarketRead]
Download = Callable[[HistoryRequest, Clock, Callable[[], bool]], HistoryResult]
NewsFetch = Callable[[NewsSource, int, Callable[[], bool]], Fetched]
NEWS_BUSY = "haber kaydı başka bir toplama komutunda açık"
ArchiveFetch = Callable[[str, int, Callable[[], bool]], Fetched]
ARCHIVE_BUSY = "arşiv başka bir arşiv komutunda açık"
SCORE_BUSY = "skor kaydı başka bir skorlayıcıda açık"
DECIDE_BUSY = "karar kaydı başka bir karar sürecinde açık"
EventsDownload = Callable[
    [Sequence[PriceNeed], PriceStore, EventPriceParts, float], DownloadOutcome
]
EVENTS_BUSY = "fiyat verisi başka bir events komutunda açık"
EVENTS_REPORT_BUSY = "rapor başka bir events komutunda açık"
_EVENTS_EXIT_CODES = {
    EventsOutcome.COMPLETED: EXIT_OK,
    EventsOutcome.REFUSED: EXIT_REFUSED,
    EventsOutcome.FAILED: EXIT_REFUSED,
    EventsOutcome.STOPPED: EXIT_DOWNLOAD_STOPPED,
    EventsOutcome.NOT_WRITTEN: EXIT_REPORT_NOT_WRITTEN,
}
FORWARD_BUSY = "fiyat verisi başka bir indirme komutunda açık"
UNKNOWN_SOURCE_NAME = "bilinmiyor"  # news missing from the news record (spec 0055, review M-1)
FORWARD_AT_INVALID = "rapor anı geçersiz (saat dilimli ISO an: YYYY-MM-DDTHH:MM:SSZ)"
_FORWARD_EXIT_CODES = {
    ForwardOutcome.COMPLETED: EXIT_OK,
    ForwardOutcome.REFUSED: EXIT_REFUSED,
    ForwardOutcome.FAILED: EXIT_REFUSED,
    ForwardOutcome.STOPPED: EXIT_DOWNLOAD_STOPPED,
    ForwardOutcome.NOT_WRITTEN: EXIT_REPORT_NOT_WRITTEN,
}
_ARCHIVE_EXIT_CODES = {
    ArchiveOutcome.COMPLETE: EXIT_OK,
    ArchiveOutcome.FAILED: EXIT_REFUSED,
    ArchiveOutcome.STOPPED: EXIT_DOWNLOAD_STOPPED,  # 4: stopped on request (R-7)
}


def utc_now() -> datetime:
    return datetime.now(UTC)


class Output:
    """Konsol ve kayıt dosyası: konsol basamadığı karakteri yer tutucuyla yazar (R-13); kayıt
    dosyası UTF-8'dir ve yalnız sona eklenir. Kayıt yazılamazsa satır konsoldadır,
    `LogWriteError` yükselir (R-15)."""

    def __init__(self, console: TextIO, log_path: str | None = None) -> None:
        reconfigure = getattr(console, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(errors="replace")
        self.console = console
        self.log_path = log_path

    def say(self, text: str) -> None:
        with suppress(OSError, ValueError):  # a closed or broken console never stops the bot
            print(text, file=self.console, flush=True)

    def __call__(self, text: str) -> None:
        self.say(text)
        if self.log_path is None:
            return
        try:
            with open(self.log_path, "a", encoding="utf-8", newline="\n") as log:
                log.write(text + "\n")
        except OSError:
            raise LogWriteError from None


LOCK_BUSY = "depo başka bir bot sürecinde kullanılıyor"


def _locked_control[T](store_path: str, command: Callable[[bool], T]) -> T:
    """Spec 0035 review round 1 L-2: depoya doğrudan yazan kontrol komutu kilidi tutarak çalışır.
    Kilit hangi nedenle alınamazsa alınamasın bot çalışıyor sayılır (`is_running=True`, round 2
    L-1: fail-closed): kontrol ile yazım arasında bot depoyu yükleyemez, eski yazım oluşmaz."""
    lock = StoreLock(store_path)
    refused = lock.acquire()
    try:
        return command(refused is not None)
    finally:
        lock.release()


class StoreLock:
    """R-6: `<depo>.lock` üzerinde işletim sistemi kilidi; süreç ölünce kalkar (plan Risk 5).

    Kilit açık dosya tutamacına aittir: aynı süreçte ikinci tutamaç da reddedilir. Dosya yerinde
    kalır, zararsızdır.
    """

    def __init__(self, store_path: str) -> None:
        self.path = f"{store_path}.lock"
        self._file: IO[bytes] | None = None

    def acquire(self) -> str | None:
        """Kilit alındıysa `None`; alınamadıysa nedeni."""
        try:
            handle = open(self.path, "a+b")  # noqa: SIM115 - held until release
        except OSError:
            return "kilit dosyası açılamıyor (depo dizini yok ya da yazılamıyor)"
        try:
            _lock(handle)
        except OSError:
            handle.close()
            return LOCK_BUSY
        self._file = handle
        return None

    def release(self) -> None:
        handle, self._file = self._file, None
        if handle is None:
            return
        try:
            _unlock(handle)
        finally:
            handle.close()


if sys.platform == "win32":
    import msvcrt

    def _lock(handle: IO[bytes]) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(handle: IO[bytes]) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def stop_signals() -> tuple[signal.Signals, ...]:
    """R-12: Ctrl+C her yerde; Windows'ta Ctrl+Break, Unix'te SIGTERM."""
    if sys.platform == "win32":
        return (signal.SIGINT, signal.SIGBREAK)
    return (signal.SIGINT, signal.SIGTERM)


def install_signals(stop: StopRequest) -> None:
    """İlk sinyal işaret koyar; ikincisi `ForcedStop` fırlatır (işleyici ana iş parçacığında)."""

    def handler(signum: int, _frame: FrameType | None) -> None:
        stop.request(signal.Signals(signum).name)

    for stop_signal in stop_signals():
        signal.signal(stop_signal, handler)


def make_wait(
    stop: StopRequest,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    stop_flag_path: Path | None = None,
) -> Callable[[float], None]:
    """≤1 s'lik parçalarla bekler; durdurma isteğinde en geç bir parça sonra döner (plan Risk 6)."""

    def wait(seconds: float) -> None:
        end = monotonic() + seconds
        while not stop.requested:
            if stop_flag_path is not None and stop_flag_path.exists():
                stop.request("cli-stop")
                break
            left = end - monotonic()
            if left <= 0:
                return
            sleep(min(_PIECE_S, left))

    return wait


def make_read(clock: Clock) -> Read:
    """Okuma yalnız herkese açık uçlara, anahtarsız gider (spec 0017)."""

    def read(pairs: tuple[str, ...], settings: ReadSettings) -> MarketRead:
        return read_market_data(pairs, settings, clock)

    return read


def _load_toml(path: Path) -> dict[str, object] | str:
    """Ayar dosyasının eşlemi ya da dosya yoksa, okunamıyorsa nedeni."""
    try:
        with open(path, "rb") as file:
            return tomllib.load(file)
    except FileNotFoundError:
        return f"ayar dosyası yok: {path.name}"
    except (OSError, ValueError, RecursionError):  # TOML, encoding and 4300-digit errors
        return f"ayar dosyası okunamıyor: {path.name}"


def _document(path: Path, output: Output, clock: Clock) -> dict[str, object] | None:
    """Ayar dosyasının eşlemi; dosya yoksa ya da okunamıyorsa `None`, nedeni konsolda."""
    document = _load_toml(path)
    if isinstance(document, str):
        output.say(line(clock(), "ayar", document))
        return None
    return document


def _same_file(first: str, second: str) -> bool:
    return Path(first).resolve() == Path(second).resolve()


def _config(path: Path, output: Output, clock: Clock) -> BotConfig | None:
    """R-2: dosya yoksa, okunamıyorsa ya da bir ayar geçersizse `None`; hiçbir şeye dokunmaz."""
    document = _document(path, output, clock)
    if document is None:
        return None
    result = load_config(document, clock())
    if result.config is None:
        output.say(line(clock(), "ayar", f"bot başlamadı: {result.message}"))
        return None
    # `app` compares the paths as text only; another spelling of the store (`./bot.db`) is caught
    # here, resolved, before any line is written (review round 1 L-3, VERIFY 0022)
    if _same_file(result.config.log_path, result.config.store_path):
        output.say(line(clock(), "ayar", "bot başlamadı: ayar geçersiz: bot.log_path"))
        return None
    return result.config


def _download_config(path: Path, output: Output, clock: Clock) -> DownloadConfig | None:
    """Spec 0023 R-2: ayarlar ağa çıkmadan ve diske yazmadan önce; ilk sorun adıyla."""
    document = _document(path, output, clock)
    if document is None:
        return None
    result = load_download_config(document, clock())
    if result.config is None:
        output.say(line(clock(), "ayar", f"indirme başlamadı: {result.message}"))
        return None
    bot = result.config.bot
    # R-1: the data file is never the store or the bot's log, however the path is spelled
    if any(_same_file(result.config.data_path, other) for other in (bot.store_path, bot.log_path)):
        output.say(line(clock(), "ayar", "indirme başlamadı: ayar geçersiz: history.data_path"))
        return None
    return result.config


def _download(
    config_path: Path, output: Output, clock: Clock, stop: StopRequest, download: Download
) -> int:
    """Kilit yok, depo ve kayıt dosyası yok: yalnız konsol (spec 0023 R-1)."""
    config = _download_config(config_path, output, clock)
    if config is None:
        return EXIT_REFUSED
    try:
        exit_ = run_download(config, DownloadParts(clock, download, output.say, stop))
    except ForcedStop:  # the second request: the line is written, `.part` is gone (R-8)
        return EXIT_FORCED
    return EXIT_OK if exit_.completed else EXIT_DOWNLOAD_STOPPED


def _backtest_config(path: Path, output: Output) -> BacktestConfig | None:
    """Spec 0025 R-2: ayarlar veri dosyası okunmadan ve hiçbir şey yazılmadan önce; ilk sorun
    adıyla. Satırlar zaman damgası taşımaz (R-12)."""
    document = _load_toml(path)
    if isinstance(document, str):
        output.say(f"backtest reddedildi: {document}")
        return None
    result = load_backtest_config(document)
    config = result.config
    if config is None:
        output.say(f"backtest reddedildi: {result.message}")
        return None
    bot = (config.bot.store_path, config.bot.log_path)
    # R-2: `app` compares the paths as text; another spelling of the same file is caught here
    if any(_same_file(config.data_path, other) for other in bot):
        output.say("backtest reddedildi: ayar geçersiz: backtest.data_path")
        return None
    if any(_same_file(config.report_path, other) for other in (config.data_path, *bot)):
        output.say("backtest reddedildi: ayar geçersiz: backtest.report_path")
        return None
    return config


def _final_configs(config: BacktestConfig, output: Output) -> tuple[BacktestConfig, ...] | None:
    """Spec 0043 R-5: aralık başına yapılandırmalar; her veri yolu bot deposunu, kayıt dosyasını
    ve rapor yolunu başka yazımla da adlandıramaz (`_backtest_config`'in kuralı)."""
    result = final_configs(config)
    if result.configs is None:
        output.say(f"backtest reddedildi: {result.message}")
        return None
    others = (config.bot.store_path, config.bot.log_path, config.report_path)
    for each in result.configs:
        if any(_same_file(each.data_path, other) for other in others):
            output.say("backtest reddedildi: ayar geçersiz: backtest.final_data")
            return None
    return result.configs


def _backtest(
    config_path: Path, output: Output, stop: StopRequest, clock: Clock, *, final: bool = False
) -> int:
    """Ağ yok, kilit yok; bot deposu ve kayıt dosyası açılmaz (spec 0025 R-1). Saat yalnız raporun
    üretim anı içindir (spec 0040 CB-2). Geçici dizin her çıkışta silinir; `.part`'ı rapor
    yazıcısı siler (R-13). `final`: son değerlendirme (spec 0042), koşuların depoları aynı geçici
    dizinde."""
    config = _backtest_config(config_path, output)
    if config is None:
        return EXIT_REFUSED
    finals = _final_configs(config, output) if final else ()
    if finals is None:
        return EXIT_REFUSED
    with tempfile.TemporaryDirectory(
        prefix="crytobot-backtest-", ignore_cleanup_errors=True
    ) as work:
        parts = BacktestParts(
            read_history,
            report_exists,
            write_report,
            output.say,
            stop,
            str(Path(work) / "backtest.db"),
            clock,
        )
        try:
            exit_ = run_evaluation(finals, parts) if final else run_backtest(config, parts)
        except ForcedStop:  # the second request: the line is written, the report is not
            return EXIT_FORCED
    return _BACKTEST_EXIT_CODES[exit_.outcome]


def file_digest(path: str) -> str | None:
    """Dosyanın baytlarının SHA-256'sı, parça parça; okunamazsa `None`."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as file:
            while chunk := file.read(_DIGEST_CHUNK):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def file_bytes(path: str) -> bytes | None:
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def _calibration_config(path: Path, output: Output) -> CalibrationConfig | None:
    """Spec 0045: ayarlar hiçbir dosya okunmadan önce; yollar çözülmüş hâlleriyle de farklı."""
    document = _load_toml(path)
    if isinstance(document, str):
        output.say(f"kalibrasyon reddedildi: {document}")
        return None
    result = load_calibration_config(document)
    config = result.config
    if config is None:
        output.say(f"kalibrasyon reddedildi: {result.message}")
        return None
    paths = [
        *(data for _, data in config.data),
        config.report_path,
        config.settings_path,
        config.records_path,
        config.final_report_path,
        config.final_records_path,
    ]
    resolved = [Path(each).resolve() for each in paths]
    if len(set(resolved)) != len(resolved) or path.resolve() in resolved:
        output.say(
            "kalibrasyon reddedildi: ayar geçersiz: calibration (aynı dosyayı adlandıran yol)"
        )
        return None
    return config


def _calibrate(
    config_path: Path, output: Output, stop: StopRequest, clock: Clock, *, final: bool
) -> int:
    """Ağ yok, kilit yok; bot deposu ve kayıt dosyası açılmaz (spec 0045 R-11)."""
    config = _calibration_config(config_path, output)
    if config is None:
        return EXIT_REFUSED
    parts = CalibrationParts(
        read_history, file_digest, file_bytes, report_exists, write_report, output.say, stop, clock
    )
    try:
        exit_ = run_calibration_final(config, parts) if final else run_calibration(config, parts)
    except ForcedStop:
        return EXIT_FORCED
    return _CALIBRATION_EXIT_CODES[exit_.outcome]


def real_news_fetch(source: NewsSource, max_bytes: int, stopped: Callable[[], bool]) -> Fetched:
    return fetch_source(source.url, source.kind, max_bytes, stopped=stopped)


def _bot_paths(path: Path) -> tuple[str, ...]:
    """Bot ayarının `[bot]` yolları, doğrulamasız (plan A-2): dosya yoksa ya da okunamıyorsa boş."""
    document = _load_toml(path)
    bot = document.get("bot") if isinstance(document, dict) else None
    if not isinstance(bot, Mapping):
        return ()
    return tuple(
        value for key in ("store_path", "log_path") if isinstance(value := bot.get(key), str)
    )


def _news_config(
    news_path: Path, bot_path: Path, output: Output, clock: Clock
) -> NewsConfig | None:
    """Spec 0046 AC-9: ağa çıkmadan ve hiçbir dosyaya dokunmadan önce, ilk sorun adıyla. Haber
    kaydı ve kayıt dosyası bot deposu ya da bot kaydı olamaz, birbirleri de olamaz: başka yazımla
    da (plan Risk 2, 13). İzin tarihi UTC bugünden sonra olamaz (spec 0055 CB-1)."""
    document = _load_toml(news_path)
    if isinstance(document, str):
        output.say(f"news: reddedildi: {document}")
        return None
    result = load_news_config(document)
    config = result.config
    if config is None:
        output.say(f"news: reddedildi: {result.message}")
        return None
    future = permission_in_future(config, _utc_today(clock))
    if future is not None:
        output.say(f"news: reddedildi: {future}")
        return None
    bot = _bot_paths(bot_path)
    if any(_same_file(config.store_path, other) for other in bot):
        output.say("news: reddedildi: ayar geçersiz: news.store_path")
        return None
    if any(_same_file(config.log_path, other) for other in (*bot, config.store_path)):
        output.say("news: reddedildi: ayar geçersiz: news.log_path")
        return None
    return config


def _news_status(config: NewsConfig, output: Output) -> int:
    """R-8: ağsız, kilitsiz; depo yoksa oluşturulmaz."""
    try:
        snapshot = read_snapshot(config.store_path)
    except StoreError as error:
        output.say(f"news: reddedildi: {error}")
        return EXIT_REFUSED
    for row in status_lines(config, snapshot):
        output.say(row)
    return EXIT_OK


def _news_reporter(bot_path: Path, reporter: ReportingService | None) -> ReportingService | None:
    if reporter is not None:
        return reporter
    document = _load_toml(bot_path)
    if not isinstance(document, Mapping):
        return None
    config = load_reporting_config(document)
    return ReportingService(config) if config.is_active else None


@dataclass(frozen=True)
class NewsStreamIO:
    """Spec 0056: akışın gerçek etkileri; testler sahtelerini verir. `env_file`: göreli `.env`."""

    connect: Callable[[str, StreamKeys, int], Connection] = open_stream
    restrictions: Callable[[str, StreamKeys, int], bytes | str | None] = fetch_restrictions
    env: Mapping[str, str] | None = None
    env_file: Path | None = Path(".env")
    first_wait_s: float = 15.0  # plan A-5: the first round waits for the first registration
    check_timeout_s: float = 40.0  # review L-3: the start-up permission check, name lookup included
    # plan A-7: Binance's time (ms) stamps every signed request; `None`: the local clock
    server_time: Callable[[str], int | None] = fetch_server_time
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


def _ms(clock: Clock) -> int:
    return int(clock().timestamp() * 1000)


def _signed_ms(io: "NewsStreamIO", url: str, clock: Clock) -> int:
    """Plan A-7 (VERIFY F-1): imzalı isteğin zaman damgası Binance'in saati; okunamazsa yerel."""
    found: int | None = None
    with suppress(Exception):
        found = io.server_time(url)
    return _ms(clock) if found is None else found


def _stream_sources(config: NewsConfig) -> list[NewsSource]:
    return [s for s in config.sources if s.enabled and s.kind == STREAM_KIND]


def _stream_keys(
    config: NewsConfig, io: NewsStreamIO, output: Output, clock: Clock
) -> dict[str, StreamKeys] | None:
    """Spec 0056 AC-1, AC-2: anahtarlar ortamdan; başlangıçta fazla yetki kesin ret. Kilitten ve
    kayıttan önce, hiçbir haber kaynağına istek gitmeden; değer mesaja girmez."""
    keys: dict[str, StreamKeys] = {}
    for source in _stream_sources(config):
        assert source.key_env is not None and source.secret_env is not None  # stream kind
        try:
            keys[source.name] = load_stream_keys(
                source.key_env, source.secret_env, io.env, io.env_file
            )
        except SecretsError as error:
            output.say(f"news: reddedildi: {error.message}")
            return None
    for source in _stream_sources(config):
        check = _bounded_check(io, source, keys[source.name], clock)
        if check.verdict is Verdict.EXCESS:
            output.say(f"news: reddedildi: {check.message}")
            return None
    return keys


def _bounded_check(
    io: NewsStreamIO, source: NewsSource, keys: StreamKeys, clock: Clock
) -> PermissionCheck:
    """Review round 1 L-3: istek zaman aşımı ad çözümlemeyi kapsamaz; denetim daemon iş
    parçacığında, sınırlı bekleyişle. Süre dolarsa doğrulanamadı: akış bekler, diğerleri sürer."""
    found: list[PermissionCheck] = []

    def attempt() -> None:
        with suppress(Exception):
            stamp = _signed_ms(io, source.url, clock)
            found.append(judge_permissions(io.restrictions(source.url, keys, stamp)))

    thread = threading.Thread(target=attempt, name="akış-yetki", daemon=True)
    thread.start()
    thread.join(timeout=io.check_timeout_s)
    return found[0] if found else PermissionCheck(Verdict.UNVERIFIED)


class _Streams:
    """Spec 0056 (plan Risk 5, 6): akış iş parçacıkları — başlat, ilk denemeyi bekle, durdur."""

    def __init__(
        self,
        config: NewsConfig,
        keys: Mapping[str, StreamKeys],
        io: NewsStreamIO,
        clock: Clock,
        stop: StopRequest,
        say: Callable[[str], None],
        store: NewsStore,
    ) -> None:
        self.io = io
        self.stop = stop
        self.halt = threading.Event()
        self.runners: dict[str, StreamRunner] = {}
        self.threads: list[threading.Thread] = []
        for source in _stream_sources(config):
            previous = store.stream_state(source.name)
            self.runners[source.name] = StreamRunner(
                source.name,
                self._parts(source, keys[source.name], clock, say),
                None if previous is None else previous.last_connected_at,
                timedelta(seconds=0 if previous is None else previous.gap_total_s),
            )

    def _parts(
        self, source: NewsSource, keys: StreamKeys, clock: Clock, say: Callable[[str], None]
    ) -> StreamParts:
        io = self.io

        def connect() -> Connection:
            return io.connect(source.url, keys, _signed_ms(io, source.url, clock))

        def check() -> PermissionCheck:
            stamp = _signed_ms(io, source.url, clock)
            return judge_permissions(io.restrictions(source.url, keys, stamp))

        def tell(text: str) -> None:
            with suppress(Exception):  # a log failure never kills the stream; the round says it
                say(redact(text, keys))

        return StreamParts(clock, io.monotonic, self._wait, self._stopped, connect, check, tell)

    def _stopped(self) -> bool:
        return self.stop.requested or self.halt.is_set()

    def _wait(self, seconds: float) -> bool:
        end = self.io.monotonic() + seconds
        while not self._stopped():
            left = end - self.io.monotonic()
            if left <= 0:
                return False
            self.halt.wait(min(1.0, left))
        return True

    def start(self) -> None:
        for runner in self.runners.values():
            thread = threading.Thread(target=runner.run, name=f"akış-{runner.name}", daemon=True)
            self.threads.append(thread)
            thread.start()
        # the first round should not say `kopuk` while the first connection is being made
        deadline = self.io.monotonic() + self.io.first_wait_s
        while self.runners and not self.stop.requested and self.io.monotonic() < deadline:
            states = [runner.status() for runner in self.runners.values()]
            if all(state.connected or state.fatal is not None for state in states):
                return
            self.io.sleep(0.1)

    def close(self, wait: bool = True) -> None:
        """Bağlantıları kapattırır; zorla durdurmada beklemez (iş parçacıkları daemon, L-4)."""
        self.halt.set()
        if not wait:
            return
        for thread in self.threads:
            thread.join(timeout=5)


def _news(
    argv: Sequence[str],
    news_path: Path,
    bot_path: Path,
    console: TextIO,
    clock: Clock,
    stop: StopRequest,
    wait: Callable[[float], None] | None,
    fetch: NewsFetch,
    reporter: ReportingService | None,
    stream_io: NewsStreamIO | None = None,
) -> int:
    """Spec 0046: `news` toplar, `news status` gösterir. Ayar → kilit → depo sırası (AC-8, AC-9).
    Spec 0056: açık akış kaynağında anahtarlar ve yetki kilitten önce; durum anahtar okumaz."""
    io = NewsStreamIO() if stream_io is None else stream_io
    output = Output(console)
    config = _news_config(news_path, bot_path, output, clock)
    if config is None:
        return EXIT_REFUSED
    if list(argv[1:]) == ["status"]:
        return _news_status(config, output)
    keys = _stream_keys(config, io, output, clock)
    if keys is None:
        return EXIT_REFUSED
    # one lock per file, however the path is spelled (plan Risk 3)
    lock = StoreLock(str(Path(config.store_path).resolve()))
    refused = lock.acquire()
    if refused is not None:
        why = NEWS_BUSY if refused == LOCK_BUSY else refused
        output.say(f"news: reddedildi: {why}")
        return EXIT_REFUSED
    output = Output(console, config.log_path)
    try:
        try:
            store = NewsStore.open(config.store_path)
        except StoreError as error:
            output(line(clock(), "haber", f"reddedildi: {error}"))
            return EXIT_REFUSED
        streams = _Streams(
            config, keys, io, clock, stop, lambda text: output(line(clock(), "haber", text)), store
        )
        forced = False
        try:
            service = _news_reporter(bot_path, reporter)
            streams.start()
            parts = CollectParts(
                clock,
                make_wait(stop) if wait is None else wait,
                lambda: stop.requested,
                lambda source, max_bytes: fetch(source, max_bytes, lambda: stop.requested),
                lambda text: output(line(clock(), "haber", text)),
                None if service is None else service.dispatch,
                None if service is None else service.drain_queue,
                None if service is None else service.take_dropped,
                None if service is None else service.take_disabled_reason,
                streams.runners,
            )
            exit_ = run_collection(config, store, parts)
        except ForcedStop:
            forced = True
            raise
        finally:
            streams.close(wait=not forced)
            store.close()
    except ForcedStop:
        return EXIT_FORCED
    except LogWriteError:
        output.say(line(clock(), "haber", "kayıt dosyası yazılamıyor: toplama durdu"))
        return EXIT_LOG_FAILED
    finally:
        lock.release()
    return EXIT_OK if exit_ is CollectionExit.STOPPED else EXIT_REFUSED


def real_archive_fetch(url: str, max_bytes: int, stopped: Callable[[], bool]) -> Fetched:
    return fetch_source(url, "binance-duyuru", max_bytes, stopped=stopped)


def _archive_config(news_path: Path, bot_path: Path, output: Output) -> ArchiveConfig | None:
    """Spec 0047 AC-10: ağa çıkmadan ve hiçbir dosyaya dokunmadan önce, ilk sorun adıyla. Arşiv ve
    kayıt dosyası ileriye dönük haber kaydı, onun kaydı, bot deposu ya da bot kaydı olamaz,
    birbirleri de olamaz: başka yazımla da (plan Risk 2)."""
    document = _load_toml(news_path)
    if isinstance(document, str):
        output.say(f"news archive: reddedildi: {document}")
        return None
    result = load_archive_config(document)
    config = result.config
    if config is None:
        output.say(f"news archive: reddedildi: {result.message}")
        return None
    others = (*_bot_paths(bot_path), config.news.store_path, config.news.log_path)
    if any(_same_file(config.store_path, other) for other in others):
        output.say("news archive: reddedildi: ayar geçersiz: news.archive_store_path")
        return None
    if any(_same_file(config.log_path, other) for other in (*others, config.store_path)):
        output.say("news archive: reddedildi: ayar geçersiz: news.archive_log_path")
        return None
    return config


def _news_archive(
    argv: Sequence[str],
    news_path: Path,
    bot_path: Path,
    console: TextIO,
    clock: Clock,
    stop: StopRequest,
    wait: Callable[[float], None] | None,
    fetch: ArchiveFetch,
) -> int:
    """Spec 0047: `news archive` doldurur, `news archive status` gösterir (AC-8, AC-9, AC-10)."""
    output = Output(console)
    config = _archive_config(news_path, bot_path, output)
    if config is None:
        return EXIT_REFUSED
    if list(argv[2:]) == ["status"]:
        try:
            rows = archive_status_lines(config)
        except ArchiveStoreError as error:
            output.say(f"news archive: reddedildi: {error}")
            return EXIT_REFUSED
        for row in rows:
            output.say(row)
        return EXIT_OK
    lock = StoreLock(str(Path(config.store_path).resolve()))
    refused = lock.acquire()
    if refused is not None:
        output.say(f"news archive: reddedildi: {ARCHIVE_BUSY if refused == LOCK_BUSY else refused}")
        return EXIT_REFUSED
    output = Output(console, config.log_path)
    try:
        try:
            store = ArchiveStore.open(config.store_path)
        except ArchiveStoreError as error:
            output(line(clock(), "arşiv", f"reddedildi: {error}"))
            return EXIT_REFUSED
        try:
            parts = ArchiveParts(
                clock,
                time.monotonic,
                make_wait(stop) if wait is None else wait,
                lambda: stop.requested,
                lambda url, max_bytes: fetch(url, max_bytes, lambda: stop.requested),
                lambda text: output(line(clock(), "arşiv", text)),
            )
            outcome = run_archive(config, store, parts)
        except ArchiveStoreError as error:
            output(line(clock(), "arşiv", f"durdu: {error}"))
            return EXIT_REFUSED
        finally:
            store.close()
    except ForcedStop:
        return EXIT_FORCED
    except LogWriteError:
        output.say(line(clock(), "arşiv", "kayıt dosyası yazılamıyor: arşiv durdu"))
        return EXIT_LOG_FAILED
    finally:
        lock.release()
    return _ARCHIVE_EXIT_CODES[outcome]


def real_score_call(stopped: Callable[[], bool]) -> ScoreCall:
    """`claude -p` alt süreci (spec 0051 R-5): komut PATH'te bir kez aranır; yoksa her çağrı
    `no_session` olur (R-6)."""
    found = shutil.which("claude")
    executable = None if found is None else [found]

    def call(model: str, system_prompt: str, prompt: str, timeout_s: float) -> ScoreReply:
        reply = call_claude(
            ClaudeRequest(model, system_prompt, prompt, timeout_s),
            executable=executable,
            stopped=stopped,
        )
        return ScoreReply(
            reply.outcome.value,
            reply.text,
            reply.overflow,
            reply.seconds,
            reply.workdir_clean,
            reply.size,
        )

    return call


def _raw_paths(document: object, section: str, keys: Sequence[str]) -> tuple[str, ...]:
    """Bir bölümün yol anahtarları, doğrulamasız: bölüm ya da anahtar yoksa boş."""
    table = document.get(section) if isinstance(document, dict) else None
    if not isinstance(table, Mapping):
        return ()
    return tuple(value for key in keys if isinstance(value := table.get(key), str))


def _score_config(
    news_path: Path, bot_path: Path, events_path: Path, output: Output, clock: Clock
) -> ScoreConfig | None:
    """Spec 0051 AC-8: hiçbir kayda dokunmadan, ilk sorun adıyla. Skor kaydı ve kayıt dosyası
    haber kaydı, arşiv, bot deposu, fiyat deposu, bağlam dosyası ya da başka bir kayıt dosyası
    olamaz, birbirleri de olamaz: başka yazımla da."""
    document = _load_toml(news_path)
    if isinstance(document, str):
        output.say(f"news score: reddedildi: {document}")
        return None
    result = load_score_config(document)
    config = result.config
    if config is None:
        output.say(f"news score: reddedildi: {result.message}")
        return None
    future = permission_in_future(config.news, _utc_today(clock))
    if future is not None:
        output.say(f"news score: reddedildi: {future}")
        return None
    events = _load_toml(events_path)
    others = (
        config.news.store_path,
        config.news.log_path,
        *_raw_paths(document, "news", ("archive_store_path", "archive_log_path")),
        *_bot_paths(bot_path),
        *_raw_paths(events, "events", ("price_store_path", "report_path", "library_path")),
        config.calibration_report_path,
        config.library_path,
        str(news_path),
        str(bot_path),
        str(events_path),
    )
    if any(_same_file(config.store_path, other) for other in others):
        output.say("news score: reddedildi: ayar geçersiz: score.store_path")
        return None
    if any(_same_file(config.log_path, other) for other in (*others, config.store_path)):
        output.say("news score: reddedildi: ayar geçersiz: score.log_path")
        return None
    return config


def _utc_today(clock: Clock) -> date:
    return clock().astimezone(UTC).date()


def _score_context(config: ScoreConfig) -> ScoreContext | str:
    """Bağlam dosyaları okunur, parmak izleri ayardakiyle karşılaştırılır (R-4, AC-6). Örnekler
    yalnız izinli bir `binance-duyuru` kaynağı varsa prompta girer (spec 0055 CB-3)."""
    report = file_bytes(config.calibration_report_path)
    if report is None:
        return "bağlam dosyası yok: score.calibration_report_path"
    library = file_bytes(config.library_path)
    if library is None:
        return "bağlam dosyası yok: score.library_path"
    try:
        return load_context(
            report,
            config.calibration_report_sha256,
            library,
            config.library_sha256,
            examples=any(
                source.permitted and source.kind in BINANCE_KINDS for source in config.news.sources
            ),
        )
    except ContextError as error:
        return str(error)


def _score_pairs(events_path: Path) -> tuple[frozenset[str], datetime | None] | str:
    """USDT spot çiftleri: `crytobot-events.toml`'un fiyat deposunun borsa bilgisi anlık
    görüntüsünden, yalnız SELECT ile ve mumsuz (plan Risk 2, A-2; 0048 R-1 ile aynı bilgi)."""
    paths = _raw_paths(_load_toml(events_path), "events", ("price_store_path",))
    if not paths:
        return "borsa bilgisi yok (crytobot-events.toml price_store_path; önce events download)"
    try:
        snapshot = read_pairs(paths[0])
    except PriceStoreError:
        return "borsa bilgisi okunamıyor"
    if snapshot is None:
        return "borsa bilgisi yok (crytobot-events.toml price_store_path; önce events download)"
    if snapshot.at is None:
        return "borsa bilgisi yok (önce events download)"
    return frozenset(snapshot.pairs), snapshot.at


def _news_score_status(config: ScoreConfig, output: Output, clock: Clock) -> int:
    """R-9: ağsız, LLM'siz, kilitsiz; kayıtlar yalnız okunur, yoksa oluşturulmaz."""
    try:
        snapshot = read_score_snapshot(config.store_path, clock().astimezone(UTC).date())
        forward = (
            None if snapshot is None else read_forward(config.news.store_path, snapshot.started_at)
        )
    except (ScoreStoreError, StoreError) as error:
        output.say(f"news score: reddedildi: {error}")
        return EXIT_REFUSED
    for row in score_status_lines(config, snapshot, forward):
        output.say(row)
    return EXIT_OK


def _news_score(
    argv: Sequence[str],
    paths: tuple[Path, Path, Path],
    console: TextIO,
    clock: Clock,
    stop: StopRequest,
    wait: Callable[[float], None] | None,
    call: ScoreCall | None,
) -> int:
    """Spec 0051: `news score` skorlar, `news score status` gösterir (AC-8, AC-9)."""
    news_path, bot_path, events_path = paths
    output = Output(console)
    config = _score_config(news_path, bot_path, events_path, output, clock)
    if config is None:
        return EXIT_REFUSED
    if list(argv[2:]) == ["status"]:
        return _news_score_status(config, output, clock)
    if not Path(config.news.store_path).is_file():
        output.say(f"news score: reddedildi: haber kaydı yok: {config.news.store_path}")
        return EXIT_REFUSED
    context = _score_context(config)
    if isinstance(context, str):
        output.say(f"news score: reddedildi: {context}")
        return EXIT_REFUSED
    pairs = _score_pairs(events_path)
    if isinstance(pairs, str):
        output.say(f"news score: reddedildi: {pairs}")
        return EXIT_REFUSED
    lock = StoreLock(str(Path(config.store_path).resolve()))
    refused = lock.acquire()
    if refused is not None:
        output.say(f"news score: reddedildi: {SCORE_BUSY if refused == LOCK_BUSY else refused}")
        return EXIT_REFUSED
    output = Output(console, config.log_path)
    try:
        try:
            store = ScoreStore.open(config.store_path, clock())
        except ScoreStoreError as error:
            output(line(clock(), "skor", f"reddedildi: {error}"))
            return EXIT_REFUSED
        try:
            parts = ScoreParts(
                clock,
                make_wait(stop) if wait is None else wait,
                lambda: stop.requested,
                real_score_call(lambda: stop.requested) if call is None else call,
                lambda text: output(line(clock(), "skor", text)),
                context,
                pairs[0],
                pairs[1],
            )
            exit_ = run_scoring(config, store, parts)
        finally:
            store.close()
    except ForcedStop:
        return EXIT_FORCED
    except LogWriteError:
        output.say(line(clock(), "skor", "kayıt dosyası yazılamıyor: skorlama durdu"))
        return EXIT_LOG_FAILED
    finally:
        lock.release()
    return EXIT_OK if exit_ is ScoreExit.STOPPED else EXIT_REFUSED


DecideCall = Callable[[str, str, str, float], DecideReply]
DecideRead = Callable[[tuple[str, ...], datetime], Mapping[str, CoinData | None]]
# spec 0059 plan Risk 2: 250 x 1h warms EMA 200 and the 7-day change; 40 x 4h covers the 30 shown
DECIDE_H1 = ReadSettings(
    "binance", timedelta(hours=1), 250, timedelta(seconds=10), timedelta(minutes=2)
)
DECIDE_H4 = ReadSettings(
    "binance", timedelta(hours=4), 40, timedelta(seconds=10), timedelta(minutes=2)
)
_DAY = timedelta(hours=24)


def real_decide_call(stopped: Callable[[], bool]) -> DecideCall:
    """`claude -p` alt süreci (spec 0059 R-3; 0051 R-5): komut PATH'te bir kez aranır."""
    found = shutil.which("claude")
    executable = None if found is None else [found]

    def call(model: str, system_prompt: str, prompt: str, timeout_s: float) -> DecideReply:
        reply = call_claude(
            ClaudeRequest(model, system_prompt, prompt, timeout_s),
            executable=executable,
            stopped=stopped,
        )
        return DecideReply(reply.outcome.value, reply.text)

    return call


def _floats(read: MarketRead) -> dict[str, tuple[tuple[Candle, ...], Decimal | None]]:
    """Çift → (mumlar, fiyat adımı); mumu okunamayan çift yoktur."""
    found: dict[str, tuple[tuple[Candle, ...], Decimal | None]] = {}
    for pair in read.pairs:
        if pair.candles is None:
            continue
        candles = tuple(
            Candle(c.open_time, float(c.open), float(c.high), float(c.low), float(c.close))
            for c in pair.candles
        )
        found[pair.pair] = (candles, pair.tick)
    return found


def _decide_events(
    score_path: str, coins: Sequence[str], boundary: datetime
) -> dict[str, tuple[EventNote, ...]] | None:
    """Son 24 saatin olay skorları, coin başına (plan Risk 3); kayıt yoksa ya da
    okunamıyorsa `None`."""
    try:
        record = read_score_record(score_path)
    except (ScoreStoreError, OSError):
        return None
    if record is None:
        return None
    moments = {
        row.news_id: row.at for row in record.results if boundary - _DAY <= row.at < boundary
    }
    notes: dict[str, list[EventNote]] = {coin: [] for coin in coins}
    for event in record.events:
        at = moments.get(event.news_id)
        if at is not None and event.coin in notes:
            notes[event.coin].append(
                EventNote(at, event.event_type, event.direction, event.severity)
            )
    return {coin: tuple(sorted(found, key=lambda e: e.at)) for coin, found in notes.items()}


def make_decide_read(
    clock: Clock,
    score_path: str,
    say: Callable[[str], None],
    market: Callable[[tuple[str, ...], ReadSettings], MarketRead] | None = None,
) -> DecideRead:
    """Herkese açık piyasa okuması (anahtarsız, spec 0017) ve skor kaydı, yalnız okuma."""

    def market_read(pairs: tuple[str, ...], settings: ReadSettings) -> MarketRead:
        return read_market_data(pairs, settings, clock)

    reader = market_read if market is None else market

    def read(coins: tuple[str, ...], boundary: datetime) -> dict[str, CoinData | None]:
        pairs = tuple(f"{coin}/{QUOTE}" for coin in coins)
        h1, h4 = _floats(reader(pairs, DECIDE_H1)), _floats(reader(pairs, DECIDE_H4))
        events = _decide_events(score_path, coins, boundary)
        if events is None:
            say("skor kaydı okunamadı ya da yok: olay skorsuz tur")
        found: dict[str, CoinData | None] = {}
        for coin, pair in zip(coins, pairs, strict=True):
            if pair not in h1 or pair not in h4:
                found[coin] = None
                continue
            found[coin] = CoinData(
                coin, h1[pair][0], h4[pair][0], h1[pair][1], () if events is None else events[coin]
            )
        return found

    return read


def _decide_config(
    paths: tuple[Path, Path, Path, Path, Path], output: Output
) -> DecideConfig | None:
    """Spec 0059 AC-1: hiçbir kayda dokunmadan, ilk sorun adıyla. Karar kaydı ve kayıt dosyası
    bot, haber, skor, gölge, forward ve olay kayıtları ya da ayar dosyaları olamaz, birbirleri de
    olamaz: başka yazımla da. Skor kaydının yolu haber ayarındakiyle aynı olmalıdır."""
    decide_path, bot_path, news_path, events_path, forward_path = paths
    document = _load_toml(decide_path)
    if isinstance(document, str):
        output.say(f"decide: reddedildi: {document}")
        return None
    result = load_decide_config(document)
    config = result.config
    if config is None:
        output.say(f"decide: reddedildi: {result.message}")
        return None
    bot, news = _load_toml(bot_path), _load_toml(news_path)
    others = (
        *_bot_paths(bot_path),
        *_raw_paths(bot, "stage", ("paper_store_path",)),
        *_raw_paths(bot, "shadow", ("record_path", "score_path", "news_path")),
        *_raw_paths(
            news, "news", ("store_path", "log_path", "archive_store_path", "archive_log_path")
        ),
        *_raw_paths(
            news, "score", ("store_path", "log_path", "calibration_report_path", "library_path")
        ),
        *_raw_paths(
            _load_toml(events_path), "events", ("price_store_path", "report_path", "library_path")
        ),
        *_raw_paths(
            _load_toml(forward_path), "forward", ("price_store_path", "report_path", "samples_path")
        ),
        *(str(path) for path in paths),
    )
    if any(_same_file(config.store_path, other) for other in others):
        output.say("decide: reddedildi: ayar geçersiz: decide.store_path")
        return None
    if any(_same_file(config.log_path, other) for other in (*others, config.store_path)):
        output.say("decide: reddedildi: ayar geçersiz: decide.log_path")
        return None
    scores = _raw_paths(news, "score", ("store_path",))
    if (
        _same_file(config.score_path, config.store_path)
        or _same_file(config.score_path, config.log_path)
        or (scores and not _same_file(config.score_path, scores[0]))
    ):
        output.say("decide: reddedildi: ayar geçersiz: decide.score_path")
        return None
    return config


def _decide_status(config: DecideConfig, output: Output, clock: Clock) -> int:
    """R-7: ağsız, LLM'siz, kilitsiz; kayıt yalnız okunur, yoksa oluşturulmaz."""
    today = clock().astimezone(UTC).date()
    try:
        snapshot = read_decide_snapshot(config.store_path, today)
    except DecideStoreError as error:
        output.say(f"decide: reddedildi: {error}")
        return EXIT_REFUSED
    for row in decide_status_lines(config, snapshot, today):
        output.say(row)
    return EXIT_OK


def _decide(
    argv: Sequence[str],
    paths: tuple[Path, Path, Path, Path, Path],
    console: TextIO,
    clock: Clock,
    stop: StopRequest,
    wait: Callable[[float], None] | None,
    effects: tuple[DecideCall | None, DecideRead | None, ReportingService | None],
) -> int:
    """Spec 0059: `decide` saatte bir karar turu koşar, `decide status` gösterir (AC-7, AC-8)."""
    call, read, reporter = effects
    output = Output(console)
    config = _decide_config(paths, output)
    if config is None:
        return EXIT_REFUSED
    if list(argv[1:]) == ["status"]:
        return _decide_status(config, output, clock)
    lock = StoreLock(str(Path(config.store_path).resolve()))
    refused = lock.acquire()
    if refused is not None:
        output.say(f"decide: reddedildi: {DECIDE_BUSY if refused == LOCK_BUSY else refused}")
        return EXIT_REFUSED
    output = Output(console, config.log_path)

    def say(text: str) -> None:
        output(line(clock(), "karar", text))

    try:
        try:
            store = DecideStore.open(config.store_path)
        except DecideStoreError as error:
            say(f"reddedildi: {error}")
            return EXIT_REFUSED
        try:
            service = _news_reporter(paths[1], reporter)
            parts = DecideParts(
                clock,
                make_wait(stop) if wait is None else wait,
                lambda: stop.requested,
                make_decide_read(clock, config.score_path, say) if read is None else read,
                real_decide_call(lambda: stop.requested) if call is None else call,
                say,
                None if service is None else service.dispatch,
            )
            exit_ = run_decide(config, store, parts)
        finally:
            store.close()
    except ForcedStop:
        return EXIT_FORCED
    except LogWriteError:
        output.say(line(clock(), "karar", "kayıt dosyası yazılamıyor: karar turu durdu"))
        return EXIT_LOG_FAILED
    finally:
        lock.release()
    return EXIT_OK if exit_ is DecideExit.STOPPED else EXIT_REFUSED


def repo_root() -> Path | None:
    """Botun çalışma ağacı: paketin üstündeki ilk `pyproject.toml`'lu dizin (spec 0048 R-10)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return None


def _inside(path: str, root: Path | None) -> bool:
    return root is not None and Path(path).resolve().is_relative_to(root.resolve())


def _events_config(
    command: str,
    events_path: Path,
    news_path: Path,
    bot_path: Path,
    root: Path | None,
    output: Output,
) -> tuple[EventsConfig, ArchiveConfig] | None:
    """Spec 0048 AC-10: ağa çıkmadan ve hiçbir dosyaya dokunmadan, ilk sorun adıyla."""

    def refuse(text: str) -> None:
        output.say(f"events {command}: reddedildi: {text}")

    document = _load_toml(events_path)
    if isinstance(document, str):
        refuse(document)
        return None
    result = load_events_config(document)
    config = result.config
    if config is None:
        refuse(result.message)
        return None
    news_document = _load_toml(news_path)
    if isinstance(news_document, str):
        refuse(news_document)
        return None
    loaded = load_archive_config(news_document)
    archive = loaded.config
    if archive is None:
        refuse(loaded.message)
        return None
    protected = (
        archive.store_path,
        archive.log_path,
        archive.news.store_path,
        archive.news.log_path,
        *_bot_paths(bot_path),
        str(events_path),
        str(news_path),
        str(bot_path),
    )
    outputs = (
        ("price_store_path", config.price_store_path),
        ("report_path", config.report_path),
        ("library_path", config.library_path),
    )
    for index, (key, path) in enumerate(outputs):
        others = (*protected, *(other for _, other in outputs[:index]))
        if any(_same_file(path, other) for other in others) or _inside(path, root):
            refuse(f"ayar geçersiz: events.{key}")
            return None
    if not Path(archive.store_path).is_file():
        refuse(f"arşiv yok: {archive.store_path}")
        return None
    return config, archive


def _event_inputs(archive: ArchiveConfig) -> Callable[[], EventInputs | str]:
    """Kaynak kayıtlar `news`'le okunur ve etiketlenir, `calibration`'ın tipine çevrilir."""

    def read() -> EventInputs | str:
        news = archive.news
        binance = tuple(each.name for each in news.sources if each.kind == "binance-duyuru")
        try:
            sources = read_library_sources(archive.store_path, news.store_path, binance)
        except ArchiveStoreError as error:
            return str(error)
        announcements = tuple(
            EventAnnouncement(
                item.article_id,
                item.origin,
                item.catalog,
                item.title,
                item.published,
                item.first_seen,
                item.event_type,
                item.direction,
                item.coins,
                title_pattern(item.title),
            )
            for item in sources.announcements
        )
        return EventInputs(
            announcements,
            EVENT_TYPES,
            archive.store_path,
            sources.archive_records,
            news.store_path,
            sources.forward_records,
            sources.rules_fingerprint,
        )

    return read


def _event_prices(path: str) -> Callable[[], PriceData | str | None]:
    def read() -> PriceData | str | None:
        try:
            return read_prices(path)
        except PriceStoreError as error:
            return str(error)

    return read


def _events_download(
    config: EventsConfig,
    archive: ArchiveConfig,
    output: Output,
    clock: Clock,
    stop: StopRequest,
    wait: Callable[[float], None] | None,
    download: EventsDownload,
) -> EventsOutcome:
    try:
        store = PriceStore.open(config.price_store_path)
    except PriceStoreError as error:
        output.say(f"events download: reddedildi: {error}")
        return EventsOutcome.REFUSED
    try:
        parts = EventPriceParts(
            clock,
            time.monotonic,
            make_wait(stop) if wait is None else wait,
            lambda: stop.requested,
            lambda text: output.say(f"events download: {text}"),
        )
        exit_ = run_events_download(
            config,
            EventDownloadParts(
                _event_inputs(archive),
                lambda needs: download(needs, store, parts, config.request_gap_s),
                output.say,
            ),
        )
    finally:
        store.close()
    return exit_.outcome


def _events(
    command: str,
    paths: tuple[Path, Path, Path],
    root: Path | None,
    console: TextIO,
    clock: Clock,
    stop: StopRequest,
    wait: Callable[[float], None] | None,
    download: EventsDownload,
) -> int:
    """Spec 0048: ayarlar → yollar → arşiv → kilit(ler) → koşu (AC-10, AC-11)."""
    output = Output(console)
    events_path, news_path, bot_path = paths
    loaded = _events_config(command, events_path, news_path, bot_path, root, output)
    if loaded is None:
        return EXIT_REFUSED
    config, archive = loaded
    wanted = [(config.price_store_path, EVENTS_BUSY)]
    if command == "measure":
        wanted.append((config.report_path, EVENTS_REPORT_BUSY))
    locks: list[StoreLock] = []
    try:
        for path, busy in wanted:
            lock = StoreLock(str(Path(path).resolve()))
            refused = lock.acquire()
            if refused is not None:
                why = busy if refused == LOCK_BUSY else refused
                output.say(f"events {command}: reddedildi: {why}")
                return EXIT_REFUSED
            locks.append(lock)
        if command == "download":
            outcome = _events_download(config, archive, output, clock, stop, wait, download)
        else:
            parts = EventMeasureParts(
                _event_inputs(archive),
                _event_prices(config.price_store_path),
                report_exists,
                write_report,
                output.say,
                clock,
            )
            outcome = run_events_measure(config, parts).outcome
    except ForcedStop:
        return EXIT_FORCED
    finally:
        for lock in locks:
            lock.release()
    return _EVENTS_EXIT_CODES[outcome]


ForwardSetup = tuple[ForwardConfig, ScoreConfig, tuple[str, ...], ShadowConfig | None]


def _forward_config(
    command: str, paths: tuple[Path, Path, Path, Path], output: Output, clock: Clock
) -> ForwardSetup | None:
    """Spec 0053 AC-10, plan Risk 6, 10: hiçbir dosyaya dokunmadan, ilk sorun adıyla. Korunanlar
    skorlayıcının bağlam dosyalarını ve 0048'in çıktılarını da içerir (review R1-3)."""
    forward_path, news_path, bot_path, events_path = paths

    def refuse(text: str) -> None:
        output.say(f"forward {command}: reddedildi: {text}")

    document = _load_toml(forward_path)
    if isinstance(document, str):
        refuse(document)
        return None
    loaded = load_forward_config(document)
    config = loaded.config
    if config is None:
        refuse(loaded.message)
        return None
    news_document = _load_toml(news_path)
    if isinstance(news_document, str):
        refuse(news_document)
        return None
    scored = load_score_config(news_document)
    score = scored.config
    if score is None:
        refuse(scored.message)
        return None
    future = permission_in_future(score.news, _utc_today(clock))
    if future is not None:
        refuse(future)
        return None
    bot_document = _load_toml(bot_path)
    if isinstance(bot_document, str):
        refuse(bot_document)
        return None
    bot = load_config(bot_document, clock())
    if bot.config is None:
        refuse(f"bot ayarı: {bot.message}")
        return None
    shadowed = load_shadow_config(bot_document)
    shadow = shadowed.config
    if shadow is None and shadowed.setting is not None:
        refuse(shadowed.message)
        return None
    protected = (
        score.store_path,
        score.log_path,
        score.calibration_report_path,
        score.library_path,
        score.news.store_path,
        score.news.log_path,
        *_raw_paths(news_document, "news", ("archive_store_path", "archive_log_path")),
        *_raw_paths(
            _load_toml(events_path), "events", ("price_store_path", "report_path", "library_path")
        ),
        *(() if shadow is None else (shadow.record_path,)),
        bot.config.store_path,
        bot.config.log_path,
        *_raw_paths(bot_document, "stage", ("paper_store_path",)),
        str(forward_path),
        str(news_path),
        str(bot_path),
    )
    outputs = (
        ("price_store_path", config.price_store_path),
        ("report_path", config.report_path),
        ("samples_path", config.samples_path),
    )
    for index, (key, path) in enumerate(outputs):
        others = (*protected, *(other for _, other in outputs[:index]))
        if any(_same_file(path, other) for other in others):
            refuse(f"ayar geçersiz: forward.{key}")
            return None
    return config, score, tuple(bot.config.turn.whitelist), shadow


def _shadow_turn(row: object) -> ShadowTurn | None:
    """Gölge kaydın bir satırı (spec 0052 A-1); beklenen alanları taşımayan satır bozuktur."""
    if not isinstance(row, Mapping):
        return None
    texts = ("turn_at", "pair", "state", "reason", "technical_buy")
    if any(not isinstance(row.get(key), str) for key in texts):
        return None
    listed = row.get("whitelist")
    if not isinstance(listed, list) or not all(isinstance(pair, str) for pair in listed):
        return None
    try:
        moment = datetime.fromisoformat(str(row["turn_at"]))
    except ValueError:
        return None
    if moment.utcoffset() is None:
        return None
    return ShadowTurn(
        moment,
        str(row["pair"]),
        tuple(str(pair) for pair in listed),
        str(row["state"]),
        str(row["reason"]),
        row["technical_buy"] == "var",
    )


def _triple(
    model: str | None, prompt: str | None, context: str | None
) -> tuple[str, str, str] | None:
    if model is None or prompt is None or context is None:
        return None
    return model, prompt, context


def _forward_sources(
    score: ScoreConfig, whitelist: tuple[str, ...], shadow: ShadowConfig | None
) -> Callable[[], ForwardSources | str]:
    """Kayıtlar `news`'le yalnız okunur (R-1), gölge kayıt burada çözülür; `calibration`'ın tipi."""

    def read() -> ForwardSources | str:
        try:
            record = read_score_record(score.store_path)
            names = read_news_sources(score.news.store_path)
        except (ScoreStoreError, StoreError) as error:
            return str(error)
        kinds = {source.name: source.kind for source in score.news.sources}
        sources = (
            {}
            if names is None
            else {news_id: kinds.get(name, "bilinmiyor") for news_id, name in names.items()}
        )
        rows: list[object] | None = None
        if shadow is not None:
            try:
                rows = _shadow_rows(shadow.record_path)
            except OSError:
                return "gölge kayıt okunamıyor"
        turns = None if rows is None else [_shadow_turn(row) for row in rows]
        results = (
            None
            if record is None
            else tuple(
                ScoredNews(
                    row.news_id,
                    row.kind,
                    row.at,
                    _triple(row.model, row.prompt_fingerprint, row.context_fingerprint),
                )
                for row in record.results
            )
        )
        events = (
            ()
            if record is None
            else tuple(
                ForwardEvent(e.news_id, e.coin, e.event_type, e.direction, e.severity)
                for e in record.events
            )
        )
        kept = None if turns is None else tuple(turn for turn in turns if turn is not None)
        # spec 0055 CB-4, closed by default (review M-1): a name missing from the config, and a
        # result whose news is not in the news record (or no record at all), is not permitted
        permitted = score.news.permitted_names
        found = names or {}
        unpermitted = {
            row.news_id: found.get(row.news_id, UNKNOWN_SOURCE_NAME)
            for row in (record.results if record is not None else ())
            if found.get(row.news_id) not in permitted
        }
        return ForwardSources(
            ForwardInputs(results, events, sources, kept, whitelist, unpermitted),
            score.store_path,
            0 if record is None else record.skipped,
            score.news.store_path,
            None if shadow is None else shadow.record_path,
            0 if turns is None else sum(turn is None for turn in turns),
        )

    return read


def write_atomic(path: str, text: str) -> bool:
    """Plan Risk 7: aynı dizinde geçici dosya, sonra `os.replace`; yarım dosya kalmaz."""
    target = Path(path)
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temp = Path(file.name)
            file.write(text)
        os.replace(temp, target)
    except OSError:
        if temp is not None:
            with suppress(OSError):
                temp.unlink()
        return False
    return True


def _report_at(argv: Sequence[str]) -> datetime | str | None:
    """`report` → `None`; `report --at <an>` → an; geçersizse ret metni."""
    if len(argv) == 1:
        return None
    try:
        moment = datetime.fromisoformat(argv[2])
    except ValueError:
        return FORWARD_AT_INVALID
    if moment.utcoffset() is None:
        return FORWARD_AT_INVALID
    return moment.astimezone(UTC)


def _forward_download(
    config: ForwardConfig,
    sources: Callable[[], ForwardSources | str],
    output: Output,
    clock: Clock,
    stop: StopRequest,
    wait: Callable[[float], None] | None,
    download: EventsDownload,
) -> ForwardOutcome:
    lock = StoreLock(str(Path(config.price_store_path).resolve()))
    refused = lock.acquire()
    if refused is not None:
        why = FORWARD_BUSY if refused == LOCK_BUSY else refused
        output.say(f"forward download: reddedildi: {why}")
        return ForwardOutcome.REFUSED
    try:
        try:
            store = PriceStore.open(config.price_store_path)
        except PriceStoreError as error:
            output.say(f"forward download: reddedildi: {error}")
            return ForwardOutcome.REFUSED
        try:
            parts = EventPriceParts(
                clock,
                time.monotonic,
                make_wait(stop) if wait is None else wait,
                lambda: stop.requested,
                lambda text: output.say(f"forward download: {text}"),
            )
            exit_ = run_forward_download(
                config,
                ForwardDownloadParts(
                    sources,
                    lambda needs: download(needs, store, parts, config.request_gap_s),
                    output.say,
                    clock,
                ),
            )
        finally:
            store.close()
    finally:
        lock.release()
    return exit_.outcome


def _forward(
    argv: Sequence[str],
    paths: tuple[Path, Path, Path, Path],
    console: TextIO,
    clock: Clock,
    stop: StopRequest,
    wait: Callable[[float], None] | None,
    download: EventsDownload,
) -> int:
    """Spec 0053: ayarlar → yollar → koşu; `download` kilitli, `report` kilitsiz (R-1)."""
    output = Output(console)
    given = list(argv)
    valid = given in (["download"], ["report"]) or (
        len(given) == 3 and given[:2] == ["report", "--at"]
    )
    if not valid:
        output.say(USAGE)
        return EXIT_REFUSED
    command = given[0]
    at = _report_at(given) if command == "report" else None
    if isinstance(at, str):
        output.say(f"forward report: reddedildi: {at}")
        return EXIT_REFUSED
    setup = _forward_config(command, paths, output, clock)
    if setup is None:
        return EXIT_REFUSED
    config, score, whitelist, shadow = setup
    sources = _forward_sources(score, whitelist, shadow)
    try:
        if command == "download":
            outcome = _forward_download(config, sources, output, clock, stop, wait, download)
        else:
            parts = ForwardReportParts(
                sources, _event_prices(config.price_store_path), write_atomic, output.say, clock
            )
            outcome = run_forward_report(config, parts, at).outcome
    except ForcedStop:
        return EXIT_FORCED
    return _FORWARD_EXIT_CODES[outcome]


def _prepare(
    config: BotConfig,
    output: Output,
    clock: Clock,
    *,
    is_live: bool = False,
    testnet: bool = False,
    live_client: object = None,
) -> int:
    if is_live:
        result = prepare_live_store(
            config.store_path,
            clock(),
            testnet=testnet,
            live_client=live_client,
        )
    else:
        result = prepare_store(config.store_path, config.opening_balance, clock())
    output(line(clock(), "hazırlık", result.message))
    return EXIT_OK if result.outcome is PrepareOutcome.PREPARED else EXIT_REFUSED


def _stage_gate(
    config_path: Path,
    bot: BotConfig,
    output: Output,
    clock: Clock,
    *,
    mode: str = "paper",
) -> tuple[bool, str | None, str | None, str | None]:
    """BR-10 aşama kapısı: kilit alınmadan, depo açılmadan ve ağa gitmeden önce denetlenir.

    `[backtest] spread` ham değeriyle kapıya gider (yoksa `None`; spec 0040 CB-4, plan Risk 6).
    Döndürür: (geçti_mi, onaylayan_adı, rapor_yolu, rapor_parmak_izi).
    """
    document = _load_toml(config_path)
    if isinstance(document, str):
        output.say(line(clock(), "başlatma", f"başlatma reddedildi: {document}"))
        return False, None, None, None

    stage_res = load_stage_config(document, mode=mode)
    if stage_res.config is None:
        output.say(line(clock(), "başlatma", f"başlatma reddedildi: {stage_res.message}"))
        return False, None, None, None

    stage = stage_res.config
    report_read = read_report(stage.report_path)
    backtest_tbl = document.get("backtest")
    raw_spread = backtest_tbl.get("spread") if isinstance(backtest_tbl, Mapping) else None

    gate_res = check_stage_gate(stage, bot, report_read, raw_spread, clock())
    if not gate_res.passed:
        output.say(line(clock(), "başlatma", f"başlatma reddedildi: {gate_res.message}"))
        return False, None, None, None

    return True, stage.approved_by, stage.report_path, stage.report_sha256


def _paper_proof_gate(
    config_path: Path, bot: BotConfig, output: Output, clock: Clock
) -> PaperProof | None:
    """Spec 0038 CB-2…CB-5: ayar ve rapor kapılarından sonra, kimlik ve yetki denetiminden (ağa
    çıkan tek adım) önce; kilit alınmadan, canlı depo açılmadan. Testnet'te de aynıdır."""
    document = _load_toml(config_path)
    stage_res = load_stage_config(document, mode="live")
    if stage_res.config is None:  # read just before by _stage_gate; a changed file is refused
        output.say(line(clock(), "başlatma", f"başlatma reddedildi: {stage_res.message}"))
        return None
    result = check_paper_proof(
        stage_res.config,
        bot,
        bot.store_path,
        clock(),
        is_lock_held,
        same_file=_same_file,
        resolve=lambda path: str(Path(path).resolve()),
    )
    if result.summary is None:
        output.say(line(clock(), "başlatma", f"başlatma reddedildi: {result.message}"))
    return result.summary


def _dashboard(
    config_path: Path,
    config: BotConfig,
    output: Output,
    clock: Clock,
    stop: StopRequest,
) -> int:
    document = _document(config_path, output, clock)
    if document is None:
        return EXIT_REFUSED
    dash_res = load_dashboard_config(document)
    if dash_res.config is None:
        output.say(line(clock(), "dashboard", f"reddedildi: {dash_res.message}"))
        return EXIT_REFUSED
    dash_cfg = dash_res.config

    def status_provider() -> tuple[int, dict[str, object]]:
        running = is_lock_held(config.store_path)
        logs_tuple: tuple[str, ...] = ()
        log_file = Path(config.log_path)
        if log_file.is_file():
            try:
                with open(log_file, "rb") as f:
                    size = log_file.stat().st_size
                    seek_pos = max(0, size - 8192)
                    f.seek(seek_pos)
                    chunk = f.read().decode("utf-8", errors="replace")
                    all_lines = [line.strip() for line in chunk.splitlines() if line.strip()]
                    logs_tuple = tuple(all_lines[-10:])
            except OSError:
                pass
        return get_dashboard_status(config, clock=clock, is_running=running, logs=logs_tuple)

    try:
        server = create_server(dash_cfg.host, dash_cfg.port, status_provider)
    except PortBusyError as err:
        output.say(line(clock(), "dashboard", f"reddedildi: {err}"))
        return EXIT_REFUSED

    output.say(f"http://{dash_cfg.host}:{dash_cfg.port}")

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        while not stop.requested:
            time.sleep(0.1)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2.0)

    return EXIT_OK


def _pair_filter(found: CoinFilter) -> PairFilter:
    """`news`'in görünümü `app`'in tipine (plan Risk 4)."""
    missing = found.missing
    return PairFilter(
        found.state.value,
        found.reason,
        tuple((ref.news_id, ref.severity) for ref in found.events),
        None if missing is None else (missing.pending, missing.schema, missing.stale),
        found.held,
    )


ShadowViewCall = Callable[[datetime, tuple[str, ...]], dict[str, PairFilter]]


def shadow_view(config: ShadowConfig) -> ShadowViewCall:
    """Tur anında skor ve haber kaydını yalnız okur; çift → filtre durumu (R-3, R-6)."""

    def view(at: datetime, pairs: tuple[str, ...]) -> dict[str, PairFilter]:
        coins = tuple(dict.fromkeys(base_of(pair) for pair in pairs))
        found = read_filter_view(config.score_path, config.news_path, at, coins)
        return {pair: _pair_filter(found[base_of(pair)]) for pair in pairs}

    return view


def shadow_append(path: str) -> Callable[[Sequence[Mapping[str, object]]], None]:
    """Bir turun satırları tek yazım ve `flush` ile, yalnız ekleme kipinde (R-8, plan Risk 5).
    Çökmede yarım kalan son satırın arkasına yazılmaz: önce satır sonu eklenir."""

    def append(rows: Sequence[Mapping[str, object]]) -> None:
        text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        with open(path, "a+b") as file:
            if file.tell() > 0:
                file.seek(-1, 2)
                if file.read(1) != b"\n":
                    text = "\n" + text
            file.write(text.encode("utf-8"))
            file.flush()

    return append


def _shadow_refused(message: str, output: Output, clock: Clock) -> str:
    output.say(line(clock(), "ayar", f"bot başlamadı: {message}"))
    return message


def _shadow_config(
    paths: tuple[Path, Path], config: BotConfig, output: Output, clock: Clock
) -> ShadowConfig | str | None:
    """Paper başlatmanın `[shadow]` bölümü: yoksa `None`, ret varsa konsola yazılmış neden (R-8).
    Kayıt dosyası açılmadan, kilit alınmadan; yollar çözülmüş hâlleriyle karşılaştırılır."""
    config_path, news_config_path = paths
    document = _load_toml(config_path)
    result = load_shadow_config(document if isinstance(document, Mapping) else {})
    shadow = result.config
    if shadow is None:
        return None if result.setting is None else _shadow_refused(result.message, output, clock)
    for key, path in (("score_path", shadow.score_path), ("news_path", shadow.news_path)):
        if _same_file(path, config.store_path):
            return _shadow_refused(f"ayar geçersiz: shadow.{key}", output, clock)
    news = _load_toml(news_config_path)
    news_keys = ("store_path", "log_path", "archive_store_path", "archive_log_path")
    others = (
        config.store_path,
        config.log_path,
        *_raw_paths(document, "stage", ("paper_store_path",)),
        shadow.score_path,
        shadow.news_path,
        str(config_path),
        str(news_config_path),
        *_raw_paths(news, "news", news_keys),
        *_raw_paths(news, "score", ("store_path", "log_path")),
    )
    if any(_same_file(shadow.record_path, other) for other in others):
        return _shadow_refused("ayar geçersiz: shadow.record_path", output, clock)
    return shadow


def _shadow_rows(path: str) -> list[object] | None:
    """Gölge kayıt yoksa `None`; çözülemeyen satır `None` öğedir (yarım kalan satır)."""
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        return None
    rows: list[object] = []
    for raw in data.split(b"\n"):
        if not raw.strip():
            continue
        try:
            rows.append(json.loads(raw.decode("utf-8")))
        except (ValueError, RecursionError):
            rows.append(None)
    return rows


def _shadow_status(config_path: Path, output: Output) -> int:
    """R-9: ağsız, LLM'siz, kilitsiz; gölge kayıt ve bot kayıt dosyası yalnız okunur."""
    document = _load_toml(config_path)
    if isinstance(document, str):
        output.say(f"shadow status: reddedildi: {document}")
        return EXIT_REFUSED
    result = load_shadow_config(document)
    if result.config is None:
        output.say(f"shadow status: reddedildi: {result.message or 'ayar eksik: shadow'}")
        return EXIT_REFUSED
    path = result.config.record_path
    try:
        rows = _shadow_rows(path)
    except OSError:
        output.say("shadow status: reddedildi: gölge kayıt okunamıyor")
        return EXIT_REFUSED
    error: str | None = None
    logs = _raw_paths(document, "bot", ("log_path",))
    if logs:
        with suppress(OSError):
            text = Path(logs[0]).read_text(encoding="utf-8", errors="replace")
            error = last_shadow_error(text.splitlines())
    for row in shadow_status_lines(path, rows, error):
        output.say(row)
    return EXIT_OK


def _start(
    config: BotConfig,
    output: Output,
    parts: LoopParts,
    *,
    trial: bool = True,
    approved_by: str | None = None,
    report_path: str | None = None,
    report_sha256: str | None = None,
    reporter: ReportingService | None = None,
    exchange: object = None,
    paper_proof: PaperProof | None = None,
) -> int:
    check = open_for_start(config.store_path, mode=config.mode)
    if check.outcome is StartOutcome.READY and config.mode == "paper":
        # spec 0038 CB-1: after READY, before any turn; the report as an absolute path (G-5)
        absolute = None if report_path is None else str(Path(report_path).resolve())
        check = record_start(
            config.store_path,
            trial=trial,
            report_path=absolute,
            report_sha256=report_sha256,
            now=parts.clock(),
        )
    if check.outcome is not StartOutcome.READY:
        hint = f"; {check.hint}" if check.hint is not None else ""
        output(line(parts.clock(), "başlatma", f"{check.message}{hint}"))
        return EXIT_REFUSED
    exit_ = run_loop(
        config,
        parts,
        exchange=exchange,  # type: ignore[arg-type]
        trial=trial,
        approved_by=approved_by,
        report_path=report_path,
        reporter=reporter,
        paper_proof=paper_proof,
    )
    if exit_.reason is ExitReason.LOG_FAILED:
        output.say(line(parts.clock(), "durdurma", _LOG_FAILED))
    return _EXIT_CODES[exit_.reason]


def run(
    argv: Sequence[str],
    *,
    config_path: Path = Path(CONFIG_FILE),
    console: TextIO = sys.stdout,
    clock: Clock = utc_now,
    stop: StopRequest | None = None,
    read: Read | None = None,
    wait: Callable[[float], None] | None = None,
    download: Download = download_history,
    reporter: ReportingService | None = None,
    live_client: object = None,
    news_config_path: Path = Path(NEWS_CONFIG_FILE),
    news_fetch: NewsFetch = real_news_fetch,
    archive_fetch: ArchiveFetch = real_archive_fetch,
    events_config_path: Path = Path(EVENTS_CONFIG_FILE),
    events_download: EventsDownload = download_event_prices,
    root: Path | None = None,
    score_call: ScoreCall | None = None,
    forward_config_path: Path = Path(FORWARD_CONFIG_FILE),
    news_stream: NewsStreamIO | None = None,
    decide_config_path: Path = Path(DECIDE_CONFIG_FILE),
    decide_call: DecideCall | None = None,
    decide_read: DecideRead | None = None,
) -> int:
    """Komutu çalıştırır, çıkış kodunu döndürür. Ayar, kilit, depo sırası: borsaya ve depoya
    ayarlar denetlenmeden dokunulmaz (R-2); kilit depodan önce alınır (R-6)."""
    stop = StopRequest() if stop is None else stop
    output = Output(console)
    if argv and argv[0] == "forward":
        return _forward(
            list(argv[1:]),
            (forward_config_path, news_config_path, config_path, events_config_path),
            console,
            clock,
            stop,
            wait,
            events_download,
        )
    if list(argv) not in COMMANDS:
        output.say(USAGE)
        return EXIT_REFUSED
    if argv[0] == "download":
        return _download(config_path, output, clock, stop, download)
    if argv[0] == "backtest":
        return _backtest(config_path, output, stop, clock, final="--final" in argv)
    if argv[0] == "calibrate":
        return _calibrate(config_path, output, stop, clock, final="--final" in argv)
    if argv[0] == "events":
        return _events(
            argv[1],
            (events_config_path, news_config_path, config_path),
            repo_root() if root is None else root,
            console,
            clock,
            stop,
            wait,
            events_download,
        )
    if list(argv[:2]) == ["news", "score"]:
        return _news_score(
            argv,
            (news_config_path, config_path, events_config_path),
            console,
            clock,
            stop,
            wait,
            score_call,
        )
    if list(argv[:2]) == ["news", "archive"]:
        return _news_archive(
            argv, news_config_path, config_path, console, clock, stop, wait, archive_fetch
        )
    if argv[0] == "news":
        return _news(
            argv,
            news_config_path,
            config_path,
            console,
            clock,
            stop,
            wait,
            news_fetch,
            reporter,
            news_stream,
        )
    if argv[0] == "shadow":
        return _shadow_status(config_path, output)
    if argv[0] == "decide":
        return _decide(
            argv,
            (
                decide_config_path,
                config_path,
                news_config_path,
                events_config_path,
                forward_config_path,
            ),
            console,
            clock,
            stop,
            wait,
            (decide_call, decide_read, reporter),
        )
    config = _config(config_path, output, clock)
    if config is None:
        return EXIT_REFUSED

    is_live = "--live" in argv
    if is_live and config.mode != "live":
        output.say(
            line(
                clock(),
                argv[0],
                "başlatma reddedildi: MODE_MISMATCH"
                " (komutta --live bayrağı var ancak config modu live değil)",
            )
        )
        return EXIT_REFUSED

    if config.mode == "live" and not is_live and argv[0] in ("start", "prepare"):
        output.say(
            line(
                clock(),
                argv[0],
                "başlatma reddedildi: LIVE_FLAG_REQUIRED"
                " (config modu live ancak --live bayrağı verilmedi)",
            )
        )
        return EXIT_REFUSED

    if argv[0] == "status":
        running = is_lock_held(config.store_path)
        res = query_status(config, clock=clock, is_running=running)
        output.say(res.message)
        return EXIT_OK if res.success else EXIT_REFUSED

    if argv[0] == "kill-switch":
        # spec 0035 plan Risk 1: çalışan bota doğrudan yazılmaz, istek bayrağına gider

        def _request_kill() -> None:
            set_kill_flag(config.store_path)

        res = _locked_control(
            config.store_path,
            lambda running: engage_kill_switch(
                config, clock=clock, is_running=running, request_kill=_request_kill
            ),
        )
        msg = res.message if res.success else f"reddedildi: {res.message}"
        output.say(line(clock(), "kill-switch", msg))
        return EXIT_OK if res.success else EXIT_REFUSED

    if argv[0] == "resume":
        # spec 0035 R-7: çalışan botta resume reddedilir
        res = _locked_control(
            config.store_path,
            lambda running: resume_operations(config, clock=clock, is_running=running),
        )
        msg = res.message if res.success else f"reddedildi: {res.message}"
        output.say(line(clock(), "resume", msg))
        return EXIT_OK if res.success else EXIT_REFUSED

    if argv[0] == "stop":
        running = is_lock_held(config.store_path)

        def _set_flag() -> None:
            set_stop_flag(config.store_path)

        res = request_stop(
            config,
            clock=clock,
            is_running=running,
            on_stop_requested=_set_flag,
        )
        msg = res.message if res.success else f"reddedildi: {res.message}"
        output.say(line(clock(), "stop", msg))
        return EXIT_OK if res.success else EXIT_REFUSED

    if argv[0] == "dashboard":
        return _dashboard(config_path, config, output, clock, stop)

    trial = len(argv) > 1 and argv[1] == "--trial"
    approved_by: str | None = None
    report_path: str | None = None
    report_sha256: str | None = None
    live_exchange: object = None
    paper_proof: PaperProof | None = None

    if argv[0] == "start":
        if is_live:
            passed, approved_by, report_path, report_sha256 = _stage_gate(
                config_path, config, output, clock, mode="live"
            )
            if not passed:
                return EXIT_REFUSED
            paper_proof = _paper_proof_gate(config_path, config, output, clock)
            if paper_proof is None:
                return EXIT_REFUSED
            document = _load_toml(config_path)
            testnet = False
            if (
                isinstance(document, Mapping)
                and "exchange" in document
                and isinstance(document["exchange"], Mapping)
            ):
                testnet = bool(document["exchange"].get("testnet", False))
            live_exch, err = create_live_exchange(
                testnet=testnet,
                client=live_client,
            )
            if live_exch is None:
                output.say(line(clock(), "başlatma", f"başlatma reddedildi: {err}"))
                return EXIT_REFUSED
            live_exchange = live_exch
            if testnet:
                output.say(line(clock(), "başlatma", "Binance Spot Testnet modunda çalışıyor"))
        elif not trial:
            passed, approved_by, report_path, report_sha256 = _stage_gate(
                config_path, config, output, clock, mode="paper"
            )
            if not passed:
                return EXIT_REFUSED
    shadow: ShadowParts | None = None
    if argv[0] == "start" and not is_live and config.mode == "paper":
        # spec 0052 R-1, R-8: paper only; refused before the log file and the lock
        found = _shadow_config((config_path, news_config_path), config, output, clock)
        if isinstance(found, str):
            return EXIT_REFUSED
        if found is not None:
            shadow = ShadowParts(shadow_view(found), shadow_append(found.record_path))

    output = Output(console, config.log_path)
    lock = StoreLock(config.store_path)
    try:
        refused = lock.acquire()
        if refused is not None:
            output(line(clock(), argv[0], f"reddedildi: {refused}"))
            return EXIT_REFUSED
        if argv[0] == "prepare":
            testnet = False
            if is_live:
                document = _load_toml(config_path)
                if (
                    isinstance(document, Mapping)
                    and "exchange" in document
                    and isinstance(document["exchange"], Mapping)
                ):
                    testnet = bool(document["exchange"].get("testnet", False))
            return _prepare(
                config,
                output,
                clock,
                is_live=is_live,
                testnet=testnet,
                live_client=live_client,
            )
        parts = LoopParts(
            clock,
            make_wait(stop, stop_flag_path=stop_flag_path(config.store_path))
            if wait is None
            else wait,
            make_read(clock) if read is None else read,
            output,
            stop,
            KillRequest(
                pending=lambda: kill_flag_set(config.store_path),
                consume=lambda: clear_kill_flag(config.store_path),
            ),
            shadow,
        )
        if reporter is None:
            document = _load_toml(config_path)
            reporting_cfg = (
                load_reporting_config(document) if isinstance(document, Mapping) else None
            )
            if reporting_cfg is not None and reporting_cfg.is_active:
                reporter = ReportingService(reporting_cfg)
        return _start(
            config,
            output,
            parts,
            trial=trial,
            approved_by=approved_by,
            report_path=report_path,
            report_sha256=report_sha256,
            reporter=reporter,
            exchange=live_exchange,
            paper_proof=paper_proof,
        )
    except LogWriteError:
        output.say(line(clock(), "durdurma", _LOG_FAILED))
        return EXIT_LOG_FAILED
    finally:
        clear_stop_flag(config.store_path)
        lock.release()


def main() -> int:
    stop = StopRequest()
    install_signals(stop)
    try:
        return run(sys.argv[1:], stop=stop)
    except ForcedStop:
        return EXIT_FORCED


if __name__ == "__main__":
    sys.exit(main())
