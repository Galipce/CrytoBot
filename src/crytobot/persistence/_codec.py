"""Kalıcı durum ↔ JSON satırı (spec 0011 R-3, R-6): sayı ve zaman metindir, `float` yok.

Okuma katıdır: `Decimal("1_000")`, `" 1 "` ya da gevşek bir ISO biçimi geri yazıma uymadığı için
bozuk sayılır. Satırlar diziler; kapanış pozisyonu kimliğiyle gösterir, alım satırındaki nesneyi
paylaşır (plan 0011 Risk 5). Bir emir dizisinin son altı alanı iki türde de aynıdır: durum, dolum,
komisyon, oluşturma zamanı, tahmini dolum, tahmini komisyon.
"""

import json
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal, DecimalException
from types import MappingProxyType
from typing import Any, NoReturn

from crytobot.execution import CloseOrder, ExecutionState, Order, OrderStatus
from crytobot.portfolio import CloseReason, Closure, Entry, EntryKind, Ledger, Position
from crytobot.risk import RiskState

_OPENING, _FILL, _CLOSE = "o", "f", "c"
_BUY_ORDER, _CLOSE_ORDER = "b", "s"


class PersistenceError(Exception):
    """Modülün tipli hata tabanı; hiçbir istisna modül dışına çıkmaz (R-10)."""


class CodecError(PersistenceError):
    """Satır birebir okunamıyor."""


def _refuse(_text: str) -> NoReturn:
    raise CodecError


# one decoder: json.loads builds a new one per call with these hooks, a third of the load (R-11)
_DECODER = json.JSONDecoder(parse_float=_refuse, parse_int=_refuse, parse_constant=_refuse)


def _dumps(row: object) -> str:
    return json.dumps(row, separators=(",", ":"))


def _loads(text: object) -> Any:
    if not isinstance(text, str):
        raise CodecError
    try:
        return _DECODER.decode(text)
    except (ValueError, RecursionError) as error:
        raise CodecError from error


def _number(value: object) -> Decimal:
    if type(value) is not str:
        raise CodecError
    try:
        number = Decimal(value)
    except DecimalException as error:
        raise CodecError from error
    if str(number) != value:
        raise CodecError
    return number


def _time(value: object) -> datetime:
    if type(value) is not str:
        raise CodecError
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as error:
        raise CodecError from error
    if moment.isoformat() != value or moment.utcoffset() is None:
        raise CodecError
    return moment


def _text(value: object) -> str:
    if type(value) is not str:
        raise CodecError
    return value


def _optional_number(value: object) -> Decimal | None:
    return None if value is None else _number(value)


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def encode_entry(entry: Entry) -> str:
    """Doğrulanmış defterin kaydı (`ledger_problems` geçti): zaman ve tutar alanlarıyla aynı."""
    if entry.kind is EntryKind.OPENING:
        return _dumps([_OPENING, entry.at.isoformat(), str(entry.usdt)])
    position = entry.position
    assert position is not None  # validated by ledger_problems
    if entry.kind is EntryKind.FILL:
        return _dumps(
            [
                _FILL,
                str(entry.usdt),
                position.client_order_id,
                position.pair,
                str(position.amount),
                str(position.cost_price),
                str(position.fee),
                str(position.stop),
                str(position.target),
                position.opened_at.isoformat(),
            ]
        )
    closure = entry.closure
    assert closure is not None  # validated by ledger_problems
    return _dumps(
        [
            _CLOSE,
            position.client_order_id,
            closure.client_order_id,
            str(closure.amount),
            str(closure.price),
            str(closure.fee),
            closure.reason.value,
            closure.closed_at.isoformat(),
            str(closure.proceeds),
            str(closure.realized),
        ]
    )


def encode_summary(ledger: Ledger) -> str:
    return _dumps(
        [
            _optional_text(ledger.balance),
            str(ledger.realized),
            list(ledger.positions),
            list(ledger.closures),
        ]
    )


def decode_ledger(rows: Iterable[object], summary: object) -> Ledger:
    """Doğrulamaz: bakiye ve toplamı `ledger_problems` kayıtlardan türetilenle karşılaştırır."""
    entries: list[Entry] = []
    bought: dict[str, Position] = {}
    closed: dict[str, Closure] = {}
    try:
        for text in rows:
            row = _loads(text)
            kind = row[0]
            if kind == _OPENING:
                _, at, usdt = row
                entries.append(Entry(EntryKind.OPENING, _time(at), _number(usdt), None))
            elif kind == _FILL:
                _, usdt, cid, pair, amount, price, fee, stop, target, opened = row
                position = Position(
                    _text(cid),
                    _text(pair),
                    _number(amount),
                    _number(price),
                    _number(fee),
                    _number(stop),
                    _number(target),
                    _time(opened),
                )
                bought[position.client_order_id] = position
                entries.append(Entry(EntryKind.FILL, position.opened_at, _number(usdt), position))
            elif kind == _CLOSE:
                _, position_id, cid, amount, price, fee, reason, at, proceeds, realized = row
                position = bought[_text(position_id)]
                closure = Closure(
                    _text(cid),
                    position,
                    _number(amount),
                    _number(price),
                    _number(fee),
                    CloseReason(reason),
                    _time(at),
                    _number(proceeds),
                    _number(realized),
                )
                closed[closure.client_order_id] = closure
                entries.append(
                    Entry(EntryKind.CLOSE, closure.closed_at, closure.proceeds, position, closure)
                )
            else:
                raise CodecError
        balance, realized_total, open_ids, closed_ids = _loads(summary)
        return Ledger(
            tuple(entries),
            _optional_number(balance),
            MappingProxyType(_pick(bought, open_ids)),
            MappingProxyType(_pick(closed, closed_ids)),
            _number(realized_total),
        )
    except (IndexError, KeyError, TypeError, ValueError) as error:
        raise CodecError from error


