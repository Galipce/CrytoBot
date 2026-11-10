"""Bir turun çalışma durumu: yükleme sonrası kayıt, gözlem, durdurmalar (spec 0016 R-1, R-5…R-7).

Süreç belleği dışında hiçbir şey turdan taşmaz; kaydedilmeyen durum bir sonraki turda diskten gelir.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from crytobot.app._control import format_audit_row
from crytobot.app._inputs import DataIssue, DataReport, TurnSettings
from crytobot.app._notices import NoticeKind, Notices, TurnMemory
from crytobot.app._result import BuyHalt, PairOutcome, TurnOutcome, TurnResult
from crytobot.execution import (
    BannedError,
    CloseOrder,
    Exchange,
    ExecutionState,
    Order,
    OrderStatus,
    stop_client_id,
)
from crytobot.persistence import StoredState, StoreOutcome, append_audit_record, save_store
from crytobot.portfolio import Closure, Fill, Ledger, SnapshotOutcome, account_state
from crytobot.risk import RiskState, engage_kill_switch, observe


class AppError(Exception):
    """`app` modülünün iç hatalarının tabanı; `run_turn`'den dışarı çıkmaz."""


class SaveRefusedError(AppError):
    """Kayıt reddedildi: tur biter, sonraki tur diskteki durumdan başlar (R-6)."""


@dataclass(frozen=True)
class KillRequest:
    """Çalışan bota kill switch isteği (spec 0035 R-4, AC-11; plan Risk 1).

    `pending()` bekleyen istek var mı; `consume()` istek depoya işlendikten sonra çağrılır. Tur
    isteği kendi kaydıyla işler; CLI çalışan botun deposuna hiç yazmaz (eski yazım oluşmaz).
    """

    pending: Callable[[], bool]
    consume: Callable[[], None]


# what stays visible without stopping the buys: risk refuses them itself (R-8)
_INFORMATIONAL = frozenset({BuyHalt.DRAWDOWN, BuyHalt.KILL_SWITCH})


def buy_fill(order: Order, at: datetime) -> Fill:
    """Dolan alım emrinin defter kaydı: alım yolu ve bilinmeyen emir sorgusu aynı kaydı yazar."""
    return Fill(
        order.client_order_id,
        order.pair,
        order.side,
        order.amount,
        order.fill_price,
        order.fee,
        order.stop,
        order.target,
        at,
    )


