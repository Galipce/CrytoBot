"""İşlem önerisi onayı: stop, boyutlama, pozisyon sayısı (0003); zarar kilitleri (0004)."""

from collections.abc import Set
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import MAX_EMAX, MAX_PREC, MIN_EMIN, Decimal, DecimalException, Inexact, localcontext
from enum import Enum
from typing import TYPE_CHECKING, cast

from crytobot.risk._limits import SCALE, RiskLimits, _in_scale, _limit_problems, _show

if TYPE_CHECKING:  # _tracking imports this module; the state is only read here
    from crytobot.risk._tracking import RiskState

BUY = "buy"


@dataclass(frozen=True)
class TradeIntent:
    """Ham alım önerisi: çift, yön, giriş, stop (`None` = stop yok), hedef (`None` = hedef yok);
    fiyatlar `Decimal`/`int`."""

    pair: str
    side: str
    entry: object
    stop: object
    target: object


@dataclass(frozen=True)
class AccountState:
    """Onay anındaki hesap: kasa ve serbest bakiye (USDT), açık pozisyon sayısı."""

    equity: object
    free_balance: object
    open_positions: object


@dataclass(frozen=True)
class PairRules:
    """Çiftin borsa kuralları: miktar adımı, asgari miktar, asgari tutar (USDT)."""

    amount_step: object
    min_amount: object
    min_notional: object


class ApprovalReason(Enum):
    """Ret nedenleri; birden fazla sorun varsa bu sıradaki ilki döner (R-8)."""

    INVALID_INPUT = "invalid_input"
    DRAWDOWN_HALT = "drawdown_halt"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    NOT_BUY = "not_buy"
    NOT_WHITELISTED = "not_whitelisted"
    INVALID_ENTRY = "invalid_entry"
    INVALID_STOP = "invalid_stop"
    INVALID_TARGET = "invalid_target"
    INSUFFICIENT_EDGE = "insufficient_edge"
    POSITION_LIMIT = "position_limit"
    BELOW_MINIMUM = "below_minimum"


@dataclass(frozen=True)
class TradeApproval:
    """Onayda `amount` dolu ve `reason` `None`; retde tersi (R-1). `intent`, karara bağlanan
    önerinin kendisidir — değiştirilmeden taşınır (spec 0006 R-14)."""

    amount: Decimal | None
    reason: ApprovalReason | None
    limited_by_balance: bool
    message: str
    intent: TradeIntent

    @property
    def approved(self) -> bool:
        return self.reason is None


def _number(value: object) -> Decimal | None:
    """`Decimal` veya `int` (`bool` hariç) sonlu bir sayı; değilse `None`."""
    if isinstance(value, bool) or not isinstance(value, Decimal | int):
        return None
    number = Decimal(value)
    return number if number.is_finite() else None


def _reached(reference: Decimal, equity: Decimal, limit: Decimal) -> bool:
    """(referans - kasa) / referans >= limit; bölmeden, tam çarpımla (sınırda yuvarlama yok)."""
    with localcontext() as exact:
        exact.prec = MAX_PREC
        # the exponent range too: a finite equity past the default Emax would raise Overflow
        exact.Emax, exact.Emin = MAX_EMAX, MIN_EMIN
        exact.traps[Inexact] = True
        return reference - equity >= limit * reference


def _out_of_scale(label: str, number: Decimal) -> str:
    return f"{label} {number} ölçeği varsayılan üs aralığı (±{SCALE}) dışında"


def _input_problems(
    limits: RiskLimits,
    account: AccountState,
    rules: PairRules,
    whitelist: object,
    fee: object,
    spread: object,
    slippage: object,
) -> list[str]:
    problems = _limit_problems(limits)
    if not isinstance(whitelist, Set):  # a str would match pairs by substring (BR-2)
        problems.append(f"beyaz liste {_show(whitelist)} bir çift kümesi olmalı")
    equity = _number(account.equity)
    if equity is None or equity <= 0:
        problems.append(f"kasa {_show(account.equity)} sıfırdan büyük bir sayı olmalı")
    elif not _in_scale(equity):
        problems.append(_out_of_scale("kasa", equity))
    free = _number(account.free_balance)
    if free is None or free < 0:
        problems.append(
            f"serbest bakiye {_show(account.free_balance)} negatif olmayan bir sayı olmalı"
        )
    elif not _in_scale(free):
        problems.append(_out_of_scale("serbest bakiye", free))
    elif equity is not None and free > equity:
        problems.append(f"serbest bakiye {free} kasadan ({equity}) büyük")
    positions = account.open_positions
    if isinstance(positions, bool) or not isinstance(positions, int) or positions < 0:
        problems.append(f"açık pozisyon {_show(positions)} negatif olmayan bir tam sayı olmalı")
    rate = _number(fee)
    if rate is None or not 0 <= rate < 1:
        problems.append(f"ücret {_show(fee)} 0 ile 1 arasında (1 hariç) olmalı")
    elif not _in_scale(rate):
        problems.append(_out_of_scale("ücret", rate))
    for label, value in (("spread", spread), ("slippage", slippage)):
        number = _number(value)  # no default: a missing cost is not silently zero (spec 0005 R-2)
        if number is None or not 0 <= number < 1:
            problems.append(f"{label} {_show(value)} 0 ile 1 arasında (1 hariç) olmalı")
        elif not _in_scale(number):
            problems.append(_out_of_scale(label, number))
    step = _number(rules.amount_step)
    if step is None or step <= 0:
        problems.append(f"miktar adımı {_show(rules.amount_step)} sıfırdan büyük olmalı")
    elif not _in_scale(step):
        problems.append(_out_of_scale("miktar adımı", step))
    for label, value in (("asgari miktar", rules.min_amount), ("asgari tutar", rules.min_notional)):
        number = _number(value)
        if number is None or number < 0:
            problems.append(f"{label} {_show(value)} negatif olmayan bir sayı olmalı")
        elif not _in_scale(number):
            problems.append(_out_of_scale(label, number))
    return problems


