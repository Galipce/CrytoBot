"""Spec 0036 AC-2, AC-3, AC-5, AC-10: canlı dolum yargısı (net, toz, komisyon, eksik bilgi)."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from types import MappingProxyType
from typing import Any

import ccxt
import pytest

from crytobot.execution import (
    EMPTY_EXECUTION,
    BinanceLiveClient,
    CloseOrder,
    ExchangeCredentials,
    ExecutionState,
    FillVerdict,
    LiveExchange,
    LiveReply,
    OrderRequest,
    OrderStatus,
    execution_problems,
    judge_fill,
    place_order,
    settle_reply,
)
from crytobot.risk import PairRules, TradeApproval, TradeIntent

PAIR = "BTC/USDT"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def order(
    filled: object = "1",
    average: object = "100",
    cost: object = "100",
    fee: object = None,
    fees: object = None,
    **extra: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {"status": "closed", "id": "42", "filled": filled, "average": average}
    if cost is not None:
        row["cost"] = cost
    if fee is not None:
        row["fee"] = fee
    if fees is not None:
        row["fees"] = fees
    row.update(extra)
    return row


def buy(raw: object, trades: object = None, amount: str = "1", step: str | None = "0.01") -> Any:
    return judge_fill(
        raw,
        trades,
        side="buy",
        pair=PAIR,
        amount=Decimal(amount),
        step=None if step is None else Decimal(step),
    )


def sell(raw: object, trades: object = None, amount: str = "1") -> Any:
    return judge_fill(raw, trades, side="sell", pair=PAIR, amount=Decimal(amount), step=None)


def test_coin_fee_net_amount_and_dust() -> None:
    """AC-2 (R-2): adım 0,01, 1 coin dolar, 0,001 coin komisyon → net 0,99, toz 0,009. Defterin
    USDT'den düştüğü tutar (net * fiyat + ücret) borsada ödenen tutardır (dolan * ortalama)."""
    fill = buy(order(fee={"cost": "0.001", "currency": "BTC"}))
    assert fill.verdict is FillVerdict.COMPLETE
    assert fill.filled == Decimal(1)
    assert fill.net == Decimal("0.99")
    assert fill.dust == Decimal("0.009")
    assert (fill.commission, fill.commission_asset) == (Decimal("0.001"), "BTC")
    assert fill.price == Decimal(100)
    assert fill.net * fill.price + fill.fee == Decimal(1) * Decimal(100)


def test_usdt_fee_keeps_filled_amount() -> None:
    """AC-3 (R-3): komisyon USDT ise pozisyon dolan miktardır, komisyon maliyete eklenir."""
    fill = buy(order(fee={"cost": "0.1", "currency": "USDT"}))
    assert fill.verdict is FillVerdict.COMPLETE
    assert fill.net == fill.filled == Decimal(1)
    assert fill.dust == 0
    assert fill.fee == Decimal("0.1")
    assert (fill.commission, fill.commission_asset) == (Decimal("0.1"), "USDT")
    assert fill.net * fill.price + fill.fee == Decimal("100.1")


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        (order(average=None, fee={"cost": "0.1", "currency": "USDT"}), "ortalama fiyat"),
        (order(filled=None, fee={"cost": "0.1", "currency": "USDT"}), "dolan miktar"),
        (order(), "komisyon bildirilmedi"),
        (order(fees=[]), "komisyon bildirilmedi"),
        (order(fee={"cost": None, "currency": "USDT"}), "komisyon bildirilmedi"),
        (order(fee={"cost": "0.1"}), "komisyon varlığı"),
        (order(fees=[{"cost": "x", "currency": "USDT"}]), "komisyon tutarı"),
        (order(cost="0", fee={"cost": "0.1", "currency": "USDT"}), "ödenen tutar"),
        (order(filled="2", fee={"cost": "0.1", "currency": "USDT"}), "emirden"),
        (None, "emir yanıtı"),
    ],
)
def test_missing_fill_fields_are_incomplete(raw: object, why: str) -> None:
    """AC-10 (R-11): "doldu" yanıtında ortalama fiyat, dolan miktar ya da komisyon yoksa tahmin
    yazılmaz: yargı eksik bilgidir, emir `UNKNOWN` kalır."""
    fill = buy(raw)
    assert fill.verdict is FillVerdict.INCOMPLETE
    assert why in fill.reason
    assert fill.price is None and fill.fee is None and fill.net is None
    settled = settle_reply(
        LiveReply(OrderStatus.FILLED, raw if isinstance(raw, dict) else None),
        side="buy",
        pair=PAIR,
        amount=Decimal(1),
        step=Decimal("0.01"),
    )
    assert settled.status is OrderStatus.UNKNOWN
    assert settled.fill is None and settled.unsupported is None
    assert settled.problem is not None and "eksik dolum bilgisi" in settled.problem


