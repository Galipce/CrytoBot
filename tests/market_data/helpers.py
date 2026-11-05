"""Spec 0017 testlerinin ortak parçaları: `FakeExchange`, kayıtlı yanıtla sahte HTTP, kurucular.

İki katman (plan Risk 14): `FakeExchange` `connect` ile verilir, davranış ve "çağrı yok" kanıtıdır.
`recorded_client` gerçek `ccxt.binance`'i yalnız HTTP oturumunu değiştirerek kullanır: istek
kurma, hata eşleme ve ayrıştırma gerçektir, ağa çıkılmaz. Kayıtların kaynağı `fixtures/README.md`.
"""

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from crytobot.market_data._client import PublicExchange, connect_public
from crytobot.market_data._numbers import utc_from_ms
from crytobot.market_data._types import ReadSettings

FIXTURES = Path(__file__).parent / "fixtures"
BTC = "BTC/USDT"
ETH = "ETH/USDT"
HOUR = timedelta(hours=1)
HOUR_MS = 3_600_000
# The recorded tickers are stamped 1793880256008 ms; the last recorded candle closes at CLOSE_MS
CLOSE_MS = 1_793_880_000_000
NOW = datetime(2026, 11, 5, 14, 44, 20, tzinfo=UTC)


def at_ms(value: int) -> datetime:
    moment = utc_from_ms(value)
    assert moment is not None
    return moment


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def make_settings(**overrides: Any) -> ReadSettings:
    values: dict[str, Any] = {
        "exchange": "binance",
        "candle_interval": HOUR,
        "candle_count": 3,
        "call_timeout": timedelta(seconds=5),
        "read_budget": timedelta(seconds=30),
    }
    return ReadSettings(**{**values, **overrides})


def clock_at(moment: datetime = NOW) -> Callable[[], datetime]:
    return lambda: moment


def market_id(pair: str) -> str:
    return pair.replace("/", "")


def market(pair: str = BTC, **overrides: Any) -> dict[str, Any]:
    """`load_markets`'ın `number=str` ile verdiği biçim; yalnız okunan alanlar."""
    quote = pair.split("/")[1]
    values: dict[str, Any] = {
        "id": market_id(pair),
        "symbol": pair,
        "quote": quote,
        "spot": True,
        "active": True,
        "info": {"isSpotTradingAllowed": True},
        "precision": {"price": "0.01", "amount": "0.001"},
        "limits": {"amount": {"min": "0.001"}, "cost": {"min": "5"}},
    }
    return {**values, **overrides}


def candle_row(
    open_ms: int,
    open_: object = "10.00",
    high: object = "11.00",
    low: object = "9.00",
    close: object = "10.50",
) -> list[object]:
    return [open_ms, open_, high, low, close, "1.0", open_ms + HOUR_MS - 1, "1.0", 1, "1", "1", "0"]


def candle_rows(count: int = 3, closes_at: int = CLOSE_MS) -> list[list[object]]:
    return [candle_row(closes_at - (count - i) * HOUR_MS) for i in range(count)]


def ticker(pair: str = BTC, **overrides: Any) -> dict[str, Any]:
    """`None` verilen alan yanıtta yoktur."""
    values: dict[str, Any] = {
        "symbol": market_id(pair),
        "lastPrice": "10.50",
        "bidPrice": "10.40",
        "askPrice": "10.60",
        "closeTime": CLOSE_MS,
    }
    merged = {**values, **overrides}
    return {key: value for key, value in merged.items() if value is not None}


class Steps:
    """Art arda yanıtlar: her çağrı sıradakini alır, sonuncu tekrarlanır."""

    def __init__(self, *steps: object) -> None:
        self.steps = list(steps)

    def next(self) -> object:
        return self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]


def _answer(planned: object) -> object:
    if isinstance(planned, Steps):
        planned = planned.next()
    if isinstance(planned, BaseException):
        raise planned
    if callable(planned):
        return planned()
    return planned


class FakeExchange:
    """Yanıtlar çift kimliğine göre verilir; çağrılar `calls`'a yazılır."""

    def __init__(
        self,
        pairs: Sequence[str] = (BTC, ETH),
        *,
        markets: object = None,
        klines: dict[str, object] | None = None,
        tickers: dict[str, object] | None = None,
    ) -> None:
        self._markets = {pair: market(pair) for pair in pairs} if markets is None else markets
        self._klines = {market_id(pair): candle_rows() for pair in pairs} | (klines or {})
        self._tickers = {market_id(pair): ticker(pair) for pair in pairs} | (tickers or {})
        self.calls: list[str] = []
        self.kline_requests: list[dict[str, Any]] = []

    def markets(self, timeout: float) -> object:
        self.calls.append("markets")
        return _answer(self._markets)

    def klines(
        self, market_id: str, interval: str, limit: int, end_ms: int, timeout: float
    ) -> object:
        self.calls.append(f"klines {market_id}")
        self.kline_requests.append(
            {"symbol": market_id, "interval": interval, "limit": limit, "end_ms": end_ms}
        )
        return _answer(self._klines[market_id])

    def ticker(self, market_id: str, timeout: float) -> object:
        self.calls.append(f"ticker {market_id}")
        return _answer(self._tickers[market_id])


def http_response(status: int, body: str, headers: dict[str, str] | None = None) -> Any:
    response = requests.Response()
    response.status_code = status
    response.reason = "recorded"
    response._content = body.encode("utf-8")
    response.headers.update(headers or {})
    return response


class FakeSession:
    """`requests.Session`'ın `ccxt`'nin kullandığı yüzü; istekler `requests`'e yazılır."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.requests: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}
        self.cookies = requests.cookies.RequestsCookieJar()

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        self.requests.append({"method": method, "url": url, **kwargs})
        for path, planned in self.routes.items():
            if path in url:
                return _answer(planned)
        raise AssertionError(f"no recorded response for {url}")


def recorded_routes() -> dict[str, Any]:
    """Kayıtlı Binance yanıtları; ayrıntılı yol kısa yoldan önce aranır."""
    routes: dict[str, Any] = {"exchangeInfo": fixture("exchange_info")}
    for symbol in ("btcusdt", "ethusdt"):
        routes[f"klines?symbol={symbol.upper()}"] = fixture(f"klines_{symbol}_1h")
        routes[f"ticker/24hr?symbol={symbol.upper()}"] = fixture(f"ticker_{symbol}")
    return {
        path: http_response(200, json.dumps(body), {"Content-Type": "application/json"})
        for path, body in routes.items()
    }


def recorded_client(routes: dict[str, Any] | None = None) -> tuple[PublicExchange, FakeSession]:
    """Gerçek `ccxt` istemcisi, sahte HTTP oturumu; yanıt bedeli testten gelebilir."""
    client = connect_public()
    session = FakeSession(recorded_routes() if routes is None else routes)
    client._exchange.session = session  # type: ignore[attr-defined]
    return client, session
