"""Spec 0036 AC-7 (R-7): yalnız kesin ret `REJECTED`; geri kalan her hata `UNKNOWN`."""

import json
from typing import Any

import ccxt
import pytest

from crytobot.execution import (
    BinanceLiveClient,
    ExchangeCredentials,
    LiveExchange,
    OrderStatus,
    is_definite_refusal,
)

CREDS = ExchangeCredentials(api_key="k", api_secret="s", testnet=False)


class RaisingCcxt:
    """`create_order` ve `fetch_order` verilen hatayı, verilen HTTP durumuyla fırlatır."""

    def __init__(self, error: Exception, status: int = 400) -> None:
        self.error = error
        self.status = status
        self.on_rest_response: Any = None
        self.number = str

    def _respond(self) -> None:
        if self.on_rest_response is not None:
            self.on_rest_response(self.status, "", "", "POST", {}, "{}")
        raise self.error

    def create_order(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._respond()
        raise AssertionError  # unreachable

    def fetch_order(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._respond()
        raise AssertionError  # unreachable


def venue(error: Exception, status: int = 400) -> LiveExchange:
    return LiveExchange(BinanceLiveClient(CREDS, exchange=RaisingCcxt(error, status)))


UNKNOWN_ERRORS = [
    ccxt.NetworkError("network"),
    ccxt.RequestTimeout("timeout"),
    ccxt.ExchangeNotAvailable("unavailable"),
    ccxt.OnMaintenance("maintenance"),
    ccxt.RateLimitExceeded("rate limit"),
    ccxt.DDoSProtection("ddos"),
    ccxt.OperationFailed("operation failed"),
    ccxt.ExchangeError("unknown exchange error"),
    ccxt.BadRequest("bad request"),
    ccxt.DuplicateOrderId("duplicate client id"),
    ccxt.OrderNotFound("not found"),
    ValueError("unrecognised"),
    Exception("anything"),
]
REFUSALS = [
    ccxt.InsufficientFunds("insufficient balance"),
    ccxt.InvalidOrder("Filter failure: LOT_SIZE"),
    ccxt.OrderImmediatelyFillable("would trigger immediately"),
    ccxt.AuthenticationError("invalid api key"),
    ccxt.PermissionDenied("permission denied"),
]


@pytest.mark.parametrize(
    ("error", "status"),
    [(e, OrderStatus.UNKNOWN) for e in UNKNOWN_ERRORS]
    + [(e, OrderStatus.REJECTED) for e in REFUSALS],
    ids=lambda v: type(v).__name__ if isinstance(v, Exception) else v.value,
)
def test_error_class_maps_to_status(error: Exception, status: OrderStatus) -> None:
    """AC-7: ağ hatası, zaman aşımı, erişilemezlik, bakım, hız sınırı ve tanınmayan her hata
    `UNKNOWN`; yetersiz bakiye, geçersiz emir ve yetki hatası `REJECTED`. Sınıf `isinstance` ile."""
    reply = venue(error).place_market("cb-x", symbol="BTC/USDT", side="buy", amount="1")
    assert reply.status is status
    assert reply.order is None
    assert is_definite_refusal(error) is (status is OrderStatus.REJECTED)


def test_class_name_alone_is_not_a_refusal() -> None:
    """R-7: adı ret gibi görünen ama ccxt ret sınıfı olmayan hata kesin ret değildir."""

    class InsufficientFunds(Exception):  # same name, not ccxt's class
        pass

    reply = venue(InsufficientFunds("x")).place_market("cb-x", "BTC/USDT", "buy", "1")
    assert reply.status is OrderStatus.UNKNOWN


@pytest.mark.parametrize("http", [500, 503, 429])
def test_server_error_or_rate_limit_is_unknown_whatever_the_class(http: int) -> None:
    reply = venue(ccxt.InsufficientFunds("x"), http).place_market("cb-x", "BTC/USDT", "buy", "1")
    assert reply.status is OrderStatus.UNKNOWN


@pytest.mark.parametrize("error", REFUSALS + UNKNOWN_ERRORS[:3])
def test_a_failed_query_never_refuses_the_order(error: Exception) -> None:
    """R-7: durumu bilinmeyen emrin sorgusu hata verirse emir hakkında bir şey bilinmez."""
    reply = venue(error).query_fill("cb-x", symbol="BTC/USDT")
    assert reply.status is OrderStatus.UNKNOWN
    assert not reply.missing


class BinanceReplying:
    """`create_order`, verilen Binance hata gövdesini ccxt'nin gerçek `handle_errors`
    eşlemesinden geçirir: sınıfı elle değil, kütüphane seçer (plan 0036 A-1)."""

    URL = "https://api.binance.com/api/v3/order"

    def __init__(self, status: int, code: int, msg: str) -> None:
        self.status = status
        self.body = json.dumps({"code": code, "msg": msg})
        self.on_rest_response: Any = None
        self.number = str
        self._real = ccxt.binance()

    def create_order(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if self.on_rest_response is not None:
            self.on_rest_response(self.status, "", self.URL, "POST", {}, self.body)
        self._real.handle_errors(
            self.status, "", self.URL, "POST", {}, self.body, json.loads(self.body), {}, None
        )
        raise AssertionError("ccxt did not raise")  # pragma: no cover


BINANCE_REPLIES = [
    (400, -1013, "Filter failure: NOTIONAL", OrderStatus.REJECTED),
    (400, -1013, "Filter failure: MIN_NOTIONAL", OrderStatus.REJECTED),
    (400, -1013, "Filter failure: LOT_SIZE", OrderStatus.REJECTED),
    (400, -1111, "Precision is over the maximum defined for this asset.", OrderStatus.REJECTED),
    (400, -1100, "Illegal characters found in parameter 'quantity'.", OrderStatus.REJECTED),
    (400, -1116, "Invalid orderType.", OrderStatus.REJECTED),
    (400, -1121, "Invalid symbol.", OrderStatus.REJECTED),
    (400, -2010, "Account has insufficient balance for requested action.", OrderStatus.REJECTED),
    (401, -2015, "Invalid API-key, IP, or permissions for action.", OrderStatus.REJECTED),
    (429, -1003, "Too many requests.", OrderStatus.UNKNOWN),
    (400, -1021, "Timestamp for this request is outside of the recvWindow.", OrderStatus.UNKNOWN),
    (408, -1007, "Timeout waiting for response from backend server.", OrderStatus.UNKNOWN),
    (400, -1000, "An unknown error occurred while processing the request.", OrderStatus.UNKNOWN),
    (400, -1128, "Combination of optional parameters invalid.", OrderStatus.UNKNOWN),
    (503, -1008, "Server is currently overloaded with other requests.", OrderStatus.UNKNOWN),
]


@pytest.mark.parametrize(
    ("http", "code", "msg", "status"),
    BINANCE_REPLIES,
    ids=[f"{c}-{m.split(':')[-1].strip()[:14]}" for _, c, m, _ in BINANCE_REPLIES],
)
def test_real_binance_reply_maps_to_status(
    http: int, code: int, msg: str, status: OrderStatus
) -> None:
    """AC-7, gerçek borsa yanıtıyla: Binance filtre ve doğrulama reddi (ccxt bunların çoğunu
    `InvalidOrder` değil `BadRequest` fırlatır), yetersiz bakiye ve yetki hatası `REJECTED`;
    hız sınırı, zaman damgası, zaman aşımı, sunucu ve tanınmayan hata `UNKNOWN`."""
    client = BinanceLiveClient(CREDS, exchange=BinanceReplying(http, code, msg))
    reply = LiveExchange(client).place_market("cb-x", symbol="BTC/USDT", side="buy", amount="1")
    assert reply.status is status
    assert reply.order is None


def test_bad_request_without_a_known_code_is_unknown() -> None:
    """R-7: gövdesiz ya da kodu doğrulama reddi olmayan `BadRequest` tanınmayan hatadır."""
    assert not is_definite_refusal(ccxt.BadRequest("x"))
    assert not is_definite_refusal(ccxt.BadRequest("x"), -1128)
    assert not is_definite_refusal(ccxt.BadRequest("x"), "-1013")
    assert is_definite_refusal(ccxt.BadRequest("x"), -1013)
