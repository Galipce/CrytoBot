"""Kapanış onayından paper piyasa satışı: kimlik, tekrar koruması, borsa kuralları, dolum
(spec 0009)."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, DecimalException, localcontext
from types import MappingProxyType

from crytobot.execution._numbers import (
    BOUNDED,
    DIGITS,
    SCALE,
    _brief,
    _in_scale,
    _number,
    _show,
    _significant,
)
from crytobot.execution._orders import (
    PAPER,
    CloseOrder,
    ExecutionState,
    Notification,
    NotificationKind,
    OrderOutcome,
    _notify,
)
from crytobot.execution._paper import OrderStatus, PaperExchange
from crytobot.risk import CloseApproval, CloseRequest, PairRules, close_request_problems

CLOSE_ID_PREFIX = "cx-"
SELL = "sell"


@dataclass(frozen=True)
class CloseOrderRequest:
    """Ham kapanış emri isteği (R-3): kapanış onayı, çiftin borsa kuralları, güncel fiyat, komisyon
    ve slippage oranı, mod. Alanlar doğrulanmadan gelir."""

    approval: object
    rules: object
    price: object
    fee: object
    slippage: object
    mode: object


@dataclass(frozen=True)
class CloseOrderResult:
    """İstek sonrası durum; emir oluşmadıysa durum istekten öncekiyle aynıdır (R-15). Sonuç
    `OrderOutcome`'dur; kapanış güvenli modda reddedilmediği için `STATUS_UNKNOWN` dönmez (R-11)."""

    state: ExecutionState
    outcome: OrderOutcome
    order: CloseOrder | None
    message: str
    notifications: tuple[Notification, ...] = ()

    @property
    def created(self) -> bool:
        return self.outcome is OrderOutcome.CREATED


def _aware(now: object) -> bool:
    """Zaman dilimi taşıyan zaman; `utcoffset`'i fırlatan ya da aralık dışı olan taşımaz (A-4)."""
    if not isinstance(now, datetime):
        return False
    try:
        return now.utcoffset() is not None
    except Exception:  # a tzinfo may raise anything: it names no time zone
        return False


def _own_problems(
    request: CloseOrderRequest, now: object, numbers: dict[str, Decimal]
) -> list[str]:
    """R-13: emrin kendi girdileri (kurallar, fiyat, oranlar, zaman); geçerlileri `numbers`'a."""
    problems: list[str] = []

    def number(label: str, value: object, rule: str) -> None:
        checked = _number(value)
        if checked is None or not _rule(checked, rule):
            problems.append(f"{label} {_show(value)} {_RULES[rule]}")
        elif not _in_scale(checked):
            problems.append(
                f"{label} {_brief(checked)} ölçeği varsayılan üs aralığı (±{SCALE}) dışında"
            )
        else:
            numbers[label] = checked

    rules = request.rules
    if not isinstance(rules, PairRules):
        problems.append(f"borsa kuralları {_show(rules)} çift kuralları olmalı")
    else:
        number("miktar adımı", rules.amount_step, "positive")
        number("asgari miktar", rules.min_amount, "minimum")
        number("asgari tutar", rules.min_notional, "minimum")
    number("fiyat", request.price, "positive")
    if "fiyat" in numbers and _significant(numbers["fiyat"]) > DIGITS:
        problems.append(f"fiyat {_brief(numbers.pop('fiyat'))} {DIGITS} anlamlı basamaktan uzun")
    number("ücret", request.fee, "rate")
    number("slippage", request.slippage, "rate")
    if not _aware(now):
        problems.append(f"şu anki zaman {_show(now)} zaman dilimi taşımalı")
    return problems


_RULES = {
    "positive": "sıfırdan büyük bir sayı olmalı",
    "minimum": "negatif olmayan bir sayı olmalı",
    "rate": "0 ile 1 arasında (1 hariç) olmalı",
}


def _rule(number: Decimal, rule: str) -> bool:
    if rule == "positive":
        return number > 0
    if rule == "minimum":
        return number >= 0
    return 0 <= number < 1


