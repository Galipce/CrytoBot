"""Spec 0014 AC-10: `t` konumundaki değer, `t`'den sonraki mumlardan etkilenmez (tam eşitlik)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crytobot.analysis import Candle
from tests.analysis.helpers import (
    INDICATOR_IDS,
    INDICATORS,
    Indicator,
    at,
    candle_series,
)


def retimed(candles: list[Candle], start: int) -> list[Candle]:
    """Aynı fiyatlar, `start` konumundan başlayan zamanlarla: seri geçerli kalır."""
    return [Candle(at(start + i), c.open, c.high, c.low, c.close) for i, c in enumerate(candles)]


@pytest.mark.parametrize("indicator", INDICATORS, ids=INDICATOR_IDS)
@given(
    candles=candle_series(min_size=1),
    other=candle_series(max_size=20),
    fraction=st.floats(min_value=0.0, max_value=1.0),
)
def test_past_values_ignore_future_candles(
    indicator: Indicator, candles: list[Candle], other: list[Candle], fraction: float
) -> None:
    cut = int(fraction * (len(candles) - 1))
    kept = candles[: cut + 1]
    expected = [series[: cut + 1] for series in indicator.compute(candles)]

    deleted = kept
    replaced = kept + retimed(other, cut + 1)
    appended = candles + retimed(other, len(candles))
    for variant in (deleted, replaced, appended):
        assert [series[: cut + 1] for series in indicator.compute(variant)] == expected
