"""Spec 0036 AC-7 (R-7): yalnız kesin ret `REJECTED`; geri kalan her hata `UNKNOWN`."""

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
    ccxt.InvalidOrder("Filter failure: NOTIONAL"),
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
