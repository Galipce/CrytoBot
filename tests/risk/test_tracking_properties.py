"""Spec 0004 AC-10 (R-8): gözlem, kaldırma ve onay dizileri bağımsız, tam aritmetikli bir modelle
aynıdır; hiçbir onay günlük zarar ya da drawdown limitinde/üstünde ya da durdurmada verilmez."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from crytobot.risk import (
    EMPTY_STATE,
    AccountState,
    ApprovalReason,
    PairRules,
    RiskLimits,
    RiskState,
    TradeIntent,
    approve_trade,
    observe,
    resume,
)

PAIR = "BTC/USDT"
START = datetime(2026, 11, 2, 20, 0, tzinfo=UTC)  # four hours before a UTC day boundary
INTENT = TradeIntent(PAIR, "buy", Decimal("100"), Decimal("95"))
RULES = PairRules(Decimal("0.001"), Decimal("0"), Decimal("0"))
FEE = Decimal("0.001")
LOCKS = {
    ApprovalReason.INVALID_INPUT,
    ApprovalReason.DRAWDOWN_HALT,
    ApprovalReason.DAILY_LOSS_LIMIT,
}
EXAMPLES = 300

# a grid, not st.decimals: hypothesis favours range ends, which turns every drop into a halt
SMALL = [Decimal(9600 + 25 * i) for i in range(25)]  # 9600..10200: daily locks, no halt
BIG = [Decimal(7000 + 250 * i) for i in range(17)]  # 7000..11000: drawdown halts
EVENT_KINDS = ["tick"] + ["observe"] * 4 + ["resume"] + ["approve"] * 3


def event(kind: str) -> st.SearchStrategy[tuple[Any, ...]]:
    if kind == "tick":
        return st.tuples(st.just(kind), st.sampled_from([0, 1, 30, 90, 180]))  # minutes
    if kind == "observe":
        return st.tuples(
            st.just(kind),
            st.sampled_from(SMALL * 2 + BIG * 2),
            st.sampled_from(["now"] * 6 + ["naive", "past", "junk"]),
        )
    if kind == "resume":
        return st.tuples(st.just(kind), st.sampled_from(["cli", "cli", "telegram", "CLI"]))
    return st.tuples(st.just(kind), st.sampled_from(["last"] * 5 + ["other"]))


events = st.sampled_from(EVENT_KINDS).flatmap(event)
limits = st.builds(
    lambda daily, drawdown: RiskLimits(Decimal("0.01"), daily, drawdown, 5),
    st.sampled_from([Decimal("0.01"), Decimal("0.02"), Decimal("0.03"), Decimal("0.05")]),
    st.sampled_from([Decimal("0.05"), Decimal("0.1"), Decimal("0.15"), Decimal("0.25")]),
)


@dataclass
class Model:
    """Spec 0004 kept in `Fraction`, written from the spec, not from the code."""

    daily: Fraction
    drawdown: Fraction
    day: date | None = None
    day_start: Fraction | None = None
    peak: Fraction | None = None
    last_time: datetime | None = None
    last: Fraction | None = None
    halted: bool = False

    def observe(self, at: datetime, equity: Fraction) -> None:
        day = at.astimezone(UTC).date()
        if day != self.day:
            self.day, self.day_start = day, equity
        self.peak = equity if self.peak is None else max(self.peak, equity)
        self.last_time, self.last = at, equity
        if (self.peak - equity) / self.peak >= self.drawdown:
            self.halted = True

    def decision(self, now: datetime, equity: Fraction) -> str:
        if self.last is None or now.astimezone(UTC).date() != self.day or equity != self.last:
            return "invalid"
        assert self.peak is not None and self.day_start is not None
        if self.halted or (self.peak - equity) / self.peak >= self.drawdown:
            return "drawdown"
        if (self.day_start - equity) / self.day_start >= self.daily:
            return "daily"
        return "open"


EXPECTED = {
    "invalid": ApprovalReason.INVALID_INPUT,
    "drawdown": ApprovalReason.DRAWDOWN_HALT,
    "daily": ApprovalReason.DAILY_LOSS_LIMIT,
}


def as_fractions(state: RiskState) -> tuple[Any, ...]:
    def f(value: Decimal | None) -> Fraction | None:
        return None if value is None else Fraction(value)

    return (state.day, f(state.day_start_equity), f(state.peak_equity), state.last_time,
            f(state.last_equity), state.halted)  # fmt: skip


def model_view(model: Model) -> tuple[Any, ...]:
    return (model.day, model.day_start, model.peak, model.last_time, model.last, model.halted)


def run(sequence: list[tuple[Any, ...]], risk: RiskLimits, record: list[str]) -> None:
    model = Model(Fraction(risk.daily_loss_limit), Fraction(risk.max_drawdown))
    state, clock = EMPTY_STATE, START
    for event in sequence:
        if event[0] == "tick":
            clock += timedelta(minutes=event[1])
        elif event[0] == "observe":
            _, equity, kind = event
            at: Any = {
                "now": clock,
                "naive": clock.replace(tzinfo=None),
                "past": (model.last_time or clock) - timedelta(seconds=1),
                "junk": clock,
            }[kind]
            value: Any = float(equity) if kind == "junk" else equity
            update = observe(state, at, value, risk)
            valid = kind == "now" or (kind == "past" and model.last_time is None)
            assert update.accepted is valid
            if valid:
                model.observe(at, Fraction(equity))
                clock = max(clock, at)
            state = update.state
        elif event[0] == "resume":
            update = resume(state, event[1])
            if event[1] == "cli" and model.halted:
                assert update.accepted
                model.halted, model.peak = False, model.last
            else:
                assert not update.accepted and update.state == state
            state = update.state
        else:
            equity = model.last if model.last is not None else Fraction(10000)
            if event[1] == "other":
                equity += 1
            decimal_equity = Decimal(equity.numerator) / Decimal(equity.denominator)
            account = AccountState(decimal_equity, min(decimal_equity, Decimal("5000")), 0)
            result = approve_trade(
                INTENT, risk, account, RULES, frozenset({PAIR}), FEE, state, clock
            )
            expected = model.decision(clock, equity)
            record.append(expected)
            if expected == "open":
                assert result.reason not in LOCKS, result.message
            else:
                assert result.reason is EXPECTED[expected] and result.amount is None
        assert as_fractions(state) == model_view(model)


# measured at 300 (build): invalid ~310, open ~215, drawdown ~70, daily ~40 decisions
@settings(max_examples=EXAMPLES)
@given(st.lists(events, max_size=40), limits)
def test_tracking_matches_exact_oracle(sequence: list[tuple[Any, ...]], risk: RiskLimits) -> None:
    """AC-10 (R-8): durum ve her onay kararı modelinkiyle birebir aynı."""
    run(sequence, risk, [])


@settings(max_examples=EXAMPLES)
@given(st.lists(events, max_size=40), limits)
def test_no_trade_past_a_limit(sequence: list[tuple[Any, ...]], risk: RiskLimits) -> None:
    """AC-10 (R-8, BR-5, BR-6): kilit varken onay verilmez; durdurma yalnız CLI ile kalkar."""
    state, clock = EMPTY_STATE, START
    for event in sequence:
        before = state
        if event[0] == "tick":
            clock += timedelta(minutes=event[1])
        elif event[0] == "observe" and event[2] == "now":
            state = observe(state, clock, event[1], risk).state
            assert state.halted or not before.halted  # an observation never lifts a halt
        elif event[0] == "resume":
            state = resume(state, event[1]).state
            if before.halted and not state.halted:
                assert event[1] == "cli"
        elif event[0] == "approve" and state.last_equity is not None:
            equity = state.last_equity
            account = AccountState(equity, min(equity, Decimal("5000")), 0)
            result = approve_trade(
                INTENT, risk, account, RULES, frozenset({PAIR}), FEE, state, clock
            )
            if result.approved:
                assert state.peak_equity is not None and state.day_start_equity is not None
                assert not state.halted
                assert state.peak_equity - equity < risk.max_drawdown * state.peak_equity
                assert (
                    state.day_start_equity - equity < risk.daily_loss_limit * state.day_start_equity
                )


def test_decisions_are_not_vacuous() -> None:
    """AC-10: diziler her kararı (geçersiz, drawdown, günlük, açık) yeterince üretir."""
    record: list[str] = []

    @settings(max_examples=EXAMPLES)
    @given(st.lists(events, max_size=40), limits)
    def collect(sequence: list[tuple[Any, ...]], risk: RiskLimits) -> None:
        run(sequence, risk, record)

    collect()

    for decision in ("invalid", "drawdown", "daily", "open"):
        assert record.count(decision) >= 20, (decision, record.count(decision))
