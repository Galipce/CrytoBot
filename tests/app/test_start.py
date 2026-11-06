"""Spec 0022 AC-2 (live depo), AC-4, AC-5, AC-6 (R-1, R-3…R-5): depo kapıları, yeniden başlama.

Depoyu yalnız hazırlık oluşturur; başlatma hiçbir durumda oluşturmaz (BR-6). Hazırlık tur atmaz.
"""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

import pytest

from crytobot.app import (
    PREPARE_HINT,
    PrepareOutcome,
    StartOutcome,
    _start,
    open_for_start,
    prepare_store,
    read_pairs,
)
from crytobot.execution import OrderStatus
from crytobot.persistence import StoreOutcome, StoreResult, create_store, load_store, save_store
from crytobot.portfolio import EMPTY_LEDGER, open_ledger
from crytobot.risk import EMPTY_STATE
from tests.app.helpers import (
    BTC,
    CROSS,
    DEPOSIT,
    ETH,
    FLAT,
    LATER,
    NOW,
    Bot,
    Exchange,
    make_settings,
    opened_store,
    pair_market,
)
from tests.app.loop_fakes import harness


def test_prepare_creates_paper_store_with_opening_balance(tmp_path: Path) -> None:
    store = tmp_path / "s.db"
    result = prepare_store(str(store), Decimal("2500.5"), NOW)
    assert result.outcome is PrepareOutcome.PREPARED
    state = load_store(store, "paper").state
    assert state is not None and state.mode == "paper"
    assert state.ledger.balance == Decimal("2500.5") and state.ledger.opened_at == NOW
    assert state.execution.orders == {} and state.ledger.positions == {}  # no turn
    assert state.risk == EMPTY_STATE


@pytest.mark.parametrize("content", [None, b"bozuk dosya"])
def test_prepare_refuses_existing_store(tmp_path: Path, content: bytes | None) -> None:
    """R-3: var olan depo (okunabilir ya da bozuk) — hiçbir şey yazılmaz."""
    store = tmp_path / "s.db"
    if content is None:
        opened_store(store)
    else:
        store.write_bytes(content)
    before = store.read_bytes()
    result = prepare_store(str(store), DEPOSIT, NOW)
    assert result.outcome is PrepareOutcome.STORE_EXISTS
    assert store.read_bytes() == before


@pytest.mark.parametrize(
    "balance",
    [None, Decimal(0), Decimal(-1), Decimal("NaN"), "1000", 10.0, Decimal("1" * 29), True],
)
def test_bad_opening_balance_creates_nothing(tmp_path: Path, balance: Any) -> None:
    """R-3: eksik, sıfır, negatif, sayı olmayan ve basamak sınırını aşan bakiye."""
    store = tmp_path / "s.db"
    result = prepare_store(str(store), balance, NOW)
    assert result.outcome is PrepareOutcome.INVALID_BALANCE
    assert result.message == "açılış bakiyesi geçersiz"
    assert not store.exists()


def test_prepare_into_a_missing_folder_writes_nothing(tmp_path: Path) -> None:
    store = tmp_path / "yok" / "s.db"
    result = prepare_store(str(store), DEPOSIT, NOW)
    assert result.outcome is PrepareOutcome.CREATE_FAILED
    assert not store.parent.exists()


