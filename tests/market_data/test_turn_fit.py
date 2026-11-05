"""Spec 0017 AC-9, AC-8 (B-43): okuma sonucu `run_turn`'e gider; `run_turn` değişmez (R-3, R-10)."""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import BuyHalt, TurnOutcome, TurnResult, to_turn_market
from crytobot.market_data import MarketRead, read_market_data
from crytobot.market_data._client import CallFailure, ExchangeCallError
from crytobot.strategy import NoProposalReason
from tests.app.helpers import Bot, bot_with_position, opened_store
from tests.market_data.helpers import (
    BTC,
    CLOSE_MS,
    ETH,
    HOUR_MS,
    FakeExchange,
    at_ms,
    candle_row,
    clock_at,
    make_settings,
    market,
    recorded_client,
    ticker,
)

OTHER = ExchangeCallError(CallFailure.OTHER)
RECORDED_NOW = at_ms(1793880300000)
FRESH_NOW = at_ms(CLOSE_MS + 60_000)  # the recorded times are fresh for the turn settings
CROSS = ("10.00", "8.00", "9.00", "10.00")  # tests/app/helpers: entry 10, stop 8, target 14


def _rows(closes: tuple[str, ...] = CROSS) -> list[list[object]]:
    count = len(closes)
    return [
        candle_row(CLOSE_MS - (count - i) * HOUR_MS, value, value, value, value)
        for i, value in enumerate(closes)
    ]


def _read(exchange: Any) -> MarketRead:
    settings = make_settings(candle_count=4)
    return read_market_data([BTC], settings, clock_at(FRESH_NOW), connect=lambda: exchange)


def _exchange(**overrides: Any) -> FakeExchange:
    values: dict[str, Any] = {
        "klines": {"BTCUSDT": _rows()},
        "tickers": {"BTCUSDT": ticker(lastPrice="10.00")},
    }
    return FakeExchange((BTC,), **{**values, **overrides})


def _turn(bot: Bot, read: MarketRead) -> TurnResult:
    assert read.read_at is not None
    return bot.turn(to_turn_market(read), now=read.read_at)


def test_clean_read_completes_a_turn(tmp_path: Path) -> None:
    """Kayıtlı Binance yanıtı olduğu gibi: durdurma yok, BTC alımı defterle çelişmez."""
    client, _ = recorded_client()
    read = read_market_data(
        [BTC, ETH], make_settings(), clock_at(RECORDED_NOW), connect=lambda: client
    )
    assert all(pair.issues == () for pair in read.pairs)

    bot = Bot(opened_store(tmp_path / "s.db"))
    result = _turn(bot, read)

    assert result.outcome is TurnOutcome.COMPLETED
    assert result.halts == ()
    assert [order.pair for order in result.buys] == [BTC]
    assert result.buys[0].created_at == read.read_at
    assert bot.conflicts() == ()


def test_short_series_is_no_proposal_and_does_not_halt(tmp_path: Path) -> None:
    """R-6, R-16: kısa seri hata değildir; tur "öneri yok" der, alımı durdurmaz."""
    bot = Bot(opened_store(tmp_path / "s.db"))
    result = _turn(bot, _read(_exchange(klines={"BTCUSDT": _rows(CROSS[-2:])})))

    assert result.halts == ()
    assert result.buys == ()
    assert [(note.pair, note.reason) for note in result.pairs] == [
        (BTC, NoProposalReason.INSUFFICIENT_HISTORY)
    ]


def test_clean_read_can_buy(tmp_path: Path) -> None:
    bot = Bot(opened_store(tmp_path / "s.db"))
    result = _turn(bot, _read(_exchange()))

    assert result.outcome is TurnOutcome.COMPLETED
    assert result.halts == ()
    assert [order.pair for order in result.buys] == [BTC]
    assert bot.conflicts() == ()


def test_recorded_scale_prices_can_buy(tmp_path: Path) -> None:
    """Kayıtlı BTC ölçeği ve spread'i: 8 ondalıklı değerler alımı kesmez, birebir geçer."""
    closes = ("80231.48000000", "78000.25000000", "79000.50000000", "80231.48000000")
    quote = ticker(lastPrice=closes[-1], bidPrice="80231.47000000", askPrice=closes[-1])
    rules = market(
        precision={"price": "0.01000000", "amount": "0.00001000"},
        limits={"amount": {"min": "0.00001000"}, "cost": {"min": "5.00000000"}},
    )
    read = _read(
        _exchange(
            markets={BTC: rules}, klines={"BTCUSDT": _rows(closes)}, tickers={"BTCUSDT": quote}
        )
    )
    assert read.pairs[0].issues == ()

    bot = Bot(opened_store(tmp_path / "s.db"))
    result = _turn(bot, read)

    assert result.halts == ()
    assert [order.pair for order in result.buys] == [BTC]
    assert bot.conflicts() == ()


