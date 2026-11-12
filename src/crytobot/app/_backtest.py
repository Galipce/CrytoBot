"""Backtest koşusu (spec 0025 R-1, R-3…R-13; plan Risk 3, 7, 8, 10, 11).

Sıra: rapor dosyası var mı (R-4) → veri dosyası (R-3) → dosya ile ayar uyumu → geçici depo →
dönemin her tur anında paper turunun aynısı (`run_turn`, simüle saat) → metrikler → rapor (konsol,
sonra dosya). Gerçek etkiler `BacktestParts` ile gelir: `app` dosya açmaz, saat çağırmaz, ağa
çıkmaz. Gerçek saat (`clock`) yalnız bir kez, raporun üretim anı için okunur; turlar simüle saatle
koşar (spec 0040 CB-2). Rapor başlığı botun etkin rapor koşullarını yazar (CB-3, G-5); dosya
yazılınca yazılan baytların parmak izi `rapor parmak izi: <hex>` satırıyla söylenir (CB-1). Geçici
depoyu (`store_path`) giriş noktası geçici bir dizinde verir; bot deposu, kilidi ve kayıt dosyası
hiç açılmaz (R-1).

Her turdan sonra depo yüklenir: kasa `account_state(defter, son bilinen tur fiyatları)` ile
bulunur (turun gözlemiyle aynı tanım, Risk 7). Günlük zarar günü, sabit bir öneriyle
`approve_trade` denemesidir (kural kopyalanmaz, Risk 8): durdurma kaldırılmış bir kopya durumla
denenir ki drawdown durdurması günlük limiti gizlemesin; depoya yazılmaz.

Durma (Risk 11): durdurma isteği her turdan önce ve son turdan sonra denetlenir; `COMPLETED`
olmayan tur sonucu koşuyu durdurur. İkisinde de rapor yazılmaz, neden adıyla söylenir. Beklenmeyen
hata tip adıyla söylenir, metni yazılmaz. İkinci istek (`ForcedStop`) satırı yazılıp yeniden
fırlatılır. Konsol satırları zaman damgası taşımaz (R-12).

Spec 0042 R-1 (plan Adım 4): varsayılan koşu yalnız örneklem içi tur anlarını (`[start, split_at)`)
koşar; sonraki mumlar hiçbir tura verilmez, rapor ve konsol yalnız örneklem içini yazar. Dönem
denetimi veri okununca: `start < split_at < holdout_at < end` (her dönem en az bir tur; ilk sorun
`ayar geçersiz: backtest.<alan>`). Son değerlendirme (`_evaluation.py`) aynı parçaları kullanır:
`_history`, `_simulate`, `_facts`, `_publish`. Spec 0043: strateji adı ve parametreleri çalışan
adayın ayarındandır (`settings.name`, `settings.parameters()`).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum

from crytobot.app._backtest_config import BacktestConfig, on_boundary
from crytobot.app._backtest_inputs import TurnInputs
from crytobot.app._inputs import _PROBE_INTENT, _PROBE_PAIR, _PROBE_RULES, PairMarket
from crytobot.app._loop import ForcedStop, StopRequest
from crytobot.app._notices import TurnMemory, TurnNotice
from crytobot.app._result import TurnOutcome, TurnResult
from crytobot.app._session import AppError
from crytobot.app._start import PrepareOutcome, prepare_store
from crytobot.app._turn import run_turn
from crytobot.backtest import (
    ReportFacts,
    TurnRecord,
    report_fingerprint,
    report_text,
    run_metrics,
)
from crytobot.execution import PAPER, CloseOrder, Order, OrderOutcome, OrderStatus, PaperExchange
from crytobot.market_data import CANDLE_INTERVALS, HistoryData, HistoryRead, HistoryReadProblem
from crytobot.persistence import StoredState, load_store
from crytobot.portfolio import SnapshotOutcome, account_state
from crytobot.risk import AccountState, ApprovalReason, RiskState, approve_trade
from crytobot.strategy import NoProposalReason, Settings

_EVENT = "backtest"
_NOT_WRITTEN = "rapor yazılmadı"
FINGERPRINT_LINE = "rapor parmak izi"
_READ_REFUSALS = {
    HistoryReadProblem.MISSING: "veri dosyası yok",
    HistoryReadProblem.UNREADABLE: "veri dosyası okunamıyor",
    HistoryReadProblem.CORRUPT: "veri dosyası bozuk",
    HistoryReadProblem.INCOMPLETE: "veri dosyası tamamlanmamış",
}


class BacktestOutcome(Enum):
    COMPLETED = "completed"
    REFUSED = "refused"
    STOPPED = "stopped"
    REPORT_NOT_WRITTEN = "report_not_written"


@dataclass(frozen=True)
class BacktestExit:
    """`turns`: yalnız tamamlanan koşuda tur sayısı, ret ve durmada 0.

    `report`: konsola yazılan rapor (yalnız koşu tamamlandıysa).
    """

    outcome: BacktestOutcome
    message: str
    turns: int
    report: str | None


@dataclass(frozen=True)
class BacktestParts:
    """Koşunun gerçek etkileri: veri dosyası okuması, rapor dosyası denetimi ve yazıcısı, konsol
    satırı, durdurma isteği, geçici deponun yolu (var olmamalı) ve üretim anının saati (UTC)."""

    read: Callable[[str], HistoryRead]
    report_exists: Callable[[str], bool]
    write_report: Callable[[str, str], bool]
    write: Callable[[str], None]
    stop: StopRequest
    store_path: str
    clock: Callable[[], datetime]


class _Halt(AppError):
    """Koşu durdu ya da reddedildi; neden metinde. `detail`: satırın sonu, yoksa sonuca göre."""

    def __init__(self, outcome: BacktestOutcome, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.message = message
        self.detail = detail


def _refused(message: str, detail: str | None = None) -> _Halt:
    return _Halt(BacktestOutcome.REFUSED, message, detail)


def _stopped(message: str) -> _Halt:
    return _Halt(BacktestOutcome.STOPPED, message)


def _interval_text(interval: timedelta) -> str:
    return CANDLE_INTERVALS.get(interval, "?")


def _report_free(path: str, parts: BacktestParts) -> None:
    """R-4: rapor yolunda (ya da `.part`'ında) bir şey varsa ret, veri dosyası okunmadan."""
    if parts.report_exists(path):
        raise _refused(f"rapor dosyası var: {path}; üzerine yazılmaz")


def _data(config: BacktestConfig, parts: BacktestParts) -> HistoryData:
    """R-3, R-4: rapor dosyası, veri dosyası ve uyum; ilk sorun adıyla."""
    _report_free(config.report_path, parts)
    return _history(config, parts)


def _history(config: BacktestConfig, parts: BacktestParts) -> HistoryData:
    """R-3; spec 0042 AC-2: veri dosyası, ayarla uyumu ve üç dönem; ilk sorun adıyla."""
    read = parts.read(config.data_path)
    if read.problem is HistoryReadProblem.UNTRUSTED:
        raise _stopped(f"güvenilmeyen veri: {read.pair or '-'} ({read.detail or '-'})")
    if read.problem is not None or read.data is None:
        text = _READ_REFUSALS.get(read.problem, "veri dosyası okunamıyor")  # type: ignore[arg-type]
        detail = f" ({read.detail})" if read.detail else ""
        raise _refused(f"{text}{detail}: {config.data_path}")
    data, bot = read.data, config.bot
    if {pair.pair for pair in data.pairs} != set(bot.turn.whitelist):
        raise _refused("veri dosyası uyumsuz: çift kümesi beyaz listeden farklı (turn.whitelist)")
    if data.candle_interval != bot.read.candle_interval:
        raise _refused("veri dosyası uyumsuz: mum aralığı farklı (market.candle_interval)")
    if not (
        on_boundary(data.start, bot.turn_interval) and on_boundary(data.end, bot.turn_interval)
    ):
        raise _refused(
            "veri dosyası uyumsuz: dönem tur aralığı sınırında değil (bot.turn_interval)"
        )
    if not data.start < config.split_at < data.end:
        raise _refused("ayar geçersiz: backtest.split_at (dönemin kesinlikle içinde değil)")
    if not config.split_at < config.holdout_at < data.end:  # split < holdout: the config's rule
        raise _refused("ayar geçersiz: backtest.holdout_at (dönemin kesinlikle içinde değil)")
    return data


def _moments(data: HistoryData, interval: timedelta) -> list[datetime]:
    moments: list[datetime] = []
    moment = data.start
    while moment < data.end:
        moments.append(moment)
        moment += interval
    return moments


def _reason_name(reason: object) -> tuple[bool, str]:
    """(öneri yok mu, ad): ret adları kaynağıyla (`risk.`, `emir.`, `app.`)."""
    if isinstance(reason, NoProposalReason):
        return True, reason.value
    if isinstance(reason, ApprovalReason):
        return False, f"risk.{reason.value}"
    if isinstance(reason, OrderOutcome):
        return False, f"emir.{reason.value}"
    assert isinstance(reason, Enum)  # PairNote
    return False, f"app.{reason.value}"


class _Run:
    def __init__(
        self, config: BacktestConfig, parts: BacktestParts, data: HistoryData, store_path: str
    ) -> None:
        self.config = config
        self.parts = parts
        self.data = data
        self.store_path = store_path
        bot = config.bot
        self.inputs = TurnInputs(data, bot.turn, bot.read.candle_count, config.spread)
        self.memory = TurnMemory()
        self.exchange = PaperExchange()
        self.marks: dict[str, Decimal] = {}
        self.closures = 0
        self.records: list[TurnRecord] = []
        self.entered: list[str] = []

    def notice(self, notice: TurnNotice) -> None:
        """R-8: bildirim hiçbir yere gitmez; yalnız girişler türüne göre sayılır."""
        if notice.entering:
            self.entered.append(notice.kind.value)

    def _state(self) -> StoredState:
        loaded = load_store(self.store_path, PAPER)
        if loaded.state is None:
            raise _stopped(f"geçici depo okunamıyor: {loaded.message}")
        return loaded.state

    def _daily_loss(self, risk: RiskState, at: datetime) -> bool:
        equity = risk.last_equity
        if equity is None or risk.day != at.date():
            return False  # no observation this day: the probe would only say "stale"
        probe = replace(risk, halted=False, peak_equity=equity)
        turn = self.config.bot.turn
        approval = approve_trade(
            _PROBE_INTENT,
            turn.limits,
            AccountState(equity, equity, 0),
            _PROBE_RULES,
            frozenset({_PROBE_PAIR}),
            turn.fee,
            self.config.spread,
            turn.slippage,
            probe,
            at,
        )
        return approval.reason is ApprovalReason.DAILY_LOSS_LIMIT

    def _costs(
        self, result: TurnResult, market: Mapping[str, PairMarket]
    ) -> tuple[Decimal, Decimal]:
        fees, slippage = Decimal(0), Decimal(0)
        orders: tuple[Order | CloseOrder, ...] = (*result.buys, *result.closes)
        for order in orders:
            if order.status is not OrderStatus.FILLED or order.fee is None:
                continue
            fees += order.fee
            price = market[order.pair].price if order.pair in market else None
            if price is not None and order.fill_price is not None:
                slippage += order.amount * abs(order.fill_price - Decimal(price))
        return fees, slippage

    def turn(self, at: datetime) -> None:
        market = self.inputs.market(at)
        missing = self.inputs.missing(market, at)
        self.entered = []
        result = run_turn(
            market=market,
            settings=self.config.bot.turn,
            store_path=self.store_path,
            now=at,
            exchange=self.exchange,
            sink=self.notice,
            memory=self.memory,
        )
        if result.outcome is not TurnOutcome.COMPLETED:
            raise _stopped(f"tur sonucu {result.outcome.value} ({result.message})")
        for pair, data in market.items():
            if data.price is not None:
                self.marks[pair] = Decimal(data.price)
        state = self._state()
        snapshot = account_state(state.ledger, dict(self.marks))
        if snapshot.outcome is not SnapshotOutcome.READY or snapshot.snapshot is None:
            raise _stopped(f"kasa hesaplanamıyor: {snapshot.message}")
        closures = tuple(state.ledger.closures.values())
        fees, slippage = self._costs(result, market)
        reasons = [_reason_name(outcome.reason) for outcome in result.pairs]
        self.records.append(
            TurnRecord(
                at=at,
                equity=snapshot.snapshot.equity,
                positions=tuple(state.ledger.positions.values()),
                marks=dict(self.marks),
                closures=closures[self.closures :],
                fees=fees,
                slippage=slippage,
                daily_loss=self._daily_loss(state.risk, at),
                halted=state.risk.halted,
                missing=missing,
                no_proposals=tuple(name for empty, name in reasons if empty),
                refusals=tuple(name for empty, name in reasons if not empty),
                notices=tuple(self.entered),
            )
        )
        self.closures = len(closures)


def strategy_setting(strategy: Settings) -> dict[str, int | Decimal | str]:
    """Raporun strateji satırının değerleri (spec 0040 CB-4), kapının adlarıyla ve adayın tanım
    sırasıyla (spec 0043, plan Risk 8)."""
    return dict(strategy.parameters())


def _facts(config: BacktestConfig, data: HistoryData, generated_at: datetime) -> ReportFacts:
    bot = config.bot
    return ReportFacts(
        data.start,
        data.end,
        _interval_text(data.candle_interval),
        _interval_text(bot.turn_interval),
        config.split_at,
        tuple(bot.turn.whitelist),
        data.downloaded_at,
        bot.read.candle_count,
        config.spread,
        strategy_setting(bot.turn.strategy),
        generated_at=generated_at,
        fee=Decimal(bot.turn.fee),
        slippage=Decimal(bot.turn.slippage),
        per_trade_risk=bot.turn.limits.per_trade_risk,
        daily_loss_limit=bot.turn.limits.daily_loss_limit,
        max_drawdown=bot.turn.limits.max_drawdown,
        max_open_positions=bot.turn.limits.max_open_positions,
        profit_cost_multiple=bot.turn.limits.profit_cost_multiple,
        opening_balance=bot.opening_balance,
        strategy_name=bot.turn.strategy.name,
        holdout_at=config.holdout_at,
    )


def _say(parts: BacktestParts, text: str) -> None:
    parts.write(f"{_EVENT} {text}")


def _in_sample(moments: Sequence[datetime], config: BacktestConfig) -> list[datetime]:
    return [moment for moment in moments if moment < config.split_at]


def _started(
    parts: BacktestParts, data: HistoryData, moments: Sequence[datetime], until: datetime | None
) -> None:
    """`until`: örneklem içi koşuda ayrım anı (dönem orada biter, konsol bunu söyler)."""
    end = data.end if until is None else until
    scope = "" if until is None else " (örneklem içi)"
    _say(
        parts,
        f"başladı: dönem={data.start.isoformat()}..{end.isoformat()}{scope}"
        f" çift={len(data.pairs)} tur={len(moments)}",
    )


def _simulate(
    config: BacktestConfig,
    parts: BacktestParts,
    data: HistoryData,
    moments: Sequence[datetime],
    store_path: str,
) -> list[TurnRecord]:
    """Verilen tur anlarını sırayla koşar; yalnız onların mumları tura verilir (spec 0042 R-1)."""
    prepared = prepare_store(store_path, config.bot.opening_balance, data.start)
    if prepared.outcome is not PrepareOutcome.PREPARED:
        raise _stopped(f"geçici depo hazırlanamadı: {prepared.message}")
    run = _Run(config, parts, data, store_path)
    for moment in moments:
        if parts.stop.requested:
            raise _stopped("durdurma isteği")
        run.turn(moment)
    if parts.stop.requested:
        raise _stopped("durdurma isteği")
    return run.records


def _publish(parts: BacktestParts, path: str, report: str, turns: int) -> BacktestExit:
    """Rapor konsola, sonra dosyaya; yazılınca parmak izi satırı (spec 0040 CB-1, G-7)."""
    parts.write(report.removesuffix("\n"))  # the writer ends the line: the same bytes as the file
    if not parts.write_report(path, report):
        message = f"rapor dosyası yazılamadı: {path}; rapor yalnız konsolda"
        _say(parts, message)
        return BacktestExit(BacktestOutcome.REPORT_NOT_WRITTEN, message, turns, report)
    parts.write(f"{FINGERPRINT_LINE}: {report_fingerprint(report)}")
    message = f"tamam: rapor dosyası {path}"
    _say(parts, message)
    return BacktestExit(BacktestOutcome.COMPLETED, message, turns, report)


def _run(config: BacktestConfig, parts: BacktestParts) -> BacktestExit:
    data = _data(config, parts)
    moments = _in_sample(_moments(data, config.bot.turn_interval), config)
    _started(parts, data, moments, config.split_at)
    records = _simulate(config, parts, data, moments, parts.store_path)
    bot = config.bot
    metrics = run_metrics(bot.opening_balance, records, config.split_at, tuple(bot.turn.whitelist))
    report = report_text(_facts(config, data, parts.clock()), metrics)
    return _publish(parts, config.report_path, report, len(moments))


def guarded(parts: BacktestParts, body: Callable[[], BacktestExit]) -> BacktestExit:
    """Ret ve durma adıyla döner. İkinci durdurma isteği (`ForcedStop`) satırı yazılıp yeniden
    fırlatılır: geçici dizini giriş noktası, `.part`'ı rapor yazıcısı siler."""
    try:
        return body()
    except _Halt as halt:
        verb = "reddedildi" if halt.outcome is BacktestOutcome.REFUSED else "durdu"
        default = "tur atılmadı" if halt.outcome is BacktestOutcome.REFUSED else _NOT_WRITTEN
        _say(parts, f"{verb}: {halt.message}; {halt.detail or default}")
        return BacktestExit(halt.outcome, halt.message, 0, None)
    except ForcedStop:
        _say(parts, f"durdu: zorla durdurma; {_NOT_WRITTEN}")
        raise
    except Exception as error:  # R-13: the type only; the text may carry anything
        message = f"beklenmeyen hata: {type(error).__name__}"
        _say(parts, f"durdu: {message}; {_NOT_WRITTEN}")
        return BacktestExit(BacktestOutcome.STOPPED, message, 0, None)


def run_backtest(config: BacktestConfig, parts: BacktestParts) -> BacktestExit:
    """Varsayılan koşu (spec 0042 R-1): yalnız örneklem içi; ret ve durma adıyla döner."""
    return guarded(parts, lambda: _run(config, parts))
