"""Spec 0014 AC-1…AC-6: küçük serilerde elle hesaplanmış değerlere `1e-9` toleransla eşitlik."""

import math
from collections.abc import Sequence

import pytest
from hypothesis import given
from pytest import approx

from crytobot.analysis import Candle, atr, bollinger, ema, macd, rsi, sma
from tests.analysis.helpers import candle_series, from_closes, from_hlc


def assert_close(actual: Sequence[float | None], expected: Sequence[float | None]) -> None:
    assert len(actual) == len(expected)
    for value, wanted in zip(actual, expected, strict=True):
        if wanted is None:
            assert value is None
        else:
            assert value == approx(wanted, rel=0, abs=1e-9)


def test_sma_hand_computed() -> None:
    # (2+4+6)/3, (4+6+5)/3, (6+5+9)/3; ilk değer n-1 = 2 konumunda
    result = sma(from_closes([2, 4, 6, 5, 9]), period=3)
    assert_close(result, [None, None, 4, 5, 20 / 3])


def test_ema_hand_computed() -> None:
    # Çarpan 2/(3+1) = 0.5; ilk değer SMA = 4; 4 + 0.5*(5-4) = 4.5; 4.5 + 0.5*(9-4.5) = 6.75
    result = ema(from_closes([2, 4, 6, 5, 9]), period=3)
    assert_close(result, [None, None, 4, 4.5, 6.75])


def test_rsi_hand_computed() -> None:
    # Değişimler +1, -0.5, +1.5, -1; ilk değer n = 2 konumunda.
    # Kazanç/kayıp: (0.5, 0.25) -> RS 2; (1, 0.125) -> RS 8; (0.5, 0.5625) -> RS 8/9
    result = rsi(from_closes([10, 11, 10.5, 12, 11]), period=2)
    assert_close(result, [None, None, 200 / 3, 800 / 9, 800 / 17])


def test_rsi_flat_market_has_no_value() -> None:
    assert rsi(from_closes([5.0] * 6), period=3) == (None,) * 6


def test_rsi_flat_start_gets_a_value_with_the_first_move_and_keeps_it() -> None:
    """Plan 0014, Risk 9: `None` seri ortasında da görünür; hareketten sonraki düz dönemde sürer."""
    result = rsi(from_closes([5.0, 5.0, 5.0, 5.0, 6.0, 6.0, 6.0]), period=2)
    assert result == (None, None, None, None, 100.0, 100.0, 100.0)


def test_rsi_only_gains_is_100() -> None:
    assert rsi(from_closes([1, 2, 3, 4, 5, 6]), period=3)[3:] == (100.0, 100.0, 100.0)


def test_rsi_only_losses_is_0() -> None:
    assert rsi(from_closes([6, 5, 4, 3, 2, 1]), period=3)[3:] == (0.0, 0.0, 0.0)


@given(candles=candle_series())
def test_rsi_stays_between_0_and_100(candles: list[Candle]) -> None:
    for period in (1, 2, 5):
        for value in rsi(candles, period=period):
            assert value is None or 0.0 <= value <= 100.0


def test_atr_hand_computed() -> None:
    # Gerçek aralıklar 3, 2, 3, 2.5, 0.5. İlk mumda `high − low` = 10 - 7.  # noqa: RUF003
    # Sonrakiler önceki kapanışı hesaba katar: üçüncü mumda |13 - 10| = 3 > 13 - 12, dördüncüde
    # |10 - 12.5| = 2.5 > 12 - 10.
    # (3+2)/2 = 2.5; (2.5+3)/2 = 2.75; (2.75+2.5)/2 = 2.625; (2.625+0.5)/2 = 1.5625
    candles = from_hlc([10, 11, 13, 12, 11.5], [7, 9, 12, 10, 11], [9, 10, 12.5, 11, 11.2])
    assert_close(atr(candles, period=2), [None, 2.5, 2.75, 2.625, 1.5625])


@given(candles=candle_series())
def test_atr_never_negative(candles: list[Candle]) -> None:
    for period in (1, 2, 5):
        for value in atr(candles, period=period):
            assert value is None or value >= 0.0