@pytest.mark.parametrize(
    "failing",
    [
        {"klines": {"BTCUSDT": OTHER}},
        {"tickers": {"BTCUSDT": OTHER}},
        {"tickers": {"BTCUSDT": ticker(lastPrice=None)}},
        {"tickers": {"BTCUSDT": ticker(closeTime=None)}},
    ],
    ids=["candles-failed", "price-failed", "no-last-price", "no-stamp"],
)
def test_missing_price_or_candles_halts_buying(tmp_path: Path, failing: dict[str, Any]) -> None:
    bot = Bot(opened_store(tmp_path / "s.db"))
    result = _turn(bot, _read(_exchange(**failing)))

    assert result.outcome is TurnOutcome.COMPLETED
    assert result.buys == ()
    assert BuyHalt.INVALID_DATA in result.halts


def test_refused_read_makes_no_trade(tmp_path: Path) -> None:
    bot = Bot(opened_store(tmp_path / "s.db"))
    refused = read_market_data([BTC, BTC], make_settings(), clock_at(FRESH_NOW))
    assert refused.input_problem is not None

    result = bot.turn(to_turn_market(refused), now=FRESH_NOW)

    assert result.buys == ()
    assert BuyHalt.INVALID_DATA in result.halts


def test_refused_read_with_its_own_time_is_an_invalid_turn(tmp_path: Path) -> None:
    bot = Bot(opened_store(tmp_path / "s.db"))
    refused = read_market_data([BTC, BTC], make_settings(), clock_at(FRESH_NOW))
    assert refused.read_at is None

    result = bot.turn(to_turn_market(refused), now=refused.read_at)

    assert result.outcome is TurnOutcome.INVALID_TIME
    assert result.buys == ()


def test_position_with_fresh_price_closes(tmp_path: Path) -> None:
    """R-3, 0016 R-4: mumu alınamayan çiftin fiyatı taze ise stop kapanışı sürer, alım durur."""
    bot = bot_with_position(tmp_path / "s.db")
    read = _read(
        _exchange(klines={"BTCUSDT": OTHER}, tickers={"BTCUSDT": ticker(lastPrice="7.00")})
    )
    assert read.pairs[0].candles is None

    result = _turn(bot, read)

    assert result.outcome is TurnOutcome.COMPLETED
    assert [order.pair for order in result.closes] == [BTC]
    assert result.buys == ()
    assert BuyHalt.INVALID_DATA in result.halts
    assert bot.stored().ledger.positions == {}


def test_position_without_a_price_stays_open(tmp_path: Path) -> None:
    bot = bot_with_position(tmp_path / "s.db")
    result = _turn(bot, _read(_exchange(tickers={"BTCUSDT": OTHER})))

    assert result.closes == ()
    assert len(bot.stored().ledger.positions) == 1


def test_b43_composition_is_clean(tmp_path: Path) -> None:
    """AC-8, B-43: okumanın geçirebildiği en ince alım fiyatı, `9E15` kapanış ve 1e12 yatırma."""
    tick = "0." + "0" * 17 + "1"
    buy_price = "10." + "0" * 17 + "1"
    rules = market(precision={"price": tick, "amount": "0.001"})
    bot = Bot(opened_store(tmp_path / "s.db", deposit=Decimal(10) ** 12))

    bought = _turn(
        bot,
        _read(_exchange(markets={BTC: rules}, tickers={"BTCUSDT": ticker(lastPrice=buy_price)})),
    )
    assert len(bought.buys) == 1, bought
    assert bought.buys[0].amount > Decimal(4) * Decimal(10) ** 9

    high = "9000000000000000"
    quote = ticker(lastPrice=high, bidPrice=high, askPrice=high)
    closed = _turn(bot, _read(_exchange(markets={BTC: rules}, tickers={"BTCUSDT": quote})))

    assert bot.conflicts() == ()
    assert len(closed.closes) == 1
    assert bot.stored().ledger.positions == {}


def test_b43_price_only_the_ledger_refuses_leaves_no_conflict(tmp_path: Path) -> None:
    """Okumanın geçirdiği 34 basamaklı kapanış fiyatını defter reddeder: kalıcı çelişki kalmaz."""
    tick = "0." + "0" * 17 + "1"
    rules = market(precision={"price": tick, "amount": "0.001"})
    bot = Bot(opened_store(tmp_path / "s.db", deposit=Decimal(10) ** 12))
    assert len(_turn(bot, _read(_exchange(markets={BTC: rules}))).buys) == 1

    high = "9000000000000000." + "0" * 17 + "1"
    quote = ticker(lastPrice=high, bidPrice=high, askPrice=high)
    read = _read(_exchange(markets={BTC: rules}, tickers={"BTCUSDT": quote}))
    assert read.pairs[0].issues == ()

    result = _turn(bot, read)

    assert bot.conflicts() == ()
    assert result.closes == ()
    assert BuyHalt.INVALID_DATA in result.halts
    assert len(bot.stored().ledger.positions) == 1
