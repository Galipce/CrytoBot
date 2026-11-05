"""Spec 0022 AC-10 (R-11, B-48): okuma borsa yasağını ve bitiş anını `MarketRead.ban` ile bildirir.

Okumanın istekleri değişmez: yasaktan sonra o okumada başka istek gitmez (0017 plan Risk 7).
"""

from datetime import timedelta

import pytest

from crytobot.market_data import ReadBan, read_market_data
from crytobot.market_data._client import CallFailure, ExchangeCallError
from tests.market_data.helpers import (
    BTC,
    ETH,
    NOW,
    FakeExchange,
    clock_at,
    http_response,
    make_settings,
    recorded_client,
    recorded_routes,
)


def test_418_reports_ban_until() -> None:
    exchange = FakeExchange(klines={"BTCUSDT": ExchangeCallError(CallFailure.BANNED, 120)})
    read = read_market_data((BTC, ETH), make_settings(), clock_at(), connect=lambda: exchange)
    assert read.ban == ReadBan(NOW + timedelta(seconds=120))
    assert exchange.calls == ["markets", "klines BTCUSDT"]


def test_418_from_the_http_answer_reports_ban_until() -> None:
    """Gerçek `ccxt`, sahte HTTP: başlık `Retry-After`'tan bitiş anına kadar."""
    routes = recorded_routes()
    routes["klines?symbol=BTCUSDT"] = http_response(
        418, '{"code":-1003,"msg":"banned"}', {"Retry-After": "259200"}
    )
    client, _ = recorded_client(routes)
    read = read_market_data((BTC,), make_settings(), clock_at(), connect=lambda: client)
    assert read.ban == ReadBan(NOW + timedelta(days=3))


def test_418_without_retry_after_reports_open_ban() -> None:
    exchange = FakeExchange(tickers={"BTCUSDT": ExchangeCallError(CallFailure.BANNED)})
    read = read_market_data((BTC,), make_settings(), clock_at(), connect=lambda: exchange)
    assert read.ban == ReadBan(None)


@pytest.mark.parametrize(
    "answer",
    [ExchangeCallError(CallFailure.RATE_LIMITED, 0.1), ExchangeCallError(CallFailure.TRANSIENT)],
)
def test_429_reports_no_ban(answer: ExchangeCallError) -> None:
    exchange = FakeExchange(klines={"BTCUSDT": answer})
    read = read_market_data((BTC,), make_settings(), clock_at(), connect=lambda: exchange)
    assert read.ban is None


def test_clean_and_refused_reads_report_no_ban() -> None:
    exchange = FakeExchange()
    clean = read_market_data((BTC,), make_settings(), clock_at(), connect=lambda: exchange)
    assert clean.pairs[0].price is not None and clean.ban is None
    refused = read_market_data((BTC, BTC), make_settings(), clock_at(), connect=lambda: exchange)
    assert refused.input_problem is not None and refused.ban is None