def test_macd_hand_computed() -> None:
    # Hızlı 2 (çarpan 2/3), yavaş 3 (çarpan 1/2), sinyal 2 (çarpan 2/3).
    # Hızlı EMA: 3/2, 19/6, 103/18, 499/54, 2227/162; yavaş EMA: 7/3, 14/3, 47/6, 143/12
    # Çizgi: 5/6, 19/18, 38/27, 593/324; sinyal: (5/6 + 19/18)/2 = 17/18, 203/162, 398/243
    result = macd(from_closes([1, 2, 4, 7, 11, 16]), fast=2, slow=3, signal=2)
    assert_close(result.macd, [None, None, 5 / 6, 19 / 18, 38 / 27, 593 / 324])
    assert_close(result.signal, [None, None, None, 17 / 18, 203 / 162, 398 / 243])
    assert_close(result.histogram, [None, None, None, 1 / 9, 25 / 162, 187 / 972])


@pytest.mark.parametrize(
    ("fast", "slow", "signal"), [(12, 26, 9), (2, 3, 2), (1, 2, 1), (3, 10, 4)]
)
def test_macd_start_positions(fast: int, slow: int, signal: int) -> None:
    closes = [100.0 + (i % 7) for i in range(slow + signal + 5)]
    result = macd(from_closes(closes), fast=fast, slow=slow, signal=signal)
    assert result.macd[slow - 2] is None
    assert result.macd[slow - 1] is not None
    assert result.signal[slow + signal - 3] is None
    assert result.signal[slow + signal - 2] is not None
    assert result.histogram[slow + signal - 3] is None
    assert result.histogram[slow + signal - 2] is not None


@given(candles=candle_series(max_size=40))
def test_macd_histogram_is_line_minus_signal(candles: list[Candle]) -> None:
    result = macd(candles, fast=2, slow=4, signal=3)
    for line, signal, histogram in zip(result.macd, result.signal, result.histogram, strict=True):
        if signal is None:
            assert histogram is None
        else:
            assert line is not None
            assert histogram == line - signal


def test_macd_signal_period_longer_than_the_line_has_no_signal() -> None:
    result = macd(from_closes([1, 2, 3, 4, 5]), fast=2, slow=3, signal=10)
    assert result.macd[2:] != (None, None, None)
    assert result.signal == (None,) * 5
    assert result.histogram == (None,) * 5


def test_bollinger_hand_computed() -> None:
    # Pencere 2, 4, 6: orta 4, varyans 8/3 (popülasyon; örneklem olsaydı 4).
    # Pencere 4, 6, 3: orta 13/3, varyans 14/9.
    result = bollinger(from_closes([2, 4, 6, 3]), period=3, k=2)
    first = math.sqrt(8 / 3)
    second = math.sqrt(14 / 9)
    assert_close(result.middle, [None, None, 4, 13 / 3])
    assert_close(result.upper, [None, None, 4 + 2 * first, 13 / 3 + 2 * second])
    assert_close(result.lower, [None, None, 4 - 2 * first, 13 / 3 - 2 * second])


@pytest.mark.parametrize("close", [0.1, 1.0, 44.3389, 1e-300])
def test_bollinger_flat_closes_collapse_bands(close: float) -> None:
    result = bollinger(from_closes([close] * 5), period=3, k=2.5)
    assert result.upper == result.middle
    assert result.lower == result.middle
    assert result.middle[2:] != (None, None, None)


def test_bollinger_lower_band_may_be_negative() -> None:
    result = bollinger(from_closes([1, 1000, 1]), period=3, k=3)
    lower = result.lower[2]
    assert lower is not None
    assert lower < 0


def test_sma_does_not_keep_a_running_sum() -> None:
    """Plan 0014, Risk 7: kayan toplamda `1e300 + 1 - 1e300 = 0` olur, küçük değerler kaybolur."""
    assert sma(from_closes([1e300, 1.0, 1.0, 1.0]), period=2) == (None, 5e299, 1.0, 1.0)
