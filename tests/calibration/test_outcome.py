"""Spec 0045 AC-1, AC-3: isabet kuralı (Q-1), taban oran (Q-3), "sat" kuralı (R-9).

Bütün mumlar düzdür (açılış 100, boy 2): ATR(14) tam 2'dir. Sinyal mumu 20; giriş 21'in açılışı
(100), hedef 100 + max(2·2, maliyet) = 104, stop 98; pencere 21…44.
"""

from decimal import Decimal

from crytobot.calibration import Costs, Direction, outcomes, tally
from tests.calibration.helpers import NO_COSTS, flat_series, period

SIGNAL = 20
LAST = SIGNAL + 24  # the 24th window candle


def hit_at(index: int, prices: tuple[float, float, float, float], count: int = 60) -> bool | None:
    series = flat_series(count, {index: prices})
    return outcomes(series, NO_COSTS, [""] * len(series.candles)).buy[SIGNAL]


def test_target_on_24th_candle_hits() -> None:
    assert hit_at(LAST, (100, 104, 99, 100)) is True


def test_target_on_25th_candle_misses() -> None:
    assert hit_at(LAST + 1, (100, 104, 99, 100)) is False


def test_stop_first_misses() -> None:
    series = flat_series(60, {30: (100, 101, 98, 100), 31: (100, 105, 99, 100)})
    assert outcomes(series, NO_COSTS, [""] * 60).buy[SIGNAL] is False


def test_both_bounds_same_candle_misses() -> None:
    assert hit_at(30, (100, 104, 98, 100)) is False


def test_cost_distance_when_atr_small() -> None:
    """Risk 4: d = 100·(2·0.02 + 0.01)/0.98 = 5.102 > 2·ATR = 4: hedef 105.102."""
    costs = Costs(Decimal("0.01"), Decimal("0.01"), Decimal("0.01"))
    below = flat_series(60, {30: (100, 105, 99, 100)})
    above = flat_series(60, {30: (100, 105.2, 99, 100)})
    assert outcomes(below, costs, [""] * 60).buy[SIGNAL] is False
    assert outcomes(above, costs, [""] * 60).buy[SIGNAL] is True
    # without costs the 2·ATR target (104) is the bound
    assert outcomes(below, NO_COSTS, [""] * 60).buy[SIGNAL] is True


def test_window_past_period_end_not_counted() -> None:
    """K-3: 24. mumun açılışı dönem bitişine eşitse sinyal sayılmaz; bitişten önceyse sayılır."""
    series = flat_series(60, {LAST: (100, 104, 99, 100)})
    results = outcomes(series, NO_COSTS, [""] * 60)
    assert tally(results, period(0, LAST), Direction.BUY, [SIGNAL]).all.signals == 0
    counted = tally(results, period(0, LAST + 1), Direction.BUY, [SIGNAL])
    assert (counted.all.signals, counted.all.hits) == (1, 1)


def test_gap_skipped_window_is_24_present() -> None:
    """K-10: eksik mum atlanır, pencere 24 mevcut mumdur; sinyal boşluklu sayılır."""
    series = flat_series(60, {LAST + 1: (100, 104, 99, 100)}, missing=(30,))
    results = outcomes(series, NO_COSTS, [""] * len(series.candles))
    assert results.buy[SIGNAL] is True  # the 25th hour is the 24th present candle
    assert results.gapped[SIGNAL] is True
    assert results.gapped[0] is False
    found = tally(results, period(0, 59), Direction.BUY, [SIGNAL])
    assert (found.all.signals, found.all.hits, found.gapped) == (1, 1, 1)


def test_overlapping_signals_counted_separately() -> None:
    """K-2: birinin penceresinde gelen sinyal ayrı sayılır."""
    series = flat_series(60, {30: (100, 104, 99, 100)})
    results = outcomes(series, NO_COSTS, [""] * 60)
    found = tally(results, period(0, 59), Direction.BUY, [SIGNAL, SIGNAL + 1])
    assert (found.all.signals, found.all.hits) == (2, 2)


def test_sell_rule_mirrors_buy() -> None:
    """R-9, Risk 6: hedef giriş - 4, stop giriş + 2; aynı kural ters yönde."""
    down = flat_series(60, {LAST: (100, 101, 96, 100)})
    results = outcomes(down, NO_COSTS, [""] * 60)
    assert results.sell[SIGNAL] is True and results.buy[SIGNAL] is False
    late = flat_series(60, {LAST + 1: (100, 101, 96, 100)})
    assert outcomes(late, NO_COSTS, [""] * 60).sell[SIGNAL] is False
    stopped = flat_series(60, {30: (100, 102, 99, 100), 31: (100, 101, 95, 100)})
    assert outcomes(stopped, NO_COSTS, [""] * 60).sell[SIGNAL] is False
    both = flat_series(60, {30: (100, 102, 96, 100)})
    assert outcomes(both, NO_COSTS, [""] * 60).sell[SIGNAL] is False


def test_no_outcome_without_atr_or_window() -> None:
    results = outcomes(flat_series(60), NO_COSTS, [""] * 60)
    assert results.buy[12] is None  # ATR(14) starts at 13
    assert results.buy[13] is False
    assert results.buy[60 - 25] is False and results.buy[60 - 24] is None


def test_base_rate_every_candle_same_rule() -> None:
    """AC-3, Risk 5: taban oran dönemin her mumu sinyal sayılarak aynı kuralla."""
    series = flat_series(80, {50: (100, 104, 99, 100)})
    results = outcomes(series, NO_COSTS, [""] * 80)
    window = period(0, 80)
    base = tally(results, window, Direction.BUY)
    every = tally(results, window, Direction.BUY, range(80))
    assert base == every
    counted = [i for i in range(80) if results.buy[i] is not None and i + 24 < 80]
    assert base.all.signals == len(counted)
    assert base.all.hits == sum(1 for i in counted if i < 50 <= i + 24)


def test_unusual_window_excluded_from_clean_count() -> None:
    """R-8: penceresinde (sinyal mumu dahil 24 mum) olağandışı mum olan sinyal temiz kümede yok."""
    series = flat_series(80)
    flags = [""] * 80
    flags[SIGNAL + 24] = "a"
    results = outcomes(series, NO_COSTS, flags)
    window = period(0, 80)
    found = tally(results, window, Direction.BUY, [SIGNAL, SIGNAL + 25, SIGNAL + 5])
    assert found.all.signals == 3
    assert found.clean.signals == 1  # 20 and 25 see candle 44; 45 does not
    assert results.unusual[SIGNAL] and results.unusual[SIGNAL + 24]
    assert not results.unusual[SIGNAL + 25]