@pytest.mark.parametrize("asset", ["BNB", "USDT", "BTC"])
def test_zero_fee_is_valid(asset: str) -> None:
    """AC-10 (R-11, G-4; plan Risk 4): sıfır komisyon geçerlidir, varlığı ne olursa olsun."""
    fill = buy(order(fees=[{"cost": "0", "currency": asset}]))
    assert fill.verdict is FillVerdict.COMPLETE
    assert fill.fee == 0 and fill.commission == 0
    assert fill.net == Decimal(1)


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        (order(filled="0.5", fee={"cost": "0.05", "currency": "USDT"}), "kısmi dolum"),
        (order(fee={"cost": "0.0001", "currency": "BNB"}), "BNB"),
        (
            order(fees=[{"cost": "0.001", "currency": "BTC"}, {"cost": "0.1", "currency": "USDT"}]),
            "iki varlık",
        ),
        (order(filled="0.01", cost="1", fee={"cost": "0.01", "currency": "BTC"}), "net miktar"),
    ],
)
def test_unsupported_buy_fills(raw: dict[str, Any], why: str) -> None:
    """AC-5 (R-5): kısmi dolum ve üçüncü varlıktan komisyon desteklenmez; emir `UNKNOWN`."""
    amount = raw["filled"] if why == "net miktar" else "1"
    fill = buy(raw, amount=amount)
    assert fill.verdict is FillVerdict.UNSUPPORTED
    assert why in fill.reason
    settled = settle_reply(
        LiveReply(OrderStatus.FILLED, raw),
        side="buy",
        pair=PAIR,
        amount=Decimal(amount),
        step=Decimal("0.01"),
    )
    assert settled.status is OrderStatus.UNKNOWN
    assert settled.unsupported is not None and why in settled.unsupported


def test_sell_fee_from_usdt_and_coin_fee_unsupported() -> None:
    """R-4: satışta komisyon USDT'den; gelir = dolan * fiyat - ücret = alınan USDT. Coinden
    kesilmişse desteklenmez (R-5)."""
    fill = sell(order(cost="100", fee={"cost": "0.1", "currency": "USDT"}))
    assert fill.verdict is FillVerdict.COMPLETE
    assert fill.net == fill.filled == Decimal(1) and fill.dust == 0
    assert fill.filled * fill.price - fill.fee == Decimal("99.9")
    coin = sell(order(fee={"cost": "0.001", "currency": "BTC"}))
    assert coin.verdict is FillVerdict.UNSUPPORTED


def test_fee_from_trades_when_order_has_none() -> None:
    """Plan 0036 Risk 2: emir sorgusu komisyon vermez; işlemler dolan miktarın tamamını
    kapsıyorsa komisyon onlardan, kapsamıyorsa eksik bilgidir."""
    trades = [
        {"amount": "0.4", "fee": {"cost": "0.04", "currency": "USDT"}},
        {"amount": "0.6", "fees": [{"cost": "0.06", "currency": "USDT"}]},
    ]
    fill = buy(order(), trades)
    assert fill.verdict is FillVerdict.COMPLETE
    assert fill.fee == Decimal("0.10")
    assert buy(order(), trades[:1]).verdict is FillVerdict.INCOMPLETE
    assert buy(order(), [{"amount": "1"}]).verdict is FillVerdict.INCOMPLETE
    assert buy(order(), [{"amount": None, "fee": {"cost": "0"}}]).verdict is FillVerdict.INCOMPLETE
    assert buy(order(), "not trades").verdict is FillVerdict.INCOMPLETE


