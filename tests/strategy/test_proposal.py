"""Spec 0015 AC-1…AC-5: öneri koşulu, kesişim ve RSI sınırları, yetersiz geçmiş, neden sırası."""

from decimal import Decimal
from typing import Any

import pytest

from crytobot.risk import TradeIntent
from crytobot.strategy import NoProposal, NoProposalReason
from tests.strategy.helpers import CROSS, CROSS_FROM_EQUAL, PAIR, run

FLAT_CROSS = (*[60.0] * 8, 30.0, 60.0, 60.0)
FLAT_CROSS_SETTINGS: dict[str, Any] = {"fast_period": 2, "slow_period": 5, "rsi_period": 1}


def reason(reason_value: NoProposalReason) -> NoProposal:
    return NoProposal(reason_value)


def test_crossover_below_threshold_gives_hand_computed_proposal() -> None:
    assert run() == TradeIntent(PAIR, "buy", Decimal(10), Decimal(8), Decimal(14))
    # ATR 1.125, k * ATR = 2.25: stop 7.75, hedef 10 + 3 * 2.25 = 16.75
    assert run(CROSS, r=3, tick=Decimal("0.01")) == TradeIntent(
        PAIR, "buy", Decimal(10), Decimal("7.75"), Decimal("16.75")
    )


def test_crossover_from_equal_emas_gives_proposal() -> None:
    assert isinstance(run(CROSS_FROM_EQUAL), TradeIntent)


def test_equal_emas_on_last_candle_is_no_crossover() -> None:
    assert run((10.0, 8.0, 9.0)) == reason(NoProposalReason.NO_CROSSOVER)


def test_fast_already_above_is_no_crossover() -> None:
    assert run((8.0, 10.0, 11.0)) == reason(NoProposalReason.NO_CROSSOVER)


def test_downward_cross_is_no_crossover() -> None:
    assert run((8.0, 10.0, 8.0)) == reason(NoProposalReason.NO_CROSSOVER)


def test_no_repeat_on_the_candle_after_crossover() -> None:
    assert isinstance(run(CROSS_FROM_EQUAL), TradeIntent)
    assert run((*CROSS_FROM_EQUAL, 11.0)) == reason(NoProposalReason.NO_CROSSOVER)


def test_rsi_below_threshold_gives_proposal() -> None:
    assert isinstance(run(rsi_threshold=Decimal("60.0000001")), TradeIntent)
    assert isinstance(run(rsi_threshold=70), TradeIntent)


@pytest.mark.parametrize("threshold", [60, Decimal(60), Decimal("60.000")])
def test_rsi_equal_to_threshold_is_too_high(threshold: Any) -> None:
    assert run(rsi_threshold=threshold) == reason(NoProposalReason.RSI_TOO_HIGH)


def test_rsi_above_threshold_is_too_high() -> None:
    assert run(rsi_threshold=50) == reason(NoProposalReason.RSI_TOO_HIGH)


def test_rsi_without_history_is_missing() -> None:
    assert run(rsi_period=50) == reason(NoProposalReason.RSI_MISSING)


def test_flat_market_rsi_is_missing() -> None:
    """Kapanış düzken yukarı kesişim: RSI 1'de iki ortalama da sıfır, "değer yok" olur."""
    assert run(FLAT_CROSS, **FLAT_CROSS_SETTINGS) == reason(NoProposalReason.RSI_MISSING)


def test_empty_series_is_insufficient_history() -> None:
    assert run(()) == reason(NoProposalReason.INSUFFICIENT_HISTORY)


def test_one_candle_short_is_insufficient_history() -> None:
    """Kesişim için `slow + 1` mum gerekir: önceki mumun yavaş EMA'sı `slow - 1` konumundadır."""
    assert run((10.0,)) == reason(NoProposalReason.INSUFFICIENT_HISTORY)
    assert run((10.0, 8.0)) == reason(NoProposalReason.INSUFFICIENT_HISTORY)
    closes = (9.0, 9.0, 9.0, 9.0, 9.0)
    assert run(closes, fast_period=2, slow_period=5) == reason(
        NoProposalReason.INSUFFICIENT_HISTORY
    )


def test_required_length_is_not_insufficient_history() -> None:
    assert run((10.0, 8.0, 9.0)) == reason(NoProposalReason.NO_CROSSOVER)
    closes = (9.0, 9.0, 9.0, 9.0, 9.0, 9.0)
    assert run(closes, fast_period=2, slow_period=5) == reason(NoProposalReason.NO_CROSSOVER)


def test_huge_period_is_insufficient_history() -> None:
    assert run(slow_period=10**5000) == reason(NoProposalReason.INSUFFICIENT_HISTORY)


def test_atr_without_history_is_missing() -> None:
    assert run(atr_period=50) == reason(NoProposalReason.ATR_MISSING)


def test_open_position_wins_over_valid_signal() -> None:
    assert isinstance(run(), TradeIntent)
    assert run(position_open=True) == reason(NoProposalReason.POSITION_OPEN)


@pytest.mark.parametrize(
    ("closes", "arguments", "expected"),
    [
        ((), {"position_open": True}, NoProposalReason.POSITION_OPEN),
        ((10.0, 8.0), {"rsi_period": 50, "atr_period": 50}, NoProposalReason.INSUFFICIENT_HISTORY),
        ((10.0, 8.0, 9.0), {"rsi_period": 50}, NoProposalReason.NO_CROSSOVER),
        ((10.0, 8.0, 9.0), {"rsi_threshold": 1}, NoProposalReason.NO_CROSSOVER),
        (CROSS_FROM_EQUAL, {"rsi_period": 50, "atr_period": 50}, NoProposalReason.RSI_MISSING),
        (CROSS_FROM_EQUAL, {"rsi_threshold": 60, "atr_period": 50}, NoProposalReason.RSI_TOO_HIGH),
        (CROSS_FROM_EQUAL, {"rsi_threshold": 60, "k": 100}, NoProposalReason.RSI_TOO_HIGH),
        (CROSS_FROM_EQUAL, {"atr_period": 50, "k": 100}, NoProposalReason.ATR_MISSING),
    ],
)
def test_first_reason_wins(
    closes: tuple[float, ...], arguments: dict[str, Any], expected: NoProposalReason
) -> None:
    assert run(closes, **arguments) == reason(expected)
