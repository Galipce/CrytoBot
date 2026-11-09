"""Spec 0032 AC-5, AC-6, AC-7, AC-8: Canlı borsa emirleri, ret, belirsizlik ve sorgulama."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from crytobot.execution import (
    EMPTY_EXECUTION,
    CloseOrderRequest,
    NotificationKind,
    OrderOutcome,
    OrderRequest,
    OrderStatus,
    QueryOutcome,
    place_close_order,
    place_order,
    query_order,
)
from crytobot.execution._credentials import ExchangeCredentials
from crytobot.execution._live import LiveExchange
from crytobot.execution._live_client import (
    BannedError,
    BinanceLiveClient,
)
from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    AccountState,
    CloseRequest,
    PairRules,
    TradeApproval,
    TradeIntent,
    approve_close,
    approve_trade,
    observe,
)

PAIR = "BTC/USDT"
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
ACCOUNT = AccountState(Decimal("10000"), Decimal("5000"), 0)
RULES = PairRules(Decimal("0.001"), Decimal("0.001"), Decimal("5"))
INTENT = TradeIntent(PAIR, "buy", Decimal("100"), Decimal("95"), Decimal("110"))


def judge(intent: TradeIntent = INTENT) -> TradeApproval:
    state = observe(EMPTY_STATE, NOW, ACCOUNT.equity, DEFAULT_LIMITS).state
    pairs = frozenset({PAIR, "ETH/USDT"})
    return approve_trade(
        intent,
        DEFAULT_LIMITS,
        ACCOUNT,
        RULES,
        pairs,
        Decimal("0.001"),
        Decimal("0.0005"),
        Decimal(0),
        state,
        NOW,
    )


APPROVAL = judge()
CREDS = ExchangeCredentials(api_key="live_key", api_secret="live_secret", testnet=False)


class FakeRequestTimeout(Exception):
    pass


class FakeRateLimitExceeded(Exception):
    pass


class FakeInsufficientFunds(Exception):
    pass


class FakeCcxtExchange:
    def __init__(
        self,
        create_order_result: dict[str, Any] | None = None,
        create_order_error: Exception | None = None,
        fetch_order_result: dict[str, Any] | None = None,
        fetch_order_error: Exception | None = None,
        status_code: int = 200,
        retry_after: str | None = None,
        error_body: str | None = None,
    ) -> None:
        self.create_order_result = create_order_result or {"status": "closed", "id": "12345"}
        self.create_order_error = create_order_error
        self.fetch_order_result = fetch_order_result
        self.fetch_order_error = fetch_order_error
        self.status_code = status_code
        self.retry_after = retry_after
        self.error_body = error_body
        self.on_rest_response: Any = None
        self.number = str

    def create_order(
        self, symbol: str, type: str, side: str, amount: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        if self.on_rest_response is not None:
            headers = {"Retry-After": self.retry_after} if self.retry_after else {}
            self.on_rest_response(self.status_code, "OK", "", "POST", headers, self.error_body)
        if self.create_order_error is not None:
            raise self.create_order_error
        return self.create_order_result

    def fetch_order(
        self, id: str | None, symbol: str, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        if self.on_rest_response is not None:
            headers = {"Retry-After": self.retry_after} if self.retry_after else {}
            self.on_rest_response(self.status_code, "OK", "", "GET", headers, self.error_body)
        if self.fetch_order_error is not None:
            raise self.fetch_order_error
        return self.fetch_order_result


def make_buy_request(**overrides: Any) -> OrderRequest:
    base: dict[str, Any] = {
        "intent_id": "s1-btc-0001",
        "intent": INTENT,
        "approval": APPROVAL,
        "rules": RULES,
        "price": Decimal("100"),
        "fee": Decimal("0.001"),
        "slippage": Decimal("0.001"),
        "mode": "live",
    }
    base.update(overrides)
    return OrderRequest(**base)


def make_close_request(**overrides: Any) -> CloseOrderRequest:
    req = CloseRequest("cb-s1-btc-0001", PAIR, Decimal("19.249"), "hedef")
    appr = approve_close(req)
    base: dict[str, Any] = {
        "approval": appr,
        "rules": RULES,
        "price": Decimal("110"),
        "fee": Decimal("0.001"),
        "slippage": Decimal("0.0005"),
        "mode": "live",
    }
    base.update(overrides)
    return CloseOrderRequest(**base)


def test_place_market_buy_order_filled() -> None:
    """AC-5: Canlı piyasa alım emri cb- kimliğiyle iletilir; dolum ve ret doğru işlenir."""
    # 1. Başarılı dolum (FILLED)
    fake_filled = FakeCcxtExchange(create_order_result={"status": "closed", "id": "101"})
    client = BinanceLiveClient(CREDS, exchange=fake_filled)
    live_venue = LiveExchange(client)

    result = place_order(EMPTY_EXECUTION, make_buy_request(), live_venue, NOW)
    assert result.outcome is OrderOutcome.CREATED
    assert result.order is not None
    assert result.order.status is OrderStatus.FILLED
    assert result.order.client_order_id == "cb-s1-btc-0001"
    assert result.order.fill_price is not None
    assert not result.state.unknown

    # 2. Borsa tarafından ret (REJECTED) — örneğin yetersiz bakiye
    fake_rejected = FakeCcxtExchange(
        create_order_error=FakeInsufficientFunds("insufficient balance")
    )
    client_rej = BinanceLiveClient(CREDS, exchange=fake_rejected)
    live_venue_rej = LiveExchange(client_rej)

    res_rej = place_order(
        EMPTY_EXECUTION, make_buy_request(intent_id="s1-btc-0002"), live_venue_rej, NOW
    )
    assert res_rej.outcome is OrderOutcome.CREATED
    assert res_rej.order is not None
    assert res_rej.order.status is OrderStatus.REJECTED
    assert res_rej.order.fill_price is None
    assert not res_rej.state.unknown


def test_place_market_close_order_filled() -> None:
    """AC-6: Canlı piyasa kapanış emri cx- kimliğiyle iletilir; dolum ve ret doğru işlenir."""
    # 1. Başarılı dolum
    fake_filled = FakeCcxtExchange(create_order_result={"status": "closed", "id": "201"})
    client = BinanceLiveClient(CREDS, exchange=fake_filled)
    live_venue = LiveExchange(client)

    result = place_close_order(EMPTY_EXECUTION, make_close_request(), live_venue, NOW)
    assert result.outcome is OrderOutcome.CREATED
    assert result.order is not None
    assert result.order.status is OrderStatus.FILLED
    assert result.order.client_order_id == "cx-s1-btc-0001"
    assert result.order.fill_price is not None
    assert not result.state.unknown

    # 2. Borsa tarafından ret
    fake_rejected = FakeCcxtExchange(
        create_order_error=FakeInsufficientFunds("position already closed")
    )
    client_rej = BinanceLiveClient(CREDS, exchange=fake_rejected)
    live_venue_rej = LiveExchange(client_rej)

    res_rej = place_close_order(EMPTY_EXECUTION, make_close_request(), live_venue_rej, NOW)
    assert res_rej.outcome is OrderOutcome.CREATED
    assert res_rej.order is not None
    assert res_rej.order.status is OrderStatus.REJECTED
    assert res_rej.order.fill_price is None
    assert not res_rej.state.unknown


def test_network_timeout_results_in_unknown_and_safe_mode() -> None:
    """AC-7: Ağ hatasında emir UNKNOWN olur, güvenli mod açılır, 418 fail-closed."""
    # 1. Zaman aşımı / ağ hatası -> UNKNOWN ve güvenli mod (BR-11)
    fake_timeout = FakeCcxtExchange(create_order_error=FakeRequestTimeout("socket timeout"))
    client = BinanceLiveClient(CREDS, exchange=fake_timeout)
    live_venue = LiveExchange(client)

    result = place_order(EMPTY_EXECUTION, make_buy_request(), live_venue, NOW)
    assert result.outcome is OrderOutcome.CREATED
    assert result.order is not None
    assert result.order.status is OrderStatus.UNKNOWN
    assert result.state.unknown
    assert any(n.kind is NotificationKind.SAFE_MODE_ENTERED for n in result.notifications)

    # Güvenli modda yeni alım isteği engellenir
    blocked = place_order(result.state, make_buy_request(intent_id="s1-btc-0003"), live_venue, NOW)
    assert blocked.outcome is OrderOutcome.STATUS_UNKNOWN
    assert blocked.order is None

    # 2. 429 Rate limited -> UNKNOWN, retry_after saklanır
    fake_429 = FakeCcxtExchange(
        create_order_error=FakeRateLimitExceeded("Too many requests"),
        status_code=429,
        retry_after="30",
    )
    client_429 = BinanceLiveClient(CREDS, exchange=fake_429)
    live_venue_429 = LiveExchange(client_429)

    res_429 = place_order(
        EMPTY_EXECUTION, make_buy_request(intent_id="s1-btc-0004"), live_venue_429, NOW
    )
    assert res_429.order is not None
    assert res_429.order.status is OrderStatus.UNKNOWN
    assert res_429.state.unknown

    # 3. 418 Banned -> fail-closed derhal BannedError
    fake_418 = FakeCcxtExchange(
        create_order_error=Exception("IP banned"),
        status_code=418,
    )
    client_418 = BinanceLiveClient(CREDS, exchange=fake_418)
    live_venue_418 = LiveExchange(client_418)

    with pytest.raises(BannedError):
        place_order(EMPTY_EXECUTION, make_buy_request(intent_id="s1-btc-0005"), live_venue_418, NOW)


def test_query_order_resolves_filled_or_rejected() -> None:
    """AC-8: Canlı sorgulama UNKNOWN emri FILLED veya REJECTED olarak çözer."""
    # Başlangıç durumu: durumu UNKNOWN olan bir emir
    fake_timeout = FakeCcxtExchange(create_order_error=FakeRequestTimeout("timeout"))
    client = BinanceLiveClient(CREDS, exchange=fake_timeout)
    live_venue = LiveExchange(client)
    initial = place_order(EMPTY_EXECUTION, make_buy_request(), live_venue, NOW)
    assert initial.state.unknown

    # 1. Borsa emrin dolduğunu doğrular -> FILLED, güvenli mod biter
    fake_resolved_fill = FakeCcxtExchange(fetch_order_result={"status": "closed", "id": "101"})
    client_res = BinanceLiveClient(CREDS, exchange=fake_resolved_fill)
    venue_res = LiveExchange(client_res)

    q_res = query_order(initial.state, "cb-s1-btc-0001", venue_res, NOW)
    assert q_res.outcome is QueryOutcome.UPDATED
    assert q_res.order is not None
    assert q_res.order.status is OrderStatus.FILLED
    assert q_res.order.fill_price is not None
    assert not q_res.state.unknown
    assert any(n.kind is NotificationKind.SAFE_MODE_EXITED for n in q_res.notifications)

    # 2. Borsa emrin hiç var olmadığını söyler (order does not exist) -> REJECTED, güvenli mod biter
    fake_not_exist = FakeCcxtExchange(
        fetch_order_error=Exception("Order does not exist"),
        error_body='{"code": -2013, "msg": "Order does not exist"}',
    )
    client_none = BinanceLiveClient(CREDS, exchange=fake_not_exist)
    venue_none = LiveExchange(client_none)

    q_rej = query_order(initial.state, "cb-s1-btc-0001", venue_none, NOW)
    assert q_rej.outcome is QueryOutcome.UPDATED
    assert q_rej.order is not None
    assert q_rej.order.status is OrderStatus.REJECTED
    assert q_rej.order.fill_price is None
    assert not q_rej.state.unknown
    assert any(n.kind is NotificationKind.SAFE_MODE_EXITED for n in q_rej.notifications)

    # 3. Ağ hatası devam ediyorsa -> UNCHANGED, UNKNOWN korunur
    fake_still_timeout = FakeCcxtExchange(fetch_order_error=FakeRequestTimeout("still timing out"))
    client_still = BinanceLiveClient(CREDS, exchange=fake_still_timeout)
    venue_still = LiveExchange(client_still)

    q_still = query_order(initial.state, "cb-s1-btc-0001", venue_still, NOW)
    assert q_still.outcome is QueryOutcome.UNCHANGED
    assert q_still.order is not None
    assert q_still.order.status is OrderStatus.UNKNOWN
    assert q_still.state.unknown


class FakeOrderNotFound(Exception):
    pass


class FakeOperationFailed(Exception):
    pass


def test_live_exchange_statuses_and_errors() -> None:
    """LiveExchange ve BinanceLiveClient çeşitli borsa durum kodları ve hatalarını test eder."""
    # 1. on_rest_response zincirleme (forward) ve geçersiz Retry-After
    forwarded = []

    def original_forward(*args: Any) -> str:
        forwarded.append(args)
        return "forwarded"

    fake_ccxt = FakeCcxtExchange(
        create_order_result={"status": "canceled"},
        status_code=502,
        retry_after="not-a-number",
        error_body="{invalid_json",
    )
    fake_ccxt.on_rest_response = original_forward
    client = BinanceLiveClient(CREDS, exchange=fake_ccxt)
    venue = LiveExchange(client)

    # place order canceled durumu
    status_canceled = venue.place("cb-test-1", "BTC/USDT", "buy", Decimal("1"))
    assert status_canceled is OrderStatus.REJECTED
    assert len(forwarded) == 1

    # query order canceled ve open durumları
    fake_ccxt.fetch_order_result = {"status": "canceled"}
    assert venue.query("cb-test-1", "BTC/USDT") is OrderStatus.REJECTED

    fake_ccxt.fetch_order_result = {"status": "open"}
    assert venue.query("cb-test-1", "BTC/USDT") is OrderStatus.UNKNOWN

    # FakeOrderNotFound sınıf adı ile yakalanan borsa sorgusu
    fake_ccxt.fetch_order_result = None
    fake_ccxt.fetch_order_error = FakeOrderNotFound("order not found")
    fake_ccxt.status_code = 200
    assert venue.query("cb-test-not-found", "BTC/USDT") is OrderStatus.REJECTED

    # Bilinen borsa ret hatası (is_unknown=False) query sırasında REJECTED döner
    fake_ccxt.fetch_order_error = FakeInsufficientFunds("invalid symbol format")
    fake_ccxt.status_code = 400
    assert venue.query("cb-test-bad", "BTC/USDT") is OrderStatus.REJECTED

    # 500 server error ve OperationFailed -> UNKNOWN
    fake_ccxt.create_order_error = FakeOperationFailed("internal error")
    fake_ccxt.status_code = 500
    assert venue.place("cb-test-500", "BTC/USDT", "buy", Decimal("1")) is OrderStatus.UNKNOWN
