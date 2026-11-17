"""Giriş noktası: `python -m crytobot prepare|start|download|backtest|calibrate|news|events` (spec
0022, 0023, 0025, 0045, 0046, 0047, 0048, 0051).

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
"""

import hashlib
import shutil
import signal
import sys
import tempfile
import threading
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import IO, TextIO

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
    KillRequest,
    LogWriteError,
    LoopParts,
    PaperProof,
    PrepareOutcome,
    StartOutcome,
    StopRequest,
    check_paper_proof,
    check_stage_gate,
    create_live_exchange,
    engage_kill_switch,
    final_configs,
    get_dashboard_status,
    line,
    load_backtest_config,
    load_calibration_config,
    load_config,
    load_download_config,
    load_events_config,
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
    run_loop,
)
from crytobot.backtest import read_report, report_exists, write_report
from crytobot.calibration import EventAnnouncement
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
    EVENT_TYPES,
    ArchiveConfig,
    ArchiveOutcome,
    ArchiveParts,
    ArchiveStore,
    ArchiveStoreError,
    CollectionExit,
    CollectParts,
    ContextError,
    Fetched,
    NewsConfig,
    NewsSource,
    NewsStore,
    ScoreCall,
    ScoreConfig,
    ScoreContext,
    ScoreExit,
    ScoreParts,
    ScoreReply,
    ScoreStore,
    ScoreStoreError,
    StoreError,
    archive_status_lines,
    fetch_source,
    load_archive_config,
    load_context,
    load_news_config,
    load_score_config,
    read_forward,
    read_library_sources,
    read_score_snapshot,
    read_snapshot,
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
USAGE = (
    "kullanım: python -m crytobot "
    "prepare|start|download|backtest|calibrate|status|kill-switch|resume|stop|dashboard|news|events"
    " [--live] [--trial] [--final] [archive] [score] [status] [download] [measure]"
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


def _news_config(news_path: Path, bot_path: Path, output: Output) -> NewsConfig | None:
    """Spec 0046 AC-9: ağa çıkmadan ve hiçbir dosyaya dokunmadan önce, ilk sorun adıyla. Haber
    kaydı ve kayıt dosyası bot deposu ya da bot kaydı olamaz, birbirleri de olamaz: başka yazımla
    da (plan Risk 2, 13)."""
    document = _load_toml(news_path)
    if isinstance(document, str):
        output.say(f"news: reddedildi: {document}")
        return None
    result = load_news_config(document)
    config = result.config
    if config is None:
        output.say(f"news: reddedildi: {result.message}")
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
) -> int:
    """Spec 0046: `news` toplar, `news status` gösterir. Ayar → kilit → depo sırası (AC-8, AC-9)."""
    output = Output(console)
    config = _news_config(news_path, bot_path, output)
    if config is None:
        return EXIT_REFUSED
    if list(argv[1:]) == ["status"]:
        return _news_status(config, output)
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
        try:
            service = _news_reporter(bot_path, reporter)
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
            )
            exit_ = run_collection(config, store, parts)
        finally:
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
            reply.outcome.value, reply.text, reply.overflow, reply.seconds, reply.workdir_clean
        )

    return call


def _raw_paths(document: object, section: str, keys: Sequence[str]) -> tuple[str, ...]:
    """Bir bölümün yol anahtarları, doğrulamasız: bölüm ya da anahtar yoksa boş."""
    table = document.get(section) if isinstance(document, dict) else None
    if not isinstance(table, Mapping):
        return ()
    return tuple(value for key in keys if isinstance(value := table.get(key), str))


def _score_config(
    news_path: Path, bot_path: Path, events_path: Path, output: Output
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


def _score_context(config: ScoreConfig) -> ScoreContext | str:
    """Bağlam dosyaları okunur, parmak izleri ayardakiyle karşılaştırılır (R-4, AC-6)."""
    report = file_bytes(config.calibration_report_path)
    if report is None:
        return "bağlam dosyası yok: score.calibration_report_path"
    library = file_bytes(config.library_path)
    if library is None:
        return "bağlam dosyası yok: score.library_path"
    try:
        return load_context(
            report, config.calibration_report_sha256, library, config.library_sha256
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
    config = _score_config(news_path, bot_path, events_path, output)
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
) -> int:
    """Komutu çalıştırır, çıkış kodunu döndürür. Ayar, kilit, depo sırası: borsaya ve depoya
    ayarlar denetlenmeden dokunulmaz (R-2); kilit depodan önce alınır (R-6)."""
    stop = StopRequest() if stop is None else stop
    output = Output(console)
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
            argv, news_config_path, config_path, console, clock, stop, wait, news_fetch, reporter
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