def place_close_order(
    state: ExecutionState, request: CloseOrderRequest, exchange: PaperExchange, now: object
) -> CloseOrderResult:
    """BR-9: kapanış onayından paper piyasa satışı oluşturur ya da isteği adlandırarak reddeder.
    Ret sırası (R-12, plan 0009 A-1): emrin kendi girdileri ve dolum ölçeği → mod → onaysız kapanış
    → talebin girdileri ve miktara bağlı ölçek → zaten var / kimlik çakışması → borsa kuralı.
    Güvenli mod kapanışı durdurmaz (R-11)."""
    approval = request.approval
    held = approval.request if isinstance(approval, CloseApproval) else None
    close = held if isinstance(held, CloseRequest) else None  # no request: unapproved (R-13)
    pair = close.pair if close is not None else None

    def reject(outcome: OrderOutcome, detail: str) -> CloseOrderResult:
        return CloseOrderResult(state, outcome, None, f"{_show(pair)}: {detail}")

    numbers: dict[str, Decimal] = {}
    problems = _own_problems(request, now, numbers)
    if problems:
        return reject(OrderOutcome.INVALID_INPUT, "geçersiz girdi: " + "; ".join(problems))
    assert isinstance(now, datetime)  # checked above
    price = numbers["fiyat"]
    try:  # the fill depends on the order's own inputs only: invalid input before the mode (A-1)
        with localcontext(BOUNDED):
            fill = price * (1 - numbers["slippage"])
    except DecimalException:
        return reject(
            OrderOutcome.INVALID_INPUT,
            f"geçersiz girdi: ölçek hesaplanamıyor (fiyat {_brief(price)}, slippage"
            f" {_brief(numbers['slippage'])})",
        )
    if not (type(request.mode) is str and request.mode == PAPER):  # plain str (plan A-4)
        return reject(
            OrderOutcome.UNSUPPORTED_MODE,
            f"mod {_show(request.mode)} desteklenmiyor: yalnızca paper",
        )
    if not isinstance(approval, CloseApproval) or approval.reason is not None or close is None:
        return reject(OrderOutcome.UNAPPROVED, "onaysız kapanış: kapanış onayı yok ya da ret")
    request_problems = close_request_problems(close)  # a hand-built approval is checked again
    if request_problems:
        return reject(OrderOutcome.INVALID_INPUT, "geçersiz girdi: " + "; ".join(request_problems))
    position_id, amount, reason = str(close.position_id), _number(close.amount), str(close.reason)
    pair = str(close.pair)
    assert amount is not None  # checked by the request rules
    step = numbers["miktar adımı"]
    try:  # the exact result does not fit in 28 digits: refused, never rounded (plan 0009 Risk 5)
        with localcontext(BOUNDED):
            notional = amount * fill
            fee = notional * numbers["ücret"]
            off_step = amount % step != 0
    except DecimalException:
        return reject(
            OrderOutcome.INVALID_INPUT,
            f"geçersiz girdi: ölçek hesaplanamıyor (miktar {_brief(amount)}, dolum fiyatı"
            f" {fill}, ücret {_brief(numbers['ücret'])}, adım {_brief(step)})",
        )
    client_order_id = CLOSE_ID_PREFIX + position_id.removeprefix("cb-")  # deterministic (R-8)
    existing = state.orders.get(client_order_id)
    if existing is not None:
        assert isinstance(existing, CloseOrder)  # a "cx-" id is a close's
        content = (existing.position_id, existing.pair, existing.amount, existing.reason)
        if content == (position_id, pair, amount, reason):
            return CloseOrderResult(
                state,
                OrderOutcome.ALREADY_EXISTS,
                existing,
                f"{_show(pair)}: {client_order_id} zaten var ({existing.status.value})",
            )
        return reject(
            OrderOutcome.ID_CONFLICT,
            f"kimlik çakışması: {client_order_id} başka bir içerikle oluşturulmuş",
        )
    if off_step:
        return reject(
            OrderOutcome.EXCHANGE_RULE,
            f"borsa kuralı: {position_id} kapanışı: miktar {_brief(amount)} miktar adımının"
            f" ({_brief(step)}) katı değil",
        )
    if amount < numbers["asgari miktar"]:
        return reject(
            OrderOutcome.EXCHANGE_RULE,
            f"borsa kuralı: {position_id} kapanışı: miktar {_brief(amount)} asgari miktarın"
            f" ({_brief(numbers['asgari miktar'])}) altında",
        )
    if notional < numbers["asgari tutar"]:
        return reject(
            OrderOutcome.EXCHANGE_RULE,
            f"borsa kuralı: {position_id} kapanışı: tutar {notional} (miktar {_brief(amount)} *"
            f" dolum fiyatı {fill}) asgari tutarın ({_brief(numbers['asgari tutar'])}) altında",
        )
    status = exchange.place(client_order_id)
    filled = status is OrderStatus.FILLED
    order = CloseOrder(
        client_order_id,
        position_id,
        pair,
        SELL,
        amount,
        reason,
        status,
        fill if filled else None,
        fee if filled else None,
        now,
    )
    orders = {**state.orders, client_order_id: order}
    quotes = dict(state.quotes)
    notifications: tuple[Notification, ...] = ()
    if status is OrderStatus.UNKNOWN:  # an unknown close stops new buys too (R-11, BR-11)
        quotes[client_order_id] = (fill, fee)
        if not state.unknown:  # once per transition (spec 0006 R-10)
            notifications = (
                _notify(NotificationKind.SAFE_MODE_ENTERED, order, now, "güvenli moda geçildi"),
            )
    return CloseOrderResult(
        ExecutionState(MappingProxyType(orders), MappingProxyType(quotes)),
        OrderOutcome.CREATED,
        order,
        f"{_show(pair)}: {client_order_id} {status.value}: {position_id} satışı, miktar"
        f" {_brief(amount)}" + (f", dolum fiyatı {fill}" if filled else ""),
        notifications,
    )
