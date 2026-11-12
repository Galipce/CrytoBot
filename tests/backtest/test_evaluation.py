"""Spec 0042 AC-3…AC-6: değerlendirme kuralı (seçim, eşikler, saklı dönem, paper adayı).

Metrikler elle kurulur: kural yalnız `trades`, `profit_factor`, `net`, `max_drawdown`'a bakar.
"""

from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crytobot.backtest import (
    HOLDOUT_DRAWDOWN,
    HOLDOUT_NET,
    MAX_DRAWDOWN,
    MIN_PROFIT_FACTOR,
    MIN_TRADES,
    NOT_ENOUGH_TRADES,
    OOS_DRAWDOWN,
    OOS_NET,
    OOS_PROFIT_FACTOR,
    OOS_TRADES,
    PASSED,
    Assessed,
    PartMetrics,
    not_enough_trades,
    paper_candidate,
    select_combination,
    verdict,
)


def part(
    trades: int = 30,
    profit_factor: Decimal | None = Decimal("1.5"),
    net: Decimal = Decimal("100"),
    drawdown: Decimal = Decimal("0.05"),
) -> PartMetrics:
    return PartMetrics(
        first_turn=None,
        last_turn=None,
        turns=0,
        start_equity=Decimal(10000),
        end_equity=Decimal(10000) + net,
        net=net,
        return_ratio=net / Decimal(10000),
        realized=net,
        unrealized=Decimal(0),
        trades=trades,
        winners=0,
        losers=0,
        win_rate=None,
        profit_factor=profit_factor,
        max_drawdown=drawdown,
        average_daily_return=None,
        fees=Decimal(0),
        slippage=Decimal(0),
        daily_loss_days=0,
        halt_started=None,
        halted_at_start=False,
        missing=(),
        no_proposals=(),
        refusals=(),
        notices=(),
    )


GOOD = part()


def test_thresholds_are_fixed_constants() -> None:
    """R-3: eşikler kodda sabit."""
    assert (30, Decimal("1.2"), Decimal("0.15")) == (MIN_TRADES, MIN_PROFIT_FACTOR, MAX_DRAWDOWN)


# --- AC-3: seçim yalnız örneklem içinde ---


def test_selection_highest_profit_factor_with_30_trades() -> None:
    combos = [
        part(trades=29, profit_factor=Decimal("9")),  # 29 trades: not eligible
        part(trades=30, profit_factor=Decimal("1.3")),
        part(trades=45, profit_factor=Decimal("1.8")),
        part(trades=31, profit_factor=Decimal("1.7")),
    ]
    assert select_combination(combos) == 2


def test_selection_undefined_factor_is_highest_ties_by_net_then_order() -> None:
    """Plan Risk 6: tanımsız kâr faktörü en yüksek; eşitlikte net kâr, sonra ızgara sırası."""
    assert select_combination([part(profit_factor=Decimal("50")), part(profit_factor=None)]) == 1
    tied = [
        part(profit_factor=Decimal("1.5"), net=Decimal("10")),
        part(profit_factor=Decimal("1.5"), net=Decimal("20")),
        part(profit_factor=Decimal("1.5"), net=Decimal("20")),
    ]
    assert select_combination(tied) == 1


def test_no_combination_with_30_trades() -> None:
    assert select_combination([part(trades=29), part(trades=0)]) is None
    assert select_combination([]) is None
    assert NOT_ENOUGH_TRADES == "geçmedi: örneklem içi işlem yetersiz"


# --- spec 0043 AC-10 (R-6) ---


