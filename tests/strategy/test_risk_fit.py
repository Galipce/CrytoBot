"""Spec 0015 AC-9: gerçekçi fiyatlı öneri `approve_trade`'den biçim nedeniyle dönmez (BR-3).

`INSUFFICIENT_EDGE`, `BELOW_MINIMUM` serbesttir: spec biçim uyumunu sorar, onayı değil. Her ölçeğin
tick'i, o ölçekte olağan bir tick'tir; `k`, `r` öneri çıkaran aralıktadır (plan 0015, Risk 9).
"""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    AccountState,
    ApprovalReason,
    PairRules,
    TradeIntent,
    approve_trade,
    observe,
)
from crytobot.strategy import propose
from tests.analysis.helpers import from_closes
from tests.strategy.helpers import CROSS, PAIR, candidate_scenarios, make_settings

NOW = datetime(2024, 1, 1, tzinfo=UTC)
EQUITY = Decimal(10000)
FORMAT_REASONS = {
    ApprovalReason.NOT_BUY,
    ApprovalReason.INVALID_ENTRY,
    ApprovalReason.INVALID_STOP,
    ApprovalReason.INVALID_TARGET,
    ApprovalReason.INVALID_INPUT,
}
SCALES = st.sampled_from(
    [
        (1e-6, Decimal("0.00000001")),
        (0.01, Decimal("0.00001")),
        (1.0, Decimal("0.01")),
        (10000.0, Decimal("0.01")),
    ]
)
STOP_MULTIPLES = st.decimals(min_value=Decimal(1), max_value=Decimal(4), places=2)
TARGET_MULTIPLES = st.decimals(min_value=Decimal(1), max_value=Decimal(5), places=2)


def proposal(scale: float, tick: Decimal, k: Decimal, r: Decimal) -> TradeIntent:
    result = propose(
        pair=PAIR,
        candles=from_closes(tuple(close * scale for close in CROSS)),
        position_open=False,
        tick=tick,
        settings=make_settings(k=k, r=r),
    )
    assert isinstance(result, TradeIntent)
    return result


@given(scale_and_tick=SCALES, k=STOP_MULTIPLES, r=TARGET_MULTIPLES)
def test_proposal_has_no_format_rejection(
    scale_and_tick: tuple[float, Decimal], k: Decimal, r: Decimal
) -> None:
    update = observe(EMPTY_STATE, NOW, EQUITY, DEFAULT_LIMITS)
    assert update.accepted
    decision = approve_trade(
        proposal(*scale_and_tick, k, r),
        DEFAULT_LIMITS,
        AccountState(EQUITY, EQUITY, 0),
        PairRules(Decimal("0.00001"), Decimal("0.00001"), Decimal(5)),
        {PAIR},
        Decimal("0.001"),
        Decimal("0.0005"),
        Decimal("0.0005"),
        update.state,
        NOW,
    )
    assert decision.reason not in FORMAT_REASONS


@given(scale_and_tick=SCALES, k=STOP_MULTIPLES, r=TARGET_MULTIPLES)
def test_every_proposal_is_buy_with_stop(
    scale_and_tick: tuple[float, Decimal], k: Decimal, r: Decimal
) -> None:
    """BR-3: stop'suz öneri yoktur."""
    intent = proposal(*scale_and_tick, k, r)
    assert intent.side == "buy"
    assert isinstance(intent.stop, Decimal)
    assert isinstance(intent.target, Decimal)


@given(scale_and_tick=SCALES, k=st.sampled_from([Decimal("1.5"), Decimal(2), Decimal(3)]))
def test_candidates_fit_risk(scale_and_tick: tuple[float, Decimal], k: Decimal) -> None:
    """Spec 0043 AC-6: S0…S3'ün alım önerisi `risk` onayından biçim nedeniyle dönmez; R-3'ün
    `k` değerleri ve `r = 2` ile."""
    scale, tick = scale_and_tick
    update = observe(EMPTY_STATE, NOW, EQUITY, DEFAULT_LIMITS)
    assert update.accepted
    for base, candles in candidate_scenarios(scale):
        settings = replace(base, k=k, r=Decimal(2))
        result = propose(
            pair=PAIR, candles=candles, position_open=False, tick=tick, settings=settings
        )
        assert isinstance(result, TradeIntent), type(settings).__name__
        decision = approve_trade(
            result,
            DEFAULT_LIMITS,
            AccountState(EQUITY, EQUITY, 0),
            PairRules(Decimal("0.00001"), Decimal("0.00001"), Decimal(5)),
            {PAIR},
            Decimal("0.001"),
            Decimal("0.0005"),
            Decimal("0.0005"),
            update.state,
            NOW,
        )
        assert decision.reason not in FORMAT_REASONS, type(settings).__name__
