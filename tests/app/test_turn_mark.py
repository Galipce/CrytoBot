"""Spec 0038 CB-4 "son tur" (G-7), plan Risk 1, A-3: paper döngüsü her tamamlanan turu işaretler."""

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import BuyHalt, TurnOutcome, TurnResult, _loop
from crytobot.app._turn import run_turn
from crytobot.execution import PaperExchange
from crytobot.market_data import MarketRead
from crytobot.persistence import StoreOutcome, StoreResult, load_store
from tests.app.helpers import BTC, NOW, opened_store
from tests.app.loop_fakes import banned_read, harness, pair_read


def last_turn(path: Path, mode: str = "paper") -> datetime | None:
    loaded = load_store(path, mode)
    assert loaded.state is not None, loaded.message
    return loaded.state.last_turn


def test_each_completed_turn_moves_the_mark_without_a_revision(tmp_path: Path) -> None:
    store = opened_store(tmp_path / "s.db")
    bot = harness(store, stop_after=2)
    seen: list[tuple[datetime | None, int]] = []

    def watch(_bot: Any) -> None:
        state = load_store(store, "paper").state
        assert state is not None
        seen.append((state.last_turn, state.revision))

    bot.read_hooks[1] = watch
    bot.run()

    first_at = bot.read_times()[0] + timedelta(seconds=bot.read_seconds)
    second_at = bot.read_times()[1] + timedelta(seconds=bot.read_seconds)
    assert seen[0][0] == first_at
    assert last_turn(store) == second_at
    loaded = load_store(store, "paper").state
    assert loaded is not None and loaded.revision == seen[0][1] + 1  # only the turn's own save


def test_a_stale_data_turn_is_marked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """G-7: veri bayatlığı nedeniyle işlem yapılmayan tur da son turdur."""
    store = opened_store(tmp_path / "s.db")
    bot = harness(store, stop_after=1)
    bot.answers[0] = lambda at: MarketRead((pair_read(BTC, at - timedelta(days=1)),), at, None)
    results: list[Any] = []

    def spy(**kwargs: Any) -> Any:
        results.append(run_turn(**kwargs))
        return results[-1]

    monkeypatch.setattr(_loop, "run_turn", spy)
    bot.run()

    (result,) = results
    assert result.outcome is TurnOutcome.COMPLETED
    assert BuyHalt.STALE_DATA in result.halts
    assert last_turn(store) == bot.read_times()[0] + timedelta(seconds=bot.read_seconds)


def test_a_banned_turn_is_marked(tmp_path: Path) -> None:
    store = opened_store(tmp_path / "s.db")
    bot = harness(store, stop_after=1)
    bot.answers[0] = lambda at: banned_read(at, at + timedelta(hours=2))

    bot.run()

    assert last_turn(store) is not None


@pytest.mark.parametrize(
    "outcome",
    [TurnOutcome.SAVE_REFUSED, TurnOutcome.UNEXPECTED_ERROR, TurnOutcome.STORE_UNAVAILABLE],
)
def test_a_turn_that_did_not_complete_is_not_marked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: TurnOutcome
) -> None:
    """A-3: yalnız tamamlanan tur; kanıt süresi ancak kısalır."""
    store = opened_store(tmp_path / "s.db")
    bot = harness(store, stop_after=1)

    def failing(**kwargs: Any) -> Any:
        return replace(run_turn(**kwargs), outcome=outcome)

    monkeypatch.setattr(_loop, "run_turn", failing)
    bot.run()

    assert last_turn(store) is None


def test_a_live_store_is_never_marked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = opened_store(tmp_path / "s.db")
    bot = harness(store, stop_after=1)
    config = replace(bot.config, mode="live")
    marked: list[object] = []
    monkeypatch.setattr(_loop, "mark_turn", lambda *args: marked.append(args))
    completed = TurnResult(TurnOutcome.COMPLETED, (), (), (), (), (), "tur tamamlandı")

    _loop._Loop(config, bot.parts(), PaperExchange()).mark(completed, NOW)

    assert marked == []


def test_a_mark_that_cannot_be_written_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = opened_store(tmp_path / "s.db")
    bot = harness(store, stop_after=1)
    refused = StoreResult(StoreOutcome.BUSY, None, (), "depo meşgul")
    monkeypatch.setattr(_loop, "mark_turn", lambda *_args: refused)

    bot.run()

    assert any("tur işareti yazılamadı: depo meşgul" in text for text in bot.events("hata"))
    assert len(bot.events("tur")) == 1
