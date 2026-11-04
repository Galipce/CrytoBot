"""Spec 0016 AC-8: kayıt reddinde alım durur, tur biter; sonraki tur diskten başlar (R-6, 0012)."""

from decimal import Decimal
from pathlib import Path

import pytest

from crytobot.app import BuyHalt, NoticeKind, TurnOutcome
from crytobot.persistence import StoreOutcome
from tests.app.helpers import (
    BTC,
    ETH,
    FLAT,
    LATER,
    Bot,
    make_settings,
    opened_store,
    pair_market,
)
from tests.app.saving import refuse_saves, writes_closure

CLOSE_AND_CROSS = {
    BTC: pair_market(price=Decimal(7), price_at=LATER),
    ETH: pair_market(price_at=LATER),
}


def _bot(tmp_path: Path) -> Bot:
    """BTC pozisyonlu; sonraki turda BTC stop'a gelir, ETH kesişir."""
    bot = Bot(opened_store(tmp_path / "s.db"), settings=make_settings((BTC, ETH)))
    bot.turn({BTC: pair_market(), ETH: pair_market(FLAT)})
    return bot


@pytest.mark.parametrize(
    "outcome",
    [
        StoreOutcome.WRITE_FAILED,
        StoreOutcome.BUSY,
        StoreOutcome.STALE_WRITE,
        StoreOutcome.HISTORY_IMMUTABLE,
    ],
)
def test_save_refusal_ends_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: StoreOutcome
) -> None:
    bot = _bot(tmp_path)
    refuse_saves(monkeypatch, outcome, writes_closure)

    result = bot.turn(CLOSE_AND_CROSS, now=LATER)

    assert result.outcome is TurnOutcome.SAVE_REFUSED
    assert BuyHalt.SAVE_REFUSED in result.halts
    assert result.buys == () and result.closes == ()
    assert NoticeKind.SAVE_REFUSED in bot.kinds()
    stored = bot.stored()
    assert stored.ledger.closures == {} and len(stored.execution.orders) == 1


def test_next_turn_retries_unsaved_close(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _bot(tmp_path)
    refuse_saves(monkeypatch, StoreOutcome.BUSY, writes_closure)
    bot.turn(CLOSE_AND_CROSS, now=LATER)

    retried = bot.turn(CLOSE_AND_CROSS, now=LATER)

    assert retried.outcome is TurnOutcome.COMPLETED
    assert [o.pair for o in retried.closes] == [BTC]
    assert [o.pair for o in retried.buys] == [ETH]
    assert len(bot.stored().ledger.closures) == 1
    assert bot.kinds(entering=False) == [NoticeKind.SAVE_REFUSED]


def test_history_halt_survives_clean_turn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R-6: süreç belleğinde durur; kapanış sürer, alım olmaz."""
    bot = _bot(tmp_path)
    refuse_saves(monkeypatch, StoreOutcome.HISTORY_IMMUTABLE, writes_closure)
    bot.turn(CLOSE_AND_CROSS, now=LATER)

    clean = bot.turn(CLOSE_AND_CROSS, now=LATER)

    assert clean.outcome is TurnOutcome.COMPLETED
    assert [o.pair for o in clean.closes] == [BTC]
    assert clean.buys == () and BuyHalt.HISTORY_IMMUTABLE in clean.halts
    assert bot.kinds().count(NoticeKind.HISTORY_IMMUTABLE) == 1


def test_history_halt_lifts_on_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _bot(tmp_path)
    refuse_saves(monkeypatch, StoreOutcome.HISTORY_IMMUTABLE, writes_closure)
    bot.turn(CLOSE_AND_CROSS, now=LATER)

    bot.restart()
    resumed = bot.turn(CLOSE_AND_CROSS, now=LATER)

    assert [o.pair for o in resumed.buys] == [ETH]
    assert BuyHalt.HISTORY_IMMUTABLE not in resumed.halts


def test_history_halt_returns_if_error_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = _bot(tmp_path)
    refuse_saves(monkeypatch, StoreOutcome.HISTORY_IMMUTABLE, writes_closure, times=2)
    bot.turn(CLOSE_AND_CROSS, now=LATER)

    bot.restart()
    again = bot.turn(CLOSE_AND_CROSS, now=LATER)

    assert again.outcome is TurnOutcome.SAVE_REFUSED
    assert again.buys == ()
    assert bot.kinds().count(NoticeKind.HISTORY_IMMUTABLE) == 2