def test_failed_lines_carry_value_and_threshold() -> None:
    """Her "geçmedi" satırı tutmayan değeri ve eşiği yazar (spec örnekleri dahil)."""
    assert not_enough_trades([part(trades=29), part(trades=4)]) == (
        "geçmedi: örneklem içi işlem yetersiz (29 < 30)"
    )
    assert not_enough_trades([]) == "geçmedi: örneklem içi işlem yetersiz (0 < 30)"
    assert verdict(part(profit_factor=Decimal("1.15")), GOOD) == (
        "geçmedi: örneklem dışı kâr faktörü (1.1500 < 1.2)"
    )
    assert verdict(part(net=Decimal("-5")), GOOD) == (
        "geçmedi: örneklem dışı net kâr (-5.00000000 USDT ≤ 0)"
    )
    assert verdict(part(trades=29), GOOD) == "geçmedi: örneklem dışı işlem sayısı (29 < 30)"
    assert verdict(part(drawdown=Decimal("0.152")), GOOD) == (
        "geçmedi: örneklem dışı drawdown (%15.2000 ≥ %15)"
    )
    assert verdict(GOOD, part(net=Decimal("-0.5"))) == (
        "geçmedi: saklı dönem net kâr (-0.50000000 USDT ≤ 0)"
    )
    assert verdict(GOOD, part(drawdown=Decimal("0.3"))) == (
        "geçmedi: saklı dönem drawdown (%30.0000 ≥ %15)"
    )
    assert verdict(GOOD, GOOD) == PASSED == "geçti"


_factors = st.one_of(st.none(), st.decimals(min_value=0, max_value=20, places=2, allow_nan=False))
_parts = st.builds(
    part,
    trades=st.integers(min_value=0, max_value=60),
    profit_factor=_factors,
    net=st.decimals(min_value=-500, max_value=500, places=2, allow_nan=False),
)


@given(
    in_sample=st.lists(_parts, min_size=1, max_size=6),
    later=st.lists(st.tuples(_parts, _parts), min_size=6, max_size=6),
)
def test_selection_ignores_later_periods(
    in_sample: list[PartMetrics], later: list[tuple[PartMetrics, PartMetrics]]
) -> None:
    """AC-3: seçim yalnız örneklem içini alır; örneklem dışı ve saklı dönem ne olursa olsun aynı.
    Kural bunu imzasıyla sağlar: sonraki dönemleri değiştirmek seçime ulaşamaz."""
    chosen = select_combination(in_sample)
    # pair every combination with arbitrary later-period results; the choice cannot depend on them
    combined = [(inside, *later[index]) for index, inside in enumerate(in_sample)]
    assert select_combination([inside for inside, _, _ in combined]) == chosen
    if chosen is not None:
        best = in_sample[chosen]
        assert best.trades >= MIN_TRADES
        for other in in_sample:
            if other.trades >= MIN_TRADES and best.profit_factor is not None:
                assert other.profit_factor is not None
                assert other.profit_factor <= best.profit_factor
    else:
        assert all(other.trades < MIN_TRADES for other in in_sample)


# --- AC-4: örneklem dışı eşik sınırları ---


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"profit_factor": Decimal("1.2"), "trades": 30}, PASSED),
        ({"profit_factor": Decimal("1.19")}, f"{OOS_PROFIT_FACTOR} (1.1900 < 1.2)"),
        # the decision is exact; a failing factor is cut toward failure, so the line never reads
        # "1.2000 < 1.2" (0043 plan Risk 6, review round 1 L-2)
        ({"profit_factor": Decimal("1.19996")}, f"{OOS_PROFIT_FACTOR} (1.1999 < 1.2)"),
        ({"profit_factor": Decimal("1.199999999")}, f"{OOS_PROFIT_FACTOR} (1.1999 < 1.2)"),
        ({"trades": 29}, f"{OOS_TRADES} (29 < 30)"),
        ({"drawdown": Decimal("0.15")}, f"{OOS_DRAWDOWN} (%15.0000 ≥ %15)"),
        ({"drawdown": Decimal("0.1499999")}, PASSED),
        ({"net": Decimal(0)}, f"{OOS_NET} (0.00000000 USDT ≤ 0)"),
        ({"net": Decimal("-0.00000001")}, f"{OOS_NET} (-0.00000001 USDT ≤ 0)"),
        ({"net": Decimal("0.00000001")}, PASSED),
    ],
)
def test_oos_threshold_boundaries(changes: dict[str, object], expected: str) -> None:
    oos = part(**changes)  # type: ignore[arg-type]
    assert verdict(oos, GOOD) == expected


def test_undefined_profit_factor_passes() -> None:
    assert verdict(part(profit_factor=None), GOOD) == PASSED


