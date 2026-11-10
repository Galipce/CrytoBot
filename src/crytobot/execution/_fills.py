"""Canlı dolum yargısı (spec 0036 R-1…R-5, R-11): borsa yanıtından deftere yazılabilecek dolum.

Saf hesaptır; borsaya çıkmaz. Üç sonuç vardır: `COMPLETE` (tam dolum: fiyat, dolan ve net miktar,
USDT karşılığı ücret, komisyon ve varlığı, toz), `UNSUPPORTED` (kısmi dolum, üçüncü varlıktan ya da
satışta coinden komisyon: spec 0037'ye kadar deftere yazılmaz) ve `INCOMPLETE` (eksik ya da
tutarsız bilgi). Son ikisi emri `UNKNOWN` bırakır, tahmin hiçbir zaman yazılmaz.

Defter `maliyet = miktar * fiyat + ücret` yazar (plan 0036 Risk 1). Pozisyon miktarı net miktardır;
fiyat ödenen USDT'nin dolan miktara bölümüdür (Risk 5: 28 basamağa, alımda aşağı, satışta yukarı
yuvarlanır); ücret, defterin bakiyeden düştüğü ya da eklediği tutar borsadakiyle birebir aynı olsun
diye `ödenen - net * fiyat` (+ USDT komisyonu) olarak hesaplanır: coin komisyonu ve toz böylece
ücrete girer, kasaya girmez.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import (
    ROUND_DOWN,
    ROUND_UP,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from enum import Enum
from typing import Any

from crytobot.execution._numbers import BOUNDED, CALC_DIGITS, DIGITS, SCALE, _in_scale, _significant
from crytobot.execution._paper import OrderStatus

_BUY, _SELL = "buy", "sell"


class FillVerdict(Enum):
    COMPLETE = "complete"
    UNSUPPORTED = "unsupported"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class LiveReply:
    """Canlı borsanın bir emir için yanıtı: durum, ham emir, gerekirse emrin işlemleri (komisyon
    için, plan 0036 Risk 2) ve "böyle emir yok" işareti (R-8)."""

    status: OrderStatus
    order: Mapping[str, Any] | None = None
    trades: Sequence[Mapping[str, Any]] | None = None
    missing: bool = False


@dataclass(frozen=True)
class ExchangeFill:
    """Yargılanmış dolum; sayılar yalnız `COMPLETE` iken dolu. `fee`, defterin USDT ücretidir;
    `commission` ve `commission_asset` borsanın kestiği ham komisyondur."""

    verdict: FillVerdict
    reason: str
    price: Decimal | None = None
    filled: Decimal | None = None
    net: Decimal | None = None
    fee: Decimal | None = None
    commission: Decimal | None = None
    commission_asset: str | None = None
    dust: Decimal | None = None


@dataclass(frozen=True)
class Settled:
    """Yanıtın emir durumuna çevrilmiş hali. `unsupported`: R-5 bildiriminin metni."""

    status: OrderStatus
    fill: ExchangeFill | None
    unsupported: str | None = None
    problem: str | None = None


def _decimal(value: object) -> Decimal | None:
    """Borsa sayısı: metin, `int` ya da `Decimal`; `float` `repr` ile (Known traps). Sonlu değilse
    ya da ölçek dışındaysa `None`."""
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, float):
            number = Decimal(repr(value))
        elif isinstance(value, str | int | Decimal):
            number = Decimal(value)
        else:
            return None
    except (DecimalException, ValueError):
        return None
    return number if number.is_finite() and _in_scale(number) else None


def fee_entries(order: Mapping[str, Any]) -> list[Mapping[str, Any]] | None:
    """Yanıttaki komisyon satırları: `fees` (doluysa) ya da `fee`; hiç bildirilmemişse `None`.
    Sıfır tutarlı satır bildirimdir (G-4)."""
    fees = order.get("fees")
    if isinstance(fees, list | tuple) and fees:
        return [entry if isinstance(entry, Mapping) else {} for entry in fees]
    fee = order.get("fee")
    if isinstance(fee, Mapping) and fee.get("cost") is not None:
        return [fee]
    return None


def _trade_fees(trades: Sequence[Mapping[str, Any]], filled: Decimal) -> list[Mapping[str, Any]]:
    """Emrin işlemlerinden komisyon; işlemler dolan miktarın tamamını kapsamıyorsa boş liste."""
    entries: list[Mapping[str, Any]] = []
    total = Decimal(0)
    for trade in trades:
        amount = _decimal(trade.get("amount")) if isinstance(trade, Mapping) else None
        found = fee_entries(trade) if isinstance(trade, Mapping) else None
        if amount is None or amount <= 0 or found is None:
            return []
        with localcontext(BOUNDED):
            total += amount
        entries.extend(found)
    return entries if total == filled else []


def _incomplete(reason: str) -> ExchangeFill:
    return ExchangeFill(FillVerdict.INCOMPLETE, reason)


def _unsupported(reason: str) -> ExchangeFill:
    return ExchangeFill(FillVerdict.UNSUPPORTED, reason)


def _rounded(cost: Decimal, filled: Decimal, rounding: str) -> Decimal:
    context = Context(
        prec=DIGITS,
        rounding=rounding,
        Emax=SCALE,
        Emin=-SCALE,
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )
    with localcontext(context):
        return cost / filled


def _fits(number: Decimal, digits: int) -> bool:
    return _in_scale(number) and _significant(number) <= digits


def judge_fill(
    order: object,
    trades: object,
    *,
    side: str,
    pair: str,
    amount: Decimal,
    step: Decimal | None,
) -> ExchangeFill:
    """R-1…R-5, R-11: "doldu" denen emrin yanıtından deftere yazılabilir dolum ya da nedeni."""
    if not isinstance(order, Mapping):
        return _incomplete("emir yanıtı yok")
    filled = _decimal(order.get("filled"))
    if filled is None or filled <= 0:
        return _incomplete("dolan miktar bildirilmedi")
    if filled < amount:
        return _unsupported(f"kısmi dolum (dolan {filled}, emir {amount})")
    if filled > amount:
        return _incomplete(f"dolan miktar ({filled}) emirden ({amount}) büyük")
    average = _decimal(order.get("average"))
    if average is None or average <= 0:
        return _incomplete("ortalama fiyat bildirilmedi")
    raw_cost = order.get("cost")
    cost = _decimal(raw_cost)
    if raw_cost is not None and (cost is None or cost <= 0):
        return _incomplete("ödenen tutar geçersiz")
    entries = fee_entries(order)
    if entries is None and isinstance(trades, Sequence) and not isinstance(trades, str):
        entries = _trade_fees(trades, filled) or None
    if entries is None:
        return _incomplete("komisyon bildirilmedi")
    base, _, quote = pair.partition("/")
    coin, usdt = Decimal(0), Decimal(0)
    for entry in entries:
        value = _decimal(entry.get("cost"))
        if value is None or value < 0:
            return _incomplete("komisyon tutarı geçersiz")
        if value == 0:  # a zero fee is valid whatever its asset (plan 0036 Risk 4)
            continue
        currency = entry.get("currency")
        if not isinstance(currency, str) or not currency:
            return _incomplete("komisyon varlığı bildirilmedi")
        with localcontext(BOUNDED):
            if currency == base and side == _BUY:
                coin += value
            elif currency == quote:
                usdt += value
            else:
                return _unsupported(f"komisyon {currency} varlığından kesildi")
    if coin > 0 and usdt > 0:
        return _unsupported("komisyon iki varlıktan kesildi")
    try:
        return _complete(side, base, quote, filled, average, cost, coin, usdt, step)
    except DecimalException:
        return _incomplete("dolum ölçeği hesaplanamıyor")


def _complete(
    side: str,
    base: str,
    quote: str,
    filled: Decimal,
    average: Decimal,
    cost: Decimal | None,
    coin: Decimal,
    usdt: Decimal,
    step: Decimal | None,
) -> ExchangeFill:
    """Tam dolumun defter değerleri; sığmayan hesap `DecimalException` fırlatır."""
    if cost is None:  # the paid USDT is the filled amount at the average price (R-2)
        price = average
        if _significant(average) > DIGITS:
            price = _rounded(average, Decimal(1), ROUND_DOWN if side == _BUY else ROUND_UP)
        with localcontext(BOUNDED):
            cost = filled * price
    else:  # what the balance loses (buy) or gains (sell) is exactly what the exchange booked
        price = _rounded(cost, filled, ROUND_DOWN if side == _BUY else ROUND_UP)
    if side == _BUY:
        if step is None or step <= 0:
            return _incomplete("miktar adımı yok")
        with localcontext(BOUNDED):
            kept = filled - coin
            net = (kept // step) * step
            dust = kept - net
            fee = cost + usdt - net * price
        if net <= 0:
            return _unsupported("komisyondan sonra net miktar sıfır")
        commission, asset = (coin, base) if coin > 0 else (usdt, quote)
    else:
        with localcontext(BOUNDED):
            net, dust = filled, Decimal(0)
            fee = filled * price - cost + usdt
        commission, asset = usdt, quote
    if fee < 0 or not (
        _fits(net, DIGITS) and _fits(price, CALC_DIGITS) and _fits(fee, CALC_DIGITS)
    ):
        return _incomplete("dolum defterin basamak sınırına sığmıyor")
    return ExchangeFill(
        FillVerdict.COMPLETE,
        "tam dolum",
        price,
        filled,
        net,
        fee,
        commission,
        asset,
        dust,
    )


def settle_reply(
    reply: LiveReply, *, side: str, pair: str, amount: Decimal, step: Decimal | None
) -> Settled:
    """R-5, R-7, R-11: yanıtın emir durumu. Yalnız tam ve desteklenen dolum `FILLED`; hiçbir şey
    dolmadan biten emir `REJECTED`; geri kalan her şey `UNKNOWN` (plan 0036 Risk 9)."""
    if reply.status is OrderStatus.REJECTED and reply.order is None:
        return Settled(OrderStatus.REJECTED, None)  # a definite refusal (R-7)
    if reply.status is OrderStatus.REJECTED:
        filled = _decimal(reply.order.get("filled")) if reply.order is not None else None
        if filled is None or filled < 0:
            return Settled(OrderStatus.UNKNOWN, None, problem="dolan miktar bildirilmedi")
        if filled == 0:  # nothing happened on the exchange
            return Settled(OrderStatus.REJECTED, None)
    elif reply.status is not OrderStatus.FILLED:
        return Settled(OrderStatus.UNKNOWN, None)
    fill = judge_fill(reply.order, reply.trades, side=side, pair=pair, amount=amount, step=step)
    if fill.verdict is FillVerdict.COMPLETE:
        return Settled(OrderStatus.FILLED, fill)
    if fill.verdict is FillVerdict.UNSUPPORTED:
        return Settled(
            OrderStatus.UNKNOWN, None, unsupported=f"desteklenmeyen dolum: {fill.reason}"
        )
    return Settled(OrderStatus.UNKNOWN, None, problem=f"eksik dolum bilgisi: {fill.reason}")
