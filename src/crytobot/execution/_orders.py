"""Onaylı öneriden paper emir: doğrulama, tekrar koruması, borsa kuralları, dolum (spec 0006)."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, DecimalException, localcontext
from enum import Enum
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
from crytobot.execution._paper import OrderStatus, PaperExchange
from crytobot.risk import PairRules, TradeApproval, TradeIntent

PAPER = "paper"
CLIENT_ID_PREFIX = "cb-"
# ASCII only: exchanges accept at most 36 of [A-Za-z0-9_-] in a client order id (R-6)
_INTENT_ID = re.compile(r"[A-Za-z0-9_-]{1,32}")


@dataclass(frozen=True)
class OrderRequest:
    """Ham emir isteği (R-1): öneri kimliği, öneri, o öneriye verilen risk onayı, çiftin borsa
    kuralları, güncel fiyat, komisyon ve slippage oranı, mod. Alanlar doğrulanmadan gelir."""

    intent_id: object
    intent: object
    approval: object
    rules: object
    price: object
    fee: object
    slippage: object
    mode: object


class OrderOutcome(Enum):
    """İsteğin sonucu; birden fazla sorun varsa ret nedenlerinden bu sıradaki ilki döner (R-11)."""

    CREATED = "created"
    ALREADY_EXISTS = "already_exists"
    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_MODE = "unsupported_mode"
    ID_CONFLICT = "id_conflict"
    STATUS_UNKNOWN = "status_unknown"
    UNAPPROVED = "unapproved"
    EXCHANGE_RULE = "exchange_rule"


@dataclass(frozen=True)
class Order:
    """Emir kaydı (R-8); dolum fiyatı ve komisyon yalnızca `FILLED` iken dolu."""

    client_order_id: str
    intent_id: str
    pair: str
    side: str
    entry: Decimal
    stop: Decimal
    target: Decimal
    amount: Decimal
    status: OrderStatus
    fill_price: Decimal | None
    fee: Decimal | None
    created_at: datetime


@dataclass(frozen=True)
class ExecutionState:
    """Emirler `clientOrderId`'ye göre, oluşturulma sırasıyla; değer değişmez (R-13). `quotes`,
    durumu bilinmeyen emrin dolarsa alacağı dolum fiyatı ve komisyondur (plan 0006 Risk 5)."""

    orders: Mapping[str, Order]
    quotes: Mapping[str, tuple[Decimal, Decimal]]

    @property
    def unknown(self) -> tuple[str, ...]:
        """Durumu bilinmeyen emirler; biri bile varsa güvenli mod (R-9)."""
        return tuple(i for i, order in self.orders.items() if order.status is OrderStatus.UNKNOWN)


EMPTY_EXECUTION = ExecutionState(MappingProxyType({}), MappingProxyType({}))


class NotificationKind(Enum):
    SAFE_MODE_ENTERED = "safe_mode_entered"
    SAFE_MODE_EXITED = "safe_mode_exited"


@dataclass(frozen=True)
class Notification:
    """Güvenli mod geçişi (R-10); gönderimi `reporting`'in işidir."""

    kind: NotificationKind
    client_order_id: str
    pair: str
    at: datetime
    message: str


@dataclass(frozen=True)
class OrderResult:
    """İstek sonrası durum; emir oluşmadıysa durum istekten öncekiyle aynıdır."""

    state: ExecutionState
    outcome: OrderOutcome
    order: Order | None
    message: str
    notifications: tuple[Notification, ...] = ()

    @property
    def created(self) -> bool:
        return self.outcome is OrderOutcome.CREATED


class QueryOutcome(Enum):
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    UNKNOWN_ORDER = "unknown_order"
    INVALID_INPUT = "invalid_input"


@dataclass(frozen=True)
class QueryResult:
    """Sorgu sonrası durum; yalnızca `UPDATED` durumu değiştirir."""

    state: ExecutionState
    outcome: QueryOutcome
    order: Order | None
    message: str
    notifications: tuple[Notification, ...] = ()


