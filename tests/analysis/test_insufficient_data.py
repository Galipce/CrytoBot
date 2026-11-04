"""Spec 0014 AC-7: yetersiz veri olağan bir durumdur: aynı uzunluk, "değer yok", hata değil."""

import pytest
from hypothesis import given

from crytobot.analysis import Candle
from tests.analysis.helpers import INDICATOR_IDS, INDICATORS, Indicator, candle_series, from_closes


@pytest.mark.parametrize("indicator", INDICATORS, ids=INDICATOR_IDS)
@given(candles=candle_series())
def test_result_has_input_length(indicator: Indicator, candles: list[Candle]) -> None:
    for series in indicator.compute(candles):
        assert len(series) == len(candles)


@pytest.mark.parametrize("indicator", INDICATORS, ids=INDICATOR_IDS)
def test_short_series_is_all_missing(indicator: Indicator) -> None:
    candles = from_closes(range(1, indicator.needs))
    for series in indicator.compute(candles):
        assert series == (None,) * len(candles)


@pytest.mark.parametrize("indicator", INDICATORS, ids=INDICATOR_IDS)
def test_first_value_needs_exactly_the_stated_length(indicator: Indicator) -> None:
    candles = from_closes([float(10 + i % 3) for i in range(indicator.needs)])
    assert indicator.compute(candles)[0][-1] is not None


@pytest.mark.parametrize("indicator", INDICATORS, ids=INDICATOR_IDS)
def test_empty_series_is_empty(indicator: Indicator) -> None:
    for series in indicator.compute([]):
        assert series == ()
