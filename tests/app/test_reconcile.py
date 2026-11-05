"""Spec 0016 AC-9: mutabakat işareti alımı durdurur, kapanışı durdurmaz (R-2, R-7, BR-11)."""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import BuyHalt, NoticeKind, _buys, _closes
from crytobot.portfolio import CloseOutcome, CloseResult, LedgerOutcome, LedgerResult
from tests.app.helpers import (
    BTC,
    ETH,
    FLAT,
    LATER,
    NEXT_CANDLE,
    Bot,
    bot_with_position,
    make_settings,
    opened_store,
    pair_market,
)

SOL = "SOL/USDT"


def _refuse_fills(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(ledger: Any, _fill: Any) -> LedgerResult:
        return LedgerResult(ledger, LedgerOutcome.INSUFFICIENT_BALANCE, None, "enjekte")

    monkeypatch.setattr(_buys, "record_fill", refuse)


def _flagged_bot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Bot:
    """Depoda BTC pozisyonu ve defterin reddettiği dolu ETH alımı var."""
    bot = Bot(opened_store(tmp_path / "s.db"), settings=make_settings((BTC, ETH, SOL)))
    bot.turn({BTC: pair_market(), ETH: pair_market(FLAT), SOL: pair_market(FLAT)})
    with monkeypatch.context() as patch:
        _refuse_fills(patch)
        bot.turn(
            {
                BTC: pair_market(price_at=LATER),
                ETH: pair_market(price_at=LATER),
                SOL: pair_market(FLAT, price_at=LATER),
            },
            now=LATER,
        )
    assert len(bot.conflicts()) == 1
    return bot


def _market_with_stop_and_cross() -> dict[str, Any]:
    return {
        BTC: pair_market(closed_at=NEXT_CANDLE, price=Decimal(7)),
        ETH: pair_market(FLAT, closed_at=NEXT_CANDLE),
        SOL: pair_market(closed_at=NEXT_CANDLE),
    }


def test_ledger_refusal_keeps_order_and_halts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _refuse_fills(monkeypatch)
    bot = Bot(opened_store(tmp_path / "s.db"), settings=make_settings((BTC, ETH)))

    result = bot.turn({BTC: pair_market(), ETH: pair_market()})

    assert [o.pair for o in result.buys] == [BTC]
    stored = bot.stored()
    assert len(stored.execution.orders) == 1 and stored.ledger.positions == {}
    assert BuyHalt.RECONCILIATION in result.halts
    assert bot.kinds() == [NoticeKind.RECONCILIATION]
    assert len(bot.conflicts()) == 1


def test_flagged_store_stops_buying_keeps_closing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = _flagged_bot(tmp_path, monkeypatch)

    result = bot.turn(_market_with_stop_and_cross(), now=NEXT_CANDLE)

    assert [o.pair for o in result.closes] == [BTC]
    assert result.buys == () and BuyHalt.RECONCILIATION in result.halts


def test_flag_survives_clean_turn_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = _flagged_bot(tmp_path, monkeypatch)
    market = _market_with_stop_and_cross()

    clean = bot.turn(market, now=NEXT_CANDLE)
    bot.restart()
    restarted = bot.turn(market, now=NEXT_CANDLE)

    assert BuyHalt.RECONCILIATION in clean.halts and BuyHalt.RECONCILIATION in restarted.halts
    assert clean.buys == () and restarted.buys == ()
    assert len(bot.conflicts()) == 1
    assert bot.kinds().count(NoticeKind.RECONCILIATION) == 2


def test_filled_close_missing_from_ledger_is_not_rewritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan Risk 10: yeniden yazılsaydı işaret temiz turda kalkardı (R-7)."""
    bot = bot_with_position(tmp_path / "s.db")
    market = {BTC: pair_market(price=Decimal(7), price_at=LATER)}

    def refuse(ledger: Any, _close: Any) -> CloseResult:
        return CloseResult(ledger, CloseOutcome.INVALID_INPUT, None, "enjekte")

    with monkeypatch.context() as patch:
        patch.setattr(_closes, "close_position", refuse)
        refused = bot.turn(market, now=LATER)
    assert BuyHalt.RECONCILIATION in refused.halts
    entries = len(bot.stored().ledger.entries)

    result = bot.turn(market, now=LATER)

    assert result.closes == ()
    stored = bot.stored()
    assert len(stored.ledger.entries) == entries and stored.ledger.closures == {}
    assert len(bot.conflicts()) == 1