@dataclass(frozen=True)
class _Checked:
    intent_id: str
    pair: str
    side: str
    entry: Decimal
    stop: Decimal
    target: Decimal
    amount: Decimal | None  # None: the approval carries no positive amount (R-2)
    step: Decimal
    min_amount: Decimal
    min_notional: Decimal
    price: Decimal
    fee: Decimal
    slippage: Decimal


def _out_of_scale(label: str, number: Decimal) -> str:
    return f"{label} {_brief(number)} ölçeği varsayılan üs aralığı (±{SCALE}) dışında"


def _too_long(label: str, number: Decimal) -> str:
    return f"{label} {_brief(number)} {DIGITS} anlamlı basamaktan uzun"


def _check(request: OrderRequest, now: object) -> _Checked | list[str]:
    """R-6, R-12: her girdiyi doğrular; sorun varsa hepsini adlandırır."""
    problems: list[str] = []
    numbers: dict[str, Decimal] = {}

    def positive(label: str, value: object) -> None:
        number = _number(value)
        if number is None or number <= 0:
            problems.append(f"{label} {_show(value)} sıfırdan büyük bir sayı olmalı")
        elif not _in_scale(number):
            problems.append(_out_of_scale(label, number))
        else:
            numbers[label] = number

    def rate(label: str, value: object) -> None:
        number = _number(value)
        if number is None or not 0 <= number < 1:
            problems.append(f"{label} {_show(value)} 0 ile 1 arasında (1 hariç) olmalı")
        elif not _in_scale(number):
            problems.append(_out_of_scale(label, number))
        else:
            numbers[label] = number

    def minimum(label: str, value: object) -> None:
        number = _number(value)
        if number is None or number < 0:
            problems.append(f"{label} {_show(value)} negatif olmayan bir sayı olmalı")
        elif not _in_scale(number):
            problems.append(_out_of_scale(label, number))
        else:
            numbers[label] = number

    intent_id = request.intent_id
    if not (isinstance(intent_id, str) and _INTENT_ID.fullmatch(intent_id)):
        problems.append(
            f"öneri kimliği {_show(intent_id)} 1-32 karakter olmalı ve yalnızca harf, rakam, - ve _"
            " içermeli"
        )
    intent = request.intent
    if not isinstance(intent, TradeIntent):
        problems.append(f"öneri {_show(intent)} bir işlem önerisi olmalı")
    else:
        if not (isinstance(intent.pair, str) and isinstance(intent.side, str)):
            problems.append(f"çift {_show(intent.pair)} ve yön {_show(intent.side)} metin olmalı")
        for label, value in (
            ("giriş", intent.entry),
            ("stop", intent.stop),
            ("hedef", intent.target),
        ):
            positive(label, value)
    approval = request.approval
    amount = _number(approval.amount) if isinstance(approval, TradeApproval) else None
    if amount is not None and amount > 0:  # a missing or non-positive amount is unapproved (R-2)
        if not _in_scale(amount):
            problems.append(_out_of_scale("miktar", amount))
        elif _significant(amount) > DIGITS:
            problems.append(_too_long("miktar", amount))
    else:
        amount = None
    rules = request.rules
    if not isinstance(rules, PairRules):
        problems.append(f"borsa kuralları {_show(rules)} çift kuralları olmalı")
    else:
        positive("miktar adımı", rules.amount_step)
        minimum("asgari miktar", rules.min_amount)
        minimum("asgari tutar", rules.min_notional)
    positive("fiyat", request.price)
    if "fiyat" in numbers and _significant(numbers["fiyat"]) > DIGITS:
        problems.append(_too_long("fiyat", numbers.pop("fiyat")))
    rate("ücret", request.fee)
    rate("slippage", request.slippage)
    if not isinstance(now, datetime) or now.utcoffset() is None:
        problems.append(f"şu anki zaman {_show(now)} zaman dilimi taşımalı")
    if problems:
        return problems
    assert isinstance(intent, TradeIntent) and isinstance(intent_id, str)  # checked above
    return _Checked(
        intent_id,
        str(intent.pair),
        str(intent.side),
        numbers["giriş"],
        numbers["stop"],
        numbers["hedef"],
        amount,
        numbers["miktar adımı"],
        numbers["asgari miktar"],
        numbers["asgari tutar"],
        numbers["fiyat"],
        numbers["ücret"],
        numbers["slippage"],
    )


