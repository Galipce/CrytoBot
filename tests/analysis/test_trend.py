"""Spec 0045 R-1, plan Risk 7: stochastic, ADX/DI, Supertrend, Donchian — elle hesaplı değerler."""

import pytest

from crytobot.analysis import (
    InvalidParameterError,
    adx,
    donchian,
    stochastic,
    supertrend,
)
from tests.analysis.helpers import candle, from_closes, from_hlc


def approx(values: tuple[float | None, ...]) -> list[object]:
    return [None if value is None else pytest.approx(value) for value in values]


def test_stochastic_hand_computed() -> None:
    candles = from_hlc([10, 11, 12, 12, 12], [8, 9, 10, 10, 10], [9, 10, 11, 10, 10])
    result = stochastic(candles, k=3, d=2)
    assert approx(result.k) == [None, None, 75.0, 100 / 3, 0.0]
    assert approx(result.d) == [None, None, None, (75 + 100 / 3) / 2, (100 / 3) / 2]


def test_stochastic_flat_window_has_no_value() -> None:
    result = stochastic(from_closes([10.0] * 5), k=3, d=2)
    assert result.k == (None,) * 5
    assert result.d == (None,) * 5


def test_adx_hand_computed() -> None:
    candles = from_hlc(
        [10, 11, 12, 11.5, 11],
        [9, 9.5, 10, 9, 9.5],
        [9.5, 10.5, 11.5, 9.5, 10.5],
    )
    result = adx(candles, period=2)
    assert approx(result.plus_di) == [None, None, 100 / 1.75, 50 / 2.125, 25 / 1.8125]
    assert approx(result.minus_di) == [None, None, 0.0, 50 / 2.125, 25 / 1.8125]
    assert approx(result.adx) == [None, None, None, 50.0, 25.0]


def test_adx_flat_series_is_zero_not_missing() -> None:
    result = adx(from_closes([10.0] * 6), period=2)
    assert result.plus_di[2:] == (0.0,) * 4
    assert result.adx[3:] == (0.0,) * 3


def test_supertrend_hand_computed() -> None:
    candles = from_hlc([10, 12, 11, 9], [8, 10, 9, 7], [9, 11.5, 9.5, 7.5])
    result = supertrend(candles, period=1, multiplier=1)
    assert result.up == (False, True, True, False)
    assert approx(result.line) == [11.0, 8.0, 8.0, 10.5]


def test_supertrend_warmup_has_no_direction() -> None:
    candles = from_hlc([10, 12, 11, 9], [8, 10, 9, 7], [9, 11.5, 9.5, 7.5])
    result = supertrend(candles, period=3, multiplier=2)
    assert result.up[:2] == (None, None)
    assert result.up[2] is False  # the first ATR position starts down


def test_donchian_uses_the_previous_candles_only() -> None:
    candles = from_hlc([10, 12, 11, 13], [8, 9, 7, 10], [9, 11, 8, 12])
    result = donchian(candles, period=2)
    assert result.upper == (None, None, 12, 12)
    assert result.lower == (None, None, 8, 7)


@pytest.mark.parametrize(
    "call",
    [
        lambda c: stochastic(c, k=0, d=3),
        lambda c: stochastic(c, k=3, d=True),
        lambda c: adx(c, period=0),
        lambda c: supertrend(c, period=2, multiplier=0),
        lambda c: supertrend(c, period=1.5, multiplier=2),  # type: ignore[arg-type]
        lambda c: donchian(c, period=-1),
    ],
)
def test_invalid_parameters_are_refused(call: object) -> None:
    candles = from_closes([1.0, 2.0, 3.0])
    with pytest.raises(InvalidParameterError):
        call(candles)  # type: ignore[operator]


def test_later_candle_never_changes_earlier_values() -> None:
    """Look-ahead yok: son mumu değiştirmek önceki konumları değiştirmez."""
    base = from_hlc(
        [10, 11, 12, 11.5, 11, 12, 13, 12.5],
        [9, 9.5, 10, 9, 9.5, 10, 11, 11],
        [9.5, 10.5, 11.5, 9.5, 10.5, 11.5, 12, 11.5],
    )
    changed = [*base[:-1], candle(7, 30, 40, 20, 35)]
    pairs = [
        (stochastic(base, k=3, d=2).d, stochastic(changed, k=3, d=2).d),
        (adx(base, period=2).adx, adx(changed, period=2).adx),
        (
            supertrend(base, period=2, multiplier=1).up,
            supertrend(changed, period=2, multiplier=1).up,
        ),
        (donchian(base, period=3).upper, donchian(changed, period=3).upper),
    ]
    for before, after in pairs:
        assert before[:-1] == after[:-1]
