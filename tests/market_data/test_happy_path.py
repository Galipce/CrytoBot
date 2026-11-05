"""Spec 0017 AC-1: kayıtlı yanıtla iki çift; tüm alanlar, sırayla ve birebir (R-1, R-9)."""

from datetime import datetime, timedelta
from decimal import Context, Decimal

from crytobot.market_data import MarketRead, MarketRules, read_market_data
from tests.market_data.helpers import (
    BTC,
    ETH,
    FakeExchange,
    at_ms,
    clock_at,
    fixture,
    make_settings,
    recorded_client,
)

# After the last recorded candle closes and after both recorded stamps
RECORDED_NOW = at_ms(1793880300000)


def _read(pairs: list[str]) -> MarketRead:
    client, _ = recorded_client()
    return read_market_data(pairs, make_settings(), clock_at(RECORDED_NOW), connect=lambda: client)


def test_two_pairs_return_every_field_in_order() -> None:
    read = _read([ETH, BTC])
    assert read.input_problem is None
    assert [pair.pair for pair in read.pairs] == [ETH, BTC]
    for pair in read.pairs:
        assert pair.issues == ()
        assert pair.candles is not None
        assert len(pair.candles) == 3
        assert pair.price is not None
        assert pair.price_at is not None
        assert pair.spread is not None
        assert pair.tick is not None
        assert pair.rules is not None


def test_values_are_decimal_and_exact() -> None:
    btc = _read([BTC]).pairs[0]
    rows = fixture("klines_btcusdt_1h")
    assert btc.candles is not None
    for candle, row in zip(btc.candles, rows, strict=True):
        assert candle.open_time == at_ms(row[0])
        values = (candle.open, candle.high, candle.low, candle.close)
        assert all(type(value) is Decimal for value in values)
        assert [str(value) for value in values] == row[1:5]
    assert str(btc.tick) == "0.01000000"
    assert btc.rules == MarketRules(
        Decimal("0.00001000"), Decimal("0.00001000"), Decimal("5.00000000")
    )
    assert btc.rules is not None
    assert str(btc.rules.min_notional) == "5.00000000"


def test_price_is_last_trade() -> None:
    recorded = fixture("ticker_btcusdt")
    btc = _read([BTC]).pairs[0]
    assert str(btc.price) == recorded["lastPrice"]
    assert str(btc.price) != recorded["bidPrice"]


def test_spread_follows_formula() -> None:
    recorded = fixture("ticker_ethusdt")
    bid = Decimal(recorded["bidPrice"])
    ask = Decimal(recorded["askPrice"])
    wide = Context(prec=120)
    exact = wide.divide(wide.subtract(ask, bid), wide.divide(wide.add(ask, bid), Decimal(2)))
    spread = _read([ETH]).pairs[0].spread
    assert spread is not None
    assert type(spread) is Decimal
    assert Decimal(0) <= spread - exact < Decimal("1E-26")


def test_times_are_utc_aware() -> None:
    read = _read([BTC])
    btc = read.pairs[0]
    assert btc.price_at == at_ms(fixture("ticker_btcusdt")["closeTime"])
    moments: list[datetime | None] = [read.read_at, btc.price_at]
    assert btc.candles is not None
    moments += [candle.open_time for candle in btc.candles]
    for moment in moments:
        assert moment is not None
        assert moment.utcoffset() == timedelta(0)


def test_request_asks_for_the_set_count_up_to_the_last_closed_candle() -> None:
    exchange = FakeExchange()
    read_market_data(
        [BTC], make_settings(candle_count=2), clock_at(RECORDED_NOW), connect=lambda: exchange
    )
    assert exchange.kline_requests == [
        {"symbol": "BTCUSDT", "interval": "1h", "limit": 2, "end_ms": 1793879999999}
    ]


def test_clock_reads_before_candles_and_after_the_ticker() -> None:
    """Plan Risk 4: mum süzgeci istekten önce, kayma denetimi yanıttan sonra, `read_at` en son."""
    ticks = iter([RECORDED_NOW + timedelta(seconds=i) for i in range(10)])
    exchange = FakeExchange()
    read = read_market_data([BTC], make_settings(), lambda: next(ticks), connect=lambda: exchange)
    # first check, candle filter, drift check, read_at
    assert read.read_at == RECORDED_NOW + timedelta(seconds=3)


def test_read_at_is_later_than_every_stamp_so_the_turn_sees_no_future() -> None:
    read = _read([BTC, ETH])
    assert read.read_at is not None
    for pair in read.pairs:
        assert pair.price_at is not None
        assert pair.price_at <= read.read_at
