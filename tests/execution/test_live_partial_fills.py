"""Spec 0037 AC-1, AC-3, AC-4, AC-6 (yürütme yarısı): kısmi dolum, üçüncü varlıktan komisyon,
kapanış ve stop kimlik nesilleri, bakiye ve fiyat sorguları."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import ccxt
import pytest

from crytobot.execution import (
    EMPTY_EXECUTION,
    PARTS,
    AssetBalance,
    BannedError,
    BinanceLiveClient,
    CloseOrderRequest,
    ExchangeCredentials,
    ExecutionState,
    FillVerdict,
    LiveExchange,
    LiveExchangeCallError,
    LiveReply,
    OrderOutcome,
    OrderRequest,
    OrderStatus,
    client_id_part,
    close_client_id,
    execution_problems,
    judge_fill,
    place_close_order,
    place_order,
    position_id_from_stop_id,
    query_order,
    record_stop_fill,
    settle_reply,
    stop_client_id,
)
from crytobot.risk import CloseRequest, PairRules, TradeApproval, TradeIntent, approve_close

PAIR = "BTC/USDT"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
RATE = Decimal("0.001")
STEP = Decimal("0.01")
RULES = PairRules(STEP, STEP, Decimal(5))


def reply(
    filled: str,
    status: str = "expired",
    average: str = "100",
    fee: dict[str, str] | None = None,
) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "status": status,
        "id": "42",
        "filled": filled,
        "average": average,
        "cost": str(Decimal(filled) * Decimal(average)),
    }
    if fee is not None:
        raw["fee"] = fee
    return raw


def usdt(cost: str) -> dict[str, str]:
    return {"cost": cost, "currency": "USDT"}


def bnb(cost: str) -> dict[str, str]:
    return {"cost": cost, "currency": "BNB"}


class Ccxt:
    """ccxt sahtesi: piyasa emri `answer` döner; piyasalar, son fiyat ve bakiye ayarlanır."""

    def __init__(
        self,
        answer: dict[str, Any] | None = None,
        markets: dict[str, Any] | None = None,
        ticker: object = None,
        ticker_error: Exception | None = None,
        balance: object = None,
    ) -> None:
        self.answer = answer or {}
        self.markets = {"BTC/USDT": {}, "BNB/USDT": {}} if markets is None else markets
        self.ticker = {"last": "600"} if ticker is None else ticker
        self.ticker_error = ticker_error
        self.balance = balance
        self.on_rest_response: Any = None
        self.number = str
        self.tickers: list[str] = []

    def create_order(self, symbol: str, type: str, side: str, amount: str, **kw: Any) -> Any:
        return dict(self.answer)

    def load_markets(self) -> Any:
        return self.markets

    def fetch_ticker(self, symbol: str) -> Any:
        self.tickers.append(symbol)
        if self.ticker_error is not None:
            raise self.ticker_error
        return self.ticker

    def fetch_balance(self) -> Any:
        return self.balance


def venue(fake: Ccxt) -> LiveExchange:
    creds = ExchangeCredentials(api_key="k", api_secret="s", testnet=False)
    return LiveExchange(BinanceLiveClient(creds, exchange=fake))


def live_buy(fake: Ccxt, amount: str = "1") -> Any:
    intent = TradeIntent(PAIR, "buy", Decimal(100), Decimal(95), Decimal(110))
    approval = TradeApproval(Decimal(amount), None, False, "onay", intent)
    request = OrderRequest("t1", intent, approval, RULES, Decimal(100), RATE, Decimal(0), "live")
    return place_order(EMPTY_EXECUTION, request, venue(fake), NOW)


def live_sell(fake: Ccxt, amount: str = "1", part: object = 0) -> Any:
    approval = approve_close(CloseRequest("cb-t1", PAIR, Decimal(amount), "hedef"))
    request = CloseOrderRequest(approval, RULES, Decimal(110), RATE, Decimal(0), "live", part)
    return place_close_order(EMPTY_EXECUTION, request, venue(fake), NOW)


def test_expired_partial_buy_is_complete() -> None:
    """AC-1 (R-1): kalanı borsada sona eren alımın dolan kısmı tam bir dolumdur: emir `FILLED`,
    dolan 0.4, pozisyon miktarı (net) 0.4, ücret gerçek komisyon; depo doğrulaması kabul eder.
    "Doldu" denen emirde dolan < emir ise tutarsızlıktır, emir `UNKNOWN` kalır."""
    result = live_buy(Ccxt(reply("0.4", fee=usdt("0.04"))))

    order = result.order
    assert result.outcome is OrderOutcome.CREATED and order.status is OrderStatus.FILLED
    assert (order.amount, order.filled, order.net, order.position_amount) == (
        Decimal(1),
        Decimal("0.4"),
        Decimal("0.4"),
        Decimal("0.4"),
    )
    assert (order.fill_price, order.fee) == (Decimal(100), Decimal("0.04"))
    assert result.state.unknown == ()
    assert execution_problems(result.state) == []

    raw = reply("0.4", status="closed", fee=usdt("0.04"))
    fill = judge_fill(raw, None, side="buy", pair=PAIR, amount=Decimal(1), step=STEP)
    assert fill.verdict is FillVerdict.INCOMPLETE and "küçük" in fill.reason
    filled_reply = LiveReply(OrderStatus.FILLED, raw)
    settled = settle_reply(filled_reply, side="buy", pair=PAIR, amount=Decimal(1), step=STEP)
    assert settled.status is OrderStatus.UNKNOWN and settled.unsupported is None


def test_expired_partial_sell_is_complete() -> None:
    """AC-3 (R-3): kalanı sona eren satışın dolan kısmı `FILLED` kapanış emridir; net = dolan."""
    result = live_sell(Ccxt(reply("0.3", average="110", fee=usdt("0.03"))))

    order = result.order
    assert order.status is OrderStatus.FILLED
    assert (order.amount, order.filled, order.position_amount) == (
        Decimal(1),
        Decimal("0.3"),
        Decimal("0.3"),
    )
    assert "dolan 0.3" in result.message
    assert execution_problems(result.state) == []


def test_partial_fill_needs_its_fee_from_the_trades() -> None:
    """Plan 0036 Risk 2: sona eren kısmi dolumda yanıtta komisyon yoksa emrin işlemleri sorulur."""

    class Trades(Ccxt):
        def __init__(self) -> None:
            super().__init__(reply("0.4"))
            self.trade_calls: list[str] = []

        def fetch_my_trades(self, symbol: str, params: dict[str, Any]) -> Any:
            self.trade_calls.append(params["orderId"])
            return [{"amount": "0.4", "fee": usdt("0.04")}]

    fake = Trades()
    result = live_buy(fake)
    assert fake.trade_calls == ["42"]
    assert result.order.status is OrderStatus.FILLED and result.order.fee == Decimal("0.04")


def test_third_asset_fee_valued_at_price() -> None:
    """AC-4 (R-4): BNB komisyonunda miktar dolan miktardır; komisyon BNB olarak kaydedilir, USDT
    değeri o turda okunan BNB/USDT fiyatıyla (0.0001 * 600 = 0.06); "tahmini" değildir."""
    fake = Ccxt(reply("1", status="closed", fee=bnb("0.0001")))
    result = live_buy(fake)

    order = result.order
    assert order.status is OrderStatus.FILLED
    assert (order.filled, order.net, order.dust) == (Decimal(1), Decimal(1), Decimal(0))
    assert (order.commission, order.commission_asset) == (Decimal("0.0001"), "BNB")
    assert order.fee == Decimal("0.06") and order.fee_estimated is False
    assert order.net * order.fill_price + order.fee == Decimal(100) + Decimal("0.06")
    assert fake.tickers == ["BNB/USDT"]
    assert execution_problems(result.state) == []

    sold = live_sell(Ccxt(reply("1", status="closed", average="110", fee=bnb("0.0001"))))
    assert sold.order.fee == Decimal("0.06") and sold.order.commission_asset == "BNB"
    assert sold.order.filled * sold.order.fill_price - sold.order.fee == Decimal("109.94")


@pytest.mark.parametrize(
    "fake",
    [
        Ccxt(reply("1", status="closed", fee=bnb("0.0001")), ticker_error=ccxt.NetworkError("x")),
        Ccxt(reply("1", status="closed", fee=bnb("0.0001")), markets={"BTC/USDT": {}}),
        Ccxt(reply("1", status="closed", fee=bnb("0.0001")), ticker={"last": None}),
        Ccxt(reply("1", status="closed", fee=bnb("0.0001")), ticker={"last": "0"}),
    ],
    ids=["price-unreadable", "no-pair", "no-last", "zero-last"],
)
def test_third_asset_fee_estimated(fake: Ccxt) -> None:
    """AC-4 (R-4, G-9): fiyat okunamazsa ya da BNB/USDT çifti borsada yoksa ücret ayardaki oranla
    tahmin edilir (1 * 100 * 0.001 = 0.1), kayıt "tahmini" işaretini taşır; emir `FILLED` olur,
    güvenli mod yoktur."""
    result = live_buy(fake)

    order = result.order
    assert order.status is OrderStatus.FILLED and result.state.unknown == ()
    assert order.fee == Decimal("0.1") and order.fee_estimated is True
    assert (order.commission, order.commission_asset) == (Decimal("0.0001"), "BNB")
    assert execution_problems(result.state) == []


def test_ban_during_the_price_does_not_drop_the_fill() -> None:
    """Spec 0034 F-4 (plan Risk 9): emir yolunda fiyat sorgusundaki ban dolumu kayıttan önce
    düşürmez; ücret tahmin edilir, ban sonraki borsa çağrısında yine gelir."""

    class BannedPrice(LiveExchange):
        def last_price(self, symbol: str) -> Decimal | None:
            raise BannedError("418")

    creds = ExchangeCredentials(api_key="k", api_secret="s", testnet=False)
    fake = Ccxt(reply("1", status="closed", fee=bnb("0.0001")))
    exchange = BannedPrice(BinanceLiveClient(creds, exchange=fake))
    intent = TradeIntent(PAIR, "buy", Decimal(100), Decimal(95), Decimal(110))
    approval = TradeApproval(Decimal(1), None, False, "onay", intent)
    request = OrderRequest("t1", intent, approval, RULES, Decimal(100), RATE, Decimal(0), "live")
    result = place_order(EMPTY_EXECUTION, request, exchange, NOW)
    assert result.order is not None
    assert result.order.status is OrderStatus.FILLED and result.order.fee_estimated is True


def test_third_asset_fee_without_price_or_rate_is_incomplete() -> None:
    """R-4: fiyat da oran da yoksa (doğrudan yargı) değer hesaplanamaz: eksik bilgidir."""
    raw = reply("1", status="closed", fee=bnb("0.0001"))
    fill = judge_fill(raw, None, side="buy", pair=PAIR, amount=Decimal(1), step=STEP)
    assert fill.verdict is FillVerdict.INCOMPLETE and "BNB" in fill.reason
    priced = judge_fill(
        raw, None, side="buy", pair=PAIR, amount=Decimal(1), step=STEP, asset_price=lambda s: None
    )
    assert priced.verdict is FillVerdict.INCOMPLETE
    odd = judge_fill(
        raw,
        None,
        side="buy",
        pair=PAIR,
        amount=Decimal(1),
        step=STEP,
        asset_price=lambda s: Decimal("NaN"),
        fee_rate=RATE,
    )
    assert odd.verdict is FillVerdict.COMPLETE and odd.estimated is True


def test_sell_coin_fee_and_two_assets_stay_unsupported() -> None:
    """R-6'nın sınırı: satışta coinden ve iki varlıktan (BNB + USDT) komisyon desteklenmez."""
    coin = judge_fill(
        reply("1", status="closed", fee={"cost": "0.001", "currency": "BTC"}),
        None,
        side="sell",
        pair=PAIR,
        amount=Decimal(1),
        step=None,
    )
    assert coin.verdict is FillVerdict.UNSUPPORTED and "coininden" in coin.reason
    raw = reply("1", status="closed")
    raw["fees"] = [bnb("0.0001"), usdt("0.1")]
    two = judge_fill(raw, None, side="buy", pair=PAIR, amount=Decimal(1), step=STEP, fee_rate=RATE)
    assert two.verdict is FillVerdict.UNSUPPORTED and "iki varlık" in two.reason


