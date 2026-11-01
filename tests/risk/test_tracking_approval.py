"""Spec 0004 AC-2, AC-4, AC-7…AC-9: onay günlük zarar ve drawdown kilitlerine uyar (BR-5, BR-6)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    AccountState,
    ApprovalReason,
    PairRules,
    RiskLimits,
    RiskState,
    TradeApproval,
    TradeIntent,
    approve_trade,
    observe,
)

PAIR = "BTC/USDT"
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
NEW_YORK, ISTANBUL = timezone(timedelta(hours=-5)), timezone(timedelta(hours=3))
INTENT = TradeIntent(PAIR, "buy", Decimal("100"), Decimal("95"), Decimal("200"))
RULES = PairRules(Decimal("0.001"), Decimal("0.001"), Decimal("5"))


def observed(*equities: str, limits: RiskLimits = DEFAULT_LIMITS) -> RiskState:
    """Equities observed a minute apart, the last one at NOW."""
    state = EMPTY_STATE
    for i, equity in enumerate(equities):
        at = NOW - timedelta(minutes=len(equities) - 1 - i)
        update = observe(state, at, Decimal(equity), limits)
        assert update.accepted, update.message
        state = update.state
    return state


def approve(
    state: RiskState,
    equity: str,
    limits: RiskLimits = DEFAULT_LIMITS,
    intent: TradeIntent = INTENT,
    now: Any = NOW,
    fee: Any = Decimal("0.001"),
) -> TradeApproval:
    account = AccountState(Decimal(equity), min(Decimal(equity), Decimal("5000")), 0)
    return approve_trade(
        intent, limits, account, RULES, frozenset({PAIR}), fee, Decimal(0), Decimal(0), state, now
    )


@pytest.mark.parametrize(
    ("equity", "reason"),
    [
        ("9701", None),
        ("9700", ApprovalReason.DAILY_LOSS_LIMIT),
        ("9000", ApprovalReason.DAILY_LOSS_LIMIT),
        ("10500", None),
    ],
    ids=["below_limit", "at_limit", "past_limit", "profit"],
)
def test_daily_loss_limit(equity: str, reason: ApprovalReason | None) -> None:
    """AC-2 (BR-5): gün başı 10000, limit %3 — kasa 9700'e (tam %3) inince o gün yeni işlem yok."""
    result = approve(observed("10000", equity), equity)

    assert result.reason is reason
    assert (result.amount is None) is (reason is not None)
    if reason is not None:
        assert PAIR in result.message and equity in result.message


def test_lowered_daily_limit_applies_at_once() -> None:
    """AC-2 (BR-5): gün içinde düşürülen limit (onaydaki limit) hemen kilitler."""
    lowered = replace(DEFAULT_LIMITS, daily_loss_limit=Decimal("0.02"))
    state = observed("10000", "9800")

    assert approve(state, "9800").approved
    assert approve(state, "9800", limits=lowered).reason is ApprovalReason.DAILY_LOSS_LIMIT


def test_halt_rejects_trades() -> None:
    """AC-4, AC-5 (BR-6): drawdown durdurmasında, kasa toparlansa da öneri reddedilir."""
    halted = observed("10000", "8500", "10000")

    result = approve(halted, "10000")

    assert result.reason is ApprovalReason.DRAWDOWN_HALT and result.amount is None
    assert "drawdown" in result.message


def test_drawdown_at_limit_rejects_even_before_a_halt_is_recorded() -> None:
    """AC-4 (BR-6): drawdown oranı onaydaki limitte/üstündeyse öneri reddedilir."""
    state = observed("10000", "9000")
    lowered = replace(DEFAULT_LIMITS, max_drawdown=Decimal("0.1"))

    assert not state.halted
    assert approve(state, "9000", limits=lowered).reason is ApprovalReason.DRAWDOWN_HALT


ORDER: dict[str, tuple[dict[str, Any], ApprovalReason]] = {
    # 10000 -> 8500 on one day: a 15% drawdown and a 15% daily loss together
    "drawdown_before_daily": ({}, ApprovalReason.DRAWDOWN_HALT),
    "input_before_drawdown": ({"fee": Decimal("1")}, ApprovalReason.INVALID_INPUT),
}


