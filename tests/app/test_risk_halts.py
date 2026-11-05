"""Spec 0016 AC-10: risk durdurmaları alımı engeller, kapanışı engellemez (R-8, R-9, BR-5, BR-6)."""

from decimal import Decimal
from pathlib import Path
from typing import Any

from crytobot.app import BuyHalt
from crytobot.risk import ApprovalReason
from crytobot.strategy import NoProposalReason
from tests.app.helpers import (
    BTC,
    ETH,
    FLAT,
    LATER,
    Bot,
    limits,
    make_settings,
    opened_store,
    pair_market,
)

STOP_AND_CROSS = {
    BTC: pair_market(price=Decimal(7), price_at=LATER),
    ETH: pair_market(price_at=LATER),
}


def _bot(tmp_path: Path, **limit_values: Any) -> Bot:
    settings = make_settings((BTC, ETH), limits=limits(**limit_values))
    bot = Bot(opened_store(tmp_path / "s.db"), settings=settings)
    bot.turn({BTC: pair_market(), ETH: pair_market(FLAT)})
    return bot


def test_drawdown_refuses_buy_allows_close(tmp_path: Path) -> None:
    """BR-6: fiyat 7: kasa ~%1.5 düşer, limit %1."""
    bot = _bot(tmp_path, max_drawdown=Decimal("0.01"))

    result = bot.turn(STOP_AND_CROSS, now=LATER)

    assert [o.pair for o in result.closes] == [BTC]
    assert result.buys == ()
    assert [p.reason for p in result.pairs if p.pair == ETH] == [ApprovalReason.DRAWDOWN_HALT]


def test_daily_loss_refuses_buy_allows_close(tmp_path: Path) -> None:
    """BR-5: fiyat 7: kasa gün başına göre ~%1.5 düşer, limit %1."""
    bot = _bot(tmp_path, daily_loss_limit=Decimal("0.01"))

    result = bot.turn(STOP_AND_CROSS, now=LATER)

    assert [o.pair for o in result.closes] == [BTC]
    assert result.buys == ()
    assert [p.reason for p in result.pairs if p.pair == ETH] == [ApprovalReason.DAILY_LOSS_LIMIT]


def test_reasons_appear_without_notice(tmp_path: Path) -> None:
    """R-9: "öneri yok" ve `risk` reddi hata değildir; bildirim üretmez."""
    bot = _bot(tmp_path, max_drawdown=Decimal("0.01"))

    flat = bot.turn(
        {BTC: pair_market(price_at=LATER), ETH: pair_market(FLAT, price_at=LATER)}, now=LATER
    )
    refused = bot.turn(STOP_AND_CROSS, now=LATER)

    reasons = {p.pair: p.reason for p in flat.pairs}
    assert reasons[BTC] is NoProposalReason.POSITION_OPEN
    assert isinstance(reasons[ETH], NoProposalReason)
    assert {p.pair: p.reason for p in refused.pairs}[ETH] is ApprovalReason.DRAWDOWN_HALT
    assert bot.notices == []


def test_result_shows_drawdown_halt(tmp_path: Path) -> None:
    """Plan Risk 12: bildirim yok ama sonuçta görünür; durdurma kapanışı kesmez."""
    bot = _bot(tmp_path, max_drawdown=Decimal("0.01"))

    result = bot.turn(STOP_AND_CROSS, now=LATER)

    assert result.halts == (BuyHalt.DRAWDOWN,)
    assert bot.notices == []