def test_unknown_buy_resolves_with_estimated_fee() -> None:
    """AC-4 (R-4): durumu bilinmeyen alımın sonraki sorgusunda BNB komisyonu fiyatı okunamazsa
    sorgudaki ücret oranıyla tahmin edilir."""
    state = live_buy(Ccxt({"status": "open", "id": "42"})).state
    assert state.unknown == ("cb-t1",)

    class Answer(Ccxt):
        def fetch_order(self, *args: Any, **kwargs: Any) -> Any:
            return reply("1", status="closed", fee=bnb("0.0001"))

    fake = Answer(ticker_error=ccxt.NetworkError("x"))
    queried = query_order(state, "cb-t1", venue(fake), NOW, step=STEP, fee_rate=RATE)
    assert queried.order is not None and queried.order.status is OrderStatus.FILLED
    assert queried.order.fee == Decimal("0.1") and queried.order.fee_estimated is True


def test_close_and_stop_id_generations() -> None:
    """Plan 0037 Risk 3: kısım 0 bugünkü `cx-`/`cs-`; kısım n `cx{n+1}-`/`cs{n+1}-`; 9. nesil yok.
    Kimlikler 36 karakteri aşmaz ve pozisyon kimliğine geri çözülür."""
    position = "cb-" + "a" * 32
    assert close_client_id(position) == "cx-" + "a" * 32
    assert stop_client_id(position) == "cs-" + "a" * 32
    assert [close_client_id(position, n)[:4] for n in (1, 8)] == ["cx2-", "cx9-"]
    assert stop_client_id(position, 3) == "cs4-" + "a" * 32
    assert all(len(close_client_id(position, n)) <= 36 for n in range(PARTS))
    for bad in (PARTS, -1, True):
        with pytest.raises(ValueError):
            close_client_id(position, bad)
    assert client_id_part(stop_client_id(position, 3)) == ("cs", position, 3)
    assert client_id_part("cx-t1") == ("cx", "cb-t1", 0)
    assert client_id_part("cb-t1") is None and client_id_part("cx1-t1") is None
    assert position_id_from_stop_id("cs5-t1") == "cb-t1"
    assert position_id_from_stop_id("cs-t1") == "cb-t1"


