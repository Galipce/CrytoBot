"""Spec 0016 Constraints: çok turlu dizide bakiye ve pozisyon bağımsız modelle aynıdır."""

import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from crytobot.app import TurnOutcome
from tests.app.helpers import (
    BTC,
    DEPOSIT,
    FEE,
    NOW,
    SLIPPAGE,
    Bot,
    opened_store,
    pair_market,
)
from tests.app.model import Model

# stop 8 ve hedef 14'ün çevresi; 15 alımda üst sınır kapısına takılır
PRICES = st.sampled_from([Decimal(p) for p in ("7", "8", "8.01", "10", "13.99", "14", "15")])
DAY = timedelta(days=1)
# her biri SQLite'a yazar; plan Risk 17
EXAMPLES = 25


def run_sequence(path: Path, prices: list[Decimal]) -> tuple[Bot, Model]:
    bot = Bot(opened_store(path))
    model = Model(FEE, SLIPPAGE, DEPOSIT)
    for index, price in enumerate(prices):
        now = NOW + index * DAY
        result = bot.turn({BTC: pair_market(closed_at=now, price=price)}, now=now)
        assert result.outcome is TurnOutcome.COMPLETED, result
        model.turn(price)
    return bot, model


def assert_same(bot: Bot, model: Model) -> None:
    stored = bot.stored()
    assert stored.ledger.balance == model.balance
    positions = list(stored.ledger.positions.values())
    if model.position is None:
        assert positions == []
    else:
        assert [p.amount for p in positions] == [model.position.amount]
    assert len(stored.ledger.closures) == model.closes
    assert bot.conflicts() == ()


@settings(max_examples=EXAMPLES)
@given(prices=st.lists(PRICES, min_size=1, max_size=6))
def test_turns_match_independent_model(prices: list[Decimal]) -> None:
    with tempfile.TemporaryDirectory() as folder:
        bot, model = run_sequence(Path(folder) / "s.db", prices)
        assert_same(bot, model)


def test_property_is_not_vacuous(tmp_path: Path) -> None:
    """Sabit dizi alım ve kapanışı gerçekten üretir; model de gerçek de aynı yolu izler."""
    prices = [Decimal(p) for p in ("10", "7", "10", "14", "15")]

    bot, model = run_sequence(tmp_path / "s.db", prices)

    assert_same(bot, model)
    assert model.history == ["buy", "close", "buy", "close"]