def _content(order: Order | _Checked) -> tuple[object, ...]:
    """R-7: tekrar korumasında karşılaştırılan içerik; fiyat, oranlar, mod ve zaman değildir."""
    return (order.pair, order.side, order.entry, order.stop, order.target, order.amount)


def _judged_differently(judged: object, checked: _Checked) -> bool:
    """R-2: onayın taşıdığı öneri, istekteki öneriyle birebir aynı değil."""
    if not isinstance(judged, TradeIntent):
        return True
    if not (isinstance(judged.pair, str) and isinstance(judged.side, str)):
        return True
    numbers = (_number(judged.entry), _number(judged.stop), _number(judged.target))
    return (judged.pair, judged.side, *numbers) != (
        checked.pair,
        checked.side,
        checked.entry,
        checked.stop,
        checked.target,
    )


def place_order(
    state: ExecutionState, request: OrderRequest, exchange: PaperExchange, now: object
) -> OrderResult:
    """BR-9: onaylı öneriden paper piyasa alımı oluşturur ya da isteği adlandırarak reddeder."""
    intent = request.intent
    pair = intent.pair if isinstance(intent, TradeIntent) else None

    def reject(outcome: OrderOutcome, detail: str) -> OrderResult:
        return OrderResult(state, outcome, None, f"{_show(pair)}: {detail}")

    checked = _check(request, now)
    if isinstance(checked, list):
        return reject(OrderOutcome.INVALID_INPUT, "geçersiz girdi: " + "; ".join(checked))
    assert isinstance(now, datetime)  # checked above
    amount = checked.amount
    try:  # before every other check: an incalculable input is invalid input first (R-11)
        with localcontext(BOUNDED):
            size = Decimal(0) if amount is None else amount  # no amount: refused as unapproved
            fill = checked.price * (1 + checked.slippage)
            notional = size * fill
            fee = notional * checked.fee
            off_step = size % checked.step != 0
    except DecimalException:  # the exact result does not fit in 28 digits (plan 0006 Risk 3)
        return reject(
            OrderOutcome.INVALID_INPUT,
            "geçersiz girdi: ölçek hesaplanamıyor (miktar"
            f" {'yok' if amount is None else _brief(amount)}, fiyat {_brief(checked.price)},"
            f" slippage {_brief(checked.slippage)}, ücret {_brief(checked.fee)},"
            f" adım {_brief(checked.step)})",
        )
    if not (isinstance(request.mode, str) and request.mode == PAPER):
        return reject(
            OrderOutcome.UNSUPPORTED_MODE,
            f"mod {_show(request.mode)} desteklenmiyor: yalnızca paper",
        )
    client_order_id = CLIENT_ID_PREFIX + checked.intent_id
    existing = state.orders.get(client_order_id)
    if existing is not None:
        if _content(existing) == _content(checked):
            return OrderResult(
                state,
                OrderOutcome.ALREADY_EXISTS,
                existing,
                f"{_show(pair)}: {client_order_id} zaten var ({existing.status.value})",
            )
        return reject(
            OrderOutcome.ID_CONFLICT,
            f"kimlik çakışması: {client_order_id} başka bir içerikle oluşturulmuş",
        )
    if state.unknown:
        return reject(
            OrderOutcome.STATUS_UNKNOWN,
            "durum belirsiz: durumu bilinmeyen emir var (" + ", ".join(state.unknown) + ");"
            " yeni emir oluşturulmaz",
        )
    approval = request.approval
    if not isinstance(approval, TradeApproval) or approval.reason is not None:
        return reject(OrderOutcome.UNAPPROVED, "onaysız öneri: risk onayı yok ya da ret")
    if amount is None:
        return reject(
            OrderOutcome.UNAPPROVED,
            f"onaysız öneri: onaylı miktar {_show(approval.amount)} sıfırdan büyük bir sayı değil",
        )
    if _judged_differently(approval.intent, checked):
        return reject(OrderOutcome.UNAPPROVED, "onaysız öneri: onay başka bir öneri için verilmiş")
    if off_step:
        return reject(
            OrderOutcome.EXCHANGE_RULE,
            f"borsa kuralı: miktar {_brief(amount)} miktar adımının ({_brief(checked.step)}) katı"
            " değil",
        )
    if amount < checked.min_amount:
        return reject(
            OrderOutcome.EXCHANGE_RULE,
            f"borsa kuralı: miktar {_brief(amount)} asgari miktarın ({_brief(checked.min_amount)})"
            " altında",
        )
    if notional < checked.min_notional:
        return reject(
            OrderOutcome.EXCHANGE_RULE,
            f"borsa kuralı: tutar {notional} (miktar {_brief(amount)} * dolum fiyatı {fill}) asgari"
            f" tutarın ({_brief(checked.min_notional)}) altında",
        )
    status = exchange.place(client_order_id)
    filled = status is OrderStatus.FILLED
    order = Order(
        client_order_id,
        checked.intent_id,
        checked.pair,
        checked.side,
        checked.entry,
        checked.stop,
        checked.target,
        amount,
        status,
        fill if filled else None,
        fee if filled else None,
        now,
    )
    orders = dict(state.orders)
    orders[client_order_id] = order
    quotes = dict(state.quotes)
    notifications: tuple[Notification, ...] = ()
    if status is OrderStatus.UNKNOWN:
        quotes[client_order_id] = (fill, fee)
        notifications = (
            _notify(NotificationKind.SAFE_MODE_ENTERED, order, now, "güvenli moda geçildi"),
        )
    return OrderResult(
        ExecutionState(MappingProxyType(orders), MappingProxyType(quotes)),
        OrderOutcome.CREATED,
        order,
        f"{_show(pair)}: {client_order_id} {status.value}: miktar {_brief(amount)}"
        + (f", dolum fiyatı {fill}" if filled else ""),
        notifications,
    )


