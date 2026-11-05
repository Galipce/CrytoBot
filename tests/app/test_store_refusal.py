"""Spec 0016 AC-7: depo yüklenemiyorsa tur hiçbir işlem yapmaz (R-5, R-8, BR-6, 0011)."""

import sqlite3
from collections.abc import Callable
from contextlib import closing
from decimal import Decimal
from pathlib import Path

import pytest

from crytobot.app import BuyHalt, NoticeKind, TurnOutcome
from crytobot.persistence import create_store
from crytobot.risk import ApprovalReason
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


def _unreadable(path: Path) -> None:
    path.write_bytes(b"this is not a database at all, not even close")


def _unknown_version(path: Path) -> None:
    opened_store(path)
    with closing(sqlite3.connect(path)) as database, database:
        database.execute("UPDATE meta SET value = '999' WHERE key = 'format_version'")


def _live_store(path: Path) -> None:
    create_store(path, "live")


@pytest.mark.parametrize(
    "prepare",
    [_unreadable, _unknown_version, _live_store],
    ids=["unreadable", "unknown_version", "mode_mismatch"],
)
def test_store_refusal_does_nothing(tmp_path: Path, prepare: Callable[[Path], None]) -> None:
    path = tmp_path / "s.db"
    prepare(path)
    before = path.read_bytes()
    bot = Bot(path)

    result = bot.turn()

    assert result.outcome is TurnOutcome.STORE_UNAVAILABLE
    assert result.buys == () and result.closes == ()
    assert path.read_bytes() == before
    assert bot.kinds() == [NoticeKind.STORE_UNAVAILABLE]


def test_busy_store_does_nothing(tmp_path: Path) -> None:
    """Gerçek kilit; `persistence`'ın bekleme süresi kadar sürer (plan Risk 15)."""
    path = opened_store(tmp_path / "s.db")
    before = path.read_bytes()
    bot = Bot(path)

    with closing(sqlite3.connect(path, isolation_level=None)) as holder:
        holder.execute("BEGIN EXCLUSIVE")
        result = bot.turn()
        holder.execute("ROLLBACK")

    assert result.outcome is TurnOutcome.STORE_UNAVAILABLE
    assert path.read_bytes() == before
    assert bot.kinds() == [NoticeKind.STORE_UNAVAILABLE]


def test_turn_does_not_create_store(tmp_path: Path) -> None:
    path = tmp_path / "s.db"
    bot = Bot(path)

    result = bot.turn()

    assert result.outcome is TurnOutcome.STORE_UNAVAILABLE
    assert not path.exists()
    assert bot.kinds() == [NoticeKind.STORE_UNAVAILABLE]


def test_restart_does_not_lift_drawdown_halt(tmp_path: Path) -> None:
    """BR-6: durdurma depodadır; yeniden başlatma kaldırmaz."""
    settings = make_settings((BTC, ETH), limits=limits(max_drawdown=Decimal("0.01")))
    bot = Bot(opened_store(tmp_path / "s.db"), settings=settings)
    bot.turn({BTC: pair_market(), ETH: pair_market(FLAT)})
    market = {
        BTC: pair_market(price=Decimal(7), price_at=LATER),
        ETH: pair_market(price_at=LATER),
    }
    bot.turn(market, now=LATER)
    assert bot.stored().risk.halted

    bot.restart()
    result = bot.turn(market, now=LATER)

    assert result.buys == ()
    assert [p.reason for p in result.pairs if p.pair == ETH] == [ApprovalReason.DRAWDOWN_HALT]
    assert BuyHalt.DRAWDOWN in result.halts
