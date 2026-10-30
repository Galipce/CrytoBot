"""Spec 0003 AC-10 (R-5, R-9): onay sonucu bağımsız, tam aritmetikli bir modelle aynıdır;
onaylanan öneri hiçbir kuralı ihlal etmez."""

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from math import floor
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from crytobot.risk import (
    HARD_CAPS,
    AccountState,
    ApprovalReason,
    PairRules,
    RiskLimits,
    TradeApproval,
    TradeIntent,
    approve_trade,
)

WHITELIST = frozenset({"BTC/USDT", "ETH/USDT"})
RATIO_CAPS = {
    "per_trade_risk": HARD_CAPS.per_trade_risk,
    "daily_loss_limit": HARD_CAPS.daily_loss_limit,
    "max_drawdown": HARD_CAPS.max_drawdown,
}

# values that break a field: wrong type, not finite, negative, zero, or just past a bound
JUNK = [Decimal("NaN"), Decimal("Infinity"), Decimal("-1"), Decimal("0"), True, 0.5, "1", None]
BROKEN: dict[str, list[Any]] = {
    "limits.per_trade_risk": [*JUNK, Decimal("0.0200001")],
    "limits.daily_loss_limit": [*JUNK, Decimal("0.0500001")],
    "limits.max_drawdown": [*JUNK, Decimal("0.2500001")],
    "limits.max_open_positions": [*JUNK, 0, 9, Decimal("5")],
    "account.equity": JUNK,
    "account.free_balance": [*JUNK, Decimal("100001")],
    "account.open_positions": [*JUNK, -1, Decimal("1")],
    "rules.amount_step": JUNK,
    "rules.min_amount": JUNK,
    "rules.min_notional": JUNK,
    "fee": [*JUNK, Decimal("1")],
    "intent.side": ["sell", "BUY", " buy"],
    "intent.pair": ["SOL/USDT", "btc/usdt", " BTC/USDT"],
    "intent.entry": JUNK,
    "intent.stop": JUNK,
}

# measured at 400 (VERIFY round 1): ~70 approvals per test, ~12 of them balance-limited; a test may
# draw no NOT_BUY case, so the reason order (R-8) is proven by test_first_reason_in_order_wins
EXAMPLES = 400

type Case = tuple[TradeIntent, RiskLimits, AccountState, PairRules, Any]


def decimals(low: Decimal | str, high: Decimal | str, places: int) -> st.SearchStrategy[Decimal]:
    return st.decimals(min_value=Decimal(low), max_value=Decimal(high), places=places)


@st.composite
def cases(draw: st.DrawFn) -> Case:
    """Valid inputs; in about half the cases exactly one field is then broken.

    Breaking several fields at once would make almost every case an "invalid input" and leave the
    sizing rules untested; the reason order (R-8) has its own example test.
    """
    limits = RiskLimits(
        draw(decimals("0.0001", "0.02", 4)),
        draw(decimals("0.0001", "0.05", 4)),
        draw(decimals("0.0001", "0.25", 4)),
        draw(st.integers(min_value=1, max_value=8)),
    )
    equity = draw(decimals("1", "100000", 2))
    account = AccountState(
        equity,
        draw(st.one_of(st.just(equity), decimals("0", equity, 2), decimals("0", equity / 20, 2))),
        draw(
            st.one_of(
                st.integers(min_value=0, max_value=limits.max_open_positions - 1),
                st.integers(min_value=0, max_value=8),
            )
        ),
    )
    rules = PairRules(
        draw(st.sampled_from([Decimal("0.00001"), Decimal("0.001"), Decimal("0.1"), 1])),
        draw(st.one_of(st.just(Decimal(0)), decimals("0", "5", 3))),
        draw(st.one_of(st.just(Decimal(0)), decimals("0", "50", 1))),
    )
    fee: Any = draw(st.one_of(st.just(Decimal(0)), decimals("0", "0.01", 4)))
    entry = draw(decimals("0.01", "70000", 4))
    stops = {
        "near": decimals(entry * Decimal("0.5"), entry, 4).filter(lambda s: 0 < s < entry),
        "far": decimals("0.0001", entry, 4).filter(lambda s: s < entry),
        "above": decimals(entry, entry * 2, 4),  # at or above the entry
        "none": st.none(),
    }
    # one_of leans on its last, simplest branch; an explicit weighted choice keeps most stops valid
    stop = draw(stops[draw(st.sampled_from(["near", "far"] * 3 + ["above", "none"]))])
    intent = TradeIntent(draw(st.sampled_from(sorted(WHITELIST))), "buy", entry, stop)

    broken = draw(st.sampled_from([*[None] * len(BROKEN), *BROKEN]))
    if broken is None:
        return intent, limits, account, rules, fee
    value = draw(st.sampled_from(BROKEN[broken]))
    if broken == "fee":
        return intent, limits, account, rules, value
    target, field = broken.split(".")
    parts: dict[str, Any] = {"intent": intent, "limits": limits, "account": account, "rules": rules}
    parts[target] = replace(parts[target], **{field: value})
    return parts["intent"], parts["limits"], parts["account"], parts["rules"], fee


