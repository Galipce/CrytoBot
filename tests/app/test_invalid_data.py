"""Spec 0016 AC-6: geçersiz veri AC-5'in durdurmasını uygular (R-4, plan Risk 6, 7)."""

import math
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.analysis import Candle
from crytobot.app import BuyHalt, NoticeKind
from crytobot.risk import PairRules
from tests.app.helpers import BTC, ETH, NOW, Bot, make_settings, opened_store, pair_market, series

SOL = "SOL/USDT"
SECOND = timedelta(seconds=1)


def _naive_candles() -> list[Candle]:
    return [Candle(c.open_time.replace(tzinfo=None), 10, 10, 10, 10) for c in series((10,) * 4)]


def _nan_candles() -> list[Candle]:
    return [*series((10.0, 8.0, 9.0)), Candle(NOW, math.nan, math.nan, math.nan, math.nan)]


INVALID: dict[str, Any] = {
    "unclosed_candle": lambda: pair_market(closed_at=NOW + SECOND, price_at=NOW),
    "future_price": lambda: pair_market(price_at=NOW + SECOND),
    "naive_price_time": lambda: pair_market(price_at=NOW.replace(tzinfo=None)),
    "naive_candle_time": lambda: pair_market(candles=_naive_candles()),
    "rejected_series": lambda: pair_market(candles=_nan_candles()),
    "not_a_series": lambda: pair_market(candles=None),
    "empty_series": lambda: pair_market(candles=[]),
    "zero_price": lambda: pair_market(price=Decimal(0)),
    "nan_price": lambda: pair_market(price=Decimal("NaN")),
    "float_price": lambda: pair_market(price=10.0),
    "missing_rules": lambda: pair_market(rules=None),
    "bad_rules": lambda: pair_market(rules=PairRules(Decimal(-1), Decimal(0), Decimal(0))),
    "missing_spread": lambda: pair_market(spread=None),
    "bad_spread": lambda: pair_market(spread=Decimal(2)),
    "missing_tick": lambda: pair_market(tick=None),
    "bad_tick": lambda: pair_market(tick=Decimal(0)),
    "not_market_data": lambda: "not market data",
    "missing_pair": lambda: None,
}


@pytest.mark.parametrize("case", INVALID)
def test_invalid_data_halts_buying(tmp_path: Path, case: str) -> None:
    bad = INVALID[case]()
    market = {BTC: pair_market()}
    if bad is not None:
        market[ETH] = bad
    bot = Bot(opened_store(tmp_path / "s.db"), settings=make_settings((BTC, ETH)))

    result = bot.turn(market)

    assert result.buys == () and result.pairs == ()
    assert BuyHalt.INVALID_DATA in result.halts
    assert [(n.kind, n.subject) for n in bot.notices] == [(NoticeKind.INVALID_DATA, ETH)]


def test_bad_third_pair_stops_first_pair_buy(tmp_path: Path) -> None:
    """Plan Risk 6: bozuk seri alımdan önce görülür; ilk çift de alınmaz."""
    bot = Bot(opened_store(tmp_path / "s.db"), settings=make_settings((BTC, ETH, SOL)))

    result = bot.turn(
        {BTC: pair_market(), ETH: pair_market(), SOL: pair_market(candles=_nan_candles())}
    )

    assert result.buys == ()
    assert bot.stored().execution.orders == {}


def test_market_that_is_not_a_mapping_is_missing_data(tmp_path: Path) -> None:
    bad: Any = [BTC]
    bot = Bot(opened_store(tmp_path / "s.db"))

    result = bot.turn(bad)

    assert result.buys == () and BuyHalt.INVALID_DATA in result.halts


def test_short_series_is_an_ordinary_reason(tmp_path: Path) -> None:
    """Plan Risk 7: kısa seri eksik veri değildir, "öneri yok"dur."""
    bot = Bot(opened_store(tmp_path / "s.db"))

    result = bot.turn({BTC: pair_market((10.0,))})

    assert result.halts == () and bot.notices == []
    assert result.pairs[0].reason.value == "insufficient_history"
