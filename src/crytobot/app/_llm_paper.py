"""LLM paper defterinin oynatma çekirdeği (spec 0060 R-3, R-4, C-2...C-4, G-2...G-8; plan Risk 6,
8).

Saf: kararlar, 1h mumlar ve borsa kuralları verilir; dosya, saat ve ağ yoktur. Saat saat, ölçüm
başlangıcından ufka (rapor anı ya da bitiş) kadar oynatılır. Her saatte sıra: o turun kararları
bekleyenlere eklenir (aynı coinde açık pozisyon ya da bekleyen varsa atlanır, G-3); bekleyenler
mumun aralığı giriş bölgesine değerse bölgenin üst ucundan dolar (piyasa kararı - rastgele ikiz -
turun anında); dolumda risk modülü kasanın o anki durumuyla onaylar ya da reddeder (G-2, G-4, G-8);
açık pozisyonlar o mumda stop (önce), hedef (dolum mumunda yalnız dolum açılışta olduysa, A-8),
sonra 168. mumda süre ile kapanır; serbest bakiye kayma payı düşülerek verilir ve ödenen tutar
kasayı aşmaz (M-3); mum kapanışında kasa gözlenir (BR-5, BR-6). Bitişte açık pozisyon "ölçüm sonu"
ile kapanır (G-6); ufuk bitişten önceyse açık kalır. Gereken aralığında mumu eksik karar baştan
"ölçülemedi" olur ve oynatmaya girmez.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from crytobot.app._llm_paper_config import (
    FEE,
    LIMITS,
    MAX_HOLD,
    OPENING_BALANCE,
    QUOTE,
    SLIPPAGE,
    SPREAD,
)
from crytobot.risk import (
    EMPTY_STATE,
    AccountState,
    ApprovalReason,
    PairRules,
    RiskState,
    TradeIntent,
    approve_trade,
    observe,
)

HOUR = timedelta(hours=1)
HOLD_BARS = int(MAX_HOLD / HOUR)


@dataclass(frozen=True)
class Bar:
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class PaperDecision:
    """Uygulanacak bir `al`. `market`: rastgele ikiz, turun anında `entry_high`'tan dolar."""

    turn: datetime
    coin: str
    entry_low: Decimal
    entry_high: Decimal
    stop: Decimal
    target: Decimal
    valid_hours: int
    market: bool = False


class Status(StrEnum):
    CLOSED = "kapandı"
    OPEN = "açık"
    PENDING = "bekliyor"
    NOT_FILLED = "dolmadı"
    SAME_COIN = "aynı coinde açık"
    UNMEASURABLE = "ölçülemedi (mum eksik)"
    REJECTED = "reddedildi"


class ExitKind(StrEnum):
    TARGET = "hedef"
    STOP = "stop"
    TIME = "süre"
    END = "ölçüm sonu"


# risk refusal names in the report (AC-5)
REJECTIONS: dict[ApprovalReason, str] = {
    ApprovalReason.DRAWDOWN_HALT: "drawdown durdurması",
    ApprovalReason.DAILY_LOSS_LIMIT: "günlük zarar",
    ApprovalReason.INSUFFICIENT_EDGE: "maliyet katı",
    ApprovalReason.POSITION_LIMIT: "açık pozisyon sınırı",
    ApprovalReason.BELOW_MINIMUM: "en küçük tutar",
    ApprovalReason.INVALID_STOP: "geçersiz stop",
    ApprovalReason.INVALID_TARGET: "geçersiz hedef",
    ApprovalReason.INVALID_ENTRY: "geçersiz giriş",
    ApprovalReason.INVALID_INPUT: "geçersiz girdi",
    ApprovalReason.NOT_WHITELISTED: "listede değil",
    ApprovalReason.KILL_SWITCH_ACTIVE: "kill switch",
    ApprovalReason.NOT_BUY: "alım değil",
}


