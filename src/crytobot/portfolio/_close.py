"""Açık pozisyonun stop ya da hedefte kapanışı ve gerçekleşen kâr/zarar (spec 0008)."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, DecimalException, localcontext
from enum import Enum
from types import MappingProxyType

from crytobot.portfolio._ledger import (
    _CLIENT_ORDER_ID,
    CloseReason,
    Closure,
    Entry,
    EntryKind,
    Ledger,
    _amount,
    _time,
)
from crytobot.portfolio._numbers import BOUNDED, _brief, _show

_AT = {CloseReason.STOP: "stop'ta", CloseReason.TARGET: "hedefte"}


@dataclass(frozen=True)
class Close:
    """Ham kapanış kaydı isteği (R-3): dolan bir kapanış satışının bilgileri. Alanlar doğrulanmadan
    gelir."""

    client_order_id: object
    position_id: object
    amount: object
    price: object
    fee: object
    reason: object
    at: object


class CloseOutcome(Enum):
    """Kapanış isteğinin sonucu; birden fazla sorun varsa ret nedenlerinden bu sıradaki ilki döner
    (R-13)."""

    CLOSED = "closed"
    ALREADY_RECORDED = "already_recorded"
    INVALID_INPUT = "invalid_input"
    NOT_OPENED = "not_opened"
    RECORD_CONFLICT = "record_conflict"
    POSITION_NOT_FOUND = "position_not_found"
    POSITION_CLOSED = "position_closed"


@dataclass(frozen=True)
class CloseResult:
    """İstek sonrası defter; kapanış eklenmediyse defter istekten öncekiyle aynıdır (R-12)."""

    ledger: Ledger
    outcome: CloseOutcome
    closure: Closure | None
    message: str

    @property
    def accepted(self) -> bool:
        return self.outcome is CloseOutcome.CLOSED


@dataclass(frozen=True)
class _Checked:
    client_order_id: str
    position_id: str
    amount: Decimal
    price: Decimal
    fee: Decimal
    reason: CloseReason
    at: datetime
    proceeds: Decimal


def _id(label: str, value: object, problems: list[str]) -> str | None:
    if isinstance(value, str) and _CLIENT_ORDER_ID.fullmatch(value):
        return value
    problems.append(
        f"{label} {_show(value)} 1-36 karakter olmalı ve yalnızca harf, rakam, - ve _ içermeli"
    )
    return None


def _check(close: Close) -> _Checked | list[str]:
    """R-7, R-14: her girdiyi doğrular; sorun varsa hepsini adlandırır. Satış gelirinin ölçeği de
    bu adımdadır (R-13)."""
    problems: list[str] = []
    client_order_id = _id("kapanış clientOrderId", close.client_order_id, problems)
    position_id = _id("pozisyon clientOrderId", close.position_id, problems)
    amount = _amount("miktar", close.amount, problems)
    price = _amount("dolum fiyatı", close.price, problems)
    fee = _amount("komisyon", close.fee, problems, zero=True)
    reason = close.reason
    if not isinstance(reason, CloseReason):
        problems.append(f"neden {_show(reason)} stop ya da hedef olmalı")
    at = _time("dolum zamanı", close.at, problems)
    if problems:
        return problems
    assert client_order_id is not None and position_id is not None  # checked above
    assert amount is not None and price is not None and fee is not None and at is not None
    assert isinstance(reason, CloseReason)
    try:
        with localcontext(BOUNDED):
            sale = amount * price
            proceeds = sale - fee
    except DecimalException:  # the exact result does not fit in 28 digits (plan 0008 Risk 5)
        return [
            f"ölçek hesaplanamıyor (miktar {_brief(amount)}, dolum fiyatı {_brief(price)},"
            f" komisyon {_brief(fee)})"
        ]
    if proceeds < 0:  # the balance never goes negative (R-7)
        return [f"komisyon {_brief(fee)} satış tutarından ({_brief(sale)}) büyük"]
    return _Checked(client_order_id, position_id, amount, price, fee, reason, at, proceeds)


def _content(closure: Closure) -> tuple[object, ...]:
    """R-9: tekrar korumasında karşılaştırılan içerik; dolum zamanı değildir."""
    return (
        closure.position.client_order_id,
        closure.amount,
        closure.price,
        closure.fee,
        closure.reason,
    )


def close_position(ledger: Ledger, close: Close) -> CloseResult:
    """R-3…R-10: dolan kapanış satışını kaydeder, geliri bakiyeye ekler, pozisyonu kapatır ve
    gerçekleşen kâr/zararı hesaplar ya da adlandırarak reddeder."""

    def reject(outcome: CloseOutcome, detail: str) -> CloseResult:
        return CloseResult(ledger, outcome, None, detail)

    checked = _check(close)
    if isinstance(checked, list):
        return reject(CloseOutcome.INVALID_INPUT, "geçersiz girdi: " + "; ".join(checked))
    balance = ledger.balance
    if balance is None:
        return reject(CloseOutcome.NOT_OPENED, "defter açılmamış: önce başlangıç yatırması")
    existing = ledger.closures.get(checked.client_order_id)
    if existing is not None:
        content = (
            checked.position_id,
            checked.amount,
            checked.price,
            checked.fee,
            checked.reason,
        )
        if _content(existing) == content:
            return CloseResult(
                ledger,
                CloseOutcome.ALREADY_RECORDED,
                existing,
                f"{existing.position.pair}: {existing.client_order_id} zaten kayıtlı",
            )
        return reject(
            CloseOutcome.RECORD_CONFLICT,
            f"kayıt çakışması: {checked.client_order_id} başka bir içerikle kayıtlı",
        )
    if ledger.bought(checked.client_order_id) is not None:  # one id space (R-9)
        return reject(
            CloseOutcome.RECORD_CONFLICT,
            f"kayıt çakışması: {checked.client_order_id} bir alımın kimliği",
        )
    position = ledger.positions.get(checked.position_id)
    if position is None:
        closer = next(
            (
                c.client_order_id
                for c in ledger.closures.values()
                if c.position.client_order_id == checked.position_id
            ),
            None,
        )
        if closer is None:
            return reject(
                CloseOutcome.POSITION_NOT_FOUND,
                f"pozisyon bulunamadı: {checked.position_id}",
            )
        return reject(
            CloseOutcome.POSITION_CLOSED,
            f"pozisyon kapalı: {checked.position_id} {closer} ile kapandı",
        )
    if checked.amount != position.amount:  # full close only (R-4)
        return reject(
            CloseOutcome.INVALID_INPUT,
            f"geçersiz girdi: miktar pozisyonla uyuşmuyor (kapanış {_brief(checked.amount)},"
            f" pozisyon {_brief(position.amount)})",
        )
    if checked.at < position.opened_at:  # R-8
        return reject(
            CloseOutcome.INVALID_INPUT,
            f"geçersiz girdi: dolum zamanı {checked.at.isoformat()} pozisyonun açılışından"
            f" ({position.opened_at.isoformat()}) önce",
        )
    try:  # after the record checks: a retry does not depend on the balance (R-13)
        with localcontext(BOUNDED):
            cost = position.amount * position.cost_price + position.fee
            realized = checked.proceeds - cost
            after = balance + checked.proceeds
            total = ledger.realized + realized
    except DecimalException:  # the exact result does not fit in 28 digits (plan 0008 Risk 5)
        return reject(
            CloseOutcome.INVALID_INPUT,
            f"geçersiz girdi: ölçek hesaplanamıyor (gelir {_brief(checked.proceeds)}, bakiye"
            f" {_brief(balance)}, gerçekleşen toplam {_brief(ledger.realized)})",
        )
    closure = Closure(
        checked.client_order_id,
        position,
        checked.amount,
        checked.price,
        checked.fee,
        checked.reason,
        checked.at,
        checked.proceeds,
        realized,
    )
    positions = {k: p for k, p in ledger.positions.items() if k != position.client_order_id}
    closures = {**ledger.closures, closure.client_order_id: closure}
    entry = Entry(EntryKind.CLOSE, checked.at, checked.proceeds, position, closure)
    return CloseResult(
        Ledger(
            (*ledger.entries, entry),
            after,
            MappingProxyType(positions),
            MappingProxyType(closures),
            total,
        ),
        CloseOutcome.CLOSED,
        closure,
        f"{position.pair}: {position.client_order_id} {_AT[checked.reason]} kapandı"
        f" ({closure.client_order_id}): gelir {_brief(checked.proceeds)} USDT, kâr/zarar"
        f" {_brief(realized)} USDT, bakiye {_brief(after)} USDT",
    )
