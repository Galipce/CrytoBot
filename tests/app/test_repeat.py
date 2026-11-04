"""Spec 0016 AC-4: aynı çiftin aynı son mumundan en fazla bir alım emri (R-3)."""

from decimal import Decimal
from pathlib import Path

import pytest

from crytobot.app import PairNote, TurnOutcome
from crytobot.app._buys import intent_id
from crytobot.persistence import StoreOutcome
from crytobot.strategy import NoProposalReason
from tests.app.helpers import (
    BTC,
    CROSS,
    LATER,
    NEXT_CANDLE,
    Bot,
    bot_with_position,
    opened_store,
    pair_market,
    refuse_saves,
    series,
    writes_order,
)


def test_second_turn_with_same_data_makes_no_order(tmp_path: Path) -> None:
    bot = bot_with_position(tmp_path / "s.db")

    result = bot.turn()

    assert result.buys == ()
    assert [p.reason for p in result.pairs] == [NoProposalReason.POSITION_OPEN]
    assert len(bot.stored().execution.orders) == 1


def test_no_reentry_from_candle_of_closed_position(tmp_path: Path) -> None:
    bot = bot_with_position(tmp_path / "s.db")

    result = bot.turn({BTC: pair_market(price=Decimal(7), price_at=LATER)}, now=LATER)

    assert len(result.closes) == 1 and result.buys == ()
    assert [p.reason for p in result.pairs] == [PairNote.ALREADY_ORDERED]
    assert len(bot.stored().execution.orders) == 2


def test_new_candle_can_buy_again(tmp_path: Path) -> None:
    bot = bot_with_position(tmp_path / "s.db")
    bot.turn({BTC: pair_market(price=Decimal(7), price_at=LATER)}, now=LATER)

    result = bot.turn({BTC: pair_market(closed_at=NEXT_CANDLE)}, now=NEXT_CANDLE)

    assert len(result.buys) == 1
    assert len(bot.stored().execution.orders) == 3


def test_unsaved_buy_retries_with_same_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """0011: kaydedilemeyen alım diskte yoktur; sonraki tur aynı kimlikle dener."""
    bot = Bot(opened_store(tmp_path / "s.db"))
    refuse_saves(monkeypatch, StoreOutcome.WRITE_FAILED, writes_order)

    refused = bot.turn()

    assert refused.outcome is TurnOutcome.SAVE_REFUSED
    assert bot.stored().execution.orders == {}

    retried = bot.turn()

    expected = "cb-" + intent_id(BTC, series(CROSS)[-1].open_time)
    assert [o.client_order_id for o in retried.buys] == [expected]
