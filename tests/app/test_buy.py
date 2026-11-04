"""Spec 0016 AC-1: alım; emir, defter ve risk durumu kaydedilir, yeniden yüklenince aynıdır."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import PairNote, TurnOutcome, _session
from crytobot.execution import OrderStatus
from crytobot.persistence import save_store
from tests.app.helpers import (
    BTC,
    DEPOSIT,
    ETH,
    FEE,
    FIRST_AMOUNT,
    NOW,
    SLIPPAGE,
    STRATEGY,
    Bot,
    limits,
    make_settings,
    opened_store,
    pair_market,
)


def test_crossover_buys_the_approved_amount(tmp_path: Path) -> None:
    """R-1, R-2: elle hesap: bütçe 100, birim kayıp 2.018, adım 0.001."""
    bot = Bot(opened_store(tmp_path / "s.db"))

    result = bot.turn()

    assert result.outcome is TurnOutcome.COMPLETED
    assert [o.amount for o in result.buys] == [FIRST_AMOUNT]
    order = result.buys[0]
    assert order.status is OrderStatus.FILLED
    assert order.fill_price == Decimal(10) * (1 + SLIPPAGE)
    assert (order.entry, order.stop, order.target) == (Decimal(10), Decimal(8), Decimal(14))
    assert bot.notices == []


def test_order_and_fill_share_one_revision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R-2: hiçbir kayıt dolu emri defter kaydı olmadan yazmaz."""
    writes: list[tuple[int, int]] = []

    def spy(path: object, base: object, ledger: Any, execution: Any, risk: Any) -> Any:
        writes.append((len(execution.orders), len(ledger.positions)))
        return save_store(path, base, ledger, execution, risk)

    monkeypatch.setattr(_session, "save_store", spy)
    bot = Bot(opened_store(tmp_path / "s.db"))

    bot.turn()

    assert (1, 1) in writes
    assert all(orders == positions for orders, positions in writes)


def test_reload_gives_same_state_and_clean_reconcile(tmp_path: Path) -> None:
    """R-1: elle hesap: maliyet = 49.554 * 10.01 * 1.001."""
    bot = Bot(opened_store(tmp_path / "s.db"))

    result = bot.turn()

    stored = bot.stored()
    cost = FIRST_AMOUNT * Decimal("10.01") * (1 + FEE)
    assert stored.ledger.balance == DEPOSIT - cost
    assert list(stored.execution.orders) == [result.buys[0].client_order_id]
    assert list(stored.ledger.positions) == [result.buys[0].client_order_id]
    assert stored.risk.last_time == NOW
    assert stored.risk.last_equity == DEPOSIT - cost + FIRST_AMOUNT * 10
    assert bot.conflicts() == ()


def test_fill_over_balance_places_no_order(tmp_path: Path) -> None:
    """Plan Risk 1: bakiyeyle sınırlı onay, slippage'la bakiyeyi aşar: emir yok, durdurma yok."""
    settings = make_settings(
        limits=limits(per_trade_risk=Decimal("0.02")),
        strategy=replace(STRATEGY, k=Decimal("0.1")),
    )
    bot = Bot(opened_store(tmp_path / "s.db"), settings=settings)

    result = bot.turn()

    assert [p.reason for p in result.pairs] == [PairNote.FILL_EXCEEDS_BALANCE]
    assert result.buys == () and result.halts == () and bot.notices == []
    assert bot.stored().execution.orders == {} and bot.conflicts() == ()


def test_risk_over_hard_cap_at_fill_places_no_order(tmp_path: Path) -> None:
    """Plan Risk 2, BR-4: giriş 10, stop 8, fiyat 15: gerçek kayıp ~348 USDT, üst sınır 200."""
    bot = Bot(opened_store(tmp_path / "s.db"))

    result = bot.turn({BTC: pair_market(price=Decimal(15))})

    assert [p.reason for p in result.pairs] == [PairNote.RISK_CAP_AT_FILL]
    assert result.buys == () and bot.notices == []


def test_risk_under_hard_cap_at_fill_still_buys(tmp_path: Path) -> None:
    """Plan Risk 2: kapı yalnız sınırı aşanı keser; fiyat 11'de kayıp ~150 USDT."""
    bot = Bot(opened_store(tmp_path / "s.db"))

    result = bot.turn({BTC: pair_market(price=Decimal(11))})

    assert [o.amount for o in result.buys] == [FIRST_AMOUNT]


def test_each_buy_is_observed_before_the_next(tmp_path: Path) -> None:
    """Plan Risk 4: son kasa iki alımı da görür; ikinci onay ilkinin kasasıyla boyutlanır."""
    bot = Bot(opened_store(tmp_path / "s.db"), settings=make_settings((BTC, ETH)))

    result = bot.turn({BTC: pair_market(), ETH: pair_market()})

    assert len(result.buys) == 2
    stored = bot.stored()
    held = sum(o.amount * 10 for o in result.buys)
    assert stored.ledger.balance is not None
    assert stored.risk.last_equity == stored.ledger.balance + held
    assert result.buys[1].amount < result.buys[0].amount