def _pick[T](known: Mapping[str, T], ids: list[str]) -> dict[str, T]:
    return {_text(i): known[i] for i in ids}


def encode_order(order: Order | CloseOrder, quote: tuple[Decimal, Decimal] | None) -> str:
    tail = [
        order.status.value,
        _optional_text(order.fill_price),
        _optional_text(order.fee),
        order.created_at.isoformat(),
        None if quote is None else str(quote[0]),
        None if quote is None else str(quote[1]),
    ]
    if isinstance(order, Order):
        head = [
            _BUY_ORDER,
            order.client_order_id,
            order.intent_id,
            order.pair,
            str(order.entry),
            str(order.stop),
            str(order.target),
            str(order.amount),
        ]
    else:
        head = [
            _CLOSE_ORDER,
            order.client_order_id,
            order.position_id,
            order.pair,
            str(order.amount),
            order.reason,
        ]
    return _dumps(head + tail)


def encode_orders(state: ExecutionState) -> list[str]:
    return [encode_order(order, state.quotes.get(cid)) for cid, order in state.orders.items()]


def decode_orders(rows: Iterable[object]) -> ExecutionState:
    orders: dict[str, Order | CloseOrder] = {}
    quotes: dict[str, tuple[Decimal, Decimal]] = {}
    try:
        for text in rows:
            row = _loads(text)
            head, (status, fill, fee, created, quote_fill, quote_fee) = row[:-6], row[-6:]
            common = (
                OrderStatus(status),
                _optional_number(fill),
                _optional_number(fee),
                _time(created),
            )
            order: Order | CloseOrder
            if head[0] == _BUY_ORDER:
                _, cid, intent, pair, entry, stop, target, amount = head
                order = Order(
                    _text(cid),
                    _text(intent),
                    _text(pair),
                    "buy",
                    _number(entry),
                    _number(stop),
                    _number(target),
                    _number(amount),
                    *common,
                )
            elif head[0] == _CLOSE_ORDER:
                _, cid, position_id, pair, amount, reason = head
                order = CloseOrder(
                    _text(cid),
                    _text(position_id),
                    _text(pair),
                    "sell",
                    _number(amount),
                    _text(reason),
                    *common,
                )
            else:
                raise CodecError
            orders[order.client_order_id] = order
            if quote_fill is not None or quote_fee is not None:
                quotes[order.client_order_id] = (_number(quote_fill), _number(quote_fee))
    except (IndexError, TypeError, ValueError) as error:
        raise CodecError from error
    return ExecutionState(MappingProxyType(orders), MappingProxyType(quotes))


def order_resolution_allowed(stored: str, new: str) -> bool:
    """R-8: yalnız `bilinmiyor` emir netleşebilir; dolum, kayıtlı tahminin kendisidir."""
    try:
        before, after = _loads(stored), _loads(new)
        if before[:-6] != after[:-6] or before[-3] != after[-3]:
            return False
        if before[-6] != OrderStatus.UNKNOWN.value or after[-2:] != [None, None]:
            return False
        if after[-6] == OrderStatus.FILLED.value:
            return bool(after[-5:-3] == before[-2:])
        return bool(after[-6] == OrderStatus.REJECTED.value and after[-5:-3] == [None, None])
    except (CodecError, IndexError, KeyError, TypeError):
        return False


def encode_risk(state: RiskState) -> str:
    return _dumps(
        [
            None if state.day is None else state.day.isoformat(),
            _optional_text(state.day_start_equity),
            _optional_text(state.peak_equity),
            None if state.last_time is None else state.last_time.isoformat(),
            _optional_text(state.last_equity),
            state.halted,
        ]
    )


def decode_risk(text: object) -> RiskState:
    try:
        day, day_start, peak, at, last, halted = _loads(text)
        parsed = None if day is None else date.fromisoformat(_text(day))
    except (TypeError, ValueError) as error:
        raise CodecError from error
    if parsed is not None and parsed.isoformat() != day:
        raise CodecError
    return RiskState(
        parsed,
        _optional_number(day_start),
        _optional_number(peak),
        None if at is None else _time(at),
        _optional_number(last),
        halted,
    )