def _notify(kind: NotificationKind, order: Order, now: datetime, what: str) -> Notification:
    return Notification(
        kind,
        order.client_order_id,
        order.pair,
        now,
        f"{order.pair}: {what}: {order.client_order_id} durumu {order.status.value}",
    )


def query_order(
    state: ExecutionState, client_order_id: object, exchange: PaperExchange, now: object
) -> QueryResult:
    """R-9: durumu bilinmeyen emrin durumunu simülatörden sorar; son bilinmeyen emir netleşince
    güvenli mod biter ve bir çıkış bildirimi üretilir."""
    if not isinstance(now, datetime) or now.utcoffset() is None:
        return QueryResult(
            state,
            QueryOutcome.INVALID_INPUT,
            None,
            f"geçersiz girdi: şu anki zaman {_show(now)} zaman dilimi taşımalı",
        )
    order = state.orders.get(client_order_id) if isinstance(client_order_id, str) else None
    if order is None:
        return QueryResult(
            state, QueryOutcome.UNKNOWN_ORDER, None, f"bilinmeyen emir: {_show(client_order_id)}"
        )
    if order.status is not OrderStatus.UNKNOWN:
        return QueryResult(
            state,
            QueryOutcome.UNCHANGED,
            order,
            f"{order.pair}: {order.client_order_id} zaten {order.status.value}",
        )
    status = exchange.query(order.client_order_id)
    if status is OrderStatus.UNKNOWN:
        return QueryResult(
            state,
            QueryOutcome.UNCHANGED,
            order,
            f"{order.pair}: {order.client_order_id} durumu hâlâ bilinmiyor",
        )
    fill, fee = state.quotes[order.client_order_id]
    filled = status is OrderStatus.FILLED
    resolved = replace(
        order, status=status, fill_price=fill if filled else None, fee=fee if filled else None
    )
    orders = dict(state.orders)
    orders[order.client_order_id] = resolved
    quotes = dict(state.quotes)
    del quotes[order.client_order_id]
    after = ExecutionState(MappingProxyType(orders), MappingProxyType(quotes))
    notifications: tuple[Notification, ...] = ()
    if not after.unknown:
        notifications = (
            _notify(NotificationKind.SAFE_MODE_EXITED, resolved, now, "güvenli moddan çıkıldı"),
        )
    return QueryResult(
        after,
        QueryOutcome.UPDATED,
        resolved,
        f"{order.pair}: {order.client_order_id} durumu {status.value}",
        notifications,
    )
