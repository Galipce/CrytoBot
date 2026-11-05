"""Spec 0017 AC-3: bir çiftin ya da alanın hatası diğerlerini etkilemez, istisna yok (R-3)."""

from typing import Any

import pytest

from crytobot.market_data import IssueReason, ReadField, ReadIssue, read_market_data
from crytobot.market_data._client import CallFailure, ExchangeCallError
from tests.market_data.helpers import (
    BTC,
    CLOSE_MS,
    ETH,
    HOUR_MS,
    FakeExchange,
    candle_rows,
    clock_at,
    make_settings,
    market,
)

BAD_SYMBOL = ExchangeCallError(CallFailure.BAD_SYMBOL)
OTHER = ExchangeCallError(CallFailure.OTHER)


def _read(exchange: Any, pairs: Any = (BTC, ETH), clock: Any = None) -> Any:
    return read_market_data(pairs, make_settings(), clock or clock_at(), connect=lambda: exchange)


def test_failed_field_stays_local_to_its_pair() -> None:
    exchange = FakeExchange(klines={"BTCUSDT": OTHER}, tickers={"ETHUSDT": BAD_SYMBOL})
    btc, eth = _read(exchange).pairs

    assert btc.candles is None
    assert btc.issues == (ReadIssue(ReadField.CANDLES, IssueReason.EXCHANGE_ERROR),)
    assert btc.price is not None
    assert btc.price_at is not None
    assert btc.spread is not None
    assert btc.tick is not None
    assert btc.rules is not None

    assert eth.candles is not None
    assert (eth.price, eth.price_at, eth.spread) == (None, None, None)
    assert {issue.field for issue in eth.issues} == {
        ReadField.PRICE,
        ReadField.PRICE_AT,
        ReadField.SPREAD,
    }
    assert {issue.reason for issue in eth.issues} == {IssueReason.BAD_SYMBOL}
    assert eth.tick is not None
    assert eth.rules is not None


def test_unusable_pair_does_not_touch_the_next() -> None:
    exchange = FakeExchange(markets={BTC: market(BTC, active=False), ETH: market(ETH)})
    btc, eth = _read(exchange).pairs
    assert btc.candles is None
    assert btc.price is None
    assert eth.issues == ()
    assert "klines BTCUSDT" not in exchange.calls
    assert "ticker BTCUSDT" not in exchange.calls


@pytest.mark.parametrize("failure", [OTHER, ExchangeCallError(CallFailure.BAD_RESPONSE)])
def test_markets_failure_names_every_field_of_every_pair(failure: Exception) -> None:
    btc, eth = _read(FakeExchange(markets=failure)).pairs
    for pair in (btc, eth):
        assert len(pair.issues) == 6
        assert {issue.field for issue in pair.issues} == set(ReadField)
        assert pair.price is None


def test_markets_answer_of_another_shape_is_malformed() -> None:
    btc = _read(FakeExchange(markets="text"), (BTC,)).pairs[0]
    assert {issue.reason for issue in btc.issues} == {IssueReason.MALFORMED_RESPONSE}


def test_no_exception_escapes() -> None:
    def explode() -> object:
        raise RuntimeError("secret-text")

    def fail_connect() -> Any:
        raise RuntimeError("secret-text")

    read = _read(FakeExchange(klines={"BTCUSDT": explode}, tickers={"ETHUSDT": explode}))
    assert read.pairs[0].candles is None
    assert read.pairs[0].price is not None
    assert read.pairs[1].candles is not None
    assert read.pairs[1].price is None
    assert "secret-text" not in repr(read)

    refused = read_market_data((BTC,), make_settings(), clock_at(), connect=fail_connect)
    assert {issue.reason for issue in refused.pairs[0].issues} == {IssueReason.UNEXPECTED}
    assert len(refused.pairs[0].issues) == 6


def test_clock_failing_mid_read_marks_the_rest_unexpected() -> None:
    answers = iter([clock_at()()])

    def clock() -> Any:
        return next(answers)  # StopIteration on the second reading

    read = _read(FakeExchange(), (BTC, ETH), clock)
    assert read.read_at == clock_at()()
    for pair in read.pairs:
        assert pair.candles is None
        assert pair.price is None
        assert {issue.reason for issue in pair.issues} == {IssueReason.UNEXPECTED}
    assert read.pairs[0].tick is not None  # settled before the clock failed


def test_gap_is_named_while_the_values_stay() -> None:
    gapped = [*candle_rows(1, CLOSE_MS - 4 * HOUR_MS), *candle_rows(2)]
    btc = _read(FakeExchange(klines={"BTCUSDT": gapped}), (BTC,)).pairs[0]
    assert btc.issues == (ReadIssue(ReadField.CANDLES, IssueReason.CANDLE_GAP),)
    assert btc.candles is not None
    assert len(btc.candles) == 2
