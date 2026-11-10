"""Spec 0036: canlı turda gerçek dolum, coinden komisyon, desteklenmeyen ve eksik dolum, "emir yok"
bekleme süresi ve USDT mutabakatı (AC-1…AC-11)."""

import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import (
    BuyHalt,
    NoticeKind,
    StartOutcome,
    TurnMemory,
    TurnNotice,
    TurnResult,
    open_for_start,
    prepare_live_store,
    run_turn,
)
from crytobot.execution import (
    AssetBalance,
    CloseOrder,
    LiveExchange,
    LiveReply,
    Order,
    OrderStatus,
    client_id_part,
    stop_client_id,
)
from crytobot.persistence import load_store
from crytobot.portfolio import CloseReason
from tests.app.helpers import (
    BTC,
    CROSS,
    ETH,
    FIRST_AMOUNT,
    FLAT,
    NOW,
    make_settings,
    pair_market,
)
from tests.app.test_live_start import FakeLiveClient

DEPOSIT = Decimal(10000)
T1 = NOW + timedelta(hours=1)
T2 = NOW + timedelta(hours=2)
# FIRST_AMOUNT 49.115 at 0.1 % taken in BTC: 49.065885 kept, step 0.001 → net 49.065
COIN_FEE = FIRST_AMOUNT * Decimal("0.001")
NET = Decimal("49.065")
DUST = Decimal("0.000885")

Replier = Callable[[str, Decimal], LiveReply]


def fill(
    cid: str,
    filled: Decimal,
    average: str,
    fee: str | None,
    asset: str = "USDT",
    trades: list[dict[str, Any]] | None = None,
) -> LiveReply:
    """Borsanın "doldu" yanıtı: dolan, ortalama, ödenen (dolan * ortalama), komisyon."""
    order: dict[str, Any] = {
        "status": "closed",
        "id": cid,
        "filled": str(filled),
        "average": average,
        "cost": str(filled * Decimal(average)),
    }
    if fee is not None:
        order["fee"] = {"cost": fee, "currency": asset}
    return LiveReply(OrderStatus.FILLED, order, trades)


def ended(
    cid: str, filled: Decimal, average: str, fee: str | None, asset: str = "USDT"
) -> LiveReply:
    """Spec 0037: bir kısmı dolup kalanı borsada sona eren emrin yanıtı (adaptör `REJECTED` +
    ham emir verir)."""
    order = dict(fill(cid, filled, average, fee, asset).order or {})
    order["status"] = "expired"
    return LiveReply(OrderStatus.REJECTED, order)


def usdt_buy(average: str = "10.01", fee: str = "0.5") -> Replier:
    return lambda cid, amount: fill(cid, amount, average, fee)


def coin_buy(average: str = "10.01", fee: Decimal = COIN_FEE) -> Replier:
    return lambda cid, amount: fill(cid, amount, average, str(fee), "BTC")


def usdt_sell(average: str = "14.97", fee: str = "0.73") -> Replier:
    return lambda cid, amount: fill(cid, amount, average, fee)


