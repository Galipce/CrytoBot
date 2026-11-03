"""Bütün bir defterin doğrulanması (spec 0011 R-6): kayıtlardan türeyen bakiye, pozisyonlar,
kapanışlar ve gerçekleşen toplam, defterin taşıdıklarıyla birebir aynı olmalıdır.

`record_fill` ve `close_position` tekrar çalıştırılmaz: her çağrı kayıtları ve pozisyonları
kopyalar, 10.000 kayıtta O(n²) olur (spec 0011 R-11). Aynı işlemler aynı sırayla burada yapılır;
`tests/portfolio/test_replay.py` motorla aynı sonucu verdiğini kanıtlar. Mesajda ham girdi yoktur.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, DecimalException, localcontext

from crytobot.portfolio._ledger import (
    _CLIENT_ORDER_ID,
    CloseReason,
    Closure,
    Entry,
    EntryKind,
    Ledger,
    Position,
)
from crytobot.portfolio._numbers import BOUNDED, CALC_DIGITS, DIGITS, _in_scale, _significant


class _Broken(Exception):
    """Defter türetilemiyor; ilk sorunu taşır, modül dışına çıkmaz."""


def _number(value: object, *, zero: bool = False, digits: int = DIGITS) -> bool:
    """Defterin kabul edeceği sayı (spec 0007 R-11); `int` geçmez, defter hep `Decimal` üretir."""
    if not (isinstance(value, Decimal) and value.is_finite()):
        return False
    if value < 0 or (value == 0 and not zero):
        return False
    if not _in_scale(value):
        return False
    # the text holds every digit, and is much cheaper than `as_tuple` at 10.000 entries (R-11)
    return len(str(value)) <= digits or _significant(value) <= digits


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def _exact(left: object, right: object) -> bool:
    """Basamağına kadar aynı: `Decimal("1.10") == Decimal("1.1")` burada yetmez (spec 0011 R-3)."""
    return left is right or repr(left) == repr(right)


def _same_number(left: object, right: Decimal) -> bool:
    return isinstance(left, Decimal) and str(left) == str(right)


def _check_position(position: object) -> Position:
    if not isinstance(position, Position):
        raise _Broken("pozisyon kaydı yok")
    client_order_id = position.client_order_id
    if not (type(client_order_id) is str and _CLIENT_ORDER_ID.fullmatch(client_order_id)):
        raise _Broken("pozisyon kimliği geçersiz")
    if type(position.pair) is not str:
        raise _Broken("çift metin değil")
    numbers = (
        _number(position.amount),
        _number(position.cost_price, digits=CALC_DIGITS),
        _number(position.fee, zero=True, digits=CALC_DIGITS),
        _number(position.stop),
        _number(position.target),
    )
    if not all(numbers):
        raise _Broken("pozisyonun sayıları geçersiz")
    if not _aware(position.opened_at):
        raise _Broken("açılış zamanı zaman dilimi taşımalı")
    return position


def _check_closure(closure: object) -> Closure:
    if not isinstance(closure, Closure):
        raise _Broken("kapanış kaydı yok")
    client_order_id = closure.client_order_id
    if not (type(client_order_id) is str and _CLIENT_ORDER_ID.fullmatch(client_order_id)):
        raise _Broken("kapanış kimliği geçersiz")
    numbers = (
        _number(closure.amount),
        _number(closure.price, digits=CALC_DIGITS),
        _number(closure.fee, zero=True, digits=CALC_DIGITS),
    )
    if not all(numbers):
        raise _Broken("kapanışın sayıları geçersiz")
    if not isinstance(closure.reason, CloseReason):
        raise _Broken("kapanış nedeni geçersiz")
    if not _aware(closure.closed_at):
        raise _Broken("kapanış zamanı zaman dilimi taşımalı")
    return closure


@dataclass
class _Replay:
    """Türeyen durum; yalnız `_replay` içinde değişir."""

    balance: Decimal | None
    realized: Decimal
    opened_at: datetime | None
    positions: dict[str, Position]
    closures: dict[str, Closure]
    bought: set[str]


def _opening(state: _Replay, entry: Entry) -> None:
    if state.balance is not None:
        raise _Broken("ikinci açılış kaydı")
    if entry.position is not None or entry.closure is not None:
        raise _Broken("açılış kaydı pozisyon taşımaz")
    if not _number(entry.usdt):
        raise _Broken("başlangıç tutarı geçersiz")
    if not _aware(entry.at):
        raise _Broken("açılış zamanı zaman dilimi taşımalı")
    state.balance, state.opened_at = entry.usdt, entry.at


def _fill(state: _Replay, entry: Entry) -> None:
    balance, opened_at = state.balance, state.opened_at
    assert balance is not None and opened_at is not None  # the caller checked the opening
    if entry.closure is not None:
        raise _Broken("dolum kaydı kapanış taşımaz")
    position = _check_position(entry.position)
    client_order_id = position.client_order_id
    if client_order_id in state.bought or client_order_id in state.closures:
        raise _Broken(f"kimlik {client_order_id} iki kez kayıtlı")
    if not _exact(entry.at, position.opened_at):
        raise _Broken("kayıt zamanı dolum zamanı değil")
    if position.opened_at < opened_at:
        raise _Broken("dolum açılıştan önce")
    with localcontext(BOUNDED):
        cost = position.amount * position.cost_price + position.fee
    if not _same_number(entry.usdt, cost):
        raise _Broken(f"{client_order_id}: kayıt tutarı maliyet değil")
    if cost > balance:
        raise _Broken(f"{client_order_id}: bakiye negatife düşüyor")
    with localcontext(BOUNDED):
        state.balance = balance - cost
    state.bought.add(client_order_id)
    state.positions[client_order_id] = position


def _close(state: _Replay, entry: Entry) -> None:
    balance = state.balance
    assert balance is not None  # the caller checked the opening
    closure = _check_closure(entry.closure)
    position = entry.position
    if not (isinstance(position, Position) and type(position.client_order_id) is str):
        raise _Broken("pozisyon kaydı yok")
    client_order_id, position_id = closure.client_order_id, position.client_order_id
    if client_order_id in state.bought or client_order_id in state.closures:
        raise _Broken(f"kimlik {client_order_id} iki kez kayıtlı")
    open_position = state.positions.get(position_id)
    if open_position is None:
        raise _Broken(f"{client_order_id}: kapatılan pozisyon açık değil")
    # the open position passed _check_position at its fill: being the same is enough (R-11)
    if not (_exact(position, open_position) and _exact(closure.position, open_position)):
        raise _Broken(f"{client_order_id}: pozisyon alım kaydıyla aynı değil")
    if closure.amount != position.amount:
        raise _Broken(f"{client_order_id}: miktar pozisyonla uyuşmuyor")
    if not _exact(entry.at, closure.closed_at):
        raise _Broken("kayıt zamanı kapanış zamanı değil")
    if closure.closed_at < position.opened_at:
        raise _Broken(f"{client_order_id}: kapanış pozisyonun açılışından önce")
    with localcontext(BOUNDED):
        sale = closure.amount * closure.price
        proceeds = sale - closure.fee
        cost = position.amount * position.cost_price + position.fee
        realized = proceeds - cost
        after = balance + proceeds
        total = state.realized + realized
    if proceeds < 0:
        raise _Broken(f"{client_order_id}: komisyon satış tutarından büyük")
    if not (_same_number(closure.proceeds, proceeds) and _same_number(closure.realized, realized)):
        raise _Broken(f"{client_order_id}: gelir ya da kâr/zarar türetilenle aynı değil")
    if not _same_number(entry.usdt, proceeds):
        raise _Broken(f"{client_order_id}: kayıt tutarı gelir değil")
    state.balance, state.realized = after, total
    del state.positions[position_id]
    state.closures[client_order_id] = closure


def _replay(ledger: Ledger) -> None:
    entries = ledger.entries
    if not isinstance(entries, tuple):
        raise _Broken("kayıtlar demet değil")
    if not (isinstance(ledger.positions, Mapping) and isinstance(ledger.closures, Mapping)):
        raise _Broken("pozisyonlar ya da kapanışlar eşleme değil")
    state = _Replay(None, Decimal(0), None, {}, {}, set())
    for index, entry in enumerate(entries):
        if not isinstance(entry, Entry):
            raise _Broken(f"kayıt {index} defter kaydı değil")
        if entry.kind is EntryKind.OPENING:
            _opening(state, entry)
        elif state.balance is None:
            raise _Broken("ilk kayıt açılış değil")
        elif entry.kind is EntryKind.FILL:
            _fill(state, entry)
        elif entry.kind is EntryKind.CLOSE:
            _close(state, entry)
        else:
            raise _Broken(f"kayıt {index} türü bilinmiyor")
    if not _exact(ledger.balance, state.balance):
        raise _Broken("bakiye kayıtlardan türeyenle aynı değil")
    if not _exact(ledger.realized, state.realized):
        raise _Broken("gerçekleşen toplam kayıtlardan türeyenle aynı değil")
    for label, held, derived in (
        ("açık pozisyonlar", ledger.positions, state.positions),
        ("kapanışlar", ledger.closures, state.closures),
    ):
        if list(held) != list(derived):
            raise _Broken(f"{label} kayıtlardan türeyenle aynı değil")
        if not all(_exact(held[key], value) for key, value in derived.items()):
            raise _Broken(f"{label} kayıtlardan türeyenle aynı değil")


def ledger_problems(ledger: object) -> list[str]:
    """R-6: defterin kayıtlarından türeyenle aynı olup olmadığı; ilk sorunda durur, istisna yok."""
    if not isinstance(ledger, Ledger):
        return ["defter değil"]
    try:
        _replay(ledger)
    except _Broken as broken:
        return [str(broken)]
    except DecimalException:  # the exact result does not fit in 60 digits (spec 0007 Risk 3)
        return ["kayıtların hesabı 60 basamağa sığmıyor"]
    return []
