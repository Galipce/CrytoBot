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
from datetime import date, datetime
from decimal import Decimal
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
from crytobot.app._notices import NoticeKind, TurnMemory, TurnNotice
from crytobot.app._paper_proof import PaperProof
from crytobot.app._result import BuyHalt, TurnOutcome, TurnResult
from crytobot.app._schedule import Due, after_turn, boundary_at_or_before, due, seconds_until
from crytobot.app._session import AppError, KillRequest
from crytobot.app._start import read_pairs
from crytobot.app._turn import run_turn
from crytobot.execution import PAPER, Exchange, OrderStatus, PaperExchange
from crytobot.market_data import MarketRead, ReadSettings
from crytobot.persistence import StoreOutcome, load_store, mark_turn
from crytobot.risk import daily_loss_reached

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
    kill_request: KillRequest | None = None  # spec 0035 R-4: çalışan bota kill switch isteği


class ExitReason(Enum):
    STOPPED = "stopped"
    READ_REFUSED = "read_refused"
    LOG_FAILED = "log_failed"
    FORCED = "forced"
    BANNED = "banned"


_REASON_TEXT = {
    ExitReason.STOPPED: "durdurma isteği",
    ExitReason.READ_REFUSED: "okuma reddi",
    ExitReason.LOG_FAILED: "kayıt dosyası yazılamıyor",
    ExitReason.FORCED: "zorla durdurma",
    ExitReason.BANNED: "borsa banı (HTTP 418)",
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
        exchange: Exchange,
        *,
        trial: bool = True,
        approved_by: str | None = None,
        report_path: str | None = None,
        reporter: object | None = None,
        paper_proof: PaperProof | None = None,
    ) -> None:
        self.config = config
        self.paper_proof = paper_proof
        self.parts = parts
        self.exchange = exchange
        self.trial = trial
        self.approved_by = approved_by
        self.report_path = report_path
        self.reporter = reporter
        self.memory = TurnMemory()  # process memory: a new process announces again (R-13)
        self.last: TurnResult | None = None
        self.turns = 0
        self.log_failed = False
        self.ban_until: datetime | None = None  # process only, never stored (R-11)
        self.missed = 0
        self.failing: set[str] = set()
        self.current_day: date | None = None
        self.day_start_equity: Decimal | None = None
        self.last_reported_date: date | None = None
        self.day_closures: list[object] = []
        self._drawdown_halted: bool = False
        self._daily_loss_halted: bool = False
        self._telegram_open: bool = False  # spec 0039: begin_turn çağrıldı, end_turn bekliyor

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

    # --- Telegram (spec 0029, 0039) ------------------------------------------------------------
    def _telegram_active(self) -> bool:
        return self.reporter is not None and bool(getattr(self.reporter, "is_active", False))

    def _telegram_result(self, at: object, label: str, err: object) -> None:
        """Gönderimin hata satırı; Telegram kapandıysa gerekçesiyle tek satır (CB-2)."""
        if err:
            self.emit(at, "hata", f"{label} iletilemedi ({err})")
        take_dropped = getattr(self.reporter, "take_dropped", None)
        take = getattr(self.reporter, "take_disabled_reason", None)
        try:
            dropped = take_dropped() if callable(take_dropped) else ()
            reason = take() if callable(take) else None
        except Exception as error:  # PB-5: Telegram turu düşürmez
            self.emit(at, "hata", error_text("telegram", error))
            return
        for dropped_err in dropped if isinstance(dropped, list) else ():
            # CB-3: kuyruktan atılan önceki mesaj da loga yazılır (review round 1 F-1)
            self.emit(at, "hata", f"telegram bildirimi iletilemedi ({dropped_err})")
        if reason:
            self.emit(at, "hata", f"telegram devre dışı ({reason})")

    def _telegram_begin(self, at: object) -> None:
        """Turun Telegram bütçesini açar ve kuyruğu iletir; reporter yoksa çağrı yok (PB-4)."""
        if not self._telegram_active():
            return
        begin = getattr(self.reporter, "begin_turn", None)
        if not callable(begin):
            return
        self._telegram_open = True
        try:
            dropped = begin()
        except Exception as error:  # PB-5
            self.emit(at, "hata", error_text("telegram", error))
            return
        for err in dropped if isinstance(dropped, list) else ():
            self.emit(at, "hata", f"telegram bildirimi iletilemedi ({err})")
        self._telegram_result(at, "telegram bildirimi", None)

    def _telegram_end(self, at: object) -> None:
        """Yalnız açılan tur kapanır (PB-4); tur içinde kapanan Telegram da kapanır."""
        if not self._telegram_open:
            return
        self._telegram_open = False
        end = getattr(self.reporter, "end_turn", None)
        if not callable(end):
            return
        try:
            end()
        except Exception as error:  # PB-5
            self.emit(at, "hata", error_text("telegram", error))

    def notice(self, notice: TurnNotice) -> None:
        self.emit(notice.at, "durum", notice_text(notice))
        if self._telegram_active():
            send = getattr(self.reporter, "send_turn_notice", None)
            if callable(send):
                err = send(
                    notice.kind.value,
                    notice.subject,
                    notice.entering,
                    notice.message,
                )
                self._telegram_result(notice.at, "telegram bildirimi", err)

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
            pairs = read_pairs(config.turn.whitelist, config.store_path, mode=config.mode)
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
        # Spec 0039 CB-4: turun bütün Telegram gönderimleri tek bütçeyi paylaşır
        self._telegram_begin(at)
        try:
            return self._run(target, market, at, banned)
        finally:
            self._telegram_end(at)

    def _run(
        self, target: Due, market: Mapping[str, object], at: datetime, banned: bool
    ) -> ExitReason | None:
        try:
            result = run_turn(
                market=market,
                settings=self.config.turn,
                store_path=self.config.store_path,
                now=at,
                exchange=self.exchange,
                sink=self.notice,
                memory=self.memory,
                kill_request=self.parts.kill_request,
            )
        except Exception as turn_err:
            if type(turn_err).__name__ == "BannedError":
                self.emit(
                    at, "durdurma", f"borsa banı (HTTP 418); fail-closed durduruldu: {turn_err}"
                )
                return ExitReason.BANNED
            raise
        self.last = result
        self.turns += 1
        self.mark(result, at)

        if self.memory.retry_after is not None:
            pause_time = self.memory.retry_after
            self.memory.retry_after = None
            self.emit(at, "bekleme", f"borsa rate limit (HTTP 429), {pause_time}s bekleniyor")
            self.pause(pause_time, at)

        # R-4: Kasa ve risk durdurma bildirimleri
        if self.reporter is not None and getattr(self.reporter, "is_active", False):
            send_notice = getattr(self.reporter, "send_turn_notice", None)
            send_fill = getattr(self.reporter, "send_fill_notice", None)
            send_close = getattr(self.reporter, "send_close_notice", None)

            if callable(send_notice):
                is_drawdown = BuyHalt.DRAWDOWN in result.halts
                if is_drawdown and not self._drawdown_halted:
                    self._drawdown_halted = True
                    err = send_notice(
                        kind=NoticeKind.DRAWDOWN_HALT.value,
                        subject="",
                        entering=True,
                        message="drawdown limiti aşıldı",
                    )
                    self._telegram_result(at, "telegram risk durdurma bildirimi", err)
                elif not is_drawdown and self._drawdown_halted:
                    self._drawdown_halted = False
                    err = send_notice(
                        kind=NoticeKind.DRAWDOWN_HALT.value,
                        subject="",
                        entering=False,
                        message="drawdown durdurması kalktı",
                    )
                    self._telegram_result(at, "telegram risk durdurma bildirimi", err)

                loaded_risk = load_store(self.config.store_path, self.config.mode)
                is_daily_loss = False
                if loaded_risk.state is not None:
                    is_daily_loss = daily_loss_reached(
                        loaded_risk.state.risk, self.config.turn.limits
                    )
                if is_daily_loss and not self._daily_loss_halted:
                    self._daily_loss_halted = True
                    err = send_notice(
                        kind=NoticeKind.DAILY_LOSS_LIMIT.value,
                        subject="",
                        entering=True,
                        message="günlük zarar limiti aşıldı",
                    )
                    self._telegram_result(at, "telegram risk durdurma bildirimi", err)
                elif not is_daily_loss and self._daily_loss_halted:
                    self._daily_loss_halted = False
                    err = send_notice(
                        kind=NoticeKind.DAILY_LOSS_LIMIT.value,
                        subject="",
                        entering=False,
                        message="günlük zarar limiti sıfırlandı",
                    )
                    self._telegram_result(at, "telegram risk durdurma bildirimi", err)

            # R-5: işlem olay bildirimleri (dolum ve kapanış)
            if callable(send_fill):
                for buy in result.buys:
                    if buy.status is OrderStatus.FILLED:
                        price = buy.fill_price if buy.fill_price is not None else buy.entry
                        err = send_fill(
                            pair=buy.pair,
                            side=buy.side,
                            amount=buy.position_amount,  # spec 0037: the part that filled, net
                            price=price,
                            stop=buy.stop,
                        )
                        self._telegram_result(at, "telegram dolum bildirimi", err)
            if callable(send_close):
                for closure in result.closures:
                    err = send_close(closure)
                    self._telegram_result(at, "telegram kapanış bildirimi", err)

        # R-6: UTC gün dönümü (00:00 UTC) günlük özet raporu
        if result.outcome is TurnOutcome.COMPLETED:
            turn_day = at.date() if isinstance(at, datetime) else None
            if turn_day is not None:
                if self.current_day is None:
                    self.current_day = turn_day
                    self.day_start_equity = result.equity
                elif turn_day > self.current_day:
                    day_to_report = self.current_day
                    self._send_daily_summary(day_to_report, at, result)
                    self.current_day = turn_day
                    self.day_start_equity = result.equity
                    self.day_closures = []

                for closure in result.closures:
                    self.day_closures.append(closure)

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

    def _send_daily_summary(
        self,
        day_to_report: date,
        at: object,
        result: TurnResult,
    ) -> None:
        if self.last_reported_date == day_to_report:
            return
        if self.reporter is None or not getattr(self.reporter, "is_active", False):
            return

        loaded = load_store(self.config.store_path, self.config.mode)
        start_eq = self.day_start_equity or self.config.opening_balance
        end_eq = result.equity if result.equity is not None else start_eq
        open_positions = 0
        closures_to_report: list[object] = list(self.day_closures)

        if loaded.state is not None:
            ledger = loaded.state.ledger
            open_positions = len(ledger.positions)
            day_closures = [
                c for c in ledger.closures.values() if c.closed_at.date() == day_to_report
            ]
            if day_closures:
                closures_to_report = list(day_closures)

        send_summary = getattr(self.reporter, "send_daily_summary", None)
        if callable(send_summary):
            err = send_summary(
                day=day_to_report,
                start_equity=start_eq,
                end_equity=end_eq,
                open_positions_count=open_positions,
                closures=closures_to_report,
            )
            self.last_reported_date = day_to_report
            self._telegram_result(at, "telegram günlük raporu", err)

    def mark(self, result: TurnResult, at: datetime) -> None:
        """Spec 0038 plan Risk 1, A-3: paper deposunun son turu; yalnız tamamlanan tur (bayat veri
        ve yasak turları dahil). Yazılamazsa kanıt yalnız kısalır, satırla bildirilir."""
        if self.config.mode != PAPER or result.outcome is not TurnOutcome.COMPLETED:
            return
        marked = mark_turn(self.config.store_path, at)
        if marked.outcome is not StoreOutcome.SAVED:
            self.emit(at, "hata", f"tur işareti yazılamadı: {marked.message}")

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
                paper_proof=self.paper_proof,
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
    exchange: Exchange | None = None,
    trial: bool = True,
    approved_by: str | None = None,
    report_path: str | None = None,
    reporter: object | None = None,
    paper_proof: PaperProof | None = None,
) -> LoopExit:
    """R-8…R-15: hazırlanmış depoyla paper turlarını aralık sınırlarında atar; nedeniyle çıkar.

    İkinci durdurma isteğinde de çıkış kaydı yazılır ve `FORCED` döner. `exchange` yalnız paper
    simülatörüdür; verilmezse yenisi kurulur. `paper_proof` geçen canlı başlatmanın paper kanıtıdır
    (spec 0038 CB-5), başlatma satırına yazılır.
    """
    loop = _Loop(
        config,
        parts,
        PaperExchange() if exchange is None else exchange,
        trial=trial,
        approved_by=approved_by,
        report_path=report_path,
        reporter=reporter,
        paper_proof=paper_proof,
    )
    try:
        return loop.run()
    except ForcedStop:
        return loop.finish(ExitReason.FORCED)