class Venue(LiveExchange):
    """Senaryolu canlı borsa: alım/satış yanıtı, sorgu yanıtları, stoplar, serbest bakiye. Spec
    0037: `prices` üçüncü varlık fiyatları (yoksa okunamaz); `coins` verilirse coin bakiyeleri
    yalnız bunlardır (yoksa her coinden bol), `balances_error` coin sorgusunun hatası."""

    def __init__(
        self,
        balance: Decimal = DEPOSIT,
        buy: Replier | None = None,
        sell: Replier | None = None,
        stop_query: OrderStatus = OrderStatus.NEW,
        prices: dict[str, Decimal] | None = None,
        coins: dict[str, Decimal] | None = None,
        balances_error: Exception | None = None,
    ) -> None:
        super().__init__(client=FakeLiveClient(free_balance=balance))
        self.balance = balance
        self.buy = buy or usdt_buy()
        self.sell = sell or usdt_sell()
        self.stop_query = stop_query
        self.prices = prices or {}
        self.coins = coins
        self.balances_error = balances_error
        self.fills: dict[str, LiveReply] = {}
        self.markets: list[dict[str, Any]] = []
        self.stops: list[dict[str, Any]] = []
        self.queried: list[str] = []
        self.priced: list[str] = []

    def fetch_free_balance(self, asset: str = "USDT") -> Decimal:
        return self.balance

    def fetch_balances(self) -> dict[str, AssetBalance]:
        if self.balances_error is not None:
            raise self.balances_error
        if self.coins is None:
            return super().fetch_balances()
        found = {coin: AssetBalance(total, total) for coin, total in self.coins.items()}
        return {"USDT": AssetBalance(self.balance, self.balance), **found}

    def last_price(self, symbol: str) -> Decimal | None:
        self.priced.append(symbol)
        return self.prices.get(symbol)

    def place_market(
        self, client_order_id: str, symbol: str = "", side: str = "", amount: object = None
    ) -> LiveReply:
        self.markets.append({"id": client_order_id, "side": side, "amount": amount})
        replier = self.buy if side == "buy" else self.sell
        return replier(client_order_id, Decimal(str(amount)))

    def query_fill(self, client_order_id: str, symbol: str = "") -> LiveReply:
        self.queried.append(client_order_id)
        return self.fills.get(client_order_id, LiveReply(OrderStatus.UNKNOWN))

    def query(self, client_order_id: str, symbol: str = "") -> OrderStatus:
        parsed = client_id_part(client_order_id)
        if parsed is not None and parsed[0] == "cs":  # every stop generation (spec 0037)
            return self.stop_query
        return OrderStatus.UNKNOWN

    def place_stop_order(
        self,
        client_order_id: str,
        symbol: str = "",
        amount: object = None,
        stop_price: object = None,
        limit_price: object = None,
    ) -> OrderStatus:
        self.stops.append({"id": client_order_id, "amount": amount})
        return OrderStatus.NEW

    def cancel_order(self, client_order_id: str, symbol: str = "") -> OrderStatus:
        return OrderStatus.CANCELED

    def fetch_order(self, client_order_id: str, symbol: str = "") -> dict[str, Any] | None:
        return None


def live_store(tmp_path: Path, name: str = "live.db") -> str:
    path = str(tmp_path / name)
    prepare_live_store(path, NOW, live_client=FakeLiveClient(free_balance=DEPOSIT))
    return path


def turn(
    path: str,
    venue: Venue,
    market: dict[str, Any],
    now: datetime = NOW,
    *,
    memory: TurnMemory | None = None,
    notices: list[TurnNotice] | None = None,
    whitelist: tuple[str, ...] = (BTC,),
) -> TurnResult:
    return run_turn(
        market=market,
        settings=make_settings(whitelist=whitelist),
        store_path=path,
        now=now,
        exchange=venue,
        sink=(notices if notices is not None else []).append,
        memory=memory if memory is not None else TurnMemory(),
    )


def stored(path: str) -> Any:
    loaded = load_store(path, "live")
    assert loaded.state is not None
    assert loaded.conflicts == ()
    return loaded.state


def ledger_balance(path: str) -> Decimal:
    balance: Decimal | None = stored(path).ledger.balance
    assert balance is not None
    return balance


BUY_MARKET = {BTC: pair_market(closes=CROSS)}


def target_market(at: datetime, price: str = "15") -> dict[str, Any]:
    return {BTC: pair_market(closes=FLAT, price=Decimal(price), closed_at=at)}


def test_buy_records_exchange_average_and_fee(tmp_path: Path) -> None:
    """AC-1 (R-1): borsa ortalama fiyatı tahminden (10.01) farklı bildirdiğinde defterdeki maliyet
    fiyatı ve ücret borsanın değerleridir; emir kaydı da gerçek dolumu taşır."""
    path = live_store(tmp_path)
    result = turn(path, Venue(buy=usdt_buy("10.02", "0.4")), BUY_MARKET)
    assert [o.status for o in result.buys] == [OrderStatus.FILLED]
    order = result.buys[0]
    assert order.fill_price == Decimal("10.02") != Decimal("10.01")
    assert order.fee == Decimal("0.4")
    state = stored(path)
    position = state.ledger.positions[order.client_order_id]
    assert (position.amount, position.cost_price, position.fee) == (
        FIRST_AMOUNT,
        Decimal("10.02"),
        Decimal("0.4"),
    )
    assert state.ledger.balance == DEPOSIT - FIRST_AMOUNT * Decimal("10.02") - Decimal("0.4")
    assert state.execution.orders[order.client_order_id] == order


