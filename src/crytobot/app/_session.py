"""Bir turun çalışma durumu: yükleme sonrası kayıt, gözlem, durdurmalar (spec 0016 R-1, R-5…R-7).

Süreç belleği dışında hiçbir şey turdan taşmaz; kaydedilmeyen durum bir sonraki turda diskten gelir.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from crytobot.app._inputs import DataIssue, DataReport, TurnSettings
from crytobot.app._notices import NoticeKind, Notices, TurnMemory
from crytobot.app._result import BuyHalt, PairOutcome, TurnOutcome, TurnResult
from crytobot.execution import CloseOrder, ExecutionState, Order, PaperExchange
from crytobot.persistence import StoredState, StoreOutcome, save_store
from crytobot.portfolio import Ledger, SnapshotOutcome, account_state
from crytobot.risk import RiskState, observe


class AppError(Exception):
    """`app` modülünün iç hatalarının tabanı; `run_turn`'den dışarı çıkmaz."""


class SaveRefusedError(AppError):
    """Kayıt reddedildi: tur biter, sonraki tur diskteki durumdan başlar (R-6)."""


# what stays visible without stopping the buys: risk refuses them itself (R-8)
_INFORMATIONAL = frozenset({BuyHalt.DRAWDOWN})


@dataclass
class TurnRun:
    """Tek turun bellekteki durumu. `state`, son başarılı kaydın ya da yüklemenin sonucudur."""

    store_path: object
    settings: TurnSettings
    market: Mapping[str, object]
    now: datetime
    exchange: PaperExchange
    notices: Notices
    memory: TurnMemory
    state: StoredState
    report: DataReport = field(default_factory=lambda: DataReport({}, {}))
    halts: dict[BuyHalt, None] = field(default_factory=dict)
    closes: list[CloseOrder] = field(default_factory=list)
    buys: list[Order] = field(default_factory=list)
    pairs: list[PairOutcome] = field(default_factory=list)

    @property
    def buying_stopped(self) -> bool:
        return any(halt not in _INFORMATIONAL for halt in self.halts)

    def halt(self, halt: BuyHalt) -> None:
        self.halts[halt] = None

    def flag_reconciliation(self, message: str) -> None:
        """R-7: işaret depodan türer; temiz turla ya da yeniden başlatmayla kalkmaz."""
        self.halt(BuyHalt.RECONCILIATION)
        self.notices.enter(NoticeKind.RECONCILIATION, "", message)

    def sync_safe_mode(self) -> None:
        """R-17: durumu bilinmeyen emir kaldıkça alım olmaz; bildirim durumdan türer (Risk 11)."""
        unknown = self.state.execution.unknown
        if unknown:
            self.halt(BuyHalt.UNKNOWN_ORDERS)
            self.notices.enter(
                NoticeKind.SAFE_MODE, "", f"güvenli mod: durumu bilinmeyen emir {len(unknown)}"
            )
        else:
            self.halts.pop(BuyHalt.UNKNOWN_ORDERS, None)
            self.notices.clear(NoticeKind.SAFE_MODE)

    def note_drawdown(self) -> None:
        if self.state.risk.halted:
            self.halt(BuyHalt.DRAWDOWN)

    def save(
        self,
        ledger: Ledger | None = None,
        execution: ExecutionState | None = None,
        risk: RiskState | None = None,
    ) -> None:
        """R-1, R-6: üç durumu tek kayıtta yazar; ret turu bitirir. R-7: işaret kayıttan da gelir"""
        current = self.state
        result = save_store(
            self.store_path,
            current,
            current.ledger if ledger is None else ledger,
            current.execution if execution is None else execution,
            current.risk if risk is None else risk,
        )
        if result.state is None:
            self.halt(BuyHalt.SAVE_REFUSED)
            self.notices.enter(NoticeKind.SAVE_REFUSED, "", f"kayıt reddedildi: {result.message}")
            if result.outcome is StoreOutcome.HISTORY_IMMUTABLE:
                self.memory.history_halted = True
                self.halt(BuyHalt.HISTORY_IMMUTABLE)
                self.notices.enter(NoticeKind.HISTORY_IMMUTABLE, "", result.message)
            raise SaveRefusedError(result.message)
        self.state = result.state
        if result.conflicts:
            self.flag_reconciliation(result.message)
        self.sync_safe_mode()

    def observe_equity(self) -> None:
        """R-16: kasayı gözler. Fiyatı eksik pozisyon varsa gözlem yok, alım zaten durmuştur."""
        ledger = self.state.ledger
        opened_at = ledger.opened_at
        if opened_at is not None and self.now < opened_at:  # plan Risk 3
            self._refuse_observation("zaman defterin açılışından eski")
            return
        snapshot = account_state(ledger, dict(self.report.prices))
        if snapshot.outcome is SnapshotOutcome.MISSING_PRICE:
            self.notices.keep(NoticeKind.OBSERVATION_REJECTED)  # not evaluated: it still lasts
            if not self.report.issues:  # a price only the ledger refuses, e.g. too many digits
                self.halt(BuyHalt.INVALID_DATA)
                self.notices.enter(NoticeKind.INVALID_DATA, "", snapshot.message)
            return
        if snapshot.snapshot is None:
            self._refuse_observation(snapshot.message)
            return
        update = observe(self.state.risk, self.now, snapshot.snapshot.equity, self.settings.limits)
        if not update.accepted:
            self._refuse_observation(update.message)
            return
        self.notices.clear(NoticeKind.OBSERVATION_REJECTED)
        if update.state != self.state.risk:  # nothing changed, nothing written (plan Risk 14)
            self.save(risk=update.state)
        self.note_drawdown()

    def _refuse_observation(self, message: str) -> None:
        self.halt(BuyHalt.OBSERVATION_REJECTED)
        self.notices.enter(NoticeKind.OBSERVATION_REJECTED, "", message)

    def apply_report(self, report: DataReport) -> None:
        """R-4: bayat ya da geçersiz herhangi bir çift o turda tüm alımları durdurur."""
        self.report = report
        for pair, issue in report.issues.items():
            if issue is DataIssue.STALE:
                self.halt(BuyHalt.STALE_DATA)
                self.notices.enter(NoticeKind.STALE_DATA, pair, f"{pair}: veri bayat")
            else:
                self.halt(BuyHalt.INVALID_DATA)
                self.notices.enter(NoticeKind.INVALID_DATA, pair, f"{pair}: veri geçersiz")

    def refuse_close(self, subject: str, message: str) -> None:
        """R-18: pozisyon açık kalır, bildirim gider; koşul sürerse sonraki turda yeniden dener."""
        self.notices.enter(NoticeKind.CLOSE_REFUSED, subject, message)

    def result(self, outcome: TurnOutcome, message: str) -> TurnResult:
        return TurnResult(
            outcome,
            tuple(self.closes),
            tuple(self.buys),
            tuple(self.pairs),
            tuple(self.halts),
            tuple(self.notices.errors),
            message,
        )
