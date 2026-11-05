"""Spec 0017 AC-10: bozuk yanıt adlı neden üretir; sonuçta ham metin ve sır yoktur (R-11)."""

from dataclasses import asdict

import pytest

from crytobot.market_data import IssueReason, ReadField, ReadIssue, _calls, read_market_data
from tests.market_data.helpers import (
    BTC,
    FakeExchange,
    clock_at,
    http_response,
    make_settings,
    recorded_client,
    recorded_routes,
)

SECRET = "sk-live-AKIA1234567890SECRET"


@pytest.mark.parametrize(
    "answer",
    [
        '{"not": "a series"}',
        "[1, 2",
        "<html>" + SECRET + "</html>",
        '[["x", "1", "1", "1", "1"]]',
    ],
)
def test_malformed_response_gives_named_issue(answer: str) -> None:
    routes = recorded_routes()
    routes["klines?symbol=BTCUSDT"] = http_response(200, answer)
    client, _ = recorded_client(routes)
    read = read_market_data((BTC,), make_settings(), clock_at(), connect=lambda: client)
    btc = read.pairs[0]
    assert btc.candles is None
    assert [issue.field for issue in btc.issues] == [ReadField.CANDLES]
    assert btc.issues[0].reason in {IssueReason.MALFORMED_RESPONSE, IssueReason.NOT_A_NUMBER}
    assert btc.price is not None


@pytest.mark.parametrize("status", [400, 401, 418, 429, 500, 503])
def test_secret_in_error_never_reaches_result(status: int, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_calls, "_RETRY_DELAYS", (0.0, 0.0))
    routes = {
        "exchangeInfo": recorded_routes()["exchangeInfo"],
        "ticker/24hr": http_response(status, SECRET),
        "klines": http_response(status, f'{{"code":-1,"msg":"{SECRET}"}}'),
    }
    client, _ = recorded_client(routes)
    read = read_market_data((BTC,), make_settings(), clock_at(), connect=lambda: client)
    btc = read.pairs[0]
    assert btc.candles is None
    assert btc.price is None
    assert SECRET not in repr(read)
    assert SECRET not in repr(asdict(read))
    for issue in btc.issues:
        assert isinstance(issue, ReadIssue)
        assert isinstance(issue.reason, IssueReason)


def test_secret_shaped_exception_text_never_reaches_result() -> None:
    exchange = FakeExchange(tickers={"BTCUSDT": RuntimeError(SECRET)})
    read = read_market_data((BTC,), make_settings(), clock_at(), connect=lambda: exchange)
    assert SECRET not in repr(read)
    assert read.pairs[0].issues[0].reason is IssueReason.UNEXPECTED
