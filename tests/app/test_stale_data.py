"""Spec 0016 AC-5: bayatlık sınırı; bayat tek çift tüm alımları durdurur (R-4, BR-11, B-39)."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from crytobot.app import BuyHalt, NoticeKind
from tests.app.helpers import (
    BTC,
    ETH,
    LATER,
    MAX_CANDLE_AGE,
    MAX_PRICE_AGE,
    MINUTE,
    NOW,
    Bot,
    make_settings,
    opened_store,
    pair_market,
)

UNIT = timedelta(microseconds=1)


def test_candle_age_at_limit_is_fresh(tmp_path: Path) -> None:
    now = NOW + MAX_CANDLE_AGE
    bot = Bot(opened_store(tmp_path / "s.db"))

    result = bot.turn({BTC: pair_market(price_at=now)}, now=now)

    assert len(result.buys) == 1 and result.halts == ()


def test_candle_one_unit_over_is_stale(tmp_path: Path) -> None:
    now = NOW + MAX_CANDLE_AGE + UNIT
    bot = Bot(opened_store(tmp_path / "s.db"))

    result = bot.turn({BTC: pair_market(price_at=now)}, now=now)

    assert result.buys == () and result.halts == (BuyHalt.STALE_DATA,)


def test_price_age_at_limit_is_fresh(tmp_path: Path) -> None:
    now = NOW + MAX_PRICE_AGE
    bot = Bot(opened_store(tmp_path / "s.db"))

    result = bot.turn({BTC: pair_market(price_at=NOW)}, now=now)

    assert len(result.buys) == 1 and result.halts == ()


def test_price_one_unit_over_is_stale(tmp_path: Path) -> None:
    now = NOW + MAX_PRICE_AGE + UNIT
    bot = Bot(opened_store(tmp_path / "s.db"))

    result = bot.turn({BTC: pair_market(price_at=NOW)}, now=now)

    assert result.buys == () and result.halts == (BuyHalt.STALE_DATA,)


def test_stale_pair_halts_every_buy(tmp_path: Path) -> None:
    now = NOW + MINUTE
    bot = Bot(opened_store(tmp_path / "s.db"), settings=make_settings((BTC, ETH)))
    stale = pair_market(price_at=now - MAX_PRICE_AGE - UNIT)

    result = bot.turn({BTC: pair_market(price_at=now), ETH: stale}, now=now)

    assert result.buys == () and result.pairs == ()
    assert [(n.kind, n.subject) for n in bot.notices] == [(NoticeKind.STALE_DATA, ETH)]


def test_stale_position_stays_fresh_one_closes(tmp_path: Path) -> None:
    """R-4: fiyatı bayat pozisyon kapanmaz, taze olan kapanır."""
    bot = Bot(opened_store(tmp_path / "s.db"), settings=make_settings((BTC, ETH)))
    bot.turn({BTC: pair_market(), ETH: pair_market()})
    low = Decimal(7)

    result = bot.turn(
        {
            BTC: pair_market(price=low, price_at=LATER - MAX_PRICE_AGE - UNIT),
            ETH: pair_market(price=low, price_at=LATER),
        },
        now=LATER,
    )

    assert [o.pair for o in result.closes] == [ETH]
    assert [p.pair for p in bot.stored().ledger.positions.values()] == [BTC]
    assert result.buys == ()


def test_clean_turn_resumes_buying(tmp_path: Path) -> None:
    bot = Bot(opened_store(tmp_path / "s.db"))
    now = NOW + MINUTE
    stale_price = now - MAX_PRICE_AGE - UNIT

    halted = bot.turn({BTC: pair_market(price_at=stale_price)}, now=now)
    resumed = bot.turn({BTC: pair_market(price_at=now)}, now=now)

    assert halted.buys == () and len(resumed.buys) == 1 and resumed.halts == ()
