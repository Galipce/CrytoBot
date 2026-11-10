"""Spec 0035 AC-1, AC-11 (R-4): çalışan bota kill switch isteği tur içinde, turun kendi kaydıyla."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import (
    BuyHalt,
    KillRequest,
    TurnMemory,
    TurnNotice,
    TurnOutcome,
    TurnResult,
    prepare_live_store,
    run_turn,
)
from crytobot.execution import Exchange, PaperExchange
from crytobot.persistence import load_audit_records, load_store
from crytobot.risk import ApprovalReason
from tests.app.helpers import BTC, ETH, FLAT, NOW, make_settings, opened_store, pair_market
from tests.app.test_live_loop import MockLiveExchange
from tests.app.test_live_start import FakeLiveClient

T1 = NOW + timedelta(hours=1)


class Request:
    """İstek bayrağı sahtesi: `pending` yanıtları sırayla, sonra son yanıt tekrarlanır."""

    def __init__(self, *answers: bool) -> None:
        self.answers = list(answers)
        self.calls = 0
        self.consumed = 0

    def pending(self) -> bool:
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return answer and self.consumed == 0

    def consume(self) -> None:
        self.consumed += 1

    def as_request(self) -> KillRequest:
        return KillRequest(self.pending, self.consume)


def store_for(tmp_path: Path, mode: str) -> Path:
    path = tmp_path / f"{mode}.db"
    if mode == "paper":
        return opened_store(path)
    prepare_live_store(str(path), NOW, live_client=FakeLiveClient(free_balance=Decimal(10000)))
    return path


def exchange_for(path: Path, mode: str) -> Exchange:
    """Canlı modda borsa bakiyesi defterle eşit: mutabakat durdurması testi karıştırmaz."""
    if mode == "paper":
        return PaperExchange()
    loaded = load_store(path, "live")
    assert loaded.state is not None and loaded.state.ledger.balance is not None
    return MockLiveExchange(free_balance=loaded.state.ledger.balance)


def turn(path: Path, mode: str, market: dict[str, Any], now: Any, **kw: Any) -> TurnResult:
    notices: list[TurnNotice] = []
    return run_turn(
        market=market,
        settings=make_settings(whitelist=(BTC, ETH)),
        store_path=path,
        now=now,
        exchange=exchange_for(path, mode),
        sink=notices.append,
        memory=kw.pop("memory", TurnMemory()),
        **kw,
    )


def stored_kill_switch(path: Path, mode: str) -> bool:
    loaded = load_store(path, mode)
    assert loaded.state is not None
    return loaded.state.risk.kill_switch


def test_live_kill_switch_blocks_next_buy_keeps_stop_close(tmp_path: Path) -> None:
    """AC-1 (R-1, R-4): canlı bot çalışırken gelen istek sonraki turda alımı durdurur; stop
    kapanışı yapılır; istek tüketilir ve denetim kaydı `engaged` yazılır."""
    path = store_for(tmp_path, "live")
    memory = TurnMemory()
    first = turn(
        path, "live", {BTC: pair_market(), ETH: pair_market(closes=FLAT)}, NOW, memory=memory
    )
    assert first.outcome is TurnOutcome.COMPLETED and len(first.buys) == 1

    request = Request(True)
    second = turn(
        path,
        "live",
        {BTC: pair_market(price=Decimal("7.9"), closed_at=T1), ETH: pair_market(closed_at=T1)},
        T1,
        memory=memory,
        kill_request=request.as_request(),
    )

    assert second.outcome is TurnOutcome.COMPLETED
    assert stored_kill_switch(path, "live")
    assert request.consumed == 1
    assert BuyHalt.KILL_SWITCH in second.halts
    assert second.buys == ()
    assert [c.pair for c in second.closes] == [BTC]
    eth = next(p for p in second.pairs if p.pair == ETH)
    assert eth.reason is ApprovalReason.KILL_SWITCH_ACTIVE
    rows = load_audit_records(path)
    assert any('"result":"engaged"' in r and '"mode":"live"' in r for r in rows)


@pytest.mark.parametrize("mode", ["live", "paper"])
def test_kill_requested_mid_turn_survives_turn(tmp_path: Path, mode: str) -> None:
    """AC-11 (R-4, G-1): tur başında istek yok, tur sırasında geliyor. Turun kaydı silinmez,
    tur bittiğinde kill switch depoda devrede; alım kaydı da korunur; sonraki tur alım yapmaz."""
    path = store_for(tmp_path, mode)
    memory = TurnMemory()
    request = Request(False, True)

    first = turn(
        path,
        mode,
        {BTC: pair_market(), ETH: pair_market(closes=FLAT)},
        NOW,
        memory=memory,
        kill_request=request.as_request(),
    )

    assert first.outcome is TurnOutcome.COMPLETED  # SAVE_REFUSED değil: eski yazım yok
    assert len(first.buys) == 1
    assert stored_kill_switch(path, mode)
    assert request.consumed == 1
    loaded = load_store(path, mode)
    assert loaded.state is not None and len(loaded.state.ledger.positions) == 1

    second = turn(path, mode, {BTC: pair_market(closed_at=T1), ETH: pair_market(closed_at=T1)}, T1)
    assert second.buys == ()
    assert BuyHalt.KILL_SWITCH in second.halts


def test_pending_request_with_kill_switch_already_on_is_only_consumed(tmp_path: Path) -> None:
    """Plan 0035 Risk 1: kill switch zaten devredeyse istek yalnız silinir, ek kayıt yazılmaz."""
    path = store_for(tmp_path, "paper")
    turn(
        path, "paper", {BTC: pair_market(closes=FLAT)}, NOW, kill_request=Request(True).as_request()
    )
    before = load_store(path, "paper")
    assert before.state is not None and before.state.risk.kill_switch
    audit_before = len(load_audit_records(path))

    request = Request(True)
    turn(
        path,
        "paper",
        {BTC: pair_market(closes=FLAT, closed_at=T1)},
        T1,
        kill_request=request.as_request(),
    )

    assert request.consumed == 1
    assert len(load_audit_records(path)) == audit_before


def test_no_request_changes_nothing(tmp_path: Path) -> None:
    """AC-10: istek yoksa tur bugünkü gibi; kill switch yazılmaz."""
    path = store_for(tmp_path, "paper")
    result = turn(path, "paper", {BTC: pair_market(), ETH: pair_market(closes=FLAT)}, NOW)
    assert len(result.buys) == 1
    assert not stored_kill_switch(path, "paper")


def test_refused_save_keeps_the_kill_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan 0035 adım 4, VERIFY round 1 F-1: kill kaydı reddedilirse (eski yazım) istek silinmez;
    tur SAVE_REFUSED biter, alım yok; kayıt yeniden çalışınca sonraki tur isteği işler."""
    from crytobot.persistence import StoreOutcome, StoreResult

    path = store_for(tmp_path, "paper")
    request = Request(True)
    monkeypatch.setattr(
        "crytobot.app._session.save_store",
        lambda *a, **k: StoreResult(StoreOutcome.STALE_WRITE, None, (), "eski yazım"),
    )

    refused = turn(path, "paper", {BTC: pair_market()}, NOW, kill_request=request.as_request())

    assert refused.outcome is TurnOutcome.SAVE_REFUSED
    assert request.consumed == 0
    assert refused.buys == ()
    assert not stored_kill_switch(path, "paper")

    monkeypatch.undo()  # the store accepts writes again
    later = turn(
        path, "paper", {BTC: pair_market(closed_at=T1)}, T1, kill_request=request.as_request()
    )

    assert request.consumed == 1
    assert stored_kill_switch(path, "paper")
    assert later.buys == ()