def test_first_failing_threshold_named() -> None:
    """Plan Risk 5: sıra net kâr → kâr faktörü → işlem sayısı → drawdown → saklı dönem."""
    everything = part(
        net=Decimal(-1), profit_factor=Decimal("0.5"), trades=3, drawdown=Decimal("0.5")
    )
    bad_holdout = part(net=Decimal(-1), drawdown=Decimal("0.5"))
    assert verdict(everything, bad_holdout) == f"{OOS_NET} (-1.00000000 USDT ≤ 0)"
    assert verdict(replace(everything, net=Decimal(1)), bad_holdout) == (
        f"{OOS_PROFIT_FACTOR} (0.5000 < 1.2)"
    )
    assert verdict(part(trades=3, drawdown=Decimal("0.5")), bad_holdout) == f"{OOS_TRADES} (3 < 30)"
    assert verdict(part(drawdown=Decimal("0.5")), bad_holdout) == (
        f"{OOS_DRAWDOWN} (%50.0000 ≥ %15)"
    )
    assert verdict(GOOD, bad_holdout) == f"{HOLDOUT_NET} (-1.00000000 USDT ≤ 0)"
    assert verdict(GOOD, part(drawdown=Decimal("0.5"))) == f"{HOLDOUT_DRAWDOWN} (%50.0000 ≥ %15)"
    for text in (OOS_NET, OOS_PROFIT_FACTOR, OOS_TRADES, OOS_DRAWDOWN):
        assert text.startswith("geçmedi: örneklem dışı ")
    for text in (HOLDOUT_NET, HOLDOUT_DRAWDOWN):
        assert text.startswith("geçmedi: saklı dönem ")


# --- AC-5: saklı dönem ---


def test_holdout_failures() -> None:
    assert verdict(GOOD, part(net=Decimal(0))) == f"{HOLDOUT_NET} (0.00000000 USDT ≤ 0)"
    assert verdict(GOOD, part(net=Decimal(-5))) == f"{HOLDOUT_NET} (-5.00000000 USDT ≤ 0)"
    assert verdict(GOOD, part(drawdown=Decimal("0.15"))) == (f"{HOLDOUT_DRAWDOWN} (%15.0000 ≥ %15)")
    assert verdict(GOOD, part(drawdown=Decimal("0.2"))) == (f"{HOLDOUT_DRAWDOWN} (%20.0000 ≥ %15)")


def test_holdout_trade_count_does_not_matter() -> None:
    assert verdict(GOOD, part(trades=1, profit_factor=Decimal("0.1"))) == PASSED


def test_holdout_zero_trades_zero_net_fails() -> None:
    assert verdict(GOOD, part(trades=0, profit_factor=None, net=Decimal(0))) == (
        f"{HOLDOUT_NET} (0.00000000 USDT ≤ 0)"
    )


# --- AC-6: paper adayı ---


def assessed(
    inside: Decimal | None, outside: Decimal | None, net: Decimal = Decimal(100), ok: bool = True
) -> Assessed:
    return Assessed(
        part(profit_factor=inside),
        part(profit_factor=outside, net=net),
        PASSED if ok else OOS_NET,
    )


def test_paper_candidate_rule_and_tie() -> None:
    """R-4: min(örneklem içi, örneklem dışı) en yüksek; eşitlikte örneklem dışı net kâr."""
    candidates = [
        assessed(Decimal("3"), Decimal("1.3")),  # min 1.3
        assessed(Decimal("1.6"), Decimal("1.7")),  # min 1.6  ← highest
        assessed(Decimal("1.5"), Decimal("9")),  # min 1.5
        assessed(Decimal("5"), Decimal("5"), ok=False),  # did not pass
    ]
    assert paper_candidate(candidates) == 1
    tied = [
        assessed(Decimal("2"), Decimal("1.6"), net=Decimal(50)),
        assessed(Decimal("1.6"), Decimal("2"), net=Decimal(80)),
        assessed(Decimal("1.6"), Decimal("1.6"), net=Decimal(80)),
    ]
    assert paper_candidate(tied) == 1  # equal net: the earlier one
    assert paper_candidate([assessed(Decimal("2"), Decimal("2")), assessed(None, None)]) == 1


def test_no_candidate() -> None:
    assert paper_candidate([]) is None
    assert paper_candidate([assessed(Decimal("2"), Decimal("2"), ok=False)]) is None
