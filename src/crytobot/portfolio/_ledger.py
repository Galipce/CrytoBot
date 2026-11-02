"""Dolan paper alımlardan defter: açılış, dolum kaydı, pozisyonlar (spec 0007); kapanışların ve
gerçekleşen kâr/zararın taşındığı ortak türler (spec 0008, kayıt `_close.py`'de)."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, DecimalException, localcontext
from enum import Enum
from types import MappingProxyType

from crytobot.portfolio._numbers import (
    BOUNDED,
    CALC_DIGITS,
    DIGITS,
    SCALE,
    _brief,
    _in_scale,
    _number,
    _show,
    _significant,
)

BUY = "buy"
# ASCII only, the exchanges' common client order id limit (spec 0007 R-11)
_CLIENT_ORDER_ID = re.compile(r"[A-Za-z0-9_-]{1,36}")


@dataclass(frozen=True)
class Fill:
    """Ham dolum kaydı isteği (R-2): dolan bir alımın bilgileri. Alanlar doğrulanmadan gelir."""

    client_order_id: object
    pair: object
    side: object
    amount: object
    price: object
    fee: object
    stop: object
    target: object
    at: object


@dataclass(frozen=True)
class Position:
    """Alımın açtığı pozisyon (R-4): her dolum ayrı bir pozisyondur; maliyet fiyatı dolum fiyatıdır.
    Açıkken `Ledger.positions`'ta, kapandıktan sonra `Closure.position`'da durur (spec 0008)."""

    client_order_id: str
    pair: str
    amount: Decimal
    cost_price: Decimal
    fee: Decimal
    stop: Decimal
    target: Decimal
    opened_at: datetime


class CloseReason(Enum):
    """Kapanış nedeni (spec 0008 R-1, R-3)."""

    STOP = "stop"
    TARGET = "hedef"


@dataclass(frozen=True)
class Closure:
    """Kapanmış pozisyon (spec 0008 R-5, R-6): kapanış satışı, geliri ve net kâr/zararı."""

    client_order_id: str
    position: Position
    amount: Decimal
    price: Decimal
    fee: Decimal
    reason: CloseReason
    closed_at: datetime
    proceeds: Decimal
    realized: Decimal


class EntryKind(Enum):
    OPENING = "opening"
    FILL = "fill"
    CLOSE = "close"


@dataclass(frozen=True)
class Entry:
    """Defter kaydı (R-9): açılışta yatırılan, dolumda düşülen, kapanışta eklenen USDT tutarı."""

    kind: EntryKind
    at: datetime
    usdt: Decimal
    position: Position | None
    closure: Closure | None = None


@dataclass(frozen=True)
class Ledger:
    """Kayıtlar eklenme sırasıyla; değer değişmez (R-9). Bakiye `None`: defter açılmamış.
    `positions` açık pozisyonlar; `closures` kapanış kimliği → kapanış, kapanma sırasıyla;
    `realized` gerçekleşen kâr/zarar toplamı (spec 0008 R-5, R-6)."""

    entries: tuple[Entry, ...]
    balance: Decimal | None
    positions: Mapping[str, Position]
    closures: Mapping[str, Closure]
    realized: Decimal

    @property
    def opened_at(self) -> datetime | None:
        return self.entries[0].at if self.entries else None

    def bought(self, client_order_id: str) -> Position | None:
        """Bu kimlikle kaydedilmiş alımın pozisyonu, açık ya da kapanmış (spec 0008 R-9)."""
        position = self.positions.get(client_order_id)
        if position is not None:
            return position
        for closure in self.closures.values():
            if closure.position.client_order_id == client_order_id:
                return closure.position
        return None


EMPTY_LEDGER = Ledger((), None, MappingProxyType({}), MappingProxyType({}), Decimal(0))


class LedgerOutcome(Enum):
    """İsteğin sonucu; birden fazla sorun varsa ret nedenlerinden bu sıradaki ilki döner (R-10)."""

    OPENED = "opened"
    RECORDED = "recorded"
    ALREADY_RECORDED = "already_recorded"
    INVALID_INPUT = "invalid_input"
    NOT_OPENED = "not_opened"
    ALREADY_OPEN = "already_open"
    RECORD_CONFLICT = "record_conflict"
    UNSUPPORTED_SIDE = "unsupported_side"
    INSUFFICIENT_BALANCE = "insufficient_balance"


@dataclass(frozen=True)
class LedgerResult:
    """İstek sonrası defter; kayıt eklenmediyse defter istekten öncekiyle aynıdır (R-9)."""

    ledger: Ledger
    outcome: LedgerOutcome
    position: Position | None
    message: str

    @property
    def accepted(self) -> bool:
        return self.outcome in (LedgerOutcome.OPENED, LedgerOutcome.RECORDED)


@dataclass(frozen=True)
class _Checked:
    client_order_id: str
    pair: str
    side: str
    amount: Decimal
    price: Decimal
    fee: Decimal
    stop: Decimal
    target: Decimal
    at: datetime


def _out_of_scale(label: str, number: Decimal) -> str:
    return f"{label} {_brief(number)} ölçeği varsayılan üs aralığı (±{SCALE}) dışında"


def _too_long(label: str, number: Decimal, digits: int = DIGITS) -> str:
    return f"{label} {_brief(number)} {digits} anlamlı basamaktan uzun"


def _amount(
    label: str, value: object, problems: list[str], *, zero: bool = False, digits: int = DIGITS
) -> Decimal | None:
    """R-11: sıfırdan büyük (`zero` ile negatif olmayan), ölçek içinde, en fazla 28 anlamlı
    basamak."""
    number = _number(value)
    if number is None or number < 0 or (number == 0 and not zero):
        rule = "negatif olmayan" if zero else "sıfırdan büyük"
        problems.append(f"{label} {_show(value)} {rule} bir sayı olmalı")
    elif not _in_scale(number):
        problems.append(_out_of_scale(label, number))
    elif _significant(number) > digits:
        problems.append(_too_long(label, number, digits))
    else:
        return number
    return None


def _time(label: str, value: object, problems: list[str]) -> datetime | None:
    if isinstance(value, datetime) and value.utcoffset() is not None:
        return value
    problems.append(f"{label} {_show(value)} zaman dilimi taşımalı")
    return None


def _check(fill: Fill) -> _Checked | list[str]:
    """R-11: her girdiyi doğrular; sorun varsa hepsini adlandırır."""
    problems: list[str] = []
    client_order_id = fill.client_order_id
    if not (isinstance(client_order_id, str) and _CLIENT_ORDER_ID.fullmatch(client_order_id)):
        problems.append(
            f"clientOrderId {_show(client_order_id)} 1-36 karakter olmalı ve yalnızca harf, rakam,"
            " - ve _ içermeli"
        )
    if not (isinstance(fill.pair, str) and isinstance(fill.side, str)):
        problems.append(f"çift {_show(fill.pair)} ve yön {_show(fill.side)} metin olmalı")
    amount = _amount("miktar", fill.amount, problems)
    price = _amount("dolum fiyatı", fill.price, problems, digits=CALC_DIGITS)  # spec 0010 R-3
    fee = _amount("komisyon", fill.fee, problems, zero=True, digits=CALC_DIGITS)
    stop = _amount("stop", fill.stop, problems)
    target = _amount("hedef", fill.target, problems)
    at = _time("dolum zamanı", fill.at, problems)
    if problems:
        return problems
    assert isinstance(client_order_id, str) and isinstance(fill.pair, str)  # checked above
    assert isinstance(fill.side, str)
    assert amount is not None and price is not None and fee is not None and at is not None
    assert stop is not None and target is not None
    return _Checked(client_order_id, fill.pair, fill.side, amount, price, fee, stop, target, at)


def _content(position: Position, side: str) -> tuple[object, ...]:
    """R-6: tekrar korumasında karşılaştırılan içerik; dolum zamanı değildir."""
    return (
        position.pair,
        side,
        position.amount,
        position.cost_price,
        position.fee,
        position.stop,
        position.target,
    )


def open_ledger(ledger: Ledger, amount: object, at: object) -> LedgerResult:
    """R-1: boş defteri başlangıç yatırmasıyla açar."""

    def reject(outcome: LedgerOutcome, detail: str) -> LedgerResult:
        return LedgerResult(ledger, outcome, None, detail)

    problems: list[str] = []
    deposit = _amount("başlangıç tutarı", amount, problems)
    opened = _time("açılış zamanı", at, problems)
    if problems:
        return reject(LedgerOutcome.INVALID_INPUT, "geçersiz girdi: " + "; ".join(problems))
    assert deposit is not None and opened is not None  # checked above
    if ledger.balance is not None:
        return reject(
            LedgerOutcome.ALREADY_OPEN, f"defter zaten açık (bakiye {_brief(ledger.balance)})"
        )
    entry = Entry(EntryKind.OPENING, opened, deposit, None)
    return LedgerResult(
        Ledger((entry,), deposit, ledger.positions, ledger.closures, ledger.realized),
        LedgerOutcome.OPENED,
        None,
        f"defter açıldı: {_brief(deposit)} USDT",
    )


def record_fill(ledger: Ledger, fill: Fill) -> LedgerResult:
    """R-2…R-6: dolan alımı kaydeder, bedelini bakiyeden düşer ve pozisyon açar ya da adlandırarak
    reddeder."""

    def reject(outcome: LedgerOutcome, detail: str) -> LedgerResult:
        return LedgerResult(ledger, outcome, None, detail)

    checked = _check(fill)
    if isinstance(checked, list):
        return reject(LedgerOutcome.INVALID_INPUT, "geçersiz girdi: " + "; ".join(checked))
    balance, opened_at = ledger.balance, ledger.opened_at
    if balance is None or opened_at is None:
        return reject(LedgerOutcome.NOT_OPENED, "defter açılmamış: önce başlangıç yatırması")
    if checked.at < opened_at:
        return reject(
            LedgerOutcome.INVALID_INPUT,
            f"geçersiz girdi: dolum zamanı {checked.at.isoformat()} açılıştan"
            f" ({opened_at.isoformat()}) önce",
        )

    def unrepresentable() -> LedgerResult:
        """The exact result does not fit in 60 digits (plan 0007 Risk 3)."""
        return reject(
            LedgerOutcome.INVALID_INPUT,
            f"geçersiz girdi: ölçek hesaplanamıyor (miktar {_brief(checked.amount)}, dolum fiyatı"
            f" {_brief(checked.price)}, komisyon {_brief(checked.fee)}, bakiye {_brief(balance)})",
        )

    try:  # before the record checks: an incalculable fill is invalid input first (R-10)
        with localcontext(BOUNDED):
            cost = checked.amount * checked.price + checked.fee
    except DecimalException:
        return unrepresentable()
    position = Position(
        checked.client_order_id,
        checked.pair,
        checked.amount,
        checked.price,
        checked.fee,
        checked.stop,
        checked.target,
        checked.at,
    )
    if checked.client_order_id in ledger.closures:  # one id space for buys and closes (0008 R-9)
        return reject(
            LedgerOutcome.RECORD_CONFLICT,
            f"kayıt çakışması: {checked.client_order_id} bir kapanışın kimliği",
        )
    existing = ledger.bought(checked.client_order_id)  # a closed buy is still recorded (0008 R-9)
    if existing is not None:
        if _content(existing, BUY) == _content(position, checked.side):
            return LedgerResult(
                ledger,
                LedgerOutcome.ALREADY_RECORDED,
                existing,
                f"{existing.pair}: {existing.client_order_id} zaten kayıtlı",
            )
        return reject(
            LedgerOutcome.RECORD_CONFLICT,
            f"kayıt çakışması: {checked.client_order_id} başka bir içerikle kayıtlı",
        )
    if checked.side != BUY:
        return reject(
            LedgerOutcome.UNSUPPORTED_SIDE,
            f"{checked.pair}: desteklenmeyen yön {_show(checked.side)}: yalnızca {BUY}",
        )
    if cost > balance:  # exact; needs no difference (plan 0007 A-2)
        return reject(
            LedgerOutcome.INSUFFICIENT_BALANCE,
            f"{checked.pair}: yetersiz bakiye: gereken {_brief(cost)} USDT, bakiye"
            f" {_brief(balance)} USDT",
        )
    try:  # after the record checks: a retry does not depend on the balance (plan 0007 A-1)
        with localcontext(BOUNDED):
            after = balance - cost
    except DecimalException:
        return unrepresentable()
    positions = dict(ledger.positions)
    positions[position.client_order_id] = position
    entry = Entry(EntryKind.FILL, checked.at, cost, position)
    return LedgerResult(
        Ledger(
            (*ledger.entries, entry),
            after,
            MappingProxyType(positions),
            ledger.closures,
            ledger.realized,
        ),
        LedgerOutcome.RECORDED,
        position,
        f"{position.pair}: {position.client_order_id} kaydedildi: miktar {_brief(position.amount)},"
        f" maliyet {_brief(cost)} USDT, bakiye {_brief(after)} USDT",
    )


class SnapshotOutcome(Enum):
    """Hesap durumu isteğinin sonucu; ret sırası: geçersiz girdi → defter açılmamış → fiyat eksik →
    ölçek hesaplanamıyor (geçersiz girdi) (plan 0007 Risk 4)."""

    READY = "ready"
    INVALID_INPUT = "invalid_input"
    NOT_OPENED = "not_opened"
    MISSING_PRICE = "missing_price"


@dataclass(frozen=True)
class AccountSnapshot:
    """R-7, R-8: `risk`'in hesap girdisi (kasa, serbest bakiye, açık pozisyon sayısı), açık
    pozisyonlar eklenme sırasıyla ve gerçekleşen kâr/zarar toplamı (spec 0008 R-11)."""

    equity: Decimal
    free_balance: Decimal
    open_positions: int
    positions: tuple[Position, ...]
    realized: Decimal


@dataclass(frozen=True)
class SnapshotResult:
    outcome: SnapshotOutcome
    snapshot: AccountSnapshot | None
    message: str


def _price(value: object) -> Decimal | None:
    """R-7, R-11: güncel fiyat sıfırdan büyük, ölçek içinde, en fazla 28 anlamlı basamak."""
    return _amount("fiyat", value, [])


def account_state(ledger: Ledger, prices: object) -> SnapshotResult:
    """R-7: serbest bakiye, açık pozisyonlar ve çift başına güncel fiyatla değerlenmiş kasa; açık
    pozisyonu olan bir çiftin fiyatı yoksa kasa hesaplanmaz."""
    if not isinstance(prices, Mapping):
        return SnapshotResult(
            SnapshotOutcome.INVALID_INPUT,
            None,
            f"geçersiz girdi: fiyatlar {_show(prices)} çift → fiyat eşlemesi olmalı",
        )
    balance = ledger.balance
    if balance is None:
        return SnapshotResult(
            SnapshotOutcome.NOT_OPENED, None, "defter açılmamış: önce başlangıç yatırması"
        )
    positions = tuple(ledger.positions.values())
    marks: dict[str, Decimal] = {}
    missing: list[str] = []
    for pair in dict.fromkeys(p.pair for p in positions):
        price = _price(prices.get(pair))
        if price is None:
            missing.append(pair)
        else:
            marks[pair] = price
    if missing:
        return SnapshotResult(
            SnapshotOutcome.MISSING_PRICE,
            None,
            "fiyat eksik: açık pozisyonu olan " + ", ".join(missing) + " için geçerli fiyat yok",
        )
    try:
        with localcontext(BOUNDED):
            equity = balance
            for position in positions:
                equity += position.amount * marks[position.pair]
    except DecimalException:  # the exact result does not fit in 60 digits (plan 0007 Risk 3)
        return SnapshotResult(
            SnapshotOutcome.INVALID_INPUT,
            None,
            f"geçersiz girdi: ölçek hesaplanamıyor (bakiye {_brief(balance)}, fiyatlar "
            + ", ".join(f"{pair} {_brief(price)}" for pair, price in marks.items())
            + ")",
        )
    return SnapshotResult(
        SnapshotOutcome.READY,
        AccountSnapshot(equity, balance, len(positions), positions, ledger.realized),
        f"kasa {_brief(equity)} USDT, serbest bakiye {_brief(balance)} USDT, açık pozisyon"
        f" {len(positions)}",
    )
