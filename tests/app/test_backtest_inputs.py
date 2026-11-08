"""Spec 0025 AC-1 (girdi kısmı), AC-6 (R-5, R-6; plan Risk 6, 8): tur anı başına girdi, ileriye
bakmadan; eksik fiyatta alım durur, fiyatsız kapanış olmaz."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from crytobot.app import BuyHalt, TurnMemory, run_turn
from crytobot.app._backtest_inputs import TurnInputs
from crytobot.execution import PaperExchange
from tests.app.backtest_helpers import COUNT, at, candles, history, settings
from tests.app.helpers import BTC, ETH, HOUR, SPREAD, TICK, opened_store

SERIES = {
    # open, high, low, close differ: the price must be the open of the candle opening at the turn
    BTC: candles(
        -COUNT, [(10, 11, 9, 10.5), (11, 12, 10, 11.5), (12, 13, 11, 12.5), (13, 14, 12, 13.5)]
    )
    + candles(0, [(14, 15, 13, 14.5), (15, 16, 14, 15.5), (16, 17, 15, 16.5)]),
}


def inputs(series: dict = SERIES, hours: int = 3, **turn: object) -> TurnInputs:  # type: ignore[type-arg]
    return TurnInputs(history(series, hours=hours), settings((BTC,), **turn), COUNT, SPREAD)


def test_turn_price_is_open_of_candle_opening_at_turn() -> None:
    """R-5: fiyat, tur anında açılan mumun açılışıdır; zamanı tur anıdır."""
    source = inputs()
    for hour, expected in ((0, "14"), (1, "15"), (2, "16")):
        market = source.market(at(hour))[BTC]
        assert market.price == Decimal(expected)
        assert market.price_at == at(hour)
        assert (market.rules, market.tick, market.spread) == (
            market.rules,
            TICK,
            SPREAD,
        )


def test_turn_sees_no_candle_closing_after_turn() -> None:
    """R-5: kapanışı tur anından sonra olan hiçbir mum tura verilmez; son `candle_count` mum."""
    source = inputs()
    for hour in range(3):
        moment = at(hour)
        series = source.market(moment)[BTC].candles
        assert series is not None
        assert len(series) == COUNT
        assert all(item.open_time + HOUR <= moment for item in series)
        assert series[-1].open_time + HOUR == moment  # the last candle closed at the turn
        assert [item.close for item in series][-1] == 13.5 + hour


def test_going_back_in_time_recounts() -> None:
    source = inputs()
    source.market(at(2))
    series = source.market(at(0))[BTC].candles
    assert series is not None and series[-1].open_time == at(-1)


def test_before_first_candle_series_is_empty_and_price_missing() -> None:
    """Geç listelenen çift: ilk mumundan önceki turda mum ve fiyat yok."""
    late = {BTC: SERIES[BTC], ETH: candles(2, [10])}
    source = TurnInputs(history(late, hours=3), settings(), COUNT, SPREAD)
    market = source.market(at(0))
    assert market[ETH].candles == () and market[ETH].price is None
    assert source.missing(market, at(0)) == (ETH,)
    market = source.market(at(2))
    assert market[ETH].price == 10 and market[ETH].candles == ()
    assert source.missing(market, at(2)) == (ETH,)  # nothing closed yet: missing data


def test_inexact_float_makes_the_series_missing() -> None:
    """Paper'daki gibi: `float`'ta birebir dönmeyen mum çiftin serisini eksik yapar."""
    odd = {
        BTC: candles(-COUNT, ["0.1000000000000000055511151231257827", 8, 9, 10]) + candles(0, [10])
    }
    source = TurnInputs(history(odd, hours=1), settings((BTC,)), COUNT, SPREAD)
    market = source.market(at(0))
    assert market[BTC].candles is None
    assert source.missing(market, at(0)) == (BTC,)


def test_stale_candles_count_as_missing() -> None:
    gap = {BTC: candles(-COUNT, [10, 8, 9, 10, None, 10])}  # the candle at hour 0 is missing
    source = TurnInputs(history(gap, hours=2), settings((BTC,)), COUNT, SPREAD)
    market = source.market(at(1))
    assert market[BTC].price == 10  # the price is there, the last closed candle is an hour old
    assert source.missing(market, at(1)) == (BTC,)
    fresh = TurnInputs(history(gap, hours=2), settings((BTC,), max_candle_age=HOUR), COUNT, SPREAD)
    assert fresh.missing(fresh.market(at(1)), at(1)) == ()


def test_missing_price_halts_buys_and_no_close_without_price(tmp_path: Path) -> None:
    """R-6, BR-11: o turda alım durur, fiyatı eksik çiftin açık pozisyonu kapatılmaz."""
    series = {
        BTC: candles(-COUNT, [10, 8, 9, 10, 10, None, 7]),  # bought at 0, no candle at 1, 7 < stop
        ETH: candles(-COUNT, [10, 10, 10, 10, 10, 10, 10]),
    }
    store = opened_store(tmp_path / "s.db", at=at(-1))
    source = TurnInputs(history(series, hours=3), settings(), COUNT, SPREAD)
    memory, exchange = TurnMemory(), PaperExchange()

    def turn(hour: int):  # type: ignore[no-untyped-def]
        market = source.market(at(hour))
        result = run_turn(
            market=market,
            settings=settings(),
            store_path=store,
            now=at(hour),
            exchange=exchange,
            sink=lambda _notice: None,
            memory=memory,
        )
        return result, source.missing(market, at(hour))

    bought, missing = turn(0)
    assert [order.pair for order in bought.buys] == [BTC] and missing == ()
    held, missing = turn(1)
    assert missing == (BTC,)
    assert held.buys == () and held.closes == ()
    assert BuyHalt.INVALID_DATA in held.halts or BuyHalt.STALE_DATA in held.halts
    closed, missing = turn(2)  # the price is back: the stop closes, buying still stops (stale)
    assert [order.pair for order in closed.closes] == [BTC]
    assert closed.buys == () and missing == (BTC,)
    assert closed.closes[0].fill_price == Decimal(7) * (1 - Decimal("0.001"))


def test_turn_interval_longer_than_candles() -> None:
    """Plan Risk 6: tur aralığı mum aralığının katıdır; her tur bir mumun açılışına denk gelir."""
    series = {BTC: candles(-COUNT, [10, 8, 9, 10, 11, 12, 13, 14])}
    source = TurnInputs(history(series, hours=4), settings((BTC,)), COUNT, SPREAD)
    market = source.market(at(2))[BTC]
    assert market.price == 13
    assert market.candles is not None
    assert [item.close for item in market.candles] == [9.0, 10.0, 11.0, 12.0]
    assert source.market(at(2) + timedelta(minutes=30))[BTC].price is None