def test_long_average_is_rounded_so_the_balance_matches() -> None:
    """Plan 0036 Risk 5: ödenen / dolan uzun basamak verir; fiyat 28 basamağa alımda aşağı,
    satışta yukarı yuvarlanır, ücret farkı taşır: bakiye borsadakiyle birebir aynı kalır."""
    raw = order(filled="3", cost="10", average="3.3333333333333333333333333333333333")
    raw["fee"] = {"cost": "0", "currency": "USDT"}
    bought = buy(raw, amount="3")
    assert bought.verdict is FillVerdict.COMPLETE
    assert bought.price == Decimal("3.333333333333333333333333333")
    assert bought.fee is not None and bought.fee >= 0
    sold = sell(raw, amount="3")
    assert sold.verdict is FillVerdict.COMPLETE
    assert sold.price == Decimal("3.333333333333333333333333334")
    with localcontext(prec=60):  # the ledger calculates exactly (60 digits)
        assert bought.net * bought.price + bought.fee == Decimal(10)
        assert sold.filled * sold.price - sold.fee == Decimal(10)


def test_without_cost_the_paid_amount_is_filled_times_average() -> None:
    """R-2: ödenen tutar bildirilmezse dolan * ortalama; uzun ortalama aynı kuralla yuvarlanır."""
    fill = buy(order(cost=None, average="100.5", fee={"cost": "0", "currency": "USDT"}))
    assert fill.price == Decimal("100.5") and fill.fee == 0
    long_average = "1." + "3" * 40
    raw = order(cost=None, average=long_average, fee={"cost": "0", "currency": "USDT"})
    assert buy(raw).price == Decimal("1." + "3" * 27)
    assert sell(raw).price == Decimal("1." + "3" * 26 + "4")


def test_a_buy_needs_the_amount_step() -> None:
    assert buy(order(fee={"cost": "0", "currency": "USDT"}), step=None).verdict is (
        FillVerdict.INCOMPLETE
    )


def test_numbers_from_the_exchange() -> None:
    """Sayı metin, `int`, `Decimal` ya da `float` (repr ile) olabilir; `bool`, sonsuz ve tanınmayan
    tür sayı değildir."""
    for filled in (1, Decimal(1), 1.0):
        assert buy(order(filled=filled, fee={"cost": 0, "currency": "USDT"})).net == Decimal(1)
    for bad in (True, "inf", "abc", [1]):
        assert buy(order(filled=bad, fee={"cost": "0", "currency": "USDT"})).verdict is (
            FillVerdict.INCOMPLETE
        )


def test_out_of_scale_fill_is_incomplete() -> None:
    raw = order(
        filled="1", cost="1E+40", average="1E+40", fee={"cost": "1E-40", "currency": "USDT"}
    )
    assert buy(raw).verdict is FillVerdict.INCOMPLETE


@pytest.mark.parametrize(
    ("reply", "status"),
    [
        (LiveReply(OrderStatus.REJECTED), OrderStatus.REJECTED),
        (
            LiveReply(OrderStatus.REJECTED, {"status": "expired", "filled": "0"}),
            OrderStatus.REJECTED,
        ),
        (
            LiveReply(OrderStatus.REJECTED, {"status": "expired", "filled": "0.5"}),
            OrderStatus.UNKNOWN,
        ),
        (LiveReply(OrderStatus.REJECTED, {"status": "expired"}), OrderStatus.UNKNOWN),
        (LiveReply(OrderStatus.UNKNOWN), OrderStatus.UNKNOWN),
        (LiveReply(OrderStatus.NEW, {"status": "open"}), OrderStatus.UNKNOWN),
    ],
)
def test_settle_reply_statuses(reply: LiveReply, status: OrderStatus) -> None:
    """Plan 0036 Risk 9: hiçbir şey dolmadan biten emir kesin ret; kısmen dolup biten ya da dolan
    miktarı bilinmeyen emir `UNKNOWN`."""
    settled = settle_reply(reply, side="buy", pair=PAIR, amount=Decimal(1), step=Decimal("0.01"))
    assert settled.status is status
    assert settled.fill is None


class TradesCcxt:
    """ccxt sahtesi: piyasa emri komisyonsuz "closed" döner; işlemler `fetch_my_trades`'ten."""

    def __init__(self, trades: object = None, error: Exception | None = None) -> None:
        self.trades = trades
        self.error = error
        self.trade_calls: list[tuple[str, dict[str, Any]]] = []
        self.on_rest_response: Any = None
        self.number = str

    def create_order(self, symbol: str, type: str, side: str, amount: str, **kw: Any) -> Any:
        cost = str(Decimal(amount) * 100)
        return {"status": "closed", "id": "777", "filled": amount, "average": "100", "cost": cost}

    def fetch_my_trades(self, symbol: str, params: dict[str, Any]) -> Any:
        self.trade_calls.append((symbol, params))
        if self.error is not None:
            raise self.error
        return self.trades


