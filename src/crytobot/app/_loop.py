"""Paper döngüsü (spec 0022 R-8…R-15; plan Risk 1, 6, 7, 9).

Kararların ve düzenin tamamı buradadır; gerçek etkiler (`clock`, `wait`, `read`, `write`, durdurma
isteği) `LoopParts` ile gelir. `app` saat çağırmaz, okuma işlevini import etmez: borsaya yalnız
kendisine verilen `read` ile çıkar. Her turun `now`'ı okumanın saatidir (`read.read_at`, 0017 trap);
yasak süresince okuma yapılmaz, tur piyasa verisi olmadan saatle atılır (plan Risk 9).

Durdurma: ilk istek yalnız işaret koyar; beklemedeyken döngü hemen çıkar, tur sürerken tur biter.
İkinci istek `ForcedStop` fırlatır: `BaseException`'dır, `run_turn`'ün hata ağı onu yutmaz; depo
yazımı atomiktir (spec 0011). Beklenmeyen hata döngüyü düşürmez: tip adıyla yazılır (R-15).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from crytobot.app._config import BotConfig
from crytobot.app._events import (
    ban_ended_text,
    ban_started_text,
    error_text,
    line,
    notice_text,
    read_refused_text,
    start_text,
    stop_text,
    turn_text,
)
from crytobot.app._market import to_turn_market
from crytobot.app._notices import TurnMemory, TurnNotice
from crytobot.app._result import TurnResult
from crytobot.app._schedule import Due, after_turn, boundary_at_or_before, due, seconds_until
from crytobot.app._session import AppError
from crytobot.app._start import read_pairs
from crytobot.app._turn import run_turn
from crytobot.execution import PaperExchange
from crytobot.market_data import MarketRead, ReadSettings

# The clock is read again at least this often while waiting: a sleep or a clock jump is seen
MAX_WAIT_S = 60.0
# Steps retried within a second: a repeat of the same failure is logged once (R-15)
_RETRIED_EVERY_SECOND = frozenset({"saat", "bekleme"})


class ForcedStop(BaseException):
    """İkinci durdurma isteği: döngü anında çıkar (R-12)."""


class LogWriteError(AppError):
    """Kayıt dosyası yazılamadı; satır konsola yazılmıştır. Bot durur (R-15)."""


class StopRequest:
    """Durdurma isteği: sinyal işleyicisi `request` çağırır. İkinci istek `ForcedStop`'tur."""

    def __init__(self) -> None:
        self.requested = False
        self.source = ""

    def request(self, source: str = "") -> None:
        if self.requested:
            raise ForcedStop(source)
        self.requested = True
        self.source = source


@dataclass(frozen=True)
class LoopParts:
    """Döngünün gerçek etkileri. `wait(saniye)` erken dönebilir (durdurma isteğinde)."""

    clock: Callable[[], datetime]
    wait: Callable[[float], None]
    read: Callable[[tuple[str, ...], ReadSettings], MarketRead]
    write: Callable[[str], None]
    stop: StopRequest


class ExitReason(Enum):
    STOPPED = "stopped"
    READ_REFUSED = "read_refused"
    LOG_FAILED = "log_failed"
    FORCED = "forced"


_REASON_TEXT = {
    ExitReason.STOPPED: "durdurma isteği",
    ExitReason.READ_REFUSED: "okuma reddi",
    ExitReason.LOG_FAILED: "kayıt dosyası yazılamıyor",
    ExitReason.FORCED: "zorla durdurma",
}


@dataclass(frozen=True)
class LoopExit:
    reason: ExitReason
    last: TurnResult | None
    turns: int


