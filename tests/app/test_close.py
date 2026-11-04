"""Spec 0016 AC-2, AC-16: kapanışlar alımdan önce; kapanış reddinde pozisyon açık kalır (R-18)."""

from decimal import Decimal
from pathlib import Path
from typing import Any

from crytobot.app import BuyHalt, NoticeKind
from crytobot.execution import OrderStatus
from crytobot.portfolio import CloseReason, EntryKind
from crytobot.risk import PairRules
from tests.app.helpers import (
    BTC,
    DEPOSIT,
    ETH,
    FEE,
    FIRST_AMOUNT,
    FLAT,
    LATER,
    RULES,
    Bot,
    Exchange,
    bot_with_position,
    make_settings,
    opened_store,
    pair_market,
)

TOO_BIG_MINIMUM = PairRules(RULES.amount_step, RULES.min_amount, Decimal(1000000))


def later(price: str, **overrides: Any) -> Any:
    return pair_market(price=Decimal(price), price_at=LATER, **overrides)


def two_pair_bot(tmp_path: Path) -> Bot:
    """BTC pozisyonlu, ETH henüz kesişmemiş; sonraki turda ETH kesişir."""
    bot = Bot(opened_store(tmp_path / "s.db"), settings=make_settings((BTC, ETH)))
    bot.turn({BTC: pair_market(), ETH: pair_market(FLAT)})
    return bot


def _closes_then_buys(bot: Bot, price: str, reason: CloseReason) -> None:
    result = bot.turn({BTC: later(price), ETH: later("10")}, now=LATER)

    assert [o.reason for o in result.closes] == [reason.value]
    assert [o.pair for o in result.buys] == [ETH]
    kinds = [entry.kind for entry in bot.stored().ledger.entries]
    assert kinds == [EntryKind.OPENING, EntryKind.FILL, EntryKind.CLOSE, EntryKind.FILL]


def test_stop_closes_before_buying(tmp_path: Path) -> None:
    _closes_then_buys(two_pair_bot(tmp_path), "7", CloseReason.STOP)


def test_target_closes_before_buying(tmp_path: Path) -> None:
    _closes_then_buys(two_pair_bot(tmp_path), "14", CloseReason.TARGET)


def test_position_between_stop_and_target_stays_open(tmp_path: Path) -> None:
    bot = bot_with_position(tmp_path / "s.db")

    result = bot.turn({BTC: later("9")}, now=LATER)

    assert result.closes == ()
    assert len(bot.stored().ledger.positions) == 1


def test_buy_approval_sees_balance_after_close(tmp_path: Path) -> None:
    """AC-2: elle hesap: kapanış sonrası kasa bakiyedir; bütçe %1, birim kayıp 2.018, adım 0.001."""
    bot = two_pair_bot(tmp_path)
    entry_cost = FIRST_AMOUNT * Decimal("10.01") * (1 + FEE)
    proceeds = FIRST_AMOUNT * Decimal("6.993") * (1 - FEE)
    balance = DEPOSIT - entry_cost + proceeds

    result = bot.turn({BTC: later("7"), ETH: later("10")}, now=LATER)

    budget = balance * Decimal("0.01")
    steps = budget // (Decimal("0.001") * Decimal("2.018"))
    assert [o.amount for o in result.buys] == [steps * Decimal("0.001")]


def test_below_minimum_close_stays_open_and_retries(tmp_path: Path) -> None:
    """R-18: asgari altı: emir yok, bildirim; koşul sürerse sonraki turda kapanır."""
    bot = bot_with_position(tmp_path / "s.db")

    refused = bot.turn({BTC: later("7", rules=TOO_BIG_MINIMUM)}, now=LATER)

    assert refused.closes == ()
    assert len(bot.stored().ledger.positions) == 1
    assert bot.kinds() == [NoticeKind.CLOSE_REFUSED]

    retried = bot.turn({BTC: later("7")}, now=LATER)

    assert len(retried.closes) == 1
    assert bot.stored().ledger.positions == {}
    assert bot.kinds(entering=False) == [NoticeKind.CLOSE_REFUSED]


def test_missing_rule_keeps_position_open(tmp_path: Path) -> None:
    """R-18, R-4: kural eksikse kapanış olmaz, bildirim gider, alım da durur."""
    bot = bot_with_position(tmp_path / "s.db")

    result = bot.turn({BTC: later("7", rules=None)}, now=LATER)

    assert result.closes == ()
    assert len(bot.stored().ledger.positions) == 1
    assert NoticeKind.CLOSE_REFUSED in bot.kinds()
    assert BuyHalt.INVALID_DATA in result.halts


def test_off_whitelist_position_closes(tmp_path: Path) -> None:
    """R-18: beyaz liste kapanışı engellemez."""
    bot = bot_with_position(tmp_path / "s.db")

    result = bot.turn({BTC: later("7")}, now=LATER, settings=make_settings(()))

    assert [o.pair for o in result.closes] == [BTC]
    assert bot.stored().ledger.positions == {}


def test_rejected_close_stays_open_and_notifies(tmp_path: Path) -> None:
    """R-18, B-17: reddedilmiş kapanış aynı kimlikle yeniden oluşmaz; pozisyon açık kalır."""
    bot = bot_with_position(tmp_path / "s.db")

    first = bot.turn(
        {BTC: later("7")}, now=LATER, exchange=Exchange(place={"cx-": OrderStatus.REJECTED})
    )

    assert [o.status for o in first.closes] == [OrderStatus.REJECTED]
    assert bot.kinds() == [NoticeKind.CLOSE_REFUSED]

    second = bot.turn({BTC: later("7")}, now=LATER)

    assert second.closes == ()
    assert len(bot.stored().ledger.positions) == 1
    assert bot.kinds() == [NoticeKind.CLOSE_REFUSED]
    assert len(bot.stored().execution.orders) == 2
    assert bot.conflicts() == ()
