"""Spec 0016 AC-11: süren durumda tek giriş, tek çıkış; alıcı hatası akışı kesmez (R-10, R-11)."""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import NoticeKind, TurnOutcome, _turn
from crytobot.execution import OrderStatus
from crytobot.persistence import StoreOutcome
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
    Exchange,
    bot_with_position,
    make_settings,
    opened_store,
    pair_market,
    refuse_saves,
    writes_closure,
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


def test_stale_price_gives_no_false_exit_for_refused_close(tmp_path: Path) -> None:
    """AC-11, R-10: fiyat bayatken kapanış değerlendirilmedi; takılı kapanış "düzeldi" sayılmaz."""
    bot = bot_with_position(tmp_path / "s.db")
    low = Decimal(7)
    bot.turn(
        {BTC: pair_market(price=low, price_at=LATER)},
        now=LATER,
        exchange=Exchange(place={"cx-": OrderStatus.REJECTED}),
    )
    stale_turn = LATER + MAX_PRICE_AGE + 2 * MINUTE
    bot.turn({BTC: pair_market(price=low, price_at=LATER)}, now=stale_turn)
    fresh_turn = stale_turn + MINUTE
    bot.turn({BTC: pair_market(price=low, price_at=fresh_turn)}, now=fresh_turn)

    assert [(n.kind, n.entering) for n in bot.notices] == [
        (NoticeKind.CLOSE_REFUSED, True),
        (NoticeKind.STALE_DATA, True),
        (NoticeKind.STALE_DATA, False),
    ]
    assert len(bot.stored().ledger.positions) == 1


def test_stale_price_gives_no_false_exit_for_rejected_observation(tmp_path: Path) -> None:
    """AC-11, R-10: gözlem yapılmayan turda saat hâlâ geride; çıkış ancak gözlem geçince gider."""
    bot = bot_with_position(tmp_path / "s.db")
    bot.turn({BTC: pair_market(price_at=LATER)}, now=LATER)
    behind = NOW + MINUTE
    bot.turn({BTC: pair_market(price_at=behind)}, now=behind)
    bot.turn({BTC: pair_market(price_at=behind - MAX_PRICE_AGE - MINUTE)}, now=behind)

    assert [(n.kind, n.entering) for n in bot.notices] == [
        (NoticeKind.OBSERVATION_REJECTED, True),
        (NoticeKind.STALE_DATA, True),
    ]

    after = LATER + MINUTE
    bot.turn({BTC: pair_market(price_at=after)}, now=after)

    assert bot.kinds(entering=False) == [NoticeKind.OBSERVATION_REJECTED, NoticeKind.STALE_DATA]
    assert bot.kinds().count(NoticeKind.OBSERVATION_REJECTED) == 1


def test_save_not_attempted_gives_no_false_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-11, R-10: yazımsız turda kayıt denenmedi; çıkış ancak bir kayıt geçince gider."""
    bot = bot_with_position(tmp_path / "s.db")
    refuse_saves(monkeypatch, StoreOutcome.WRITE_FAILED, writes_closure, times=2)
    low = Decimal(7)
    bot.turn({BTC: pair_market(price=low, price_at=LATER)}, now=LATER)
    stale_turn = LATER + MAX_PRICE_AGE + 2 * MINUTE
    bot.turn({BTC: pair_market(price=low, price_at=LATER)}, now=stale_turn)
    refused_again = stale_turn + MINUTE
    bot.turn({BTC: pair_market(price=low, price_at=refused_again)}, now=refused_again)

    assert [(n.kind, n.entering) for n in bot.notices] == [
        (NoticeKind.SAVE_REFUSED, True),
        (NoticeKind.STALE_DATA, True),
    ]

    written = refused_again + MINUTE
    result = bot.turn({BTC: pair_market(price=low, price_at=written)}, now=written)

    assert len(result.closes) == 1
    assert bot.kinds(entering=False) == [NoticeKind.SAVE_REFUSED, NoticeKind.STALE_DATA]
    assert bot.kinds().count(NoticeKind.SAVE_REFUSED) == 1


def test_stale_price_gives_no_false_exit_for_price_the_ledger_refused(tmp_path: Path) -> None:
    """Review 2 F-4: defterin kullanmadığı fiyat sürerken gözlem yapılmayan turda çıkış yok."""
    bot = bot_with_position(tmp_path / "s.db")
    long_price = Decimal("9." + "1" * 28)
    bot.turn({BTC: pair_market(price=long_price, price_at=LATER)}, now=LATER)
    stale_turn = LATER + MAX_PRICE_AGE + 2 * MINUTE
    bot.turn({BTC: pair_market(price=long_price, price_at=LATER)}, now=stale_turn)

    assert [(n.kind, n.subject, n.entering) for n in bot.notices] == [
        (NoticeKind.INVALID_DATA, "", True),
        (NoticeKind.STALE_DATA, BTC, True),
    ]

    fresh = stale_turn + MINUTE
    bot.turn({BTC: pair_market(price_at=fresh)}, now=fresh)

    assert bot.kinds(entering=False) == [NoticeKind.INVALID_DATA, NoticeKind.STALE_DATA]


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


def test_start_text_trial_and_confirmed() -> None:
    from datetime import timedelta

    from crytobot.app import TRIAL_MARK
    from crytobot.app._events import start_text

    # Deneme modu
    trial = start_text(timedelta(hours=1), "bot.db", ("BTC/USDT",), trial=True)
    assert TRIAL_MARK in trial
    assert "onaylı:" not in trial

    # Eksik onay bilgisiyle kanıtlı istenirse yine TRIAL_MARK taşır
    fallback = start_text(timedelta(hours=1), "bot.db", ("BTC/USDT",), trial=False)
    assert TRIAL_MARK in fallback

    # Kanıtlı mod
    confirmed = start_text(
        timedelta(hours=1),
        "bot.db",
        ("BTC/USDT",),
        trial=False,
        approved_by="Galip Badem",
        report_path="report.txt",
    )
    assert TRIAL_MARK not in confirmed
    assert "onaylı: onaylayan=Galip Badem rapor=report.txt" in confirmed


def test_paper_start_text_is_byte_for_byte_unchanged_without_paper_proof() -> None:
    """Spec 0038 PB-1: paper kanıtı verilmeyen başlatma satırı 0038 öncesiyle aynıdır."""
    from datetime import timedelta

    from crytobot.app._events import TRIAL_MARK, start_text

    interval, pairs = timedelta(hours=1), ("BTC/USDT", "ETH/USDT")
    prefix = "başladı: mod=paper aralık=1h depo=bot.db çiftler=BTC/USDT,ETH/USDT"

    assert start_text(interval, "bot.db", pairs, trial=True) == f"{prefix} — {TRIAL_MARK}"
    assert start_text(
        interval,
        "bot.db",
        pairs,
        trial=False,
        approved_by="Galip Badem",
        report_path="report.txt",
    ) == (f"{prefix} onaylı: onaylayan=Galip Badem rapor=report.txt")


def test_turn_text_trial_and_confirmed() -> None:
    from crytobot.app import TRIAL_MARK
    from crytobot.app._events import turn_text
    from crytobot.app._result import TurnResult

    res = TurnResult(TurnOutcome.COMPLETED, (), (), (), (), (), "tamamlandı")

    # Deneme
    t_trial = turn_text(res, LATER, missed=0, banned=False, trial=True)
    assert TRIAL_MARK in t_trial

    # Kanıtlı
    t_confirmed = turn_text(res, LATER, missed=0, banned=False, trial=False)
    assert TRIAL_MARK not in t_confirmed
    assert t_confirmed.endswith("(tamamlandı)")
