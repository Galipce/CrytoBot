"""Spec 0017 AC-2: yalnız herkese açık veri, anahtar yok; emir ve hesap çağrısı yapılamaz (R-2)."""

import pytest

from crytobot.market_data._client import _BinancePublic, connect_public
from tests.market_data.helpers import recorded_client


def _use_every_call(client: object) -> None:
    client.markets(5.0)  # type: ignore[attr-defined]
    client.klines("BTCUSDT", "1h", 3, 1793879999999, 5.0)  # type: ignore[attr-defined]
    client.ticker("BTCUSDT", 5.0)  # type: ignore[attr-defined]


def test_keys_in_environment_are_not_used(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("BINANCE_API_KEY", "BINANCE_SECRET", "BINANCE_APIKEY", "API_KEY", "SECRET"):
        monkeypatch.setenv(name, "secret-from-environment")
    client, session = recorded_client()
    _use_every_call(client)
    exchange = client._exchange  # type: ignore[attr-defined]
    assert not exchange.apiKey
    assert not exchange.secret
    assert "secret-from-environment" not in str(session.requests)


def test_only_public_calls_are_recorded() -> None:
    client, session = recorded_client()
    _use_every_call(client)
    assert [request["method"] for request in session.requests] == ["GET", "GET", "GET"]
    paths = [request["url"].split("?")[0] for request in session.requests]
    assert paths == [
        "https://api.binance.com/api/v3/exchangeInfo",
        "https://api.binance.com/api/v3/klines",
        "https://api.binance.com/api/v3/ticker/24hr",
    ]


def test_requests_carry_no_key_or_signature() -> None:
    client, session = recorded_client()
    _use_every_call(client)
    for request in session.requests:
        assert "signature" not in request["url"]
        assert "timestamp" not in request["url"]
        assert "X-MBX-APIKEY" not in (request["headers"] or {})


def test_the_client_exposes_only_the_three_reads() -> None:
    public = {name for name in vars(_BinancePublic) if not name.startswith("_")}
    assert public == {"markets", "klines", "ticker"}
    assert type(connect_public()) is _BinancePublic