@dataclass(frozen=True)
class PaperTrade:
    """Bir kararın sonucu. `rejection` yalnız `reddedildi`de; `net` kapanışta, maliyetlerden
    sonra."""

    decision: PaperDecision
    status: Status
    rejection: str | None = None
    filled_at: datetime | None = None
    fill_price: Decimal | None = None
    amount: Decimal | None = None
    exit_at: datetime | None = None
    exit_price: Decimal | None = None
    exit_kind: ExitKind | None = None
    net: Decimal | None = None


@dataclass(frozen=True)
class Replay:
    """`curve`: kasanın saatlik eğrisi (açılış dahil); `halted_at`: drawdown durdurmasının anı."""

    trades: tuple[PaperTrade, ...]
    curve: tuple[tuple[datetime, Decimal], ...]
    halted_at: datetime | None
    final_equity: Decimal
    halted_equity: Decimal | None = None


@dataclass
class _Open:
    index: int
    coin: str
    amount: Decimal
    fill_price: Decimal
    paid: Decimal  # cost + entry fee
    stop: Decimal
    target: Decimal
    fill_bar: datetime
    at_open: bool  # filled at the bar's open: the target may count in the fill bar (A-8)


Bars = Mapping[str, Mapping[datetime, Bar]]


def needed_span(decision: PaperDecision) -> tuple[datetime, datetime]:
    """Kararın ölçülmesi için gereken mumlar `[başlangıç, bitiş)`: geçerlilik + üst süre."""
    return decision.turn, decision.turn + HOUR * (decision.valid_hours + HOLD_BARS + 1)


def _complete(bars: Bars, decision: PaperDecision, horizon: datetime) -> bool:
    series = bars.get(decision.coin, {})
    start, end = needed_span(decision)
    moment = start
    while moment < min(end, horizon):
        if moment not in series:
            return False
        moment += HOUR
    return True


