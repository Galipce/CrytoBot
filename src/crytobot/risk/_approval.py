"""İşlem önerisi onayı: zorunlu stop, risk temelli boyutlama, pozisyon sayısı (spec 0003)."""

from collections.abc import Set
from dataclasses import dataclass
from decimal import MAX_PREC, Decimal, DecimalException, Inexact, localcontext
from enum import Enum
from typing import cast

from crytobot.risk._limits import RiskLimits, _limit_problems

BUY = "buy"


@dataclass(frozen=True)
class TradeIntent:
    """Ham alım önerisi: çift, yön, giriş, stop (`None` = stop yok); fiyatlar `Decimal`/`int`."""

    pair: str
    side: str
    entry: object
    stop: object


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
    NOT_BUY = "not_buy"
    NOT_WHITELISTED = "not_whitelisted"
    INVALID_ENTRY = "invalid_entry"
    INVALID_STOP = "invalid_stop"
    POSITION_LIMIT = "position_limit"
    BELOW_MINIMUM = "below_minimum"


@dataclass(frozen=True)
class TradeApproval:
    """Onayda `amount` dolu ve `reason` `None`; retde tersi (R-1)."""

    amount: Decimal | None
    reason: ApprovalReason | None
    limited_by_balance: bool
    message: str

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
        exact.traps[Inexact] = True
        return reference - equity >= limit * reference


def _input_problems(
    limits: RiskLimits, account: AccountState, rules: PairRules, whitelist: object, fee: object
) -> list[str]:
    problems = _limit_problems(limits)
    if not isinstance(whitelist, Set):  # a str would match pairs by substring (BR-2)
        problems.append(f"beyaz liste {whitelist!r} bir çift kümesi olmalı")
    equity = _number(account.equity)
    if equity is None or equity <= 0:
        problems.append(f"kasa {account.equity!r} sıfırdan büyük bir sayı olmalı")
    free = _number(account.free_balance)
    if free is None or free < 0:
        problems.append(f"serbest bakiye {account.free_balance!r} negatif olmayan bir sayı olmalı")
    elif equity is not None and free > equity:
        problems.append(f"serbest bakiye {free} kasadan ({equity}) büyük")
    positions = account.open_positions
    if isinstance(positions, bool) or not isinstance(positions, int) or positions < 0:
        problems.append(f"açık pozisyon {positions!r} negatif olmayan bir tam sayı olmalı")
    rate = _number(fee)
    if rate is None or not 0 <= rate < 1:
        problems.append(f"ücret {fee!r} 0 ile 1 arasında (1 hariç) olmalı")
    step = _number(rules.amount_step)
    if step is None or step <= 0:
        problems.append(f"miktar adımı {rules.amount_step!r} sıfırdan büyük olmalı")
    for label, value in (("asgari miktar", rules.min_amount), ("asgari tutar", rules.min_notional)):
        number = _number(value)
        if number is None or number < 0:
            problems.append(f"{label} {value!r} negatif olmayan bir sayı olmalı")
    return problems


def approve_trade(
    intent: TradeIntent,
    limits: RiskLimits,
    account: AccountState,
    rules: PairRules,
    whitelist: Set[str],
    fee: object,
) -> TradeApproval:
    """BR-2, BR-3, BR-4, BR-7: alım önerisini onaylar ve miktarını belirler ya da reddeder."""

    def reject(reason: ApprovalReason, detail: str) -> TradeApproval:
        return TradeApproval(None, reason, False, f"{intent.pair!r}: {detail}")

    problems = _input_problems(limits, account, rules, whitelist, fee)
    if problems:
        return reject(ApprovalReason.INVALID_INPUT, "geçersiz girdi: " + "; ".join(problems))
    if intent.side != BUY:
        return reject(ApprovalReason.NOT_BUY, f"yön {intent.side!r}: yalnızca alım onaylanır")
    if intent.pair not in whitelist:
        return reject(ApprovalReason.NOT_WHITELISTED, "beyaz listede değil")
    entry = _number(intent.entry)
    if entry is None or entry <= 0:
        return reject(ApprovalReason.INVALID_ENTRY, f"giriş {intent.entry!r} sıfırdan büyük olmalı")
    if intent.stop is None:
        return reject(ApprovalReason.INVALID_STOP, "stop-loss yok")
    stop = _number(intent.stop)
    if stop is None or stop <= 0 or stop >= entry:
        return reject(
            ApprovalReason.INVALID_STOP,
            f"stop {intent.stop!r} sıfırdan büyük ve girişten ({entry}) küçük olmalı",
        )
    positions = cast(int, account.open_positions)  # validated above
    if positions >= limits.max_open_positions:
        return reject(
            ApprovalReason.POSITION_LIMIT,
            f"açık pozisyon {positions}, limit {limits.max_open_positions}",
        )
    return _size(intent.pair, entry, stop, limits, account, rules, fee)


def _size(
    pair: str,
    entry: Decimal,
    stop: Decimal,
    limits: RiskLimits,
    account: AccountState,
    rules: PairRules,
    fee: object,
) -> TradeApproval:
    """R-5, R-6: risk bütçesine ve serbest bakiyeye sığan, adıma aşağı yuvarlı en büyük miktar."""
    equity, free, rate, step, min_amount, min_notional = (
        cast(Decimal, _number(value))  # validated by _input_problems
        for value in (
            account.equity,
            account.free_balance,
            fee,
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
            f"{pair!r}: geçersiz girdi: ölçek hesaplanamıyor (adım {step}, kasa {equity})",
        )
    if amount <= 0 or amount < min_amount or notional < min_notional:
        return TradeApproval(
            None,
            ApprovalReason.BELOW_MINIMUM,
            False,
            f"{pair!r}: miktar {amount} (tutar {notional}) borsa asgarisinin altında"
            f" (asgari miktar {min_amount}, asgari tutar {min_notional})",
        )
    note = " (serbest bakiyeyle sınırlı)" if limited_by_balance else ""
    return TradeApproval(amount, None, limited_by_balance, f"{pair!r}: {amount} onaylandı{note}")