@dataclass
class TurnRun:
    """Tek turun bellekteki durumu. `state`, son başarılı kaydın ya da yüklemenin sonucudur."""

    store_path: object
    settings: TurnSettings
    market: Mapping[str, object]
    now: datetime
    exchange: Exchange
    notices: Notices
    memory: TurnMemory
    state: StoredState
    report: DataReport = field(default_factory=lambda: DataReport({}, {}))
    halts: dict[BuyHalt, None] = field(default_factory=dict)
    closes: list[CloseOrder] = field(default_factory=list)
    buys: list[Order] = field(default_factory=list)
    pairs: list[PairOutcome] = field(default_factory=list)
    closures: list[Closure] = field(default_factory=list)
    last_equity: Decimal | None = None
    kill_request: KillRequest | None = None

    def apply_kill_request(self) -> None:
        """Spec 0035 R-4, AC-11: bekleyen kill switch isteği turun kendi kaydıyla depoya işlenir.

        Kayıt reddedilirse `SaveRefusedError` turu bitirir ve istek silinmez (sonraki tur yeniden
        dener). Kill switch zaten devredeyse yalnız istek silinir.
        """
        request = self.kill_request
        if request is None or not request.pending():
            return
        if not self.state.risk.kill_switch:
            self.save(risk=engage_kill_switch(self.state.risk).state)
            row = format_audit_row(
                self.now,
                "kill-switch on",
                "engaged",
                "çalışan bot isteği işledi",
                mode=self.state.mode,
            )
            append_audit_record(self.store_path, row)
        request.consume()
        self.note_drawdown()

    @property
    def buying_stopped(self) -> bool:
        return any(halt not in _INFORMATIONAL for halt in self.halts)

    def halt(self, halt: BuyHalt) -> None:
        self.halts[halt] = None

    def flag_reconciliation(self, message: str) -> None:
        """R-7: işaret depodan türer; temiz turla ya da yeniden başlatmayla kalkmaz."""
        self.halt(BuyHalt.RECONCILIATION)
        self.notices.enter(NoticeKind.RECONCILIATION, "", message)

    def stop_failed(self, subject: str, message: str) -> None:
        """Spec 0034 R-5, F-2, F-3: pozisyonun borsa stopu yok ya da belirsiz; alım durur. Bildirim
        pozisyona özgüdür ve her canlı turda stoplardan yeniden türer (yokluk çıkışı getirir)."""
        self.halt(BuyHalt.STOP_ORDER_FAILED)
        self.notices.enter(NoticeKind.STOP_ORDER_FAILED, subject, f"güvenli mod: {message}")

    def raise_if_banned(self, error: Exception) -> None:
        """Spec 0034 F-4: ban (418) yutulmaz; döngü `BANNED` ile durur (`_loop`)."""
        if isinstance(error, BannedError):
            raise error

    def place_exchange_stop(
        self, position_id: str, pair: str, amount: Decimal, stop: Decimal
    ) -> None:
        """Spec 0034 R-4, R-5: pozisyon için borsaya şartlı stop. Çağıran dolumu önceden kaydetti
        (F-4): borsa çağrısı ne olursa olsun alım defterde kalır."""
        stop_id = stop_client_id(position_id)
        try:
            status = self.exchange.place_stop_order(
                client_order_id=stop_id,
                symbol=pair,
                amount=amount,
                stop_price=stop,
                limit_price=stop * (1 - self.settings.slippage),
            )
        except Exception as error:
            self.raise_if_banned(error)
            self.stop_failed(
                position_id, f"borsa stop emri başarısız ({stop_id}, {type(error).__name__})"
            )
            return
        if status not in (OrderStatus.NEW, OrderStatus.FILLED):
            self.stop_failed(position_id, f"borsa stop emri başarısız ({stop_id}, {status.value})")

    def reconcile_balance(self) -> None:
        """Spec 0033 R-6: Canlı modda tur başı bakiye mutabakatı (tolerans <= 0.05 USDT)."""
        if self.state.mode != "live":
            return
        fetch_bal = getattr(self.exchange, "fetch_free_balance", None)
        if not callable(fetch_bal):
            return
        try:
            ex_balance = fetch_bal(asset="USDT")
        except Exception as err:
            retry_after = getattr(err, "retry_after", None)
            if retry_after is not None and retry_after > 0:
                self.memory.retry_after = retry_after
            if type(err).__name__ == "BannedError":
                raise
            self.halt(BuyHalt.BALANCE_CHECK_FAILED)
            self.notices.enter(
                NoticeKind.SAFE_MODE,
                "",
                f"güvenli mod: borsa bakiye sorgusu başarısız ({type(err).__name__})",
            )
            return

        if ex_balance is None:
            self.halt(BuyHalt.BALANCE_CHECK_FAILED)
            self.notices.enter(
                NoticeKind.SAFE_MODE, "", "güvenli mod: borsa serbest bakiyesi alınamadı"
            )
            return

        ledger_balance = self.state.ledger.balance
        if ledger_balance is None:
            return
        diff = abs(ledger_balance - ex_balance)
        if diff > Decimal("0.05"):
            self.halt(BuyHalt.RECONCILIATION_HALT)
            self.notices.enter(
                NoticeKind.RECONCILIATION,
                "",
                f"bakiye mutabakat farkı toleransı aştı: "
                f"defter={ledger_balance}, borsa={ex_balance}, fark={diff}",
            )

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
        else:
            self.halts.pop(BuyHalt.DRAWDOWN, None)
        if self.state.risk.kill_switch:
            self.halt(BuyHalt.KILL_SWITCH)
        else:
            self.halts.pop(BuyHalt.KILL_SWITCH, None)

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
        self.notices.evaluated(NoticeKind.SAVE_REFUSED)  # only a write that went through ends it
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
            if not self.report.issues:  # a price only the ledger refuses, e.g. too many digits
                self.halt(BuyHalt.INVALID_DATA)
                self.notices.enter(NoticeKind.INVALID_DATA, "", snapshot.message)
            return
        if snapshot.snapshot is None:
            self._refuse_observation(snapshot.message)
            return
        self.last_equity = snapshot.snapshot.equity
        self.notices.clear(NoticeKind.INVALID_DATA)  # the ledger priced every position
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
            tuple(self.closures),
            self.last_equity,
        )
