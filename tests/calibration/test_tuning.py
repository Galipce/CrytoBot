"""Spec 0045 AC-5, AC-6, AC-8: seçim, dayanıklılık, çapraz sınama, hüküm (R-4, R-5, R-7; Risk 9)."""

from dataclasses import replace

from crytobot.analysis import Candle
from crytobot.calibration import (
    INDICATORS,
    PAIRS,
    Choice,
    Count,
    CrossTest,
    IntervalData,
    PairSeries,
    Robustness,
    Tally,
    cross_test,
    grid,
    robustness,
    select,
    stage_one,
    verdict,
)
from tests.calibration.helpers import CROSS, NO_COSTS, TUNE, UNSEEN, oscillating, small_data

SPECS = {spec.name: spec for spec in INDICATORS}
RSI = SPECS["RSI"]
DONCHIAN = SPECS["Donchian"]


def counts(**chosen: Count) -> dict[tuple[int | float, ...], Count]:
    """Donchian ızgarası (10, 20, 30, 55, 100): `n<değer>=Count`, verilmeyen 0 sinyal."""
    found = {setting: Count(0, 0) for setting in grid(DONCHIAN)}
    for key, value in chosen.items():
        found[(int(key[1:]),)] = value
    return found


def test_highest_rate_tie_first_in_grid() -> None:
    found = counts(n20=Count(40, 20), n30=Count(50, 30), n55=Count(60, 36))
    assert select(DONCHIAN, found).setting == (30,)  # 0.6 == 0.6: the earlier one
    found = counts(n20=Count(40, 20), n55=Count(60, 37))
    assert select(DONCHIAN, found).setting == (55,)


def test_29_signals_not_selectable() -> None:
    found = counts(n10=Count(29, 29), n20=Count(30, 1))
    assert select(DONCHIAN, found).setting == (20,)


def test_no_setting_reason_written() -> None:
    found = counts(n10=Count(29, 29), n100=Count(3, 1))
    chosen = select(DONCHIAN, found)
    assert chosen.setting is None
    assert chosen.reason == "ayar yok: hiçbir ayar 30 sinyale ulaşmadı (en çok 29)"


def test_fragile_below_half_not_at_half() -> None:
    """Komşuların yarısından azı taban oranı geçerse dayanıksız; tam yarısı geçerse değil."""
    base = Count(100, 40)  # 40%
    good, bad = Count(30, 15), Count(30, 12)  # 50% passes, 40% does not (strictly greater)
    rsi_counts = {setting: bad for setting in grid(RSI)}
    # (14, 30): neighbours (10,30), (21,30), (14,25), (14,35)
    rsi_counts[(10, 30)] = good
    rsi_counts[(21, 30)] = good
    at_half = robustness(RSI, (14, 30), rsi_counts, base)
    assert (at_half.passing, at_half.total, at_half.fragile) == (2, 4, False)
    rsi_counts[(21, 30)] = Count(0, 0)  # no signals: does not pass
    below = robustness(RSI, (14, 30), rsi_counts, base)
    assert (below.passing, below.fragile) == (1, True)


def test_three_of_four_passes_two_fails() -> None:
    base = Count(100, 50)
    above, equal, empty = Count(40, 21), Count(40, 20), Count(0, 0)
    assert not cross_test([(above, base), (above, base), (above, base), (equal, base)]).failed
    two = cross_test([(above, base), (above, base), (equal, base), (empty, base)])
    assert (two.passing, two.total, two.failed) == (2, 4, True)


def data(changes: dict[str, PairSeries] | None = None) -> list[IntervalData]:
    series = dict(small_data()[0].series)
    series.update(changes or {})
    return [IntervalData("1h", series)]


def _later(series: PairSeries, after: int) -> PairSeries:
    """`after` konumundan sonraki mumların fiyatını iki katına çıkarır."""
    candles = tuple(
        candle
        if index < after
        else Candle(
            candle.open_time, candle.open * 2, candle.high * 2, candle.low * 2, candle.close * 2
        )
        for index, candle in enumerate(series.candles)
    )
    return replace(series, candles=candles)


