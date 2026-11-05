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
from tests.app.helpers import (
    BTC,
    CROSS,
    DEPOSIT,
    ETH,
    LATER,
    NEXT_CANDLE,
    NOW,
    RULES,
    TICK,
    Bot,
    bot_with_position,
    make_settings,
    opened_store,
    pair_market,
    series,
)

SOL = "SOL/USDT"
SECOND = timedelta(seconds=1)
NO_MINIMUM = PairRules(RULES.amount_step, RULES.min_amount, Decimal(0))
MICRO = Decimal("0.000001")
MICRO_STEP = Decimal("0.00000001")


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
    "price_over_scale": lambda: pair_market(price=Decimal("1E16")),
    "price_past_lowest_place": lambda: pair_market(price=Decimal("1E-29")),
    "long_price_past_lowest_place": lambda: pair_market(price=Decimal("9.11E-27")),
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


@pytest.mark.parametrize("price", [Decimal("1E16"), Decimal("1E-29")])
def test_price_out_of_scale_places_no_close(tmp_path: Path, price: Decimal) -> None:
    """Review round 2 F-3: emir oluşsaydı defter reddeder, işaret kalıcı olurdu."""
    bot = bot_with_position(tmp_path / "s.db")
    orders = len(bot.stored().execution.orders)

    result = bot.turn({BTC: pair_market(price=price, price_at=LATER, rules=NO_MINIMUM)}, now=LATER)

    assert result.closes == () and BuyHalt.INVALID_DATA in result.halts
    assert (NoticeKind.INVALID_DATA, BTC) in [(n.kind, n.subject) for n in bot.notices]
    stored = bot.stored()
    assert len(stored.execution.orders) == orders and len(stored.ledger.positions) == 1
    assert bot.conflicts() == ()


@pytest.mark.parametrize(
    "price", [Decimal("9.1111111E15"), Decimal("1E-28"), Decimal("9.1111111E-21")]
)
@pytest.mark.parametrize(
    ("scale", "deposit", "step"),
    [(Decimal(1), DEPOSIT, Decimal("0.001")), (MICRO, Decimal(10) ** 12, MICRO_STEP)],
    ids=["ordinary_amount", "huge_amount"],
)
def test_price_at_the_limits_closes_into_the_ledger(
    tmp_path: Path, price: Decimal, scale: Decimal, deposit: Decimal, step: Decimal
) -> None:
    """Review round 2 F-3: sınırdaki fiyat ve ~5e15 birimlik pozisyon defterden geçer."""
    closes = tuple(float(Decimal(str(close)) * scale) for close in CROSS)
    rules = PairRules(step, step, Decimal(0))
    bot = Bot(opened_store(tmp_path / "s.db", deposit=deposit))
    tick = step if scale == MICRO else TICK
    bought = bot.turn({BTC: pair_market(closes, price=Decimal(10) * scale, rules=rules, tick=tick)})
    assert len(bought.buys) == 1, bought

    result = bot.turn(
        {BTC: pair_market(closes, price=price, price_at=LATER, rules=rules, tick=tick)},
        now=LATER,
    )

    assert len(result.closes) == 1, result
    assert bot.stored().ledger.positions == {} and bot.conflicts() == ()


def test_bad_third_pair_stops_first_pair_buy(tmp_path: Path) -> None:
    """Plan Risk 6: bozuk seri alımdan önce görülür; ilk çift de alınmaz."""
    bot = Bot(opened_store(tmp_path / "s.db"), settings=make_settings((BTC, ETH, SOL)))

    result = bot.turn(
        {BTC: pair_market(), ETH: pair_market(), SOL: pair_market(candles=_nan_candles())}
    )

    assert result.buys == ()
    assert bot.stored().execution.orders == {}


@pytest.mark.parametrize(
    "bad_price",
    [
        {"price_at": LATER + SECOND},
        {"price": Decimal("NaN"), "price_at": LATER},
        {"price_at": LATER.replace(tzinfo=None)},
    ],
    ids=["future_price", "nan_price", "naive_price_time"],
)
def test_invalid_position_price_stays_open_other_closes(
    tmp_path: Path, bad_price: dict[str, Any]
) -> None:
    """R-4, VERIFY round 1 V-2: geçersiz fiyatlı pozisyon kapanmaz, geçerli olan kapanır."""
    bot = Bot(opened_store(tmp_path / "s.db"), settings=make_settings((BTC, ETH)))
    bot.turn({BTC: pair_market(), ETH: pair_market()})

    halted = bot.turn(
        {BTC: pair_market(**bad_price), ETH: pair_market(price=Decimal(7), price_at=LATER)},
        now=LATER,
    )

    assert [o.pair for o in halted.closes] == [ETH]
    assert halted.buys == ()
    assert BuyHalt.INVALID_DATA in halted.halts
    assert [p.pair for p in bot.stored().ledger.positions.values()] == [BTC]

    clean = bot.turn(
        {
            BTC: pair_market(closed_at=NEXT_CANDLE),
            ETH: pair_market(closed_at=NEXT_CANDLE),
        },
        now=NEXT_CANDLE,
    )

    assert clean.halts == ()
    assert [o.pair for o in clean.buys] == [ETH]
    assert sorted(p.pair for p in bot.stored().ledger.positions.values()) == [BTC, ETH]


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
