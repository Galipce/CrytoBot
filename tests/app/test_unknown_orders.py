"""Spec 0016 AC-15: durumu bilinmeyen emirler (R-17, 0006, BR-11)."""

from decimal import Decimal
from pathlib import Path
from typing import Any

from crytobot.app import BuyHalt, NoticeKind
from crytobot.execution import OrderStatus
from tests.app.helpers import (
    BTC,
    ETH,
    LATER,
    MINUTE,
    NOW,
    Bot,
    Exchange,
    bot_with_position,
    make_settings,
    opened_store,
    pair_market,
)

UNKNOWN_BUY = Exchange(place={"cb-": OrderStatus.UNKNOWN})
UNKNOWN_CLOSE = Exchange(place={"cx-": OrderStatus.UNKNOWN})
FILLED_QUERY = Exchange(query={"cb-": OrderStatus.FILLED, "cx-": OrderStatus.FILLED})
REJECTED_QUERY = Exchange(query={"cb-": OrderStatus.REJECTED})


def _bot(tmp_path: Path) -> tuple[Bot, dict[str, Any]]:
    bot = Bot(opened_store(tmp_path / "s.db"), settings=make_settings((BTC, ETH)))
    return bot, {BTC: pair_market(), ETH: pair_market()}


def test_unknown_order_stops_buying(tmp_path: Path) -> None:
    bot, market = _bot(tmp_path)

    result = bot.turn(market, exchange=UNKNOWN_BUY)

    assert [(o.pair, o.status) for o in result.buys] == [(BTC, OrderStatus.UNKNOWN)]
    assert result.halts == (BuyHalt.UNKNOWN_ORDERS,)
    assert bot.stored().ledger.positions == {}


def test_resolved_fill_reaches_ledger(tmp_path: Path) -> None:
    bot = Bot(opened_store(tmp_path / "s.db"))
    bot.turn(exchange=UNKNOWN_BUY)

    result = bot.turn(exchange=FILLED_QUERY)

    stored = bot.stored()
    assert list(stored.ledger.positions) == [result.buys[0].client_order_id]
    assert result.buys[0].status is OrderStatus.FILLED
    assert bot.conflicts() == ()


def test_safe_mode_notices_reach_sink(tmp_path: Path) -> None:
    bot, market = _bot(tmp_path)

    bot.turn(market, exchange=UNKNOWN_BUY)
    assert [(n.kind, n.entering) for n in bot.notices] == [(NoticeKind.SAFE_MODE, True)]

    bot.turn(market, exchange=FILLED_QUERY)
    assert [(n.kind, n.entering) for n in bot.notices] == [
        (NoticeKind.SAFE_MODE, True),
        (NoticeKind.SAFE_MODE, False),
    ]


def test_restart_with_unknown_order_notifies_again(tmp_path: Path) -> None:
    """R-10: `execution` geçiş üretmez; durum depodan türer (plan Risk 11)."""
    bot, market = _bot(tmp_path)
    bot.turn(market, exchange=UNKNOWN_BUY)

    bot.restart()
    bot.turn(market)

    assert bot.kinds() == [NoticeKind.SAFE_MODE, NoticeKind.SAFE_MODE]


def test_still_unknown_keeps_buying_stopped(tmp_path: Path) -> None:
    bot, market = _bot(tmp_path)
    bot.turn(market, exchange=UNKNOWN_BUY)

    result = bot.turn(market)

    assert result.buys == () and result.halts == (BuyHalt.UNKNOWN_ORDERS,)
    assert len(bot.stored().execution.orders) == 1
    assert bot.kinds() == [NoticeKind.SAFE_MODE]


def test_rejected_resolution_leaves_ledger_alone(tmp_path: Path) -> None:
    bot = Bot(opened_store(tmp_path / "s.db"))
    bot.turn(exchange=UNKNOWN_BUY)

    result = bot.turn(exchange=REJECTED_QUERY)

    assert [o.status for o in result.buys] == [OrderStatus.REJECTED]
    assert bot.conflicts() == ()
    assert bot.kinds(entering=False) == [NoticeKind.SAFE_MODE]


def test_unknown_close_resolves_to_closure(tmp_path: Path) -> None:
    bot = bot_with_position(tmp_path / "s.db")
    market = {BTC: pair_market(price=Decimal(7), price_at=LATER)}

    pending = bot.turn(market, now=LATER, exchange=UNKNOWN_CLOSE)

    assert [o.status for o in pending.closes] == [OrderStatus.UNKNOWN]
    assert bot.stored().ledger.closures == {}

    waiting = bot.turn(market, now=LATER)

    assert waiting.closes == () and BuyHalt.UNKNOWN_ORDERS in waiting.halts

    resolved = bot.turn(market, now=LATER, exchange=FILLED_QUERY)

    assert [o.status for o in resolved.closes] == [OrderStatus.FILLED]
    stored = bot.stored()
    assert stored.ledger.positions == {} and len(stored.ledger.closures) == 1
    assert bot.conflicts() == ()


def test_clock_before_order_defers_query(tmp_path: Path) -> None:
    """Plan Risk 3: `now`, emirden eskiyse sorgu ertelenir; alım durmaya devam eder."""
    bot = Bot(opened_store(tmp_path / "s.db"))
    bot.turn(exchange=UNKNOWN_BUY)
    earlier = NOW - MINUTE

    result = bot.turn({BTC: pair_market(closed_at=earlier)}, now=earlier, exchange=FILLED_QUERY)

    assert result.buys == () and BuyHalt.UNKNOWN_ORDERS in result.halts
    assert bot.stored().ledger.positions == {} and bot.conflicts() == ()
