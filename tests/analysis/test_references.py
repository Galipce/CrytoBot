"""Spec 0014 AC-1…AC-6: indikatörler yayımlanmış tablolarla aynıdır (kaynaklar `references.py`'de).

Plan 0014, Risk 4: her test iki şeyi birden arar. Tablo `0.00` gösteriyorsa 2 basamağa yuvarlanınca
eşitlik (spec'in tanımı); tüm kaynaklarda saklı hücreye `1e-9` toleransla eşitlik.
"""

from collections.abc import Sequence

from crytobot.analysis import atr, ema, rsi, sma
from tests.analysis import references as ref
from tests.analysis.helpers import from_closes, from_hlc

TOLERANCE = 1e-9


def assert_matches(
    actual: Sequence[float | None], published: Sequence[float | None], *, places: int | None = None
) -> None:
    assert len(actual) == len(published)
    for position, (value, expected) in enumerate(zip(actual, published, strict=True)):
        if expected is None:
            assert value is None, position
            continue
        assert value is not None, position
        assert abs(value - expected) <= TOLERANCE, position
        if places is not None:
            assert round(value, places) == round(expected, places), position


def first_value(series: Sequence[float | None]) -> int:
    return next(i for i, value in enumerate(series) if value is not None)


def test_sma_matches_published_series() -> None:
    result = sma(from_closes(ref.MOVAVG_CLOSES), period=10)
    assert_matches(result, ref.SMA_10, places=2)
    assert first_value(result) == 9


def test_ema_matches_published_series() -> None:
    result = ema(from_closes(ref.MOVAVG_CLOSES), period=10)
    assert_matches(result, ref.EMA_10, places=2)
    assert first_value(result) == 9


def test_rsi_matches_published_series() -> None:
    result = rsi(from_closes(ref.RSI_CLOSES), period=14)
    assert_matches(result, ref.RSI_14, places=2)
    assert first_value(result) == 14


def test_atr_matches_published_series() -> None:
    result = atr(from_hlc(ref.ATR_HIGHS, ref.ATR_LOWS, ref.ATR_CLOSES), period=14)
    assert_matches(result, ref.ATR_14, places=2)
    assert first_value(result) == 13