def test_coin_fee_position_net_dust_outside_equity(tmp_path: Path) -> None:
    """AC-2 (R-2): komisyon coinden kesilince pozisyon net miktardır; toz emir kaydındadır, kasaya
    katılmaz; defterin USDT bakiyesinden borsada ödenen tutar (dolan * ortalama) düşer."""
    path = live_store(tmp_path)
    result = turn(path, Venue(buy=coin_buy()), BUY_MARKET)
    order = result.buys[0]
    assert (order.filled, order.net, order.dust) == (FIRST_AMOUNT, NET, DUST)
    assert (order.commission, order.commission_asset) == (COIN_FEE, "BTC")
    state = stored(path)
    position = state.ledger.positions[order.client_order_id]
    assert position.amount == NET
    paid = FIRST_AMOUNT * Decimal("10.01")
    assert state.ledger.balance == DEPOSIT - paid
    assert result.equity == state.ledger.balance + NET * Decimal(10)  # dust is not in the equity
    assert state.execution.orders[order.client_order_id].dust == DUST


def test_net_below_minimum_records_and_halts(tmp_path: Path) -> None:
    """AC-2 (R-2, G-1; plan Risk 7): net miktar asgari tutarın altındaysa pozisyon yine kaydedilir,
    güvenli mod devreye girer, alım durur, bildirim üretilir; sonraki turda da sürer."""
    path = live_store(tmp_path)
    notices: list[TurnNotice] = []
    memory = TurnMemory()
    venue = Venue(buy=coin_buy(fee=FIRST_AMOUNT - Decimal("0.5")))  # 0.5 * 10 < 10 USDT minimum
    market = {BTC: pair_market(closes=CROSS), ETH: pair_market(closes=CROSS)}
    result = turn(path, venue, market, memory=memory, notices=notices, whitelist=(BTC, ETH))
    assert [o.pair for o in result.buys] == [BTC]
    subject = result.buys[0].client_order_id
    assert stored(path).ledger.positions[subject].amount == Decimal("0.5")
    assert BuyHalt.POSITION_BELOW_MINIMUM in result.halts
    entered = [n for n in notices if n.kind is NoticeKind.POSITION_BELOW_MINIMUM]
    assert [(n.subject, n.entering) for n in entered] == [(subject, True)]
    assert BTC in entered[0].message and subject in entered[0].message

    later = {BTC: pair_market(closes=FLAT, closed_at=T1), ETH: pair_market(closed_at=T1)}
    venue_later = Venue(balance=ledger_balance(path))
    again = turn(path, venue_later, later, T1, memory=memory, notices=notices, whitelist=(BTC, ETH))
    assert BuyHalt.POSITION_BELOW_MINIMUM in again.halts
    assert again.buys == ()
    assert [n.entering for n in notices if n.kind is NoticeKind.POSITION_BELOW_MINIMUM] == [True]


def test_close_sells_net_and_records_real_fill(tmp_path: Path) -> None:
    """AC-4 (R-4): kapanış satışı net miktarla verilir; tam dolan kapanış ortalama fiyat ve
    gerçek komisyonla deftere geçer."""
    path = live_store(tmp_path)
    turn(path, Venue(buy=coin_buy()), BUY_MARKET)
    venue = Venue(balance=ledger_balance(path), sell=usdt_sell("14.97", "0.73"))
    result = turn(path, venue, target_market(T1), T1)
    sells = [m for m in venue.markets if m["side"] == "sell"]
    assert [m["amount"] for m in sells] == [NET]
    (closure,) = result.closures
    assert (closure.amount, closure.price, closure.fee) == (NET, Decimal("14.97"), Decimal("0.73"))
    assert closure.proceeds == NET * Decimal("14.97") - Decimal("0.73")
    assert stored(path).ledger.positions == {}


def test_exchange_stop_fill_records_real_fill(tmp_path: Path) -> None:
    """AC-4 (R-4; plan Risk 2, 3): borsada dolan stop, borsanın ortalama fiyatı ve emrin
    işlemlerinden gelen komisyonla deftere geçer; tahmin yazılmaz."""
    path = live_store(tmp_path)
    first = turn(path, Venue(), BUY_MARKET)
    subject = first.buys[0].client_order_id
    stop_id = stop_client_id(subject)
    venue = Venue(balance=ledger_balance(path), stop_query=OrderStatus.FILLED)
    trades = [{"amount": str(FIRST_AMOUNT), "fee": {"cost": "0.39", "currency": "USDT"}}]
    venue.fills[stop_id] = fill(stop_id, FIRST_AMOUNT, "7.95", None, trades=trades)
    result = turn(path, venue, target_market(T1, "7.9"), T1)
    (closure,) = result.closures
    assert closure.client_order_id == stop_id
    assert closure.reason is CloseReason.STOP
    assert (closure.price, closure.fee) == (Decimal("7.95"), Decimal("0.39"))
    assert BuyHalt.STOP_ORDER_FAILED not in result.halts