def test_tuning_uses_btc_tuning_period_only() -> None:
    """AC-5: ayarlama yalnız BTC'nin ayarlama dönemini kullanır: diğer çiftler ve dönem sonrası
    değişse de seçim aynıdır; çapraz sınama ise diğer çiftleri görür."""
    periods = (TUNE, CROSS, UNSEEN)
    first = stage_one(data(), NO_COSTS, periods_of=periods)
    base = data()[0].series
    other = {pair: oscillating(seed + 50, pair=pair) for seed, pair in enumerate(PAIRS[1:])}
    other[PAIRS[0]] = _later(base[PAIRS[0]], 330)  # after the tuning windows end
    second = stage_one(data(other), NO_COSTS, periods_of=periods)
    assert [(c.indicator, c.setting, c.reason, c.fragile) for c in first.choices] == [
        (c.indicator, c.setting, c.reason, c.fragile) for c in second.choices
    ]
    tuned = {m.pair for m in first.measurements if m.period == TUNE.name}
    assert tuned == {PAIRS[0]}
    assert {m.period for m in first.measurements} == {TUNE.name, CROSS.name}
    assert any(c.setting is not None for c in first.choices)


def test_cross_test_keeps_settings() -> None:
    """AC-6: çapraz sınama ayarı değiştirmez: ölçülen ayar seçilen ayardır."""
    measured = stage_one(data(), NO_COSTS, periods_of=(TUNE, CROSS, UNSEEN))
    for choice in measured.choices:
        spec = SPECS[choice.indicator]
        cross_settings = {
            m.setting
            for m in measured.measurements
            if m.indicator == choice.indicator and m.period == CROSS.name
        }
        expected = {spec.default} | ({choice.setting} if choice.setting else set())
        assert cross_settings == expected
        if choice.setting is not None:
            assert choice.cross is not None and choice.cross.total == 4
            assert choice.cross_failed == (choice.cross.passing < 3)


def tally(signals: int, hits: int, clean: tuple[int, int] | None = None) -> Tally:
    clean_signals, clean_hits = clean or (signals, hits)
    return Tally(Count(signals, hits), Count(clean_signals, clean_hits), 0)


CHOSEN = Choice("RSI", "1h", (14, 30), None, False, False, Robustness(4, 4), CrossTest(4, 4))


def test_exactly_5_points_usable() -> None:
    """AC-8: taban oranı tam 5 puan geçen "kullanılabilir"dir (Fraction ile kesin)."""
    result = verdict(CHOSEN, tally(100, 45), tally(1000, 400))
    assert result.usable and result.failures == ()


def test_verdict_conditions_each_failing_line() -> None:
    """AC-8: tutmayan her koşul değeri ve eşiğiyle yazılır."""
    low = verdict(CHOSEN, tally(100, 43), tally(1000, 398))
    assert low.failures == ("geçmedi: isabet taban oranı 5 puan geçmiyor (+3.20 < +5)",)
    few = verdict(CHOSEN, tally(29, 29), tally(1000, 400))
    assert few.failures == ("geçmedi: sinyal sayısı 30'dan az (29 < 30)",)
    dirty = verdict(CHOSEN, tally(100, 50, (40, 10)), tally(1000, 400, (800, 300)))
    assert dirty.failures == (
        "geçmedi: olağandışısız isabet taban oranın altında (25.00% < 37.50%)",
    )
    no_clean = verdict(CHOSEN, tally(100, 50, (0, 0)), tally(1000, 400, (800, 300)))
    assert no_clean.failures == (
        "geçmedi: olağandışısız isabet taban oranın altında (olağandışısız sinyal yok)",
    )
    flagged = replace(
        CHOSEN, fragile=True, cross_failed=True, neighbours=Robustness(1, 4), cross=CrossTest(2, 4)
    )
    assert verdict(flagged, tally(100, 50), tally(1000, 400)).failures == (
        "geçmedi: ayar dayanıksız (taban oranı geçen komşu 1/4 < yarısı)",
        "geçmedi: çapraz sınamada geçmedi (2/4 çift < 3)",
    )
    none = Choice("RSI", "1h", None, "ayar yok: x", False, False)
    assert verdict(none, tally(0, 0), tally(1000, 400)).failures == (
        "geçmedi: ayar seçilmedi (ayar yok: x)",
    )
    assert not verdict(none, tally(0, 0), tally(1000, 400)).usable
