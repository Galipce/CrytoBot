"""Canlı dolum yargısı (spec 0036 R-1…R-5, R-11; spec 0037 R-1, R-3, R-4): borsa yanıtından
deftere yazılabilecek dolum.

Borsaya yalnız üçüncü varlık komisyonunun fiyatı için, çağıranın verdiği `asset_price` ile çıkar.
Üç sonuç vardır: `COMPLETE` (fiyat, dolan ve net miktar, USDT karşılığı ücret, komisyon ve varlığı,
toz; kalanı borsada sona ermiş emirde dolan kısım, `partial`), `UNSUPPORTED` (iki varlıktan ya da
satışta coinden komisyon, komisyondan sonra net sıfır: deftere yazılmaz) ve `INCOMPLETE` (eksik
ya da tutarsız bilgi; "doldu" denen emirde dolan < emir de budur). Son ikisi emri `UNKNOWN`
bırakır.

Spec 0037 R-4 (D-4): komisyon üçüncü bir varlıktan (ör. BNB) kesildiyse miktar dolan miktardır;
komisyonun USDT değeri `<varlık>/USDT` fiyatıyla, fiyat okunamazsa dolan * fiyat * ayardaki ücret
oranıyla tahmin edilir (`estimated`). Değer 28 anlamlı basamağa ROUND_HALF_EVEN yuvarlanır: bir
değerlemedir, borsanın kestiği tutar `commission`'da tam durur.

Defter `maliyet = miktar * fiyat + ücret` yazar (plan 0036 Risk 1). Pozisyon miktarı net miktardır;
fiyat ödenen USDT'nin dolan miktara bölümüdür (Risk 5: 28 basamağa, alımda aşağı, satışta yukarı
yuvarlanır); ücret, defterin bakiyeden düştüğü ya da eklediği tutar borsadakiyle birebir aynı olsun
diye `ödenen - net * fiyat` (+ USDT komisyonu) olarak hesaplanır: coin komisyonu ve toz böylece
ücrete girer, kasaya girmez.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
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
# spec 0037 R-4: what `asset_price` answers for "<asset>/USDT"; `None` when it cannot be read
AssetPrice = Callable[[str], Decimal | None]


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
    `commission` ve `commission_asset` borsanın kestiği ham komisyondur. `partial`: emrin bir
    kısmı doldu, kalanı borsada sona erdi (spec 0037 R-1, R-3); `estimated`: üçüncü varlık
    komisyonunun USDT değeri ayardaki orandan tahmin (R-4)."""

    verdict: FillVerdict
    reason: str
    price: Decimal | None = None
    filled: Decimal | None = None
    net: Decimal | None = None
    fee: Decimal | None = None
    commission: Decimal | None = None
    commission_asset: str | None = None
    dust: Decimal | None = None
    partial: bool = False
    estimated: bool = False


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


# R-4: a third asset's commission valued in USDT, 28 significant digits
_VALUE = Context(
    prec=DIGITS,
    rounding=ROUND_HALF_EVEN,
    Emax=SCALE,
    Emin=-SCALE,
    traps=[InvalidOperation, DivisionByZero, Overflow],
)


def _third_value(
    asset: str,
    quote: str,
    commission: Decimal,
    filled: Decimal,
    average: Decimal,
    asset_price: AssetPrice | None,
    fee_rate: Decimal | None,
) -> tuple[Decimal, bool] | None:
    """Spec 0037 R-4: üçüncü varlık komisyonunun USDT değeri ve "tahmini" işareti; fiyat da oran da
    yoksa `None`. Fiyat sıfırdan büyük, ölçek içinde bir sayı olmalı (G-9)."""
    price = asset_price(f"{asset}/{quote}") if asset_price is not None else None
    if price is not None and not (
        isinstance(price, Decimal) and price.is_finite() and price > 0 and _in_scale(price)
    ):
        price = None
    with localcontext(_VALUE):
        if price is not None:
            return +(commission * price), False
        if fee_rate is None:
            return None
        return +(filled * average * fee_rate), True


