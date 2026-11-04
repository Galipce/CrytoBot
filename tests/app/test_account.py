"""Spec 0016 AC-14: kasa hesaplanamıyor (R-16); geri giden saat (plan Risk 3)."""

from decimal import Decimal
from pathlib import Path

from crytobot.app import BuyHalt, NoticeKind, TurnOutcome
from crytobot.persistence import create_store
from tests.app.helpers import (
    BTC,
    ETH,
    FLAT,
    HOUR,
    LATER,
    MAX_PRICE_AGE,
    MINUTE,
    NOW,
    Bot,
    bot_with_position,
    make_settings,
    opened_store,
    pair_market,
)


def test_unopened_ledger_does_nothing(tmp_path: Path) -> None:
    path = tmp_path / "s.db"
    create_store(path, "paper")
    before = path.read_bytes()
    bot = Bot(path)

    result = bot.turn()

    assert result.outcome is TurnOutcome.LEDGER_NOT_OPENED and result.buys == ()
    assert bot.kinds() == [NoticeKind.LEDGER_NOT_OPENED]
    assert path.read_bytes() == before


def test_rejected_observation_halts_buy_keeps_closing(tmp_path: Path) -> None:
    """Son gözlem LATER; tur ondan eski ama pozisyonun açılışından yeni: kapanış sürer."""
    bot = Bot(opened_store(tmp_path / "s.db"), settings=make_settings((BTC, ETH)))
    bot.turn({BTC: pair_market(), ETH: pair_market(FLAT)})
    bot.turn({BTC: pair_market(price_at=LATER), ETH: pair_market(FLAT, price_at=LATER)}, now=LATER)
    earlier = NOW + MINUTE

    result = bot.turn(
        {BTC: pair_market(price=Decimal(7), price_at=earlier), ETH: pair_market(price_at=earlier)},
        now=earlier,
    )

    assert [o.pair for o in result.closes] == [BTC]
    assert result.buys == () and BuyHalt.OBSERVATION_REJECTED in result.halts
    assert bot.kinds() == [NoticeKind.OBSERVATION_REJECTED]
    assert bot.stored().risk.last_time == LATER
    assert bot.conflicts() == ()


def test_stale_position_skips_observation(tmp_path: Path) -> None:
    """R-16: bayat fiyatlı pozisyonda gözlem yok, risk durumu değişmez."""
    bot = bot_with_position(tmp_path / "s.db")
    before = bot.stored().risk

    result = bot.turn({BTC: pair_market(price_at=LATER - MAX_PRICE_AGE - MINUTE)}, now=LATER)

    assert BuyHalt.STALE_DATA in result.halts
    assert bot.stored().risk == before


def test_clock_before_position_open_places_no_close(tmp_path: Path) -> None:
    """Plan Risk 3: emir oluşsaydı defter reddeder, işaret kalıcı olurdu."""
    bot = bot_with_position(tmp_path / "s.db")
    earlier = NOW - MINUTE

    result = bot.turn({BTC: pair_market(closed_at=earlier, price=Decimal(7))}, now=earlier)

    assert result.closes == ()
    assert len(bot.stored().execution.orders) == 1 and bot.conflicts() == ()
    assert NoticeKind.CLOSE_REFUSED in bot.kinds()

    retried = bot.turn({BTC: pair_market(price=Decimal(7), price_at=LATER)}, now=LATER)

    assert len(retried.closes) == 1


def test_clock_before_ledger_open_places_no_buy(tmp_path: Path) -> None:
    """Plan Risk 3: defter `NOW - HOUR`'da açıldı."""
    earlier = NOW - 2 * HOUR
    bot = Bot(opened_store(tmp_path / "s.db"))

    result = bot.turn({BTC: pair_market(closed_at=earlier)}, now=earlier)

    assert result.buys == () and BuyHalt.OBSERVATION_REJECTED in result.halts
    assert bot.conflicts() == ()


def test_price_only_the_ledger_refuses_halts_buying(tmp_path: Path) -> None:
    """Plan Risk 7: 29 basamaklı fiyat tazedir ama defter kullanmaz: gözlem yok, alım durur."""
    bot = bot_with_position(tmp_path / "s.db")
    long_price = Decimal("9." + "1" * 28)

    result = bot.turn({BTC: pair_market(price=long_price, price_at=LATER)}, now=LATER)

    assert BuyHalt.INVALID_DATA in result.halts
    assert NoticeKind.INVALID_DATA in bot.kinds()
    assert result.buys == ()
