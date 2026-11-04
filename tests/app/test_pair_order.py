"""Spec 0016 AC-3: beyaz liste sırası; limit ve bakiye sonraki çiftin onayında görünür (R-2)."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from crytobot.risk import ApprovalReason
from tests.app.helpers import (
    BTC,
    ETH,
    STRATEGY,
    Bot,
    limits,
    make_settings,
    opened_store,
    pair_market,
)


@pytest.mark.parametrize("order", [(BTC, ETH), (ETH, BTC)], ids=["btc_first", "eth_first"])
def test_pairs_follow_whitelist_order(tmp_path: Path, order: tuple[str, str]) -> None:
    bot = Bot(opened_store(tmp_path / "s.db"), settings=make_settings(order))

    result = bot.turn({BTC: pair_market(), ETH: pair_market()})

    assert tuple(o.pair for o in result.buys) == order


def test_position_limit_reaches_next_pair(tmp_path: Path) -> None:
    """BR-7: ilk alım limiti doldurur, ikinci onay aynı turda görür."""
    settings = make_settings((BTC, ETH), limits=limits(max_open_positions=1))
    bot = Bot(opened_store(tmp_path / "s.db"), settings=settings)

    result = bot.turn({BTC: pair_market(), ETH: pair_market()})

    assert [o.pair for o in result.buys] == [BTC]
    assert [(p.pair, p.reason) for p in result.pairs] == [(ETH, ApprovalReason.POSITION_LIMIT)]


def test_balance_reaches_next_pair(tmp_path: Path) -> None:
    """Slippage 0, dar stop: ilk alım bakiyeyi bitirir, ikinci asgarinin altında kalır."""
    settings = make_settings(
        (BTC, ETH),
        limits=limits(per_trade_risk=Decimal("0.02")),
        strategy=replace(STRATEGY, k=Decimal("0.1")),
        slippage=Decimal(0),
    )
    bot = Bot(opened_store(tmp_path / "s.db"), settings=settings)

    result = bot.turn({BTC: pair_market(), ETH: pair_market()})

    assert [o.pair for o in result.buys] == [BTC]
    assert [(p.pair, p.reason) for p in result.pairs] == [(ETH, ApprovalReason.BELOW_MINIMUM)]
