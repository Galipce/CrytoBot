"""Spec 0017 AC-9, R-10: okuma sonucunun tur girdisine çevirisi; elle kurulmuş `MarketRead`.

Kopya projede de koşar, `tests/market_data`'dan import etmez (Known trap, 0016 plan Risk 16).
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from crytobot.analysis import Candle
from crytobot.app import PairMarket, to_turn_market
from crytobot.market_data import (
    InputProblem,
    IssueReason,
    MarketCandle,
    MarketRead,
    MarketRules,
    PairRead,
    ReadField,
    ReadIssue,
)
from crytobot.risk import PairRules

BTC = "BTC/USDT"
ETH = "ETH/USDT"
OPENED = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
AT = datetime(2026, 11, 5, 13, 0, 44, tzinfo=UTC)


def _candle(*values: str) -> MarketCandle:
    open_, high, low, close = (Decimal(value) for value in values)
    return MarketCandle(OPENED, open_, high, low, close)


CANDLE = _candle("80100.01000000", "80308.35000000", "80000.50000000", "80231.48000000")


def _pair(pair: str = BTC, **overrides: Any) -> PairRead:
    values: dict[str, Any] = {
        "candles": (CANDLE,),
        "price": Decimal("80231.48000000"),
        "price_at": AT,
        "spread": Decimal("0.00012460"),
        "tick": Decimal("0.01000000"),
        "rules": MarketRules(Decimal("0.00001000"), Decimal("0.00002000"), Decimal("5.00000000")),
        "issues": (),
    }
    return PairRead(pair, **{**values, **overrides})


def _read(*pairs: PairRead) -> MarketRead:
    return MarketRead(pairs, AT, None)


def test_translation_is_lossless() -> None:
    market = to_turn_market(_read(_pair()))

    assert list(market) == [BTC]
    data = market[BTC]
    assert data.candles == (Candle(OPENED, 80100.01, 80308.35, 80000.5, 80231.48),)
    assert data.price_at == AT
    assert data.rules == PairRules(
        Decimal("0.00001000"), Decimal("0.00002000"), Decimal("5.00000000")
    )
    for translated, read in (
        (data.price, "80231.48000000"),
        (data.spread, "0.00012460"),
        (data.tick, "0.01000000"),
    ):
        assert type(translated) is Decimal
        assert str(translated) == read


def test_rule_values_keep_their_places() -> None:
    rules = to_turn_market(_read(_pair()))[BTC].rules
    assert rules is not None
    assert str(rules.amount_step) == "0.00001000"
    assert str(rules.min_amount) == "0.00002000"
    assert str(rules.min_notional) == "5.00000000"


def test_candle_values_keep_their_places() -> None:
    candle = _candle("1.5", "2.5", "0.5", "1.25")
    candles = to_turn_market(_read(_pair(candles=(candle,))))[BTC].candles
    assert candles == (Candle(OPENED, 1.5, 2.5, 0.5, 1.25),)


@pytest.mark.parametrize("place", range(4))
def test_inexact_float_series_is_missing(place: int) -> None:
    """Plan Risk 13: tek bir değer `float`'a sığmıyorsa serinin tamamı eksik veridir."""
    values = ["10.5", "11.5", "9.5", "10.25"]
    values[place] = "10.12345678901234567890"
    series = (CANDLE, _candle(*values))

    data = to_turn_market(_read(_pair(candles=series)))[BTC]

    assert data.candles is None
    assert data.price == Decimal("80231.48000000")


@pytest.mark.parametrize("value", ["1E+400", "1E-400"])
def test_value_outside_float_range_is_missing(value: str) -> None:
    candle = _candle(value, value, value, value)
    assert to_turn_market(_read(_pair(candles=(candle,))))[BTC].candles is None


def test_inexact_series_of_one_pair_leaves_the_other() -> None:
    inexact = _candle("10.12345678901234567890", "11", "9", "10")
    market = to_turn_market(_read(_pair(BTC, candles=(inexact,)), _pair(ETH)))
    assert market[BTC].candles is None
    assert market[ETH].candles is not None


def test_missing_fields_stay_missing() -> None:
    issues = tuple(ReadIssue(field, IssueReason.BUDGET_ENDED) for field in ReadField)
    empty = PairRead(BTC, None, None, None, None, None, None, issues)
    assert to_turn_market(_read(empty))[BTC] == PairMarket(None, None, None, None, None, None)


def test_empty_series_stays_an_empty_series() -> None:
    assert to_turn_market(_read(_pair(candles=())))[BTC].candles == ()


def test_order_follows_the_read() -> None:
    assert list(to_turn_market(_read(_pair(ETH), _pair(BTC)))) == [ETH, BTC]


def test_refused_read_gives_no_pairs() -> None:
    assert to_turn_market(MarketRead((), None, InputProblem.PAIRS)) == {}