class _Loop:
    def __init__(
        self,
        config: BotConfig,
        parts: LoopParts,
        exchange: PaperExchange,
        *,
        trial: bool = True,
        approved_by: str | None = None,
        report_path: str | None = None,
    ) -> None:
        self.config = config
        self.parts = parts
        self.exchange = exchange
        self.trial = trial
        self.approved_by = approved_by
        self.report_path = report_path
        self.memory = TurnMemory()  # process memory: a new process announces again (R-13)
        self.last: TurnResult | None = None
        self.turns = 0
        self.log_failed = False
        self.ban_until: datetime | None = None  # process only, never stored (R-11)
        self.missed = 0
        self.failing: set[str] = set()

    # --- output -----------------------------------------------------------------------------
    def emit(self, at: object, event: str, text: str) -> None:
        try:
            self.parts.write(line(at, event, text))
        except Exception:  # LogWriteError or a broken writer: nothing more can be logged
            self.log_failed = True

    def failed(self, step: str, error: Exception, at: object = None) -> None:
        """R-15: tip adıyla, istisna metni olmadan.

        Saniyede bir yeniden denenen `saat` ve `bekleme` art arda hata verirse bir kez yazılır;
        `okuma` sınır başına bir kez çalışır, her hatası yazılır (review round 1 L-2).
        """
        if step in self.failing:
            return
        if step in _RETRIED_EVERY_SECOND:
            self.failing.add(step)
        self.emit(at, "hata", error_text(step, error))

    def recovered(self, step: str) -> None:
        self.failing.discard(step)

    def notice(self, notice: TurnNotice) -> None:
        self.emit(notice.at, "durum", notice_text(notice))

    # --- effects with the loop's error net ----------------------------------------------------
    def moment(self) -> datetime | None:
        try:
            moment = self.parts.clock()
        except Exception as error:
            self.failed("saat", error)
            return None
        if not (isinstance(moment, datetime) and moment.utcoffset() is not None):
            self.failed("saat", TypeError())
            return None
        self.recovered("saat")
        return moment

    def pause(self, seconds: float, at: object) -> None:
        try:
            self.parts.wait(min(seconds, MAX_WAIT_S))
        except Exception as error:
            self.failed("bekleme", error, at)
            return
        self.recovered("bekleme")

    # --- one turn -----------------------------------------------------------------------------
    def banned(self, now: datetime) -> bool:
        until = self.ban_until
        if until is None:
            return False
        if now < until:
            return True
        self.ban_until = None
        self.emit(now, "yasak", ban_ended_text(until))
        return False

    def read(self, now: datetime) -> tuple[Mapping[str, object], datetime] | ExitReason | None:
        """Okuma: tur girdisi ve zamanı; ret `READ_REFUSED`; beklenmeyen hata `None` (tur yok)."""
        config = self.config
        try:
            pairs = read_pairs(config.turn.whitelist, config.store_path)
            read = self.parts.read(pairs, config.read)
        except Exception as error:
            self.failed("okuma", error, now)
            return None
        if read.input_problem is not None or read.read_at is None:  # R-10, B-50
            self.emit(now, "okuma", read_refused_text(read.input_problem))
            return ExitReason.READ_REFUSED
        if read.ban is not None:  # R-11, B-48: no cap on a reported end
            reported = read.ban.until
            until = read.read_at + self.config.turn_interval if reported is None else reported
            self.ban_until = until
            self.emit(read.read_at, "yasak", ban_started_text(until, reported is not None))
        return to_turn_market(read), read.read_at

    def turn(self, target: Due) -> ExitReason | None:
        now = self.moment()
        if now is None:
            self.missed += target.missed  # R-8: carried to the next summary
            return None
        banned = self.banned(now)
        if banned:
            market: Mapping[str, object] = {}  # all data missing: no buy, no close (BR-11)
            at = now
        else:
            read = self.read(now)
            if read is None:
                self.missed += target.missed  # R-8: carried to the next summary
                return None
            if isinstance(read, ExitReason):
                return read
            market, at = read
        result = run_turn(
            market=market,
            settings=self.config.turn,
            store_path=self.config.store_path,
            now=at,
            exchange=self.exchange,
            sink=self.notice,
            memory=self.memory,
        )
        self.last = result
        self.turns += 1
        self.emit(
            at,
            "tur",
            turn_text(
                result,
                at,
                self.missed + target.missed,
                banned,
                trial=self.trial,
            ),
        )
        self.missed = 0
        return None

    # --- the loop -----------------------------------------------------------------------------
    def finish(self, reason: ExitReason) -> LoopExit:
        text = _REASON_TEXT[reason]
        if reason is ExitReason.STOPPED and self.parts.stop.source:
            text = f"{text} ({self.parts.stop.source})"
        self.emit(self.moment(), "durdurma", stop_text(text, self.last, self.turns))
        return LoopExit(reason, self.last, self.turns)

    def next_due(self, last: datetime | None) -> Due | None:
        now = self.moment()
        if now is None:
            self.pause(1.0, None)
            return None
        interval = self.config.turn_interval
        if last is None:  # R-8: the first turn runs at once and uses its own boundary
            return Due(boundary_at_or_before(now, interval), 0)
        found = due(last, now, interval)
        if found is None:
            self.pause(seconds_until(last, now, interval), now)
        return found

    def run(self) -> LoopExit:
        config = self.config
        self.emit(
            self.moment(),
            "başlatma",
            start_text(
                config.turn_interval,
                config.store_path,
                tuple(config.turn.whitelist),
                trial=self.trial,
                approved_by=self.approved_by,
                report_path=self.report_path,
            ),
        )
        last: datetime | None = None
        while True:
            if self.log_failed:
                return self.finish(ExitReason.LOG_FAILED)
            if self.parts.stop.requested:
                return self.finish(ExitReason.STOPPED)
            target = self.next_due(last)
            if target is None or self.parts.stop.requested:
                continue
            stopped = self.turn(target)
            if stopped is not None:
                return self.finish(stopped)
            ended = self.moment()
            if ended is None:
                last = target.boundary
                continue
            last, during = after_turn(target.boundary, ended, config.turn_interval)
            self.missed += during


def run_loop(
    config: BotConfig,
    parts: LoopParts,
    *,
    exchange: PaperExchange | None = None,
    trial: bool = True,
    approved_by: str | None = None,
    report_path: str | None = None,
) -> LoopExit:
    """R-8…R-15: hazırlanmış depoyla paper turlarını aralık sınırlarında atar; nedeniyle çıkar.

    İkinci durdurma isteğinde de çıkış kaydı yazılır ve `FORCED` döner. `exchange` yalnız paper
    simülatörüdür; verilmezse yenisi kurulur.
    """
    loop = _Loop(
        config,
        parts,
        PaperExchange() if exchange is None else exchange,
        trial=trial,
        approved_by=approved_by,
        report_path=report_path,
    )
    try:
        return loop.run()
    except ForcedStop:
        return loop.finish(ExitReason.FORCED)
