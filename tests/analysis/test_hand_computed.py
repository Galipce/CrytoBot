"""Spec 0014 AC-1…AC-6: küçük serilerde elle hesaplanmış değerlere `1e-9` toleransla eşitlik."""

from collections.abc import Sequence

from hypothesis import given
from pytest import approx

from crytobot.analysis import Candle, atr, ema, rsi, sma
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
