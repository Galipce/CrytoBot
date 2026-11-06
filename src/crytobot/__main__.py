"""Giriş noktası: `python -m crytobot prepare|start` (spec 0022; plan Risk 1, 5, 6, 13).

Karar içermez: kararların hepsi `app`'tedir. Burada yalnız gerçek etkiler bağlanır: ayar dosyası
(`tomllib`, çalışma dizinindeki `crytobot.toml`), gerçek UTC saati, ≤1 s'lik parçalarla bekleme,
sinyaller, tek süreç kilidi, konsol ve kayıt dosyası yazıcısı, piyasa okuması. Yalnız paper vardır;
mod seçeneği, API anahtarı ve ortam değişkeni okunmaz.

Çıkış kodları: 0 temiz durma ya da hazırlık tamam, 1 başlatma ya da hazırlık reddi, 2 okuma reddiyle
durma, 3 kayıt dosyası yazılamıyor, 130 zorla durma.
"""

import signal
import sys
import time
import tomllib
from collections.abc import Callable, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import IO, TextIO

from crytobot.app import (
    PREPARE_HINT,
    BotConfig,
    ExitReason,
    ForcedStop,
    LogWriteError,
    LoopParts,
    PrepareOutcome,
    StartOutcome,
    StopRequest,
    line,
    load_config,
    open_for_start,
    prepare_store,
    run_loop,
)
from crytobot.market_data import MarketRead, ReadSettings, read_market_data

CONFIG_FILE = "crytobot.toml"
USAGE = "kullanım: python -m crytobot prepare|start"
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_READ_REFUSED = 2
EXIT_LOG_FAILED = 3
EXIT_FORCED = 130
_EXIT_CODES = {
    ExitReason.STOPPED: EXIT_OK,
    ExitReason.READ_REFUSED: EXIT_READ_REFUSED,
    ExitReason.LOG_FAILED: EXIT_LOG_FAILED,
    ExitReason.FORCED: EXIT_FORCED,
}
_LOG_FAILED = "kayıt dosyası yazılamıyor: bot durdu"
_PIECE_S = 1.0

Clock = Callable[[], datetime]
Read = Callable[[tuple[str, ...], ReadSettings], MarketRead]


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
            return "depo başka bir bot sürecinde kullanılıyor"
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
) -> Callable[[float], None]:
    """≤1 s'lik parçalarla bekler; durdurma isteğinde en geç bir parça sonra döner (plan Risk 6)."""

    def wait(seconds: float) -> None:
        end = monotonic() + seconds
        while not stop.requested:
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


def _config(path: Path, output: Output, clock: Clock) -> BotConfig | None:
    """R-2: dosya yoksa, okunamıyorsa ya da bir ayar geçersizse `None`; hiçbir şeye dokunmaz."""
    try:
        with open(path, "rb") as file:
            document = tomllib.load(file)
    except FileNotFoundError:
        output.say(line(clock(), "ayar", f"ayar dosyası yok: {path.name}"))
        return None
    except (OSError, ValueError, RecursionError):  # TOML, encoding and 4300-digit errors
        output.say(line(clock(), "ayar", f"ayar dosyası okunamıyor: {path.name}"))
        return None
    result = load_config(document, clock())
    if result.config is None:
        output.say(line(clock(), "ayar", f"bot başlamadı: {result.message}"))
    return result.config


def _prepare(config: BotConfig, output: Output, clock: Clock) -> int:
    result = prepare_store(config.store_path, config.opening_balance, clock())
    output(line(clock(), "hazırlık", result.message))
    return EXIT_OK if result.outcome is PrepareOutcome.PREPARED else EXIT_REFUSED


def _start(config: BotConfig, output: Output, parts: LoopParts) -> int:
    check = open_for_start(config.store_path)
    if check.outcome is not StartOutcome.READY:
        hint = f"; {PREPARE_HINT}" if check.hint is not None else ""
        output(line(parts.clock(), "başlatma", f"{check.message}{hint}"))
        return EXIT_REFUSED
    exit_ = run_loop(config, parts)
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
) -> int:
    """Komutu çalıştırır, çıkış kodunu döndürür. Ayar, kilit, depo sırası: borsaya ve depoya
    ayarlar denetlenmeden dokunulmaz (R-2); kilit depodan önce alınır (R-6)."""
    stop = StopRequest() if stop is None else stop
    output = Output(console)
    if list(argv) not in (["prepare"], ["start"]):
        output.say(USAGE)
        return EXIT_REFUSED
    config = _config(config_path, output, clock)
    if config is None:
        return EXIT_REFUSED
    output = Output(console, config.log_path)
    lock = StoreLock(config.store_path)
    try:
        refused = lock.acquire()
        if refused is not None:
            output(line(clock(), argv[0], f"reddedildi: {refused}"))
            return EXIT_REFUSED
        if argv[0] == "prepare":
            return _prepare(config, output, clock)
        parts = LoopParts(
            clock,
            make_wait(stop) if wait is None else wait,
            make_read(clock) if read is None else read,
            output,
            stop,
        )
        return _start(config, output, parts)
    except LogWriteError:
        output.say(line(clock(), "durdurma", _LOG_FAILED))
        return EXIT_LOG_FAILED
    finally:
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
