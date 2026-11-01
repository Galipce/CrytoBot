"""Spec 0005 AC-11 (R-10): kâr/maliyet eşiği bağımsız, tam aritmetikli bir modelle aynıdır;
hiçbir girdi onaydan istisna fırlatmaz; Telegram katı düşüremez."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    HARD_FLOOR_MULTIPLE,
    AccountState,
    ApprovalReason,
    LimitChange,
    PairRules,
    TradeApproval,
    TradeIntent,
    approve_trade,
    decide_change,
    observe,
)

PAIR = "BTC/USDT"
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
ACCOUNT = AccountState(Decimal("100000"), Decimal("100000"), 0)
RULES = PairRules(Decimal("0.00001"), Decimal("0"), Decimal("0"))
STATE = observe(EMPTY_STATE, NOW, ACCOUNT.equity, DEFAULT_LIMITS).state
EDGE_REASONS = {ApprovalReason.INVALID_TARGET, ApprovalReason.INSUFFICIENT_EDGE}
EXAMPLES = 300

rates = st.one_of(st.just(Decimal(0)), st.decimals("0", "0.01", places=4))
multiples = st.sampled_from([Decimal(v) for v in ("1", "1.5", "2", "3", "5", "10")])
# where the target sits: below/at the entry, at the threshold (fee and slippage 0), or around it
PLACES = ["below", "at_entry", "boundary", "just_above", "near"] + ["far"] * 2


@st.composite
def cases(draw: st.DrawFn) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, str]:
    entry = draw(st.decimals("0.01", "70000", places=4))
    multiple = draw(multiples)
    fee, spread, slippage = draw(rates), draw(rates), draw(rates)
    place = draw(st.sampled_from(PLACES))
    if place in ("boundary", "just_above"):
        fee = slippage = Decimal(0)  # then the threshold target is exact: entry * (1 + k * spread)
        spread = draw(st.decimals("0.0001", "0.01", places=4))  # spread 0 puts it at the entry
        target = entry * (1 + multiple * spread)
        target += Decimal("0.0001") if place == "just_above" else 0
    else:
        factor = {"below": "0.99", "at_entry": "1", "near": "1.002", "far": "1.05"}[place]
        target = entry * Decimal(factor)
    return entry, target, fee, spread, slippage, multiple, place


def model(entry: Fraction, target: Fraction, fee: Fraction, spread: Fraction,
          slippage: Fraction, multiple: Fraction) -> str:  # fmt: skip
    """Spec 0005 R-1, R-3 in `Fraction`, written from the spec, not from the code."""
    if target <= entry:
        return "invalid_target"
    profit = target - entry
    cost = (entry + target) * fee + entry * spread + (entry + target) * slippage
    return "open" if profit > multiple * cost else "edge"


def run(case: tuple[Any, ...]) -> tuple[str, TradeApproval]:
    entry, target, fee, spread, slippage, multiple, _ = case
    stop = entry / 2
    limits = replace(DEFAULT_LIMITS, profit_cost_multiple=multiple)
    result = approve_trade(
        TradeIntent(PAIR, "buy", entry, stop, target),
        limits,
        ACCOUNT,
        RULES,
        frozenset({PAIR}),
        fee,
        spread,
        slippage,
        STATE,
        NOW,
    )
    expected = model(*(Fraction(v) for v in (entry, target, fee, spread, slippage, multiple)))
    return expected, result


EXPECTED = {
    "invalid_target": ApprovalReason.INVALID_TARGET,
    "edge": ApprovalReason.INSUFFICIENT_EDGE,
}


# measured at 300 (build): open ~109, edge ~102, invalid target ~89, of which at the boundary ~37
@settings(max_examples=EXAMPLES)
@given(cases())
def test_threshold_matches_exact_oracle(case: tuple[Any, ...]) -> None:
    """AC-11 (R-3, R-10): eşik kararı modelinkiyle birebir; eşiği geçmeyen öneri onaylanmaz."""
    expected, result = run(case)

    if expected == "open":
        assert result.reason not in EDGE_REASONS, result.message
    else:
        assert result.reason is EXPECTED[expected] and result.amount is None


JUNK: list[Any] = [
    None, True, 0.5, "1", Decimal("NaN"), Decimal("-Infinity"), Decimal(0), Decimal(-1), 0, 3,
    Decimal("1E+1000000"), Decimal("1E-1000000"), Decimal("1E-999999999999"),
    Decimal("1E+999999999999"), Decimal("9.99E+999999"), Decimal("1E-999999"),
    Decimal("0E-999999999999"), Decimal("0.001"), Decimal("100"), Decimal("95"),
    10**4300, -10**4300,  # past Python 3.12's 4300-digit int -> str limit (review round 1 F-1)
]  # fmt: skip
junk = st.sampled_from(JUNK)


@settings(max_examples=EXAMPLES)
@given(st.tuples(*[junk] * 11))
def test_no_input_raises(values: tuple[Any, ...]) -> None:
    """AC-11 (R-7, R-8): rastgele ve aralık dışı girdilerle onay istisna değil, bir sonuç verir."""
    entry, stop, target, equity, free, fee, spread, slippage, step, min_amount, min_notional = (
        values
    )
    state = observe(EMPTY_STATE, NOW, equity, DEFAULT_LIMITS).state

    result = approve_trade(
        TradeIntent(PAIR, "buy", entry, stop, target),
        DEFAULT_LIMITS,
        AccountState(equity, free, 0),
        PairRules(step, min_amount, min_notional),
        frozenset({PAIR}),
        fee,
        spread,
        slippage,
        state,
        NOW,
    )

    assert isinstance(result, TradeApproval)
    assert (result.amount is None) is (result.reason is not None)


changes = st.tuples(
    st.sampled_from([Decimal(v) for v in ("0.5", "1", "1.5", "2", "3", "10", "NaN")]),
    st.sampled_from(["telegram", "telegram", "cli", "TELEGRAM", "sms"]),
)


@settings(max_examples=EXAMPLES)
@given(st.lists(changes, max_size=20))
def test_telegram_never_lowers_the_multiple(requests: list[tuple[Decimal, str]]) -> None:
    """AC-11 (R-5, R-10): Telegram katı düşüremez; kat hiçbir kanaldan 1'in altına inmez."""
    limits = DEFAULT_LIMITS
    for value, channel in requests:
        before = limits.profit_cost_multiple
        decision = decide_change(limits, LimitChange("profit_cost_multiple", value, channel))
        limits = decision.limits
        if channel == "telegram":
            assert limits.profit_cost_multiple >= before
        assert limits.profit_cost_multiple >= HARD_FLOOR_MULTIPLE


def test_decisions_are_not_vacuous() -> None:
    """AC-11: üreteç her kararı (geçersiz hedef, eşik altı, açık) ve sınırı yeterince üretir."""
    record: list[str] = []

    @settings(max_examples=EXAMPLES)
    @given(cases())
    def collect(case: tuple[Any, ...]) -> None:
        expected, result = run(case)
        record.append(expected)
        if case[-1] == "boundary":
            record.append("at_boundary")
            assert result.reason is ApprovalReason.INSUFFICIENT_EDGE

    collect()

    for decision in ("invalid_target", "edge", "open", "at_boundary"):
        assert record.count(decision) >= 20, (decision, record.count(decision))