def _floor(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def replay(
    decisions: Sequence[PaperDecision],
    bars: Bars,
    rules: Mapping[str, PairRules],
    start: datetime,
    end: datetime,
    horizon: datetime,
) -> Replay:
    """`decisions` tur sırasıyla; `horizon` ≤ `end`: bu anda ve sonrasında açılan mum oynatılmaz."""
    horizon = min(_floor(horizon), end)
    results: list[PaperTrade | None] = [None] * len(decisions)
    by_turn: dict[datetime, list[int]] = {}
    for index, decision in enumerate(decisions):
        if not start <= decision.turn < end or decision.turn >= horizon:
            continue
        if not _complete(bars, decision, horizon):
            results[index] = PaperTrade(decision, Status.UNMEASURABLE)
            continue
        by_turn.setdefault(decision.turn, []).append(index)
    whitelist = {f"{coin}/{QUOTE}" for coin in rules}
    state: RiskState = observe(EMPTY_STATE, start, OPENING_BALANCE, LIMITS).state
    cash = OPENING_BALANCE
    marks: dict[str, Decimal] = {}
    pending: list[int] = []
    positions: list[_Open] = []
    curve: list[tuple[datetime, Decimal]] = [(start, OPENING_BALANCE)]
    halted_at: datetime | None = None
    halted_equity: Decimal | None = None

    def equity() -> Decimal:
        return cash + sum((p.amount * marks[p.coin] for p in positions), Decimal(0))

    def close(position: _Open, at: datetime, price: Decimal, kind: ExitKind) -> None:
        nonlocal cash
        proceeds = position.amount * price
        fee = proceeds * FEE
        cash += proceeds - fee
        positions.remove(position)
        previous = results[position.index]
        assert previous is not None
        results[position.index] = PaperTrade(
            previous.decision,
            Status.CLOSED,
            None,
            previous.filled_at,
            previous.fill_price,
            previous.amount,
            at,
            price,
            kind,
            proceeds - fee - position.paid,
        )

    moment = start
    while moment < horizon:
        for index in by_turn.get(moment, ()):
            coin = decisions[index].coin
            busy = any(p.coin == coin for p in positions) or any(
                decisions[i].coin == coin for i in pending
            )
            if busy:
                results[index] = PaperTrade(decisions[index], Status.SAME_COIN)
            else:
                pending.append(index)
        for index in list(pending):
            decision = decisions[index]
            bar = bars[decision.coin][moment]
            if moment >= decision.turn + HOUR * decision.valid_hours:
                pending.remove(index)
                results[index] = PaperTrade(decision, Status.NOT_FILLED)
                continue
            touched = bar.low <= decision.entry_high and bar.high >= decision.entry_low
            if not (decision.market or touched):
                continue
            pending.remove(index)
            state = observe(state, moment, equity(), LIMITS).state
            approval = approve_trade(
                TradeIntent(
                    f"{decision.coin}/{QUOTE}",
                    "buy",
                    decision.entry_high,
                    decision.stop,
                    decision.target,
                ),
                LIMITS,
                # the risk module sizes the balance without slippage: leave its share aside (M-3)
                AccountState(equity(), cash / (1 + SLIPPAGE), len(positions)),
                rules[decision.coin],
                whitelist,
                FEE,
                SPREAD,
                SLIPPAGE,
                state,
                moment,
            )
            if approval.amount is None or approval.reason is not None:
                name = REJECTIONS.get(approval.reason) if approval.reason else None
                results[index] = PaperTrade(decision, Status.REJECTED, name or "reddedildi")
                continue
            pair_rules = rules[decision.coin]
            step = Decimal(str(pair_rules.amount_step))
            amount = approval.amount
            price = decision.entry_high * (1 + SLIPPAGE)
            while amount > 0 and amount * price * (1 + FEE) > cash:  # never spend past the cash
                amount -= step
            notional = amount * decision.entry_high
            if (
                amount <= 0
                or amount < Decimal(str(pair_rules.min_amount))
                or notional < Decimal(str(pair_rules.min_notional))
            ):
                results[index] = PaperTrade(decision, Status.REJECTED, "en küçük tutar")
                continue
            paid = amount * price * (1 + FEE)
            cash -= paid
            marks[decision.coin] = price
            positions.append(
                _Open(
                    index,
                    decision.coin,
                    amount,
                    price,
                    paid,
                    decision.stop,
                    decision.target,
                    moment,
                    decision.market or bar.open <= decision.entry_high,
                )
            )
            results[index] = PaperTrade(decision, Status.OPEN, None, moment, price, amount)
        for position in list(positions):
            bar = bars[position.coin][moment]
            target_counts = moment != position.fill_bar or position.at_open
            if bar.low <= position.stop:
                close(position, moment + HOUR, position.stop * (1 - SLIPPAGE), ExitKind.STOP)
            elif target_counts and bar.high >= position.target:
                close(position, moment + HOUR, position.target * (1 - SLIPPAGE), ExitKind.TARGET)
            elif moment >= position.fill_bar + HOUR * HOLD_BARS:
                close(position, moment + HOUR, bar.close * (1 - SLIPPAGE), ExitKind.TIME)
        for position in positions:
            marks[position.coin] = bars[position.coin][moment].close
        after = moment + HOUR
        if positions or curve[-1][1] != equity():
            update = observe(state, after, equity(), LIMITS)
            state = update.state
            curve.append((after, equity()))
            if state.halted and halted_at is None:
                halted_at, halted_equity = after, equity()
        moment = after
    if horizon >= end:
        last = end - HOUR
        for position in list(positions):
            bar = bars[position.coin][last]
            close(position, end, bar.close * (1 - SLIPPAGE), ExitKind.END)
        for index in pending:
            results[index] = PaperTrade(decisions[index], Status.NOT_FILLED)
        pending.clear()
        if curve[-1][1] != equity():
            curve.append((end, equity()))
    else:
        for index in pending:
            results[index] = PaperTrade(decisions[index], Status.PENDING)
    trades = tuple(result for result in results if result is not None)
    return Replay(trades, tuple(curve), halted_at, equity(), halted_equity)