def test_incomplete_exchange_stop_fill_is_not_recorded(tmp_path: Path) -> None:
    """Plan 0036 Risk 3: komisyonu bildirilmeyen stop dolumu tahminle yazılmaz; alım durur."""
    path = live_store(tmp_path)
    subject = turn(path, Venue(), BUY_MARKET).buys[0].client_order_id
    stop_id = stop_client_id(subject)
    venue = Venue(balance=ledger_balance(path), stop_query=OrderStatus.FILLED)
    venue.fills[stop_id] = fill(stop_id, FIRST_AMOUNT, "7.95", None)
    notices: list[TurnNotice] = []
    result = turn(path, venue, target_market(T1, "10"), T1, notices=notices)
    assert result.closures == ()
    assert BuyHalt.STOP_ORDER_FAILED in result.halts
    assert subject in stored(path).ledger.positions
    failed = [n for n in notices if n.kind is NoticeKind.STOP_ORDER_FAILED]
    assert failed and "komisyon bildirilmedi" in failed[0].message


@pytest.mark.parametrize("case", ["partial_buy", "third_asset_buy", "partial_close"])
def test_partial_and_bnb_fills_recorded_without_safe_mode(tmp_path: Path, case: str) -> None:
    """Spec 0037 AC-6 (R-6; plan Risk 6): 0036'da güvenli moda geçiren üç vaka — kalanı sona eren
    kısmi alım, kısmi kapanış, üçüncü varlıktan (BNB) komisyonlu alım — artık deftere yazılır:
    emir `FILLED`, durumu bilinmeyen emir yok, güvenli mod ve "desteklenmeyen dolum" bildirimi
    yok; ikinci çiftin alımı aynı turda sürer."""
    path = live_store(tmp_path)
    notices: list[TurnNotice] = []
    both = (BTC, ETH)
    order: Order | CloseOrder
    if case == "partial_close":
        turn(path, Venue(), BUY_MARKET)
        partial: Replier = lambda cid, amount: ended(cid, amount - 1, "14.97", "0.7")  # noqa: E731
        venue = Venue(balance=ledger_balance(path), sell=partial)
        market = {**target_market(T1), ETH: pair_market(closes=CROSS, closed_at=T1)}
        result = turn(path, venue, market, T1, notices=notices, whitelist=both)
        (closure,) = result.closures
        assert closure.amount == FIRST_AMOUNT - 1
        assert stored(path).ledger.positions[closure.position.client_order_id].amount == 1
        order = result.closes[0]
        assert [o.pair for o in result.buys] == [ETH]
    else:
        replier: Replier = (
            (lambda cid, amount: ended(cid, amount - 1, "10.01", "0.5"))
            if case == "partial_buy"
            else (lambda cid, amount: fill(cid, amount, "10.01", "0.02", "BNB"))
        )
        market = {BTC: pair_market(closes=CROSS), ETH: pair_market(closes=CROSS)}
        result = turn(path, Venue(buy=replier), market, notices=notices, whitelist=both)
        order = result.buys[0]
        position = stored(path).ledger.positions[order.client_order_id]
        assert position.amount == (FIRST_AMOUNT - 1 if case == "partial_buy" else FIRST_AMOUNT)
        assert [o.pair for o in result.buys] == [BTC, ETH]
    assert order.status is OrderStatus.FILLED
    assert BuyHalt.UNKNOWN_ORDERS not in result.halts
    assert stored(path).execution.unknown == ()
    assert not any(n.kind is NoticeKind.UNSUPPORTED_FILL for n in notices)
    assert not any(n.kind is NoticeKind.SAFE_MODE for n in notices)


def test_partial_close_rest_retried_next_turn(tmp_path: Path) -> None:
    """Spec 0037 AC-6 (R-3, R-6; plan Risk 6 — 0036'nın "yeniden denenmez" testi): kısmi dolan
    kapanıştan sonraki turda kalan pozisyon yeniden değerlendirilir ve hedefteyse sonraki nesil
    kimlikle (`cx2-`) kalan miktar satılır; "elle bakılmalı" bildirimi yoktur."""
    path = live_store(tmp_path)
    turn(path, Venue(), BUY_MARKET)
    memory = TurnMemory()
    notices: list[TurnNotice] = []
    partial: Replier = lambda cid, amount: ended(cid, amount - 1, "14.97", "0.7")  # noqa: E731
    venue = Venue(balance=ledger_balance(path), sell=partial)
    close_id = turn(path, venue, target_market(T1), T1, memory=memory, notices=notices).closes[0]
    assert close_id.client_order_id.startswith("cx-")

    again = Venue(balance=ledger_balance(path))
    later = turn(path, again, target_market(T2), T2, memory=memory, notices=notices)
    assert again.queried == []
    sells = [m for m in again.markets if m["side"] == "sell"]
    assert [(m["id"][:4], m["amount"]) for m in sells] == [("cx2-", Decimal(1))]
    assert BuyHalt.UNKNOWN_ORDERS not in later.halts
    assert stored(path).ledger.positions == {}
    assert not any(n.kind is NoticeKind.UNSUPPORTED_FILL for n in notices)