def _state_problems(state: "RiskState", now: object, equity: object) -> list[str]:
    """Spec 0004 R-7: durum boş, başka günden ya da başka bir kasayla güncellenmişse bayattır."""
    if state.day is None or state.last_equity is None:
        return ["risk durumu boş: önce kasa gözlenmeli"]
    # observe never builds such a state; a hand-built one would break or blow up _reached
    equities = (state.day_start_equity, state.peak_equity, state.last_equity)
    if not all(isinstance(e, Decimal) and e.is_finite() for e in equities):
        return ["risk durumu geçersiz: gün başı, zirve ya da son kasa eksik"]
    if not all(_in_scale(cast(Decimal, e)) for e in equities):
        return [f"risk durumu geçersiz: kasa ölçeği varsayılan üs aralığı (±{SCALE}) dışında"]
    if not isinstance(now, datetime) or now.utcoffset() is None:
        return [f"şu anki zaman {_show(now)} zaman dilimi taşımalı"]
    problems = []
    if now.astimezone(UTC).date() != state.day:
        problems.append(f"risk durumu bayat: gün {state.day}, bugün {now.astimezone(UTC).date()}")
    number = _number(equity)
    if number is not None and number != state.last_equity:
        problems.append(f"risk durumu bayat: son kasa {state.last_equity}, onaydaki kasa {number}")
    return problems


def approve_trade(
    intent: TradeIntent,
    limits: RiskLimits,
    account: AccountState,
    rules: PairRules,
    whitelist: Set[str],
    fee: object,
    spread: object,
    slippage: object,
    state: "RiskState",
    now: object,
) -> TradeApproval:
    """BR-2…BR-7: alım önerisini onaylar ve miktarını belirler ya da reddeder."""

    def reject(reason: ApprovalReason, detail: str) -> TradeApproval:
        return TradeApproval(None, reason, False, f"{_show(intent.pair)}: {detail}", intent)

    problems = _input_problems(limits, account, rules, whitelist, fee, spread, slippage)
    problems += _state_problems(state, now, account.equity)
    if problems:
        return reject(ApprovalReason.INVALID_INPUT, "geçersiz girdi: " + "; ".join(problems))
    equity = cast(Decimal, _number(account.equity))  # validated above, equal to the state's
    peak, day_start = cast(Decimal, state.peak_equity), cast(Decimal, state.day_start_equity)
    if state.halted or _reached(peak, equity, limits.max_drawdown):
        return reject(
            ApprovalReason.DRAWDOWN_HALT,
            f"drawdown durdurması: zirve {peak}, kasa {equity}, limit {limits.max_drawdown}",
        )
    if _reached(day_start, equity, limits.daily_loss_limit):
        return reject(
            ApprovalReason.DAILY_LOSS_LIMIT,
            f"günlük zarar limiti: gün başı {day_start}, kasa {equity},"
            f" limit {limits.daily_loss_limit}",
        )
    if intent.side != BUY:
        return reject(ApprovalReason.NOT_BUY, f"yön {_show(intent.side)}: yalnızca alım onaylanır")
    if intent.pair not in whitelist:
        return reject(ApprovalReason.NOT_WHITELISTED, "beyaz listede değil")
    entry = _number(intent.entry)
    if entry is None or entry <= 0:
        return reject(
            ApprovalReason.INVALID_ENTRY, f"giriş {_show(intent.entry)} sıfırdan büyük olmalı"
        )
    if not _in_scale(entry):
        return reject(ApprovalReason.INVALID_ENTRY, _out_of_scale("giriş", entry))
    if intent.stop is None:
        return reject(ApprovalReason.INVALID_STOP, "stop-loss yok")
    stop = _number(intent.stop)
    if stop is None or stop <= 0 or stop >= entry:
        return reject(
            ApprovalReason.INVALID_STOP,
            f"stop {_show(intent.stop)} sıfırdan büyük ve girişten ({entry}) küçük olmalı",
        )
    if not _in_scale(stop):
        return reject(ApprovalReason.INVALID_STOP, _out_of_scale("stop", stop))
    if intent.target is None:
        return reject(ApprovalReason.INVALID_TARGET, "hedef fiyat yok")
    target = _number(intent.target)
    if target is None or target <= entry:
        return reject(
            ApprovalReason.INVALID_TARGET,
            f"hedef {_show(intent.target)} girişten ({entry}) büyük bir sayı olmalı",
        )
    if not _in_scale(target):
        return reject(ApprovalReason.INVALID_TARGET, _out_of_scale("hedef", target))
    costs = cast(
        tuple[Decimal, Decimal, Decimal], tuple(_number(v) for v in (fee, spread, slippage))
    )
    profit, cost, clears = _edge(entry, target, *costs, limits.profit_cost_multiple)
    if not clears:
        return reject(
            ApprovalReason.INSUFFICIENT_EDGE,
            f"yetersiz kâr beklentisi: beklenen kâr {profit}, efektif maliyet {cost},"
            f" kat {Decimal(limits.profit_cost_multiple)}",
        )
    positions = cast(int, account.open_positions)  # validated above
    if positions >= limits.max_open_positions:
        return reject(
            ApprovalReason.POSITION_LIMIT,
            f"açık pozisyon {_show(positions)}, limit {limits.max_open_positions}",
        )
    return _size(intent, entry, stop, target, costs, limits, account, rules)