def test_balance_not_written_leaves_store_that_start_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan Risk 12: dosya otomatik silinmez; başlatma "defter açılmamış" ile reddeder."""
    store = tmp_path / "s.db"
    refused = StoreResult(StoreOutcome.WRITE_FAILED, None, (), "yazılamadı")
    monkeypatch.setattr(_start, "save_store", lambda *_: refused)
    result = prepare_store(str(store), DEPOSIT, NOW)
    assert result.outcome is PrepareOutcome.BALANCE_NOT_WRITTEN
    assert "depo oluştu" in result.message and store.exists()
    monkeypatch.undo()
    check = open_for_start(str(store))
    assert check.outcome is StartOutcome.LEDGER_NOT_OPENED and check.hint is None


def _busy(path: object, mode: object) -> StoreResult:
    return StoreResult(StoreOutcome.BUSY, None, (), "depo meşgul")


@pytest.mark.parametrize(
    ("make", "outcome", "named"),
    [
        ("missing", StartOutcome.STORE_MISSING, "depo yok"),
        ("unreadable", StartOutcome.STORE_UNREADABLE, "depo okunamıyor"),
        ("busy", StartOutcome.STORE_BUSY, "depo meşgul"),
        ("not_opened", StartOutcome.LEDGER_NOT_OPENED, "defter açılmamış"),
        ("live", StartOutcome.MODE_MISMATCH, "paper modunda değil"),
    ],
)
def test_start_refuses_each_store_problem_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make: str, outcome: StartOutcome, named: str
) -> None:
    """R-4: başlatma reddeder, nedeni adıyla söyler, depo oluşturmaz ve değiştirmez."""
    store = tmp_path / "s.db"
    if make == "unreadable":
        store.write_bytes(b"bozuk")
    elif make == "busy":
        opened_store(store)
        monkeypatch.setattr(_start, "load_store", _busy)
    elif make == "not_opened":
        assert create_store(store, "paper").state is not None
    elif make == "live":
        created = create_store(store, "live")
        assert created.state is not None
        ledger = open_ledger(EMPTY_LEDGER, DEPOSIT, NOW).ledger
        saved = save_store(store, created.state, ledger, created.state.execution, EMPTY_STATE)
        assert saved.state is not None
    before = store.read_bytes() if store.exists() else None
    check = open_for_start(str(store))
    assert check.outcome is outcome
    assert check.message.startswith("başlatma reddedildi: ") and named in check.message
    assert (store.read_bytes() if store.exists() else None) == before


def test_live_store_is_refused_without_a_turn(tmp_path: Path) -> None:
    """R-1, AC-2: live depoyla başlatma adıyla reddedilir; tur de yalnız paper açar."""
    store = tmp_path / "s.db"
    created = create_store(store, "live")
    assert created.state is not None
    ledger = open_ledger(EMPTY_LEDGER, DEPOSIT, NOW).ledger
    assert save_store(store, created.state, ledger, created.state.execution, EMPTY_STATE).state
    check = open_for_start(str(store))
    assert check.outcome is StartOutcome.MODE_MISMATCH
    bot = harness(store)
    bot.run()
    (summary,) = bot.events("tur")
    assert "sonuç=store_unavailable" in summary and "alım=0" in summary
    assert load_store(store, "live").state is not None


@pytest.mark.parametrize("make", ["missing", "unreadable", "not_opened", "live", "ready", "busy"])
def test_prepare_hint_only_when_store_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make: str
) -> None:
    store = tmp_path / "s.db"
    if make == "unreadable":
        store.write_bytes(b"bozuk")
    elif make == "not_opened":
        create_store(store, "paper")
    elif make == "live":
        create_store(store, "live")
    elif make in ("ready", "busy"):
        opened_store(store)
    if make == "busy":
        monkeypatch.setattr(_start, "load_store", _busy)
    check = open_for_start(str(store))
    assert check.hint == (PREPARE_HINT if make == "missing" else None)
    assert (check.outcome is StartOutcome.READY) == (make == "ready")
    assert store.exists() == (make != "missing")  # start never creates the store


def test_read_pairs_are_whitelist_then_positions(tmp_path: Path) -> None:
    bot = Bot(opened_store(tmp_path / "s.db"))
    bot.turn({BTC: pair_market()})
    assert read_pairs((ETH,), str(bot.path)) == (ETH, BTC)
    assert read_pairs((BTC, ETH), str(bot.path)) == (BTC, ETH)
    assert read_pairs((ETH,), str(tmp_path / "yok.db")) == (ETH,)


class QueryLog(Exchange):
    """Sorgular kaydedilir; sorgunun sonucu `UNKNOWN`'dır, emir bilinmez kalır."""

    queried: ClassVar[list[str]] = []

    def query(self, client_order_id: str) -> OrderStatus:
        QueryLog.queried.append(client_order_id)
        return OrderStatus.UNKNOWN


def test_restart_keeps_positions_unknown_orders_and_halt(tmp_path: Path) -> None:
    """R-5: açık pozisyon, durumu bilinmeyen emir ve süren drawdown durdurması aynen yüklenir;
    durdurma sürer, alım olmaz, bilinmeyen emir sorgulanır (BR-6, BR-11)."""
    settings = make_settings((BTC, ETH))
    bot = Bot(opened_store(tmp_path / "s.db"), settings=settings)
    assert len(bot.turn({BTC: pair_market(), ETH: pair_market(FLAT)}).buys) == 1
    unknown = Exchange(place={"cb-": OrderStatus.UNKNOWN})
    eth = pair_market(price_at=LATER)
    bought = bot.turn({BTC: pair_market(price_at=LATER), ETH: eth}, now=LATER, exchange=unknown)
    assert [order.status for order in bought.buys] == [OrderStatus.UNKNOWN]
    state = bot.stored()
    halted = save_store(
        bot.path, state, state.ledger, state.execution, replace(state.risk, halted=True)
    )
    assert halted.state is not None
    before = bot.stored()

    assert open_for_start(str(bot.path)).outcome is StartOutcome.READY
    QueryLog.queried = []
    restarted = harness(bot.path, turn=settings, closes=CROSS)
    exit_ = restarted.run(exchange=QueryLog())
    assert exit_.last is not None
    after = load_store(bot.path, "paper").state
    assert after is not None
    assert after.ledger.positions == before.ledger.positions
    assert after.execution.unknown == before.execution.unknown != ()
    assert after.risk.halted and after.risk.peak_equity == before.risk.peak_equity
    assert exit_.last.buys == ()
    assert {halt.value for halt in exit_.last.halts} >= {"drawdown", "unknown_orders"}
    assert QueryLog.queried == list(before.execution.unknown)
