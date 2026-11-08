"""Spec 0029 (AC-4, R-4, G-3): risk modülü daily_loss_reached sorgusu testleri."""

from datetime import UTC, datetime
from decimal import Decimal

from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    RiskLimits,
    RiskState,
    daily_loss_reached,
    observe,
)

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def _state(day_start: str, last_equity: str, halted: bool = False) -> RiskState:
    return RiskState(
        day=NOW.date(),
        day_start_equity=Decimal(day_start),
        peak_equity=max(Decimal(day_start), Decimal(last_equity)),
        last_time=NOW,
        last_equity=Decimal(last_equity),
        halted=halted,
    )


def test_daily_loss_reached_query() -> None:
    # Default daily_loss_limit is 0.03 (3%)
    limits = DEFAULT_LIMITS
    assert limits.daily_loss_limit == Decimal("0.03")

    # Day start 1000, current 980 -> loss = 20 (2% < 3%) -> False
    st_under = _state("1000", "980")
    assert not daily_loss_reached(st_under, limits)

    # Day start 1000, current 970 -> loss = 30 (3% == 3%) -> True
    st_exact = _state("1000", "970")
    assert daily_loss_reached(st_exact, limits)

    # Day start 1000, current 960 -> loss = 40 (4% > 3%) -> True
    st_over = _state("1000", "960")
    assert daily_loss_reached(st_over, limits)

    # Profit day: Day start 1000, current 1050 -> False
    st_profit = _state("1000", "1050")
    assert not daily_loss_reached(st_profit, limits)

    # Empty state -> False
    assert not daily_loss_reached(EMPTY_STATE, limits)

    # Custom limits: 5% limit
    custom_limits = RiskLimits(
        per_trade_risk=Decimal("0.01"),
        daily_loss_limit=Decimal("0.05"),
        max_drawdown=Decimal("0.10"),
        max_open_positions=3,
        profit_cost_multiple=Decimal("2.0"),
    )
    # At 970 (3% loss), 5% limit is NOT reached
    assert not daily_loss_reached(st_exact, custom_limits)
    # At 950 (5% loss), 5% limit IS reached
    st_5pct = _state("1000", "950")
    assert daily_loss_reached(st_5pct, custom_limits)


def test_daily_loss_reached_via_observe() -> None:
    # State created naturally through observe
    state = EMPTY_STATE
    update = observe(state, NOW, Decimal("1000"), DEFAULT_LIMITS)
    assert update.accepted
    state = update.state
    assert not daily_loss_reached(state, DEFAULT_LIMITS)

    # Drawdown to 975 (2.5% loss)
    update = observe(state, NOW, Decimal("975"), DEFAULT_LIMITS)
    assert update.accepted
    state = update.state
    assert not daily_loss_reached(state, DEFAULT_LIMITS)

    # Further drop to 970 (3% loss)
    update = observe(state, NOW, Decimal("970"), DEFAULT_LIMITS)
    assert update.accepted
    state = update.state
    assert daily_loss_reached(state, DEFAULT_LIMITS)


def test_daily_loss_reached_invalid_inputs() -> None:
    # Incomplete state
    incomplete = RiskState(
        day=NOW.date(),
        day_start_equity=None,
        peak_equity=Decimal("1000"),
        last_time=NOW,
        last_equity=Decimal("950"),
        halted=False,
    )
    assert not daily_loss_reached(incomplete, DEFAULT_LIMITS)

    # Invalid non-decimal values
    bad_equity = RiskState(
        day=NOW.date(),
        day_start_equity=Decimal("1000"),
        peak_equity=Decimal("1000"),
        last_time=NOW,
        last_equity="not-a-decimal",  # type: ignore[arg-type]
        halted=False,
    )
    assert not daily_loss_reached(bad_equity, DEFAULT_LIMITS)