def _edge(
    entry: Decimal,
    target: Decimal,
    rate: Decimal,
    spread: Decimal,
    slippage: Decimal,
    multiple: Decimal,
) -> tuple[Decimal, Decimal, bool]:
    """Spec 0005 R-3: birim başına kâr ve efektif maliyet; kâr kat çarpı maliyeti geçiyor mu."""
    with localcontext() as exact:
        exact.prec = MAX_PREC
        # every operand is inside the default exponent range (R-7): exact, bounded, no Overflow
        exact.Emax, exact.Emin = MAX_EMAX, MIN_EMIN
        exact.traps[Inexact] = True
        profit = target - entry
        both_legs = entry + target
        cost = both_legs * rate + entry * spread + both_legs * slippage
        return profit, cost, profit > multiple * cost


def _size(
    intent: TradeIntent,
    entry: Decimal,
    stop: Decimal,
    target: Decimal,
    costs: tuple[Decimal, Decimal, Decimal],
    limits: RiskLimits,
    account: AccountState,
    rules: PairRules,
) -> TradeApproval:
    """R-5, R-6: risk bütçesine ve serbest bakiyeye sığan, adıma aşağı yuvarlı en büyük miktar."""
    rate, spread, slippage = costs
    pair = intent.pair
    equity, free, step, min_amount, min_notional = (
        cast(Decimal, _number(value))  # validated by _input_problems
        for value in (
            account.equity,
            account.free_balance,
            rules.amount_step,
            rules.min_amount,
            rules.min_notional,
        )
    )
    # exact arithmetic: a rounded comparison could approve one step more than the budget allows
    try:
        with localcontext() as exact:
            exact.prec = MAX_PREC
            exact.traps[Inexact] = True
            budget = equity * limits.per_trade_risk
            unit_loss = (entry - stop) + entry * rate + stop * rate
            unit_cost = entry * (1 + rate)
            # integer division is never rounded here: the quotient is the largest fitting step count
            by_risk = budget // (step * unit_loss)
            by_balance = free // (step * unit_cost)
            limited_by_balance = by_balance < by_risk
            amount = min(by_risk, by_balance) * step
            notional = amount * entry
    except DecimalException:  # a value past the context's exponent range: no exact answer exists
        return TradeApproval(
            None,
            ApprovalReason.INVALID_INPUT,
            False,
            f"{_show(pair)}: geçersiz girdi: ölçek hesaplanamıyor (giriş {entry}, stop {stop},"
            f" hedef {target}, ücret {rate}, spread {spread}, slippage {slippage},"
            f" serbest bakiye {free}, adım {step}, kasa {equity})",
            intent,
        )
    if amount <= 0 or amount < min_amount or notional < min_notional:
        return TradeApproval(
            None,
            ApprovalReason.BELOW_MINIMUM,
            False,
            f"{_show(pair)}: miktar {amount} (tutar {notional}) borsa asgarisinin altında"
            f" (asgari miktar {min_amount}, asgari tutar {min_notional})",
            intent,
        )
    note = " (serbest bakiyeyle sınırlı)" if limited_by_balance else ""
    return TradeApproval(
        amount, None, limited_by_balance, f"{_show(pair)}: {amount} onaylandı{note}", intent
    )
