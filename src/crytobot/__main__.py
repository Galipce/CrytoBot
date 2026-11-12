"""Giriş noktası: `python -m crytobot prepare|start|download|backtest` (spec 0022, 0023, 0025).

Karar içermez: kararların hepsi `app`'tedir. Burada yalnız gerçek etkiler bağlanır: ayar dosyası
(`tomllib`, çalışma dizinindeki `crytobot.toml`), gerçek UTC saati, ≤1 s'lik parçalarla bekleme,
sinyaller, tek süreç kilidi, konsol ve kayıt dosyası yazıcısı, piyasa okuması. Yalnız paper vardır;
mod seçeneği, API anahtarı ve ortam değişkeni okunmaz.

Ağ (spec 0041): `[exchange] testnet` yalnız `app.load_network` ile, `start` ve `prepare` için bir
kez okunur; testnet canlı koşusunda okuma, emir/hesap istemcisi ve Telegram öneki aynı ağdandır.

`download` (spec 0023) geçmiş veriyi aynı ayar dosyasının `[history]` bölümüne göre indirir. Kilit
alınmaz, depo ve kayıt dosyası açılmaz: çıktı yalnız konsoladır, çalışan bir paper botu etkilenmez.

`backtest` (spec 0025) veri dosyasıyla, aynı ayar dosyasının `[backtest]` bölümüne göre koşar. Ağa
çıkılmaz, saat verilmez, kilit alınmaz; bot deposu ve kayıt dosyası açılmaz. Turların durumu
`tempfile` ile açılan geçici bir dizindeki depodadır ve dizin her çıkışta silinir (zorla durdurma
dahil; süreç öldürülürse işletim sisteminin geçici dizininde kalır, bir daha okunmaz). Konsol
satırları zaman damgası taşımaz.

Çıkış kodları: 0 temiz durma, hazırlık, indirme ya da backtest tamam, 1 başlatma, hazırlık, indirme
ya da backtest reddi (ayarlar, veri dosyası, rapor dosyası var), 2 okuma reddiyle durma, 3 kayıt
dosyası yazılamıyor, 4 indirme durdu, 5 backtest durdu, 6 backtest tamam ama rapor dosyası
yazılamadı (rapor konsolda), 130 zorla durma.
"""

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
    DownloadConfig,
    DownloadParts,
    ExitReason,
    ForcedStop,
    KillRequest,
    LogWriteError,
    LoopParts,
    PaperProof,
    PrepareOutcome,
    StartOutcome,
    StopRequest,
    bind_live_network,
    check_paper_proof,
    check_stage_gate,
    create_live_exchange,
    engage_kill_switch,
    get_dashboard_status,
    line,
    load_backtest_config,
    load_config,
    load_download_config,
    load_network,
    load_stage_config,
    network_note_text,
    open_for_start,
    prepare_live_store,
    prepare_store,
    query_status,
    record_start,
    request_stop,
    resume_operations,
    run_backtest,
    run_download,
    run_loop,
)
from crytobot.backtest import read_report, report_exists, write_report
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
from crytobot.market_data import (
    HistoryRequest,
    HistoryResult,
    MarketRead,
    ReadSettings,
    download_history,
    read_history,
    read_market_data,
)
from crytobot.reporting import ReportingService, load_reporting_config

CONFIG_FILE = "crytobot.toml"
USAGE = (
    "kullanım: python -m crytobot "
    "prepare|start|download|backtest|status|kill-switch|resume|stop|dashboard [--live] [--trial]"
)
COMMANDS = (
    ["prepare"],
    ["prepare", "--live"],
    ["start"],
    ["start", "--live"],
    ["start", "--trial"],
    ["download"],
    ["backtest"],
    ["status"],
    ["kill-switch"],
    ["kill-switch", "on"],
    ["resume"],
    ["stop"],
    ["dashboard"],
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
_LOG_FAILED = "kayıt dosyası yazılamıyor: bot durdu"
TESTNET_LABEL = "[TESTNET]"  # spec 0041 CB-5: every Telegram message of a testnet run
_PIECE_S = 1.0

Clock = Callable[[], datetime]
Read = Callable[[tuple[str, ...], ReadSettings], MarketRead]
Download = Callable[[HistoryRequest, Clock, Callable[[], bool]], HistoryResult]


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


def make_read(clock: Clock, testnet: bool = False) -> Read:
    """Okuma yalnız herkese açık uçlara, anahtarsız gider (spec 0017). Spec 0041 CB-1: testnet
    koşusunda bütün okumalar testnet'ten; mainnet'e geri dönülmez."""

    def read(pairs: tuple[str, ...], settings: ReadSettings) -> MarketRead:
        return read_market_data(pairs, settings, clock, testnet=testnet)

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


def _backtest(config_path: Path, output: Output, stop: StopRequest, clock: Clock) -> int:
    """Ağ yok, kilit yok; bot deposu ve kayıt dosyası açılmaz (spec 0025 R-1). Saat yalnız raporun
    üretim anı içindir (spec 0040 CB-2). Geçici dizin her çıkışta silinir; `.part`'ı rapor
    yazıcısı siler (R-13)."""
    config = _backtest_config(config_path, output)
    if config is None:
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
            exit_ = run_backtest(config, parts)
        except ForcedStop:  # the second request: the line is written, the report is not
            return EXIT_FORCED
    return _BACKTEST_EXIT_CODES[exit_.outcome]


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
    testnet: bool = False,
) -> int:
    check = open_for_start(config.store_path, mode=config.mode)
    if check.outcome is StartOutcome.READY and config.mode == "live":
        # spec 0041 CB-4, plan Risk 4: under the lock, before any turn; G-1 records mainnet
        check = bind_live_network(config.store_path, testnet)
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
    if testnet:  # spec 0041 CB-2, G-5: console and log file, never Telegram
        output(line(parts.clock(), "başlatma", network_note_text()))
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
        return _backtest(config_path, output, stop, clock)
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

    testnet = False
    if argv[0] in ("start", "prepare"):
        # spec 0041 CB-3, plan Risk 7: the network's one reader, before every other gate
        network_document = _load_toml(config_path)
        if isinstance(network_document, str):
            output.say(line(clock(), "ayar", f"bot başlamadı: {network_document}"))
            return EXIT_REFUSED
        network = load_network(network_document, config.mode)
        if network.network is None:
            output.say(line(clock(), "ayar", f"bot başlamadı: {network.message}"))
            return EXIT_REFUSED
        testnet = network.network == "testnet"

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
            # spec 0041 CB-4: the store's network before credentials, the step that goes out
            live_exch, err = create_live_exchange(
                testnet=testnet,
                client=live_client,
                store_path=config.store_path,
            )
            if live_exch is None:
                output.say(line(clock(), "başlatma", f"başlatma reddedildi: {err}"))
                return EXIT_REFUSED
            live_exchange = live_exch
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
            make_read(clock, testnet=testnet) if read is None else read,
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
                reporter = ReportingService(reporting_cfg, label=TESTNET_LABEL if testnet else None)
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
            testnet=testnet,
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
