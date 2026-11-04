"""Spec 0016 AC-11: süren durumda tek giriş, tek çıkış; alıcı hatası akışı kesmez (R-10, R-11)."""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import NoticeKind, TurnOutcome, _turn
from crytobot.risk import PairRules
from tests.app.helpers import (
    BTC,
    ETH,
    FLAT,
    LATER,
    MAX_PRICE_AGE,
    MINUTE,
    NOW,
    RULES,
    Bot,
    make_settings,
    opened_store,
    pair_market,
)

SOL = "SOL/USDT"
SECRET = "api-key-sir-degeri"
TOO_BIG_MINIMUM = PairRules(RULES.amount_step, RULES.min_amount, Decimal(1000000))


def _stale(now: Any) -> dict[str, Any]:
    return {BTC: pair_market(price_at=now - MAX_PRICE_AGE - MINUTE)}


def test_lasting_state_notifies_once_then_exit_once(tmp_path: Path) -> None:
    bot = Bot(opened_store(tmp_path / "s.db"))

    bot.turn(_stale(NOW + MINUTE), now=NOW + MINUTE)
    bot.turn(_stale(NOW + 2 * MINUTE), now=NOW + 2 * MINUTE)
    assert [(n.kind, n.entering) for n in bot.notices] == [(NoticeKind.STALE_DATA, True)]

    bot.turn({BTC: pair_market(FLAT, price_at=LATER)}, now=LATER)
    bot.turn({BTC: pair_market(FLAT, price_at=LATER)}, now=LATER)

    assert [(n.kind, n.entering) for n in bot.notices] == [
        (NoticeKind.STALE_DATA, True),
        (NoticeKind.STALE_DATA, False),
    ]


def test_restart_notifies_lasting_state_again(tmp_path: Path) -> None:
    bot = Bot(opened_store(tmp_path / "s.db"))
    bot.turn(_stale(NOW + MINUTE), now=NOW + MINUTE)

    bot.restart()
    bot.turn(_stale(NOW + MINUTE), now=NOW + MINUTE)

    assert bot.kinds() == [NoticeKind.STALE_DATA, NoticeKind.STALE_DATA]


def test_failing_sink_does_not_stop_trading(tmp_path: Path) -> None:
    """BTC kapanışı reddedilir (bildirim), ETH kapanır, SOL alınır; alıcı her seferinde patlar."""
    settings = make_settings((BTC, ETH, SOL))
    bot = Bot(opened_store(tmp_path / "s.db"), settings=settings)
    bot.turn({BTC: pair_market(), ETH: pair_market(), SOL: pair_market(FLAT)})
    low = Decimal(7)

    def sink(_notice: Any) -> None:
        raise RuntimeError(SECRET)

    result = bot.turn(
        {
            BTC: pair_market(price=low, price_at=LATER, rules=TOO_BIG_MINIMUM),
            ETH: pair_market(price=low, price_at=LATER),
            SOL: pair_market(price_at=LATER),
        },
        now=LATER,
        sink=sink,
    )

    assert result.outcome is TurnOutcome.COMPLETED
    assert [o.pair for o in result.closes] == [ETH]
    assert [o.pair for o in result.buys] == [SOL]
    assert result.notice_errors == ("RuntimeError",)
    assert SECRET not in repr(result)


def test_notice_has_no_secret(tmp_path: Path) -> None:
    """R-10: depo yolu sır sayılır; ne bildirimde ne sonuçta görünür."""
    path = tmp_path / SECRET / "s.db"
    bot = Bot(path)

    result = bot.turn()

    assert bot.kinds() == [NoticeKind.STORE_UNAVAILABLE]
    assert SECRET not in repr(bot.notices)
    assert SECRET not in repr(result)


def test_early_end_gives_no_false_exit(tmp_path: Path) -> None:
    """Plan Risk 11: depo yüklenemeyen turda bayatlık değerlendirilmedi: çıkış üretilmez."""
    path = opened_store(tmp_path / "s.db")
    bot = Bot(path)
    now = NOW + MINUTE
    bot.turn(_stale(now), now=now)

    moved = path.with_suffix(".moved")
    path.rename(moved)
    bot.turn(_stale(now), now=now)
    moved.rename(path)
    bot.turn(_stale(now), now=now)

    assert [(n.kind, n.entering) for n in bot.notices] == [
        (NoticeKind.STALE_DATA, True),
        (NoticeKind.STORE_UNAVAILABLE, True),
        (NoticeKind.STORE_UNAVAILABLE, False),
    ]


def test_unexpected_error_is_named_without_its_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R-11, plan Risk 13: tur istisna fırlatmaz; yalnız tip adı görünür."""
    bot = Bot(opened_store(tmp_path / "s.db"))

    def explode(*_args: Any) -> None:
        raise RuntimeError(SECRET)

    with monkeypatch.context() as patch:
        patch.setattr(_turn, "load_store", explode)
        result = bot.turn()

    assert result.outcome is TurnOutcome.UNEXPECTED_ERROR
    assert "RuntimeError" in result.message and SECRET not in repr(result)
    assert bot.kinds() == [NoticeKind.UNEXPECTED_ERROR]
    assert SECRET not in repr(bot.notices)

    recovered = bot.turn()

    assert recovered.outcome is TurnOutcome.COMPLETED
    assert bot.kinds(entering=False) == [NoticeKind.UNEXPECTED_ERROR]


def test_unexpected_error_mid_turn_keeps_what_was_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R-11: daha önce kaydedilen kapanış sonuçta görünür."""
    bot = Bot(opened_store(tmp_path / "s.db"), settings=make_settings((BTC, ETH)))
    bot.turn({BTC: pair_market(), ETH: pair_market(FLAT)})
    market = {
        BTC: pair_market(price=Decimal(7), price_at=LATER),
        ETH: pair_market(price_at=LATER),
    }

    def explode(_run: Any) -> None:
        raise RuntimeError(SECRET)

    monkeypatch.setattr(_turn, "buy_pairs", explode)
    result = bot.turn(market, now=LATER)

    assert result.outcome is TurnOutcome.UNEXPECTED_ERROR
    assert [o.pair for o in result.closes] == [BTC]
    assert SECRET not in repr(result)