def judge_fill(
    order: object,
    trades: object,
    *,
    side: str,
    pair: str,
    amount: Decimal,
    step: Decimal | None,
    ended: bool = False,
    asset_price: AssetPrice | None = None,
    fee_rate: Decimal | None = None,
) -> ExchangeFill:
    """R-1…R-5, R-11: "doldu" denen emrin yanıtından deftere yazılabilir dolum ya da nedeni.

    Spec 0037: `ended` iken (kalanı borsada sona ermiş ya da iptal edilmiş emir) dolan < emir kısmi
    dolumdur ve `COMPLETE`'tir (R-1, R-3); "doldu" denen emirde tutarsızlıktır (`INCOMPLETE`).
    Üçüncü varlık komisyonunun değeri `asset_price` ile, okunamazsa `fee_rate` ile (R-4)."""
    if not isinstance(order, Mapping):
        return _incomplete("emir yanıtı yok")
    filled = _decimal(order.get("filled"))
    if filled is None or filled <= 0:
        return _incomplete("dolan miktar bildirilmedi")
    partial = filled < amount
    if partial and not ended:
        return _incomplete(f"doldu denen emirde dolan ({filled}) emirden ({amount}) küçük")
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
    third: dict[str, Decimal] = {}
    for entry in entries:
        value = _decimal(entry.get("cost"))
        if value is None or value < 0:
            return _incomplete("komisyon tutarı geçersiz")
        if value == 0:  # a zero fee is valid whatever its asset (plan 0036 Risk 4)
            continue
        currency = entry.get("currency")
        if not isinstance(currency, str) or not currency:
            return _incomplete("komisyon varlığı bildirilmedi")
        try:
            with localcontext(BOUNDED):
                if currency == base:
                    if side != _BUY:
                        return _unsupported(f"satışta komisyon {currency} coininden kesildi")
                    coin += value
                elif currency == quote:
                    usdt += value
                else:  # spec 0037 R-4: a third asset, e.g. BNB
                    third[currency] = third.get(currency, Decimal(0)) + value
        except DecimalException:
            return _incomplete("komisyon tutarı geçersiz")
    if (coin > 0) + (usdt > 0) + len(third) > 1:
        return _unsupported("komisyon iki varlıktan kesildi")
    try:
        if third:
            ((asset, commission),) = third.items()
            valued = _third_value(asset, quote, commission, filled, average, asset_price, fee_rate)
            if valued is None:
                return _incomplete(f"komisyonun ({asset}) USDT değeri hesaplanamıyor")
            value, estimated = valued
            fill = _complete(side, base, quote, filled, average, cost, coin, value, step)
            if fill.verdict is not FillVerdict.COMPLETE:
                return fill
            return replace(
                fill,
                commission=commission,
                commission_asset=asset,
                partial=partial,
                estimated=estimated,
            )
        fill = _complete(side, base, quote, filled, average, cost, coin, usdt, step)
    except DecimalException:
        return _incomplete("dolum ölçeği hesaplanamıyor")
    return replace(fill, partial=partial) if fill.verdict is FillVerdict.COMPLETE else fill


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
        "dolum",
        price,
        filled,
        net,
        fee,
        commission,
        asset,
        dust,
    )


def settle_reply(
    reply: LiveReply,
    *,
    side: str,
    pair: str,
    amount: Decimal,
    step: Decimal | None,
    asset_price: AssetPrice | None = None,
    fee_rate: Decimal | None = None,
) -> Settled:
    """R-5, R-7, R-11: yanıtın emir durumu. Yalnız desteklenen dolum `FILLED`; hiçbir şey
    dolmadan biten emir `REJECTED`; geri kalan her şey `UNKNOWN` (plan 0036 Risk 9). Spec 0037
    R-1, R-3: bir kısmı dolup kalanı borsada sona eren emir dolan kısmıyla `FILLED`'dır."""
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
    fill = judge_fill(
        reply.order,
        reply.trades,
        side=side,
        pair=pair,
        amount=amount,
        step=step,
        ended=reply.status is OrderStatus.REJECTED,  # ended on the exchange with a part filled
        asset_price=asset_price,
        fee_rate=fee_rate,
    )
    if fill.verdict is FillVerdict.COMPLETE:
        return Settled(OrderStatus.FILLED, fill)
    if fill.verdict is FillVerdict.UNSUPPORTED:
        return Settled(
            OrderStatus.UNKNOWN, None, unsupported=f"desteklenmeyen dolum: {fill.reason}"
        )
    return Settled(OrderStatus.UNKNOWN, None, problem=f"eksik dolum bilgisi: {fill.reason}")
