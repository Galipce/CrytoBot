"""Spec 0041 CB-1, PB-2: testnet'te okumalar yalnız testnet'ten; hata sınıfları mainnet'le aynı.

Gerçek `ccxt.binance` yalnız HTTP oturumu değiştirilerek kullanılır (`helpers.recorded_client`):
istek adresi, hata eşleme ve ayrıştırma gerçektir, ağa çıkılmaz.
"""

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import pytest
import requests

from crytobot.market_data import MarketRead, read_market_data
from crytobot.market_data import _read as read_module
from crytobot.market_data._client import PublicExchange, connect_public
from tests.market_data.helpers import (
    BTC,
    ETH,
    FakeSession,
    clock_at,
    http_response,
    make_settings,
    recorded_routes,
)
from tests.market_data.test_happy_path import RECORDED_NOW

TESTNET_HOST = "testnet.binance.vision"


def _client(testnet: bool, routes: dict[str, Any]) -> tuple[PublicExchange, FakeSession]:
    client = connect_public(testnet=testnet)
    session = FakeSession(routes)
    client._exchange.session = session  # type: ignore[attr-defined]
    return client, session


def _read(client: PublicExchange) -> MarketRead:
    return read_market_data(
        (BTC, ETH), make_settings(), clock_at(RECORDED_NOW), connect=lambda: client
    )


def _hosts(session: FakeSession) -> set[str]:
    return {urlsplit(request["url"]).hostname or "" for request in session.requests}


def _summary(read: MarketRead) -> object:
    """Okumanın karşılaştırılabilir özü: çiftlerin alanları ve sorunları, yasak."""
    pairs = tuple(
        (pair.pair, pair.candles, pair.price, pair.spread, pair.tick, pair.rules, pair.issues)
        for pair in read.pairs
    )
    return pairs, read.input_problem, read.ban


def test_testnet_reads_only_testnet_hosts() -> None:
    """CB-1: piyasa listesi, mum ve fiyat testnet'ten; mainnet'e tek istek yok."""
    client, session = _client(True, recorded_routes())

    read = _read(client)

    assert session.requests, "no request was made"
    assert _hosts(session) == {TESTNET_HOST}
    paths = [urlsplit(request["url"]).path for request in session.requests]
    assert any(path.endswith("/exchangeInfo") for path in paths)
    assert any(path.endswith("/klines") for path in paths)
    assert any(path.endswith("/ticker/24hr") for path in paths)
    assert all(pair.issues == () for pair in read.pairs)


def test_mainnet_reads_never_reach_the_testnet() -> None:
    """PB-1, PB-2: varsayılan istemci bugünkü gibi mainnet'e gider."""
    client, session = _client(False, recorded_routes())

    _read(client)

    assert session.requests
    assert TESTNET_HOST not in _hosts(session)
    assert _hosts(session) == {"api.binance.com"}


def _error_routes(failing: str, response: Callable[[], Any]) -> dict[str, Any]:
    routes = recorded_routes()
    assert failing in routes  # replaced in place: the lookup order stays the recorded one
    routes[failing] = response
    return routes


def _json_error(status: int, code: int, headers: dict[str, str] | None = None) -> Any:
    body = json.dumps({"code": code, "msg": "recorded"})
    every = {"Content-Type": "application/json", **(headers or {})}
    return lambda: http_response(status, body, every)


def _unreachable() -> Any:
    raise requests.exceptions.ConnectionError("unreachable")


FAILURES: list[tuple[str, str, Callable[[], Any]]] = [
    ("ban", "exchangeInfo", _json_error(418, -1003, {"Retry-After": "120"})),
    ("rate_limit", "klines?symbol=BTCUSDT", _json_error(429, -1003, {"Retry-After": "7"})),
    ("server", "ticker/24hr?symbol=ETHUSDT", _json_error(503, -1001)),
    ("try_again", "klines?symbol=ETHUSDT", _json_error(400, -1008)),
    ("bad_symbol", "ticker/24hr?symbol=BTCUSDT", _json_error(400, -1121)),
    ("unreachable", "exchangeInfo", _unreachable),
]


@pytest.mark.parametrize(("name", "failing", "response"), FAILURES, ids=[f[0] for f in FAILURES])
def test_testnet_failure_classes_match_mainnet(
    name: str, failing: str, response: Callable[[], Any]
) -> None:
    """CB-1: aynı hata yanıtı iki ağda aynı okumayı verir (bayat alan, yasak, bütçe)."""
    main_client, _ = _client(False, _error_routes(failing, response))
    test_client, test_session = _client(True, _error_routes(failing, response))

    mainnet = _read(main_client)
    testnet = _read(test_client)

    assert _summary(testnet) == _summary(mainnet)
    assert any(pair.issues for pair in testnet.pairs) or testnet.ban is not None, name
    assert _hosts(test_session) == {TESTNET_HOST}


def test_testnet_unreachable_does_not_fall_back() -> None:
    """S-3: testnet'e ulaşılamazsa okuma eksik kalır; mainnet'e tek istek gitmez."""
    routes = {"binance": _unreachable}
    client, session = _client(True, routes)

    read = _read(client)

    assert all(pair.candles is None and pair.price is None for pair in read.pairs)
    assert all(pair.issues for pair in read.pairs)
    assert session.requests
    assert _hosts(session) == {TESTNET_HOST}


class _Connects:
    """`connect_public` yerine: hangi ağla kurulduğunu yazar, ağa çıkmaz."""

    def __init__(self) -> None:
        self.networks: list[bool] = []

    def __call__(self, testnet: bool = False) -> PublicExchange:
        self.networks.append(testnet)
        client, _ = _client(testnet, recorded_routes())
        return client


def test_default_read_is_mainnet(monkeypatch: pytest.MonkeyPatch) -> None:
    """PB-2: `connect` ve ağ verilmeyen okuma (paper, backtest dışı her çağrı) mainnet'tir."""
    connects = _Connects()
    monkeypatch.setattr(read_module, "connect_public", connects)

    read_market_data((BTC,), make_settings(), clock_at(RECORDED_NOW))

    assert connects.networks == [False]


def test_testnet_read_builds_a_testnet_client(monkeypatch: pytest.MonkeyPatch) -> None:
    connects = _Connects()
    monkeypatch.setattr(read_module, "connect_public", connects)

    read_market_data((BTC,), make_settings(), clock_at(RECORDED_NOW), testnet=True)

    assert connects.networks == [True]
