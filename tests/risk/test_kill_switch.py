"""Spec 0030 AC-2, AC-3, AC-4, AC-5: Risk katmanı acil durdurma (kill switch) ve resume testleri."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    AccountState,
    ApprovalReason,
    CloseRequest,
    PairRules,
    RiskState,
    TrackingReason,
    TradeIntent,
    approve_close,
    approve_trade,
    engage_kill_switch,
    observe,
    resume,
    risk_state_problems,
)

T0 = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
RULES = PairRules(Decimal("0.001"), Decimal("0.001"), Decimal("5"))
INTENT = TradeIntent("BTC/USDT", "buy", Decimal("100"), Decimal("95"), Decimal("200"))
CLOSE_REQ = CloseRequest("cb-pos-1", "BTC/USDT", Decimal("1.5"), "stop")


def make_state(equity: str = "10000", kill_switch: bool = False) -> RiskState:
    state = observe(EMPTY_STATE, T0, Decimal(equity), DEFAULT_LIMITS).state
    if kill_switch:
        state = engage_kill_switch(state).state
    return state


def test_kill_switch_active_reason_defined() -> None:
    """ApprovalReason.KILL_SWITCH_ACTIVE tanımlıdır."""
    assert ApprovalReason.KILL_SWITCH_ACTIVE.value == "kill_switch_active"


def test_approve_trade_rejected_when_kill_switch_active() -> None:
    """AC-3 (R-5): Kill switch devredeyken yeni alım KILL_SWITCH_ACTIVE ile reddedilir."""
    state = make_state(kill_switch=True)
    account = AccountState(Decimal("10000"), Decimal("5000"), 0)

    result = approve_trade(
        INTENT,
        DEFAULT_LIMITS,
        account,
        RULES,
        frozenset({"BTC/USDT"}),
        Decimal("0.001"),
        Decimal(0),
        Decimal(0),
        state,
        T0,
    )

    assert not result.approved
    assert result.reason is ApprovalReason.KILL_SWITCH_ACTIVE
    assert "kill switch aktif" in result.message


def test_approve_close_allowed_when_kill_switch_active() -> None:
    """AC-3 (R-5, BR-9): Kill switch devredeyken açık pozisyon kapanışları engellenmez."""
    approval = approve_close(CLOSE_REQ)
    assert approval.approved
    assert approval.reason is None


def test_engage_kill_switch_idempotent() -> None:
    """AC-2 (R-2): Kill switch devreye alma idempotenttir; zaten devredeyse durumu korur."""
    state = make_state(kill_switch=False)
    assert not state.kill_switch

    update1 = engage_kill_switch(state)
    assert update1.accepted
    assert update1.state.kill_switch
    assert "devreye alındı" in update1.message

    update2 = engage_kill_switch(update1.state)
    assert update2.accepted
    assert update2.state.kill_switch
    assert "zaten devrede" in update2.message


def test_observe_preserves_kill_switch() -> None:
    """Gözlem yapıldığında kill_switch durumu korunur."""
    state = make_state(kill_switch=True)
    later = T0 + timedelta(hours=1)
    observed_update = observe(state, later, Decimal("10200"), DEFAULT_LIMITS)

    assert observed_update.accepted
    assert observed_update.state.kill_switch
    assert observed_update.state.last_equity == Decimal("10200")


def test_resume_clears_kill_switch_and_resets_peak() -> None:
    """AC-4 (R-3): Resume kill switch'i kaldırır ve zirveyi son kasaya eşitler."""
    state = make_state("10000", kill_switch=True)
    later = observe(state, T0 + timedelta(hours=1), Decimal("9000"), DEFAULT_LIMITS).state
    assert later.kill_switch
    assert later.peak_equity == Decimal("10000")

    update = resume(later, "cli")
    assert update.accepted
    assert not update.state.kill_switch
    assert update.state.peak_equity == Decimal("9000")
    assert "durdurma kaldırıldı" in update.message


def test_resume_clears_both_kill_switch_and_drawdown_halt() -> None:
    """AC-4 (R-3): Hem kill switch hem drawdown aktifken resume ikisini birden kaldırır."""
    # 10000 -> 8400 causes drawdown halt with max_drawdown=0.15
    halted = observe(
        observe(EMPTY_STATE, T0, Decimal("10000"), DEFAULT_LIMITS).state,
        T0 + timedelta(hours=1),
        Decimal("8400"),
        DEFAULT_LIMITS,
    ).state
    assert halted.halted

    both = engage_kill_switch(halted).state
    assert both.halted and both.kill_switch

    update = resume(both, "cli")
    assert update.accepted
    assert not update.state.halted
    assert not update.state.kill_switch
    assert update.state.peak_equity == Decimal("8400")


def test_resume_refused_when_neither_kill_switch_nor_halt_active() -> None:
    """AC-5 (R-3): Ne kill switch ne de drawdown yoksa resume reddedilir."""
    normal = make_state("10000", kill_switch=False)
    assert not normal.halted and not normal.kill_switch

    update = resume(normal, "cli")
    assert not update.accepted
    assert update.reason is TrackingReason.NOT_HALTED
    assert "durdurma yok" in update.message


def test_resume_on_empty_state_with_kill_switch() -> None:
    """Gözlem yapılmamış boş durumda kill switch açılıp sonra resume edilebilir."""
    empty_with_ks = engage_kill_switch(EMPTY_STATE).state
    assert empty_with_ks.kill_switch

    update = resume(empty_with_ks, "cli")
    assert update.accepted
    assert not update.state.kill_switch


def test_risk_state_problems_validates_kill_switch() -> None:
    """risk_state_problems kill_switch alanını tip kontrolünden geçirir."""
    valid_state = make_state(kill_switch=True)
    assert risk_state_problems(valid_state) == []

    from dataclasses import replace

    invalid_ks: RiskState = replace(valid_state, kill_switch="not_a_bool")  # type: ignore[arg-type]
    problems = risk_state_problems(invalid_ks)
    assert "kill switch işareti doğru ya da yanlış olmalı" in problems
