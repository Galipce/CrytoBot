"""Spec 0044 AC-1 (sayım yarısı), R-3; plan Adım 4, Risk 1, 3: `period_gaps` ve `has_candle`.

Boşluk kuralı indirme özetininkidir (`boşluk=`); eşitlik gerçek indirme (`run_download` + sahte
borsa) ve gerçek okuma (`read_history`) üzerinden kanıtlanır.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from crytobot.market_data import (
    CandleGap,
    HistoryPair,
    MarketCandle,
    MarketRules,
    has_candle,
    period_gaps,
    read_history,
)
from tests.market_data.helpers import BTC, ETH, HOUR, HOUR_MS
from tests.market_data.history_helpers import (
    START,
    START_MS,
    WARMUP,
    FakeHistoryExchange,
    at,
    make_request,
    rows_between,
    run_download,
)

ONE = Decimal(1)  # prices and rules play no part in gaps
RULES = MarketRules(ONE, ONE, ONE)
END = START + timedelta(hours=24)


def pair(hours: list[int], name: str = BTC, interval: timedelta = HOUR) -> HistoryPair:
    """`hours`: dönem başına göre mum açılışları (negatif: ısınma)."""
    return HistoryPair(
        name,
        ONE,
        RULES,
        tuple(MarketCandle(START + hour * interval, ONE, ONE, ONE, ONE) for hour in hours),
    )


def gap(first: int, last: int, count: int) -> CandleGap:
    return CandleGap(BTC, START + first * HOUR, START + last * HOUR, count)


EVERY = list(range(-WARMUP, 24))


@pytest.mark.parametrize(
    ("hours", "expected"),
    [
        (EVERY, ()),
        ([h for h in EVERY if h != 5], (gap(5, 5, 1),)),  # a single missing candle: n = 1
        ([h for h in EVERY if not 5 <= h <= 8], (gap(5, 8, 4),)),  # consecutive: one line
        (
            [h for h in EVERY if h not in (2, 10, 11)],
            (gap(2, 2, 1), gap(10, 11, 2)),
        ),  # time order
        ([h for h in EVERY if not -2 <= h <= 1], (gap(0, 1, 2),)),  # from the warm-up: in-period
        ([h for h in EVERY if not -3 <= h <= -1], ()),  # warm-up only: not a gap
        ([h for h in EVERY if h < 20], (gap(20, 23, 4),)),  # the end is missing
        ([h for h in EVERY if h != 23], (gap(23, 23, 1),)),  # only the last candle
        (list(range(6, 24)), ()),  # listed inside the period: before its first candle, no gap
        (list(range(6, 10)), (gap(10, 23, 14),)),  # listed late, then the end is missing
    ],
    ids=[
        "none",
        "single",
        "consecutive",
        "two_in_order",
        "warm_up_overflow",
        "warm_up_only",
        "end_missing",
        "last_only",
        "listed_late",
        "listed_late_end_missing",
    ],
)
def test_gap_boundaries(hours: list[int], expected: tuple[CandleGap, ...]) -> None:
    """AC-1: tek eksik `n=1`, ardışıklar tek satır, ısınmadan taşan yalnız dönem içi mumlarla,
    sondaki eksik son beklenen mumda biter, ilk mumdan önceki eksiklik boşluk değildir."""
    assert period_gaps(pair(hours), HOUR, START, END) == expected


def test_gap_on_four_hour_candles() -> None:
    four = 4 * HOUR
    hours = [h for h in range(-3, 6) if h != 2]
    expected = (CandleGap(BTC, START + 2 * four, START + 2 * four, 1),)
    assert period_gaps(pair(hours, interval=four), four, START, START + 6 * four) == expected


def test_no_candles_has_no_gaps() -> None:
    assert period_gaps(pair([]), HOUR, START, END) == ()


@pytest.mark.parametrize(
    ("hours", "found"),
    [
        ([], False),
        (list(range(-3, 0)), False),  # warm-up only
        ([24, 25], False),  # after the end (excluded)
        ([0], True),  # the start is included
        ([23], True),  # the last candle closing by the end
        ([12], True),  # a single candle: not refused (AC-2)
    ],
)
def test_has_candle_is_open_inside_start_inclusive_end_exclusive(
    hours: list[int], found: bool
) -> None:
    """R-3, plan Risk 3: açılışı `[start, end)` içinde mum."""
    assert has_candle(pair(hours), START, END) is found


# --- AC-1: satır sayısı indirme özetindeki `boşluk=` değerine eşit ---

DAYS = 2
PERIOD_END_MS = START_MS + DAYS * 24 * HOUR_MS


@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    missing=st.sets(st.integers(-WARMUP - 2, DAYS * 24 + 1), max_size=30),
    listed=st.integers(-WARMUP - 2, 20),
)
def test_gap_count_equals_download_summary(
    tmp_path_factory: pytest.TempPathFactory, missing: set[int], listed: int
) -> None:
    """AC-1 (K-3): her çiftte satır sayısı = özetin `boşluk=`; eksik mum sayıları toplamı dönem
    içinde, çiftin ilk mumundan sonra eksik olan mumlardır."""
    folder = tmp_path_factory.mktemp("gaps")
    first_ms = START_MS + listed * HOUR_MS
    history = {
        name: [
            row
            for row in rows_between(first_ms, PERIOD_END_MS + 3 * HOUR_MS)
            if (row[0] - START_MS) // HOUR_MS not in missing  # type: ignore[operator]
        ]
        for name in (BTC, ETH)
    }
    in_period = [
        row
        for row in history[BTC]
        if START_MS <= row[0] < PERIOD_END_MS  # type: ignore[operator]
    ]
    if not in_period:
        return  # the download stops on a pair without period candles (0023 R-6)
    path = folder / "h.jsonl"
    result = run_download(make_request(path, days=DAYS), FakeHistoryExchange(history))
    assert result.stop is None, result.stop
    read = read_history(str(path))
    assert read.data is not None, read.problem
    data = read.data
    for summary, item in zip(result.summaries, data.pairs, strict=True):
        found = period_gaps(item, data.candle_interval, data.start, data.end)
        assert len(found) == summary.gaps
        first = max(START_MS, int(item.candles[0].open_time.timestamp()) * 1000)
        absent = {hour for hour in missing if first <= START_MS + hour * HOUR_MS < PERIOD_END_MS}
        assert sum(each.count for each in found) == len(absent)
        assert all(at(START_MS) <= each.first <= each.last < data.end for each in found)
        assert [each.first for each in found] == sorted(each.first for each in found)