def test_close_order_part_selects_the_id() -> None:
    """Plan 0037 Risk 3: kapanış isteğinin kısmı kimliği seçer; aralık dışı kısım geçersiz girdi."""
    filled = Ccxt(reply("1", status="closed", average="110", fee=usdt("0.11")))
    assert live_sell(filled, part=1).order.client_order_id == "cx2-t1"
    for bad in (PARTS, -1, "1", None):
        refused = live_sell(filled, part=bad)
        assert refused.outcome is OrderOutcome.INVALID_INPUT and "kısım" in refused.message


def test_later_generation_ids_pass_validation() -> None:
    """Depo doğrulaması her nesli kabul eder; başka pozisyonun kimliği ve stop nedeni olmayan
    `cs…-` reddedilir."""
    order = live_sell(Ccxt(reply("1", status="closed", average="110", fee=usdt("0.11"))), part=2)
    order = order.order
    assert order.client_order_id == "cx3-t1"

    def problems(**changes: Any) -> list[str]:
        changed = replace(order, **changes)
        orders = {changed.client_order_id: changed}
        return execution_problems(ExecutionState(MappingProxyType(orders), MappingProxyType({})))

    assert problems() == []
    assert problems(client_order_id="cx3-other") == [
        "emir 0: kimlik pozisyon kimliğinden türemiyor"
    ]
    assert problems(client_order_id="cs3-t1") == ["emir 0: borsa stop emrinin nedeni stop değil"]
    assert problems(client_order_id="cs3-t1", reason="stop") == []
    assert problems(fee_estimated=None) == ["emir 0: borsa dolumu geçersiz"]
    paper = replace(order, filled=None, net=None, commission=None, commission_asset=None, dust=None)
    paper_state = ExecutionState(MappingProxyType({"cx3-t1": paper}), MappingProxyType({}))
    assert execution_problems(paper_state) == []
    estimated = replace(paper, fee_estimated=True)
    estimated_state = ExecutionState(MappingProxyType({"cx3-t1": estimated}), MappingProxyType({}))
    assert execution_problems(estimated_state) == ["emir 0: borsa dolumu olmadan tahmini ücret"]