def test_exchange_stop_uses_net_amount(tmp_path: Path) -> None:
    """AC-6 (R-6, S-2): 0034 borsa stop emri pozisyonun net miktarıyla verilir."""
    path = live_store(tmp_path)
    venue = Venue(buy=coin_buy())
    subject = turn(path, venue, BUY_MARKET).buys[0].client_order_id
    assert venue.stops == [{"id": stop_client_id(subject), "amount": NET}]


def test_not_found_restart_resets_count(tmp_path: Path) -> None:
    """AC-8 (R-8, D-5): "emir yok" gözlemi süreç belleğindedir; bot yeniden başlarsa ilk gözlem yine
    `UNKNOWN` bırakır, ancak sonraki turdaki tekrar emri reddeder."""
    path = live_store(tmp_path)
    placed = turn(path, Venue(buy=lambda cid, amount: LiveReply(OrderStatus.UNKNOWN)), BUY_MARKET)
    cid = placed.buys[0].client_order_id
    venue = Venue()
    venue.fills[cid] = LiveReply(OrderStatus.UNKNOWN, missing=True)
    first_process = TurnMemory()
    turn(path, venue, BUY_MARKET, NOW + timedelta(minutes=6), memory=first_process)
    assert stored(path).execution.unknown == (cid,)

    restarted = TurnMemory()
    turn(path, venue, BUY_MARKET, NOW + timedelta(minutes=12), memory=restarted)
    assert stored(path).execution.unknown == (cid,)

    result = turn(path, venue, BUY_MARKET, NOW + timedelta(minutes=18), memory=restarted)
    state = stored(path)
    assert state.execution.unknown == ()
    assert state.execution.orders[cid].status is OrderStatus.REJECTED
    assert state.ledger.positions == {}
    assert [o.status for o in result.buys] == [OrderStatus.REJECTED]


