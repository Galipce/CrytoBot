"""Spec 0011 AC-13 (R-13, B-10): elle kurulmuş geçersiz risk durumu adıyla reddedilir."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    AccountState,
    ApprovalReason,
    PairRules,
    RiskState,
    TradeApproval,
    TradeIntent,
    approve_trade,
    observe,
    resume,
    risk_state_problems,
)

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
INTENT = TradeIntent("BTC/USDT", "buy", Decimal("100"), Decimal("95"), Decimal("200"))
RULES = PairRules(Decimal("0.001"), Decimal("0.001"), Decimal("5"))
INVALID = "risk durumu geçersiz: gün başı, zirve ya da son kasa geçersiz"
MISSING = "risk durumu geçersiz: gün başı, zirve ya da son kasa eksik"
FRESH = observe(EMPTY_STATE, NOW, Decimal("10000"), DEFAULT_LIMITS).state


def approve(state: RiskState) -> TradeApproval:
    account = AccountState(Decimal("10000"), Decimal("5000"), 0)
    return approve_trade(
        INTENT,
        DEFAULT_LIMITS,
        account,
        RULES,
        frozenset({"BTC/USDT"}),
        Decimal("0.001"),
        Decimal(0),
        Decimal(0),
        state,
        NOW,
    )


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), 10000])
@pytest.mark.parametrize("field", ["day_start_equity", "peak_equity", "last_equity"])
def test_b10_invalid_equity_is_named_invalid_not_missing(field: str, value: Any) -> None:
    result = approve(replace(FRESH, **{field: value}))

    assert result.reason is ApprovalReason.INVALID_INPUT and result.amount is None
    assert INVALID in result.message
    assert MISSING not in result.message


def test_b10_missing_equity_keeps_todays_message() -> None:
    result = approve(replace(FRESH, peak_equity=None))

    assert result.reason is ApprovalReason.INVALID_INPUT
    assert MISSING in result.message
    assert INVALID not in result.message


def test_b10_missing_comes_before_invalid() -> None:
    result = approve(replace(FRESH, peak_equity=None, day_start_equity=Decimal("NaN")))

    assert MISSING in result.message


@pytest.mark.parametrize("day", [10**4300, "2026-11-03", 20261103], ids=["huge", "text", "int"])
def test_b10_a_day_that_is_no_date_is_refused_without_raising(day: Any) -> None:
    result = approve(replace(FRESH, day=day))

    assert result.reason is ApprovalReason.INVALID_INPUT and result.amount is None
    assert "risk durumu geçersiz: gün" in result.message


def test_b10_a_valid_state_is_still_judged_normally() -> None:
    assert approve(FRESH).reason is None
    stale = approve(replace(FRESH, day=(NOW - timedelta(days=1)).date()))
    assert stale.reason is ApprovalReason.INVALID_INPUT and "bayat" in stale.message


def test_observed_and_resumed_states_have_no_problems() -> None:
    """R-6: `observe` ve `resume`'un ürettiği her durum geçerlidir; boş durum da."""
    halted = observe(FRESH, NOW, Decimal("100"), DEFAULT_LIMITS).state
    assert halted.halted

    assert risk_state_problems(EMPTY_STATE) == []
    assert risk_state_problems(FRESH) == []
    assert risk_state_problems(halted) == []
    assert risk_state_problems(resume(halted, "cli").state) == []


hand_built: Any = replace  # deliberately wrong field types
OVERFLOWING = datetime.min.replace(tzinfo=timezone(timedelta(hours=1)))


IMPOSSIBLE: dict[str, Any] = {
    "not_a_state": "durum",
    "empty_but_halted": replace(EMPTY_STATE, halted=True),
    "partly_empty": replace(FRESH, peak_equity=None),
    "day_wrong": replace(FRESH, day=date(2026, 11, 4)),
    "day_not_a_date": hand_built(FRESH, day=20261103),
    "day_is_a_datetime": replace(FRESH, day=NOW),
    "time_not_a_time": hand_built(FRESH, last_time="2026-11-03"),
    "time_naive": replace(FRESH, last_time=NOW.replace(tzinfo=None)),
    "time_overflows": replace(FRESH, last_time=OVERFLOWING),
    "peak_below_last": replace(FRESH, peak_equity=Decimal("9999")),
    "nan_equity": replace(FRESH, last_equity=Decimal("NaN")),
    "int_equity": hand_built(FRESH, day_start_equity=10000),
    "zero_equity": replace(FRESH, day_start_equity=Decimal(0)),
    "out_of_scale": replace(FRESH, peak_equity=Decimal("1E+1000000")),
    "halted_not_bool": hand_built(FRESH, halted=1),
}


@pytest.mark.parametrize("case", list(IMPOSSIBLE))
def test_state_observe_could_not_produce_is_named(case: str) -> None:
    """Spec 0011 R-6: `observe`'un üretemeyeceği durumda sorun adlandırılır, istisna yok."""
    assert risk_state_problems(IMPOSSIBLE[case])
