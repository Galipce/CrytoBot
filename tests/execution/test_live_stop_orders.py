"""Spec 0034 AC-3, AC-4, AC-7: Canlı borsa şartlı stop iletimi, fallback, yaşam döngüsü ve iptal."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from crytobot.execution import (
    STOP_ID_PREFIX,
    ExchangeCredentials,
    LiveExchange,
    OrderStatus,
    position_id_from_stop_id,
    stop_client_id,
)
from crytobot.execution._live_client import BinanceLiveClient

CREDS = ExchangeCredentials(api_key="live_key", api_secret="live_secret", testnet=False)
PAIR = "BTC/USDT"
NOW = datetime(2026, 11, 10, 10, 0, tzinfo=UTC)


class FakeRequestTimeout(Exception):
    pass


class FakeExchangeError(Exception):
    pass


class FakeOrderNotFound(Exception):
    pass


class FakeCcxtExchange:
    def __init__(
        self,
        create_order_result: dict[str, Any] | None = None,
        create_order_error: Exception | None = None,
        cancel_order_result: dict[str, Any] | None = None,
        cancel_order_error: Exception | None = None,
        fetch_order_result: dict[str, Any] | None = None,
        fetch_order_error: Exception | None = None,
        status_code: int = 200,
        error_body: str | None = None,
    ) -> None:
        self.create_order_result = create_order_result or {"status": "open", "id": "stop123"}
        self.create_order_error = create_order_error
        self.cancel_order_result = (
            {"status": "canceled", "id": "stop123"}
            if cancel_order_result is None and cancel_order_error is None
            else cancel_order_result
        )
        self.cancel_order_error = cancel_order_error
        self.fetch_order_result = fetch_order_result
        self.fetch_order_error = fetch_order_error
        self.status_code = status_code
        self.error_body = error_body
        self.on_rest_response: Any = None
        self.number = str
        self.created_orders: list[dict[str, Any]] = []
        self.canceled_orders: list[dict[str, Any]] = []

    def create_order(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: str,
        price: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.on_rest_response is not None:
            self.on_rest_response(self.status_code, "OK", "", "POST", {}, self.error_body)
        self.created_orders.append(
            {
                "symbol": symbol,
                "type": type,
                "side": side,
                "amount": amount,
                "price": price,
                "params": params or {},
            }
        )
        if self.create_order_error is not None:
            raise self.create_order_error
        return self.create_order_result

    def cancel_order(
        self, id: str | None, symbol: str, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        if self.on_rest_response is not None:
            self.on_rest_response(self.status_code, "OK", "", "POST", {}, self.error_body)
        self.canceled_orders.append({"id": id, "symbol": symbol, "params": params})
        if self.cancel_order_error is not None:
            raise self.cancel_order_error
        return self.cancel_order_result

    def fetch_order(
        self, id: str | None, symbol: str, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        if self.on_rest_response is not None:
            self.on_rest_response(self.status_code, "OK", "", "GET", {}, self.error_body)
        if self.fetch_order_error is not None:
            raise self.fetch_order_error
        return self.fetch_order_result


def test_stop_client_id_and_position_id_derivation() -> None:
    """Tekil stop emri kimliği türetimi ve ters dönüşümü."""
    pos_id = "cb-test-pos-001"
    stop_id = stop_client_id(pos_id)
    assert stop_id == "cs-test-pos-001"
    assert stop_id.startswith(STOP_ID_PREFIX)
    assert position_id_from_stop_id(stop_id) == pos_id


def test_live_buy_filled_places_stop_order_with_client_id() -> None:
    """Spec 0034 AC-3: Canlı alım dolumu sonrası borsaya tekil kimlikli şartlı stop emri iletimi."""
    fake_ccxt = FakeCcxtExchange(create_order_result={"status": "open", "id": "s-1"})
    client = BinanceLiveClient(CREDS, exchange=fake_ccxt)
    venue = LiveExchange(client)

    stop_id = stop_client_id("cb-pos-999")
    status = venue.place_stop_order(
        client_order_id=stop_id,
        symbol=PAIR,
        amount=Decimal("49.115"),
        stop_price=Decimal("95.00"),
        limit_price=Decimal("94.90"),
    )

    assert status is OrderStatus.NEW
    assert len(fake_ccxt.created_orders) == 1
    call = fake_ccxt.created_orders[0]
    assert call["symbol"] == PAIR
    assert call["type"] == "STOP_LOSS"
    assert call["side"] == "sell"
    assert call["amount"] == "49.115"
    assert call["params"]["stopPrice"] == "95.00"
    assert call["params"]["newClientOrderId"] == "cs-pos-999"


def test_stop_order_lifecycle_and_order_status_mapping() -> None:
    """Spec 0034 AC-4: Borsa stop emri yaşam döngüsü ve OrderStatus durum eşlemesi."""
    fake_ccxt = FakeCcxtExchange()
    client = BinanceLiveClient(CREDS, exchange=fake_ccxt)
    venue = LiveExchange(client)
    stop_id = "cs-order-status-test"

    # 1. new / open -> OrderStatus.NEW
    for raw in ("new", "open"):
        fake_ccxt.fetch_order_result = {"status": raw}
        assert venue.query(stop_id, PAIR) is OrderStatus.NEW

    # 2. closed / filled -> OrderStatus.FILLED
    for raw in ("closed", "filled"):
        fake_ccxt.fetch_order_result = {"status": raw}
        assert venue.query(stop_id, PAIR) is OrderStatus.FILLED

    # 3. canceled / cancelled -> OrderStatus.CANCELED
    for raw in ("canceled", "cancelled"):
        fake_ccxt.fetch_order_result = {"status": raw}
        assert venue.query(stop_id, PAIR) is OrderStatus.CANCELED

    # 4. rejected / expired -> OrderStatus.REJECTED
    for raw in ("rejected", "expired"):
        fake_ccxt.fetch_order_result = {"status": raw}
        assert venue.query(stop_id, PAIR) is OrderStatus.REJECTED

    # 5. Bilinmeyen metin -> OrderStatus.UNKNOWN
    fake_ccxt.fetch_order_result = {"status": "unrecognized_state"}
    assert venue.query(stop_id, PAIR) is OrderStatus.UNKNOWN

    # 6. Ağ hatası / timeout -> OrderStatus.UNKNOWN
    fake_ccxt.fetch_order_error = FakeRequestTimeout("timed out")
    assert venue.query(stop_id, PAIR) is OrderStatus.UNKNOWN

    # 7. Emir bulunamadı (None) -> OrderStatus.REJECTED
    fake_ccxt.fetch_order_error = None
    fake_ccxt.fetch_order_result = None
    assert venue.query(stop_id, PAIR) is OrderStatus.REJECTED


def test_stop_order_fallback_to_stop_loss_limit() -> None:
    """R-4: STOP_LOSS reddedildiğinde STOP_LOSS_LIMIT fallback çağrılır."""
    call_count = 0

    def mock_create(
        symbol: str,
        type: str,
        side: str,
        amount: str,
        price: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if type == "STOP_LOSS":
            raise FakeExchangeError("STOP_LOSS market order not supported on this pair")
        return {"status": "open", "id": "fallback-limit-stop"}

    fake_ccxt = FakeCcxtExchange()
    fake_ccxt.create_order = mock_create  # type: ignore[method-assign]
    client = BinanceLiveClient(CREDS, exchange=fake_ccxt)
    venue = LiveExchange(client)

    status = venue.place_stop_order(
        client_order_id="cs-fallback-test",
        symbol=PAIR,
        amount=Decimal("10"),
        stop_price=Decimal("95"),
        limit_price=Decimal("94.905"),
    )

    assert status is OrderStatus.NEW
    assert call_count == 2


def test_stop_order_network_error_does_not_attempt_fallback() -> None:
    """R-5 (BR-11 Fail-closed): Ağ hatası / belirsizlik durumunda ikinci emir denenmez."""
    fake_ccxt = FakeCcxtExchange(create_order_error=FakeRequestTimeout("gateway timeout"))
    client = BinanceLiveClient(CREDS, exchange=fake_ccxt)
    venue = LiveExchange(client)

    status = venue.place_stop_order(
        client_order_id="cs-net-test",
        symbol=PAIR,
        amount=Decimal("10"),
        stop_price=Decimal("95"),
        limit_price=Decimal("94.905"),
    )

    assert status is OrderStatus.UNKNOWN
    # Yalnızca bir kez denenmiş olmalı, ikinci emir (fallback) iletilmemelidir
    assert len(fake_ccxt.created_orders) == 1


def test_cancel_order_and_race_condition_resolution() -> None:
    """R-7: Stop emri iptali ve iptal anında emrin dolmuş olma durumu (yarış koşulu)."""
    # 1. Normal başarılı iptal
    fake_ccxt = FakeCcxtExchange(cancel_order_result={"status": "canceled"})
    client = BinanceLiveClient(CREDS, exchange=fake_ccxt)
    venue = LiveExchange(client)

    res = venue.cancel_order("cs-pos-1", PAIR)
    assert res is OrderStatus.CANCELED
    assert fake_ccxt.canceled_orders[0]["params"]["origClientOrderId"] == "cs-pos-1"

    # 2. İptal çağrısı hata verdi veya None döndü (çünkü emir zaten dolmuş)
    fake_ccxt_filled = FakeCcxtExchange(
        cancel_order_error=FakeOrderNotFound("Order already filled"),
        fetch_order_result={"status": "filled", "price": "95.00"},
    )
    client_filled = BinanceLiveClient(CREDS, exchange=fake_ccxt_filled)
    venue_filled = LiveExchange(client_filled)

    res_filled = venue_filled.cancel_order("cs-pos-2", PAIR)
    assert res_filled is OrderStatus.FILLED