def live_buy(fake: TradesCcxt) -> Any:
    creds = ExchangeCredentials(api_key="k", api_secret="s", testnet=False)
    venue = LiveExchange(BinanceLiveClient(creds, exchange=fake))
    intent = TradeIntent(PAIR, "buy", Decimal(100), Decimal(95), Decimal(110))
    approval = TradeApproval(Decimal(1), None, False, "onay", intent)
    rules = PairRules(Decimal("0.01"), Decimal("0.01"), Decimal(5))
    request = OrderRequest(
        "t1", intent, approval, rules, Decimal(100), Decimal("0.001"), Decimal(0), "live"
    )
    return place_order(EMPTY_EXECUTION, request, venue, NOW)


def test_live_fee_comes_from_the_order_trades() -> None:
    """Plan 0036 Risk 2: yanıtta komisyon yoksa adaptör emrin işlemlerini (`orderId`) sorar."""
    fake = TradesCcxt([{"amount": "1", "fee": {"cost": "0.001", "currency": "BTC"}}])
    result = live_buy(fake)
    assert fake.trade_calls == [(PAIR, {"orderId": "777"})]
    assert result.order.status is OrderStatus.FILLED
    assert (result.order.net, result.order.dust) == (Decimal("0.99"), Decimal("0.009"))


@pytest.mark.parametrize(
    "fake",
    [TradesCcxt(error=ccxt.NetworkError("network")), TradesCcxt("not a list"), TradesCcxt([])],
    ids=["error", "not-a-list", "empty"],
)
def test_failed_trades_leave_the_fill_unknown(fake: TradesCcxt) -> None:
    """Spec 0034 F-4, R-11: işlemler alınamazsa istisna çıkmaz; dolum eksik bilgidir, emir
    `UNKNOWN` kaydedilir ve sonraki turda yeniden sorulur."""
    result = live_buy(fake)
    assert result.order.status is OrderStatus.UNKNOWN
    assert result.state.unknown == ("cb-t1",)


def test_execution_problems_checks_exchange_fill() -> None:
    """Spec 0036: depo yalnız `execution`'ın üretebileceği borsa dolumunu kabul eder."""
    fake = TradesCcxt([{"amount": "1", "fee": {"cost": "0.001", "currency": "BTC"}}])
    state = live_buy(fake).state
    good = state.orders["cb-t1"]
    assert execution_problems(state) == []

    def problems(**changes: Any) -> list[str]:
        orders = {"cb-t1": replace(good, **changes)}
        return execution_problems(ExecutionState(MappingProxyType(orders), state.quotes))

    assert problems(net=Decimal(2)) == ["emir 0: borsa dolumunun miktarı emirle uyuşmuyor"]
    assert problems(filled=Decimal("0.5")) == ["emir 0: borsa dolumunun miktarı emirle uyuşmuyor"]
    assert problems(commission_asset="") == ["emir 0: borsa dolumu geçersiz"]
    assert problems(dust=Decimal(-1)) == ["emir 0: borsa dolumu geçersiz"]
    assert problems(net=None) == ["emir 0: borsa dolumu geçersiz"]
    unfilled = {"cb-t1": replace(good, status=OrderStatus.REJECTED, fill_price=None, fee=None)}
    rejected = ExecutionState(MappingProxyType(unfilled), state.quotes)
    assert execution_problems(rejected) == ["emir 0: dolmamış emirde borsa dolumu var"]
    close = CloseOrder(
        "cx-t1", "cb-t1", PAIR, "sell", Decimal(1), "stop", OrderStatus.FILLED,
        Decimal(100), Decimal("0.1"), NOW, Decimal(1), Decimal("0.9"), Decimal("0.1"), "USDT",
        Decimal(0),
    )  # fmt: skip
    closes = ExecutionState(MappingProxyType({"cx-t1": close}), MappingProxyType({}))
    assert execution_problems(closes) == ["emir 0: kapanışın net miktarı dolan miktar değil"]