@pytest.mark.parametrize("case", list(ORDER))
def test_rejection_order(case: str) -> None:
    """AC-7 (R-7): geçersiz girdi → drawdown durdurması → günlük zarar limiti → spec 0003 sırası."""
    overrides, reason = ORDER[case]

    result = approve(observed("10000", "8500"), "8500", **overrides)

    assert result.reason is reason


def test_daily_limit_before_spec_0003_reasons() -> None:
    """AC-7: günlük limit doluyken stop'suz öneri "günlük zarar limiti" ile reddedilir."""
    result = approve(observed("10000", "9700"), "9700", intent=replace(INTENT, stop=None))

    assert result.reason is ApprovalReason.DAILY_LOSS_LIMIT


STALE: dict[str, tuple[RiskState, str, Any, str]] = {
    "empty": (EMPTY_STATE, "10000", NOW, "risk durumu boş"),
    "other_day": (observed("10000"), "10000", NOW + timedelta(days=1), "risk durumu bayat: gün"),
    "other_equity": (observed("10000"), "9990", NOW, "risk durumu bayat: son kasa 10000"),
    "naive_now": (observed("10000"), "10000", datetime(2026, 11, 2, 10, 0), "şu anki zaman"),
    # 2026-11-03 03:00 UTC: the next UTC day, though its local date is still the state's day
    "next_utc_day_local_same": (
        observed("10000"),
        "10000",
        datetime(2026, 11, 2, 22, 0, tzinfo=NEW_YORK),
        "risk durumu bayat: gün",
    ),
}


@pytest.mark.parametrize("case", list(STALE))
def test_stale_or_empty_state_is_invalid_input(case: str) -> None:
    """AC-8 (R-7): boş, başka günden ya da başka kasayla güncellenmiş durum geçersiz girdidir."""
    state, equity, now, named = STALE[case]

    result = approve(state, equity, now=now)

    assert result.reason is ApprovalReason.INVALID_INPUT and result.amount is None
    assert named in result.message


def test_fresh_state_matches_spec_0003() -> None:
    """AC-9: kilitsiz ve kasası aynı taze durumla sonuç spec 0003 AC-1 ile aynıdır (19.249)."""
    result = approve(observed("10000"), "10000")

    assert result.approved and result.amount == Decimal("19.249")


def test_largest_in_range_equity_is_a_named_result() -> None:
    """R-7 (spec 0003 R-1, A-2): aralığın en büyük kasası adlandırılmış bir sonuç verir."""
    huge = "9.99E+999999"

    result = approve(observed(huge), huge)

    assert result.reason is ApprovalReason.INVALID_INPUT and result.amount is None
    assert "ölçek hesaplanamıyor" in result.message


TINY = Decimal("1E-999999999999")
SCALE_NAMED = "risk durumu geçersiz: kasa ölçeği"
MISSING_NAMED = "risk durumu geçersiz: gün başı, zirve ya da son kasa eksik"
HAND_BUILT: dict[str, tuple[RiskState, str]] = {
    "huge_peak": (
        RiskState(NOW.date(), Decimal("1"), Decimal("1E+999999999999"), NOW, Decimal("1"), False),
        SCALE_NAMED,
    ),
    "tiny_equity": (RiskState(NOW.date(), TINY, Decimal("10000"), NOW, TINY, False), SCALE_NAMED),
    "no_peak": (RiskState(NOW.date(), Decimal("1"), None, NOW, Decimal("1"), False), MISSING_NAMED),
}


@pytest.mark.parametrize("case", list(HAND_BUILT))
def test_hand_built_state_past_the_range_is_invalid_input(case: str) -> None:
    """R-7 (A-2, A-3): aralık dışı ya da eksik kasalı durum, kendi nedeniyle geçersiz girdidir."""
    state, named = HAND_BUILT[case]

    result = approve(state, str(state.last_equity))

    assert result.reason is ApprovalReason.INVALID_INPUT and result.amount is None
    assert named in result.message
    other = MISSING_NAMED if named == SCALE_NAMED else SCALE_NAMED
    assert other not in result.message


def test_non_utc_now_on_the_same_utc_day_is_fresh() -> None:
    """AC-8 (R-7): gün UTC'ye göre karşılaştırılır; aynı UTC günündeki +03:00 zaman tazedir."""
    result = approve(observed("10000"), "10000", now=datetime(2026, 11, 2, 13, 0, tzinfo=ISTANBUL))

    assert result.approved