def exact(value: object) -> Fraction | None:
    if isinstance(value, bool) or not isinstance(value, Decimal | int):
        return None
    if isinstance(value, Decimal) and not value.is_finite():
        return None
    return Fraction(value)


def known(value: object) -> Fraction:
    """A value the code has already accepted as a finite number."""
    number = exact(value)
    assert number is not None
    return number


def count(value: object) -> int | None:
    return value if type(value) is int else None


Expected = tuple[ApprovalReason | None, Fraction | None, bool]


def oracle(case: Case) -> Expected:
    """Spec 0003'ü `Fraction` ile koddan bağımsız kurar: (neden, miktar, bakiye sınırı)."""
    intent, limits, account, rules, fee = case
    ratios = {name: exact(getattr(limits, name)) for name in RATIO_CAPS}
    positions_limit, positions = count(limits.max_open_positions), count(account.open_positions)
    equity, free, rate = exact(account.equity), exact(account.free_balance), exact(fee)
    step = exact(rules.amount_step)
    min_amount, min_notional = exact(rules.min_amount), exact(rules.min_notional)
    if (
        any(r is None or not 0 < r <= RATIO_CAPS[n] for n, r in ratios.items())
        or positions_limit is None
        or not 1 <= positions_limit <= HARD_CAPS.max_open_positions
        or equity is None
        or equity <= 0
        or free is None
        or not 0 <= free <= equity
        or positions is None
        or positions < 0
        or rate is None
        or not 0 <= rate < 1
        or step is None
        or step <= 0
        or min_amount is None
        or min_amount < 0
        or min_notional is None
        or min_notional < 0
    ):
        return ApprovalReason.INVALID_INPUT, None, False
    if intent.side != "buy":
        return ApprovalReason.NOT_BUY, None, False
    if intent.pair not in WHITELIST:
        return ApprovalReason.NOT_WHITELISTED, None, False
    entry = exact(intent.entry)
    if entry is None or entry <= 0:
        return ApprovalReason.INVALID_ENTRY, None, False
    stop = exact(intent.stop)
    if stop is None or not 0 < stop < entry:
        return ApprovalReason.INVALID_STOP, None, False
    if positions >= positions_limit:
        return ApprovalReason.POSITION_LIMIT, None, False
    budget = equity * known(limits.per_trade_risk)
    by_risk = floor(budget / (step * ((entry - stop) + entry * rate + stop * rate)))
    by_balance = floor(free / (step * entry * (1 + rate)))
    amount = min(by_risk, by_balance) * step
    if amount <= 0 or amount < min_amount or amount * entry < min_notional:
        return ApprovalReason.BELOW_MINIMUM, None, False
    return None, amount, by_balance < by_risk


def actual(result: TradeApproval) -> Expected:
    amount = None if result.amount is None else Fraction(result.amount)
    return result.reason, amount, result.limited_by_balance


@settings(max_examples=EXAMPLES)
@given(cases())
def test_approval_matches_exact_oracle(
    case: Case,
) -> None:
    """AC-10 (R-5, R-8): her girdide neden, miktar ve bakiye sınırı modelinkiyle birebir aynı."""
    intent, limits, account, rules, fee = case
    result = approve_trade(intent, limits, account, rules, WHITELIST, fee)

    assert actual(result) == oracle(case)


@settings(max_examples=EXAMPLES)
@given(cases())
def test_approved_trades_hold_invariants(
    case: Case,
) -> None:
    """AC-10 (R-9, BR-2…BR-4, BR-7): onaylanan öneri sınırlar içinde; bir adım fazlası taşar."""
    intent, limits, account, rules, fee = case
    result = approve_trade(intent, limits, account, rules, WHITELIST, fee)
    if not result.approved:
        assert result.amount is None
        return
    assert result.amount is not None
    amount = Fraction(result.amount)
    entry, stop, rate = known(intent.entry), known(intent.stop), known(fee)
    step = known(rules.amount_step)
    budget = known(account.equity) * known(limits.per_trade_risk)
    free = known(account.free_balance)

    def loss(a: Fraction) -> Fraction:
        return a * (entry - stop) + a * entry * rate + a * stop * rate

    def cost(a: Fraction) -> Fraction:
        return a * entry * (1 + rate)

    assert intent.side == "buy" and intent.pair in WHITELIST
    assert 0 < stop < entry
    assert known(account.open_positions) < limits.max_open_positions
    assert loss(amount) <= budget and cost(amount) <= free
    assert (amount / step).denominator == 1
    assert amount >= known(rules.min_amount) and amount * entry >= known(rules.min_notional)
    assert loss(amount + step) > budget or cost(amount + step) > free