class NoStopClient(FakeLiveClient):
    """Gerçek `LiveExchange` altında: alım tam dolar; stop sorgusu "emir yok" der."""

    def __init__(self) -> None:
        super().__init__(free_balance=DEPOSIT)
        self.stop_calls: list[str] = []

    def place_market_order(
        self, symbol: str, side: str, amount: str, client_order_id: str
    ) -> dict[str, Any]:
        return dict(fill(client_order_id, Decimal(amount), "10.01", "0.5").order or {})

    def place_stop_order(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.stop_calls.append(kwargs["client_order_id"])
        return {"status": "open", "id": kwargs["client_order_id"]}


def test_stop_order_not_found_unchanged(tmp_path: Path) -> None:
    """AC-8 (G-6): borsa stop emirleri (`cs-`) bu kurala girmez, 0034'teki gibi kalır: borsada
    olmayan stop ilk gözlemde, 5 dakika beklemeden yeniden verilir."""
    path = live_store(tmp_path)
    client = NoStopClient()
    exchange = LiveExchange(client)
    first = run_turn(
        market=BUY_MARKET,
        settings=make_settings(),
        store_path=path,
        now=NOW,
        exchange=exchange,
        sink=lambda n: None,
        memory=TurnMemory(),
    )
    stop_id = stop_client_id(first.buys[0].client_order_id)
    assert client.stop_calls == [stop_id]
    run_turn(
        market={BTC: pair_market(closes=FLAT)},
        settings=make_settings(),
        store_path=path,
        now=NOW + timedelta(minutes=1),
        exchange=exchange,
        sink=lambda n: None,
        memory=TurnMemory(),
    )
    assert client.stop_calls == [stop_id, stop_id]


def test_unknown_buy_resolves_with_real_fill(tmp_path: Path) -> None:
    """AC-9 (R-9, R-10): `UNKNOWN` kalan canlı alım sonraki turda dolmuş çıkınca deftere borsanın
    gerçek dolumu (tahmin değil) net miktarla yazılır, depo çelişki taşımaz, güvenli mod biter."""
    path = live_store(tmp_path)
    placed = turn(path, Venue(buy=lambda cid, amount: LiveReply(OrderStatus.UNKNOWN)), BUY_MARKET)
    cid = placed.buys[0].client_order_id
    assert stored(path).execution.quotes[cid][0] == Decimal("10.01")
    venue = Venue(stop_query=OrderStatus.REJECTED)  # no stop yet: the unknown buy had none
    venue.fills[cid] = fill(cid, FIRST_AMOUNT, "10.03", str(COIN_FEE), "BTC")
    result = turn(path, venue, target_market(T1, "10"), T1)
    assert BuyHalt.UNKNOWN_ORDERS not in result.halts
    state = stored(path)
    position = state.ledger.positions[cid]
    assert (position.amount, position.cost_price) == (NET, Decimal("10.03"))
    assert state.ledger.balance == DEPOSIT - FIRST_AMOUNT * Decimal("10.03")
    assert state.execution.orders[cid].fill_price == Decimal("10.03")
    assert venue.stops == [{"id": stop_client_id(cid), "amount": NET}]


def test_incomplete_fill_stays_unknown(tmp_path: Path) -> None:
    """AC-10 (R-11): "doldu" yanıtında komisyon yoksa (işlemler de alınamadıysa) emir `UNKNOWN`
    olur, defter tahmin yazmaz, güvenli mod devreye girer."""
    path = live_store(tmp_path)
    notices: list[TurnNotice] = []
    venue = Venue(buy=lambda cid, amount: fill(cid, amount, "10.01", None))
    result = turn(path, venue, BUY_MARKET, notices=notices)
    assert [o.status for o in result.buys] == [OrderStatus.UNKNOWN]
    assert stored(path).ledger.positions == {}
    assert stored(path).ledger.balance == DEPOSIT
    assert BuyHalt.UNKNOWN_ORDERS in result.halts
    assert any(n.kind is NoticeKind.SAFE_MODE and n.entering for n in notices)
    assert not any(n.kind is NoticeKind.UNSUPPORTED_FILL for n in notices)


def test_zero_fee_fill_is_recorded(tmp_path: Path) -> None:
    """AC-10 (R-11, G-4): sıfır komisyonlu dolum geçerlidir ve deftere yazılır."""
    path = live_store(tmp_path)
    result = turn(path, Venue(buy=usdt_buy("10.01", "0")), BUY_MARKET)
    order = result.buys[0]
    assert order.status is OrderStatus.FILLED and order.fee == 0
    assert stored(path).ledger.positions[order.client_order_id].fee == 0


def test_balance_reconciles_after_coin_fee_buy_and_close(tmp_path: Path) -> None:
    """AC-11 (R-10, R-12): coinden komisyonlu bir alım ve bir kapanıştan sonra borsa bakiyesi
    gerçek dolumlara uyduğunda mutabakat durdurması ve defter ↔ emir çelişkisi oluşmaz."""
    path = live_store(tmp_path)
    turn(path, Venue(buy=coin_buy()), BUY_MARKET)
    exchange_balance = DEPOSIT - FIRST_AMOUNT * Decimal("10.01")  # what Binance debited
    closing_turn = turn(path, Venue(balance=exchange_balance), target_market(T1), T1)
    assert BuyHalt.RECONCILIATION_HALT not in closing_turn.halts
    assert len(closing_turn.closures) == 1
    exchange_balance += NET * Decimal("14.97") - Decimal("0.73")  # what Binance credited
    after = turn(path, Venue(balance=exchange_balance), target_market(T2, "10"), T2)
    assert BuyHalt.RECONCILIATION_HALT not in after.halts
    assert BuyHalt.RECONCILIATION not in after.halts
    assert ledger_balance(path) == exchange_balance  # stored() also asserts no conflicts


def test_old_live_store_start_names_prepare(tmp_path: Path) -> None:
    """AC-12 (R-13): eski canlı depo başlatmada adıyla reddedilir, `prepare --live` istenir."""
    path = live_store(tmp_path)
    with closing(sqlite3.connect(path)) as database:
        database.execute("DELETE FROM meta WHERE key = 'fills'")
        database.commit()
    check = open_for_start(path, mode="live")
    assert check.outcome is StartOutcome.LIVE_STORE_OUTDATED
    assert "eski canlı depo" in check.message
    assert check.hint is not None and "prepare --live" in check.hint
