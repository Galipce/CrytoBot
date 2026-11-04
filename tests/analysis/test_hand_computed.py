"""Spec 0014 AC-1…AC-6: küçük serilerde elle hesaplanmış değerlere `1e-9` toleransla eşitlik."""

from collections.abc import Sequence

from pytest import approx

from crytobot.analysis import ema, sma
from tests.analysis.helpers import from_closes


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
