"""Bir turun çalışma durumu: yükleme sonrası kayıt, gözlem, durdurmalar (spec 0016 R-1, R-5…R-7).

Süreç belleği dışında hiçbir şey turdan taşmaz; kaydedilmeyen durum bir sonraki turda diskten gelir.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from crytobot.app._control import format_audit_row
from crytobot.app._inputs import DataIssue, DataReport, PairMarket, TurnSettings
from crytobot.app._notices import NoticeKind, Notices, TurnMemory
from crytobot.app._result import BuyHalt, PairOutcome, TurnOutcome, TurnResult
from crytobot.execution import (
    PARTS,
    BannedError,
    CloseOrder,
    Exchange,
    ExecutionState,
    Order,
    OrderStatus,
    stop_client_id,
)
from crytobot.persistence import StoredState, StoreOutcome, append_audit_record, save_store
from crytobot.portfolio import Closure, Fill, Ledger, Position, SnapshotOutcome, account_state
from crytobot.risk import PairRules, RiskState, engage_kill_switch, observe


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
# spec 0033 R-6: the USDT reconciliation tolerance
_BALANCE_TOLERANCE = Decimal("0.05")


def third_asset_fees(execution: ExecutionState) -> Decimal:
    """Spec 0037 R-4 (plan Risk 2): dolan emirlerde üçüncü varlıktan (ör. BNB) kesilen komisyonların
    defterdeki USDT değerlerinin toplamı. Defter bu değeri USDT bakiyesinden düşer (alım) ya da
    gelirden keser (satış); borsa ise USDT'den değil o varlıktan keser: borsanın USDT bakiyesi
    defterinkinden bu toplam kadar fazladır. Değer emrin ücretidir, alımdaki toz hariç (ücret
    `ödenen + değer - net * fiyat`tır; fark yalnız 28 basamaklık fiyat yuvarlamasıdır)."""
    total = Decimal(0)
    for order in execution.orders.values():
        asset = order.commission_asset
        if order.status is not OrderStatus.FILLED or asset is None or order.fee is None:
            continue
        base, _, quote = order.pair.partition("/")
        if asset in (base, quote):
            continue
        dust = order.dust if isinstance(order, Order) and order.dust is not None else Decimal(0)
        price = order.fill_price if order.fill_price is not None else Decimal(0)
        total += order.fee - dust * price
    return total


def buy_fill(order: Order, at: datetime) -> Fill:
    """Dolan alım emrinin defter kaydı: alım yolu ve bilinmeyen emir sorgusu aynı kaydı yazar.
    Spec 0036 R-2: canlıda pozisyon miktarı net miktardır."""
    return Fill(
        order.client_order_id,
        order.pair,
        order.side,
        order.position_amount,
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
        self, position_id: str, pair: str, amount: Decimal, stop: Decimal, part: int = 0
    ) -> None:
        """Spec 0034 R-4, R-5: pozisyon için borsaya şartlı stop. Çağıran dolumu önceden kaydetti
        (F-4): borsa çağrısı ne olursa olsun alım defterde kalır. Spec 0037 (plan Risk 3): kısmi
        kapanıştan sonraki stop `part` neslinin kimliğiyle; nesil kalmadıysa elle bakılmalı."""
        if part >= PARTS:
            self.stop_failed(
                position_id,
                f"pozisyon {part} kez kısmen kapandı, yeni stop kimliği yok; elle bakılmalı",
            )
            return
        stop_id = stop_client_id(position_id, part)
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

    def note_fill(self, order: Order | CloseOrder) -> None:
        """Spec 0037 R-1, R-3, R-4: dolan canlı emrin olay bildirimleri: kısmi dolum (dolan, emir)
        ve tahmini ücret. Bir kez gider; durum değildir."""
        if order.status is not OrderStatus.FILLED or order.filled is None:
            return
        cid, pair = order.client_order_id, order.pair
        if order.filled < order.amount:
            self.notices.event(
                NoticeKind.PARTIAL_FILL,
                cid,
                f"{pair}: {cid} kısmen doldu: dolan {order.filled}, emir {order.amount}; dolan"
                " kısım deftere yazıldı",
            )
        if order.fee_estimated:
            self.notices.event(
                NoticeKind.ESTIMATED_FEE,
                cid,
                f"{pair}: {cid} komisyonu {order.commission} {order.commission_asset};"
                f" {order.commission_asset}/USDT fiyatı okunamadı, ücret ayardaki oranla tahmin"
                f" edildi ({order.fee} USDT)",
            )

    def unsupported_fill(self, client_order_id: str, pair: str, reason: str) -> None:
        """Spec 0036 R-5: henüz desteklenmeyen dolum deftere yazılmadı; emir `UNKNOWN` kalır
        (güvenli mod). Bildirim emir netleşene kadar sürer."""
        self.notices.enter(
            NoticeKind.UNSUPPORTED_FILL,
            client_order_id,
            f"{pair}: {client_order_id}: {reason}; deftere yazılmadı, elle bakılmalı",
        )

    def rules_of(self, pair: str) -> PairRules | None:
        data = self.market.get(pair)
        rules = data.rules if isinstance(data, PairMarket) else None
        return rules if isinstance(rules, PairRules) else None

    def check_position_minimums(self) -> None:
        """Spec 0036 R-2 (plan Risk 7): canlıda her açık pozisyon o turun kurallarıyla denetlenir;
        asgari miktarın ya da (güncel fiyatla) asgari tutarın altındaki pozisyon alımı durdurur.
        Kalıcı durum yoktur; kurallar ya da fiyat yoksa önceki bildirim sürer."""
        if self.state.mode != "live":
            return
        for subject, position in self.state.ledger.positions.items():
            below = self._below_minimum(position)
            if below is None:
                self.notices.keep(NoticeKind.POSITION_BELOW_MINIMUM, subject)
                if (NoticeKind.POSITION_BELOW_MINIMUM, subject) in self.memory.active:
                    self.halt(BuyHalt.POSITION_BELOW_MINIMUM)
            elif below:
                self.halt(BuyHalt.POSITION_BELOW_MINIMUM)
                self.notices.enter(
                    NoticeKind.POSITION_BELOW_MINIMUM,
                    subject,
                    f"güvenli mod: {position.pair}: {subject} pozisyonu ({position.amount})"
                    " borsanın asgari miktarının ya da tutarının altında; satılamaz, elle"
                    " bakılmalı",
                )

    def _below_minimum(self, position: Position) -> bool | None:
        """Asgarinin altında mı; değerlendirilemiyorsa `None`."""
        rules = self.rules_of(position.pair)
        if rules is None:
            return None
        min_amount, min_notional = rules.min_amount, rules.min_notional
        if not (isinstance(min_amount, Decimal | int) and isinstance(min_notional, Decimal | int)):
            return None
        if position.amount < min_amount:
            return True
        price = self.report.prices.get(position.pair)
        if price is None:
            return None
        return position.amount * price < min_notional

    def reconcile_balance(self) -> None:
        """Spec 0033 R-6: Canlı modda tur başı bakiye mutabakatı (tolerans <= 0.05 USDT).

        Spec 0037 (plan Risk 2): beklenen USDT, defter bakiyesi + üçüncü varlık komisyonlarının USDT
        değeridir. Ardından coin mutabakatı (R-5; Amendment A-1: açık pozisyon varken ikinci çağrı,
        `fetch_balances`). Sorgulardan biri başarısızsa güvenli mod (G-8); coin bildirimleri
        sürer."""
        if self.state.mode != "live":
            return
        fetch_bal = getattr(self.exchange, "fetch_free_balance", None)
        if not callable(fetch_bal):
            return
        try:
            ex_balance = fetch_bal(asset="USDT")
        except Exception as err:
            self._balance_error(err)
            return

        if ex_balance is None:
            self._balance_failed("güvenli mod: borsa serbest bakiyesi alınamadı")
            return

        ledger_balance = self.state.ledger.balance
        if ledger_balance is None:
            return
        expected = ledger_balance + third_asset_fees(self.state.execution)
        diff = abs(expected - ex_balance)
        if diff > _BALANCE_TOLERANCE:
            self.halt(BuyHalt.RECONCILIATION_HALT)
            self.notices.enter(
                NoticeKind.RECONCILIATION,
                "",
                f"bakiye mutabakat farkı toleransı aştı: "
                f"beklenen={expected}, borsa={ex_balance}, fark={diff}",
            )
        self._reconcile_coins()

    def _balance_error(self, err: Exception) -> None:
        """Bakiye sorgusu hatası: 429 bekleme süresi saklanır, ban yutulmaz, kalanı güvenli mod."""
        retry_after = getattr(err, "retry_after", None)
        if retry_after is not None and retry_after > 0:
            self.memory.retry_after = retry_after
        if type(err).__name__ == "BannedError":
            raise err
        self._balance_failed(f"güvenli mod: borsa bakiye sorgusu başarısız ({type(err).__name__})")

    def _balance_failed(self, message: str) -> None:
        """G-8: bakiye bilinmiyor; alım durur, coin eksikliği değerlendirilmedi (sürer)."""
        self.halt(BuyHalt.BALANCE_CHECK_FAILED)
        self.notices.enter(NoticeKind.SAFE_MODE, "", message)
        for kind, subject in tuple(self.memory.active):
            if kind is NoticeKind.COIN_SHORTFALL:
                self.notices.keep(kind, subject)

    def _reconcile_coins(self) -> None:
        """Spec 0037 R-5 (A-15): açık pozisyonu olan her coinde borsadaki toplam (serbest + emirde
        bekleyen) o coindeki açık pozisyonların net toplamından bir miktar adımından fazla azsa
        alım durur, bildirim çift adıyla. Fazla coin yok sayılır. Adım yoksa önceki bildirim sürer.
        Kalıcı durum yoktur: koşul düzelince bildirim yokluğuyla biter (çıkış bildirimi)."""
        held: dict[str, Decimal] = {}
        for position in self.state.ledger.positions.values():
            held[position.pair] = held.get(position.pair, Decimal(0)) + position.amount
        if not held:
            return
        fetch = getattr(self.exchange, "fetch_balances", None)
        if not callable(fetch):
            return
        try:
            balances = fetch()
        except Exception as err:
            self._balance_error(err)
            return
        if not isinstance(balances, Mapping):
            self._balance_failed("güvenli mod: borsa coin bakiyeleri alınamadı")
            return
        for pair, expected in held.items():
            rules = self.rules_of(pair)
            step = rules.amount_step if rules is not None else None
            if not (isinstance(step, Decimal) and step.is_finite() and step > 0):
                self.notices.keep(NoticeKind.COIN_SHORTFALL, pair)
                if (NoticeKind.COIN_SHORTFALL, pair) in self.memory.active:
                    self.halt(BuyHalt.COIN_SHORTFALL)
                continue
            coin = pair.partition("/")[0]
            total = getattr(balances.get(coin), "total", Decimal(0))
            if not isinstance(total, Decimal):
                total = Decimal(0)
            if expected - total > step:
                self.halt(BuyHalt.COIN_SHORTFALL)
                self.notices.enter(
                    NoticeKind.COIN_SHORTFALL,
                    pair,
                    f"güvenli mod: {pair}: borsadaki {coin} ({total}) açık pozisyonların net"
                    f" toplamından ({expected}) az; yeni alım durdu, kapanışlar sürer",
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