def test_record_stop_fill_uses_the_generation() -> None:
    """Spec 0037: kısmi kapanıştan sonra dolan stop `cs{n+1}-` kimliğiyle yazılır."""
    raw = reply("1", status="closed", average="95", fee=usdt("0.09"))
    fill = judge_fill(raw, None, side="sell", pair=PAIR, amount=Decimal(1), step=None)
    order, state = record_stop_fill(EMPTY_EXECUTION, "cb-t1", PAIR, Decimal(1), fill, NOW, part=1)
    assert order.client_order_id == "cs2-t1"
    assert execution_problems(state) == []


def test_fetch_balances_one_call_free_and_total() -> None:
    """R-5 (plan Risk 8): tek bakiye çağrısıyla serbest ve toplam (serbest + emirde bekleyen);
    toplam yoksa serbest + `used`."""
    balance = {
        "free": {"USDT": "900.5", "BTC": "0.2"},
        "used": {"BTC": "0.3"},
        "total": {"USDT": "900.5"},
    }
    found = venue(Ccxt(balance=balance)).fetch_balances()
    assert found == {
        "BTC": AssetBalance(Decimal("0.2"), Decimal("0.5")),
        "USDT": AssetBalance(Decimal("900.5"), Decimal("900.5")),
    }


@pytest.mark.parametrize(
    "balance",
    [None, {"free": "x"}, {"free": {"BTC": "-1"}}, {"free": {"BTC": "abc"}}, {"free": {"BTC": []}}],
)
def test_fetch_balances_refuses_bad_replies(balance: object) -> None:
    with pytest.raises(LiveExchangeCallError):
        venue(Ccxt(balance=balance)).fetch_balances()


def test_last_price_reads_the_ticker_and_passes_the_ban() -> None:
    """R-4 (G-9; plan Risk 9): son fiyat; çift yoksa `None`; ban yutulmaz."""
    assert venue(Ccxt()).last_price("BNB/USDT") == Decimal(600)
    assert venue(Ccxt(ticker={"last": 600.5})).last_price("BNB/USDT") == Decimal("600.5")
    assert venue(Ccxt(markets={})).last_price("BNB/USDT") is None
    assert venue(Ccxt(ticker={"last": "abc"})).last_price("BNB/USDT") is None
    assert venue(Ccxt(ticker="no ticker")).last_price("BNB/USDT") is None

    class Banned(Ccxt):
        def fetch_ticker(self, symbol: str) -> Any:
            client = getattr(self, "client", None)
            assert client is not None
            client._seen.status = 418
            raise ccxt.DDoSProtection("418")

    fake = Banned()
    exchange = venue(fake)
    fake.client = exchange.client  # type: ignore[attr-defined]
    with pytest.raises(BannedError):
        exchange.last_price("BNB/USDT")
