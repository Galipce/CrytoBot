"""Spec 0048 AC-1 (çift var/yok), AC-3, AC-4, AC-5, AC-6 (R-4, R-5, Q-3, G-2, G-7; plan Risk 5, 8):
örnekler, giriş mumu, isabet, taban oran, ölçülemeyen nedenleri, ana sonuç, çakışma.

Sentetik seri: saatlik, düz (açılış = kapanış = 100, yüksek 101, düşük 99): ATR 2, hedef mesafesi
max(4, maliyet 0.45) = 4, stop 2. Düz mum hiçbir sınıra değmez; sınır mumları elle konur.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest

from crytobot.analysis import Candle
from crytobot.calibration import (
    AFTER,
    BEFORE,
    TOTAL,
    CoinPrices,
    Costs,
    EventAnnouncement,
    EventMeasured,
    Move,
    Reason,
    Span,
    event_samples,
    measure_events,
    price_needs,
    reason_counts,
    sample_span,
    table_rows,
)
from crytobot.market_data._event_prices import _pairs
from tests.market_data.helpers import fixture

H = timedelta(hours=1)
START = datetime(2024, 1, 1, tzinfo=UTC)
COSTS = Costs(Decimal("0.001"), Decimal("0.001"), Decimal("0.0005"))
CUTOFF = datetime(2024, 6, 1, tzinfo=UTC)
TYPES = (
    ("spot listeleme", "olumlu"),
    ("listeden çıkarma", "olumsuz"),
    ("askıya alma ve bakım", "nötr"),
)
R = 800  # the reference candle index: 800 candles before it, the base window and ATR warm-up
LENGTH = 900


def at(index: int) -> datetime:
    return START + index * H


def candles(
    length: int = LENGTH,
    *,
    bounds: Mapping[int, tuple[float, float]] | None = None,
    drop: frozenset[int] = frozenset(),
    first: int = 0,
    half: float = 1.0,
) -> tuple[Candle, ...]:
    """Düz seri `[first, length)`; `bounds`: konum → (yüksek, düşük); `drop`: eksik mumlar."""
    found = []
    for index in range(first, length):
        if index in drop:
            continue
        high, low = (bounds or {}).get(index, (100 + half, 100 - half))
        found.append(Candle(at(index), 100.0, high, low, 100.0))
    return tuple(found)


def announcement(article: str = "1", **values: Any) -> EventAnnouncement:
    defaults: dict[str, Any] = {
        "origin": "arşiv",
        "catalog": "c",
        "title": "Binance Will List ABC (ABC)",
        "published": at(R),
        "first_seen": None,
        "event_type": "spot listeleme",
        "direction": "olumlu",
        "coins": ("ABC",),
        "pattern": "p",
    }
    return EventAnnouncement(article, **{**defaults, **values})


def measure(
    *items: EventAnnouncement,
    series: tuple[Candle, ...] | None = None,
    prices: Mapping[str, CoinPrices] | None = None,
) -> EventMeasured:
    if prices is None:
        prices = {"ABC": CoinPrices(True, candles() if series is None else series)}
    return measure_events(event_samples(items), prices, COSTS, CUTOFF, TYPES)


def only(measured: EventMeasured) -> Any:
    assert len(measured.results) == 1
    return measured.results[0]


# --- AC-1: the pair as the exchange information lists it -------------------------------------


def test_break_pair_counts_as_pair() -> None:
    """Kaldırılmış (`BREAK`) ama borsa bilgisinde bulunan çift "çift var"dır (G-3)."""
    markets = {
        each["symbol"]: {"info": each, "spot": True} for each in fixture("exchange_info")["symbols"]
    }
    pairs = {pair.base: pair for pair in _pairs(markets)}
    assert pairs["EOS"].status == "BREAK"
    result = only(
        measure(
            announcement(coins=("EOS",)),
            prices={"EOS": CoinPrices("EOS" in pairs, candles())},
        )
    )
    assert result.reason is None


def test_no_usdt_pair_not_measured() -> None:
    markets = {
        each["symbol"]: {"info": each, "spot": True} for each in fixture("exchange_info")["symbols"]
    }
    pairs = {pair.base: pair for pair in _pairs(markets)}
    assert "ETHBTC" not in {pair.symbol for pair in pairs.values()}
    result = only(measure(announcement(coins=("XYZ",)), prices={"XYZ": CoinPrices(False, ())}))
    assert result.reason is Reason.NO_PAIR
    assert only(measure(announcement(coins=("XYZ",)), prices={})).reason is Reason.NO_PAIR


# --- AC-3: entry and hit -----------------------------------------------------------------------


def test_entry_strictly_after_reference() -> None:
    inside = only(measure(announcement(published=at(R) + timedelta(minutes=30))))
    assert inside.entry_time == at(R + 1)
    assert inside.entry_price == 100.0


def test_entry_exactly_one_hour_later_measured() -> None:
    result = only(measure(announcement(published=at(R))))  # the candle opening at R is not it
    assert (result.reason, result.entry_time) == (None, at(R + 1))


def test_entry_later_than_one_hour_not_measured() -> None:
    series = candles(drop=frozenset({R + 1}))
    assert only(measure(announcement(published=at(R)), series=series)).reason is Reason.NO_ENTRY
    later = announcement(published=at(R) + timedelta(seconds=1))
    assert only(measure(later, series=series)).reason is Reason.NO_ENTRY


def test_hit_on_24th_not_25th() -> None:
    # entry candle R+1 is the window's 1st: the 24th is R+24, the 25th R+25
    on_24th = only(measure(announcement(), series=candles(bounds={R + 24: (104.0, 99.0)})))
    on_25th = only(measure(announcement(), series=candles(bounds={R + 25: (104.0, 99.0)})))
    assert (on_24th.up, on_25th.up) == (True, False)


def test_stop_first_and_both_bounds_miss() -> None:
    stop_first = candles(bounds={R + 3: (100.5, 98.0), R + 5: (104.0, 99.0)})
    both = candles(bounds={R + 3: (104.0, 98.0)})
    assert only(measure(announcement(), series=stop_first)).up is False
    assert only(measure(announcement(), series=both)).up is False
    assert only(measure(announcement(), series=candles(bounds={R + 3: (104.0, 98.01)}))).up


def test_cost_distance_when_atr_small() -> None:
    # ATR 0.02: 2xATR 0.04 is below the cost distance 100 x 0.0045090 = 0.4509
    factor = COSTS.factor()
    assert 100 * factor > 0.04
    short = candles(half=0.01, bounds={R + 2: (100.2, 99.99)})  # reaches 2xATR, not the cost
    long = candles(half=0.01, bounds={R + 2: (100.46, 99.99)})
    assert only(measure(announcement(), series=short)).up is False
    assert only(measure(announcement(), series=long)).up is True


def test_up_down_symmetric() -> None:
    up = only(measure(announcement(), series=candles(bounds={R + 4: (104.0, 99.0)})))
    down = only(measure(announcement(), series=candles(bounds={R + 4: (101.0, 96.0)})))
    assert (up.up, up.down) == (True, False)
    assert (down.up, down.down) == (False, True)
    both_stop = only(measure(announcement(), series=candles(bounds={R + 4: (104.0, 96.0)})))
    assert (both_stop.up, both_stop.down) == (False, False)


def test_first_seen_used_when_publish_unknown() -> None:
    seen = only(measure(announcement(published=None, first_seen=at(R))))
    assert (seen.reason, seen.sample.from_first_seen, seen.entry_time) == (None, True, at(R + 1))
    known = only(measure(announcement(published=at(R), first_seen=at(R + 5))))
    assert (known.sample.reference, known.sample.from_first_seen) == (at(R), False)
    unknown = only(measure(announcement(published=None, first_seen=None)))
    assert unknown.reason is Reason.NO_TIME


# --- AC-4: main result and overlap -------------------------------------------------------------


def rows_of(measured: EventMeasured, name: str, move: Move) -> dict[str, Any]:
    return {
        row.period: row
        for row in table_rows(measured)
        if (row.event_type, row.move) == (name, move)
    }


def test_main_result_by_expected_direction() -> None:
    measured = measure(
        announcement("1"),
        announcement("2", event_type="listeden çıkarma", direction="olumsuz"),
    )
    assert rows_of(measured, "spot listeleme", Move.UP)[TOTAL].main is True
    assert rows_of(measured, "spot listeleme", Move.DOWN)[TOTAL].main is False
    assert rows_of(measured, "listeden çıkarma", Move.DOWN)[TOTAL].main is True
    assert rows_of(measured, "listeden çıkarma", Move.UP)[TOTAL].main is False


def test_neutral_two_tables_no_main() -> None:
    measured = measure(announcement(event_type="askıya alma ve bakım", direction="nötr"))
    for move in (Move.UP, Move.DOWN):
        assert {row.main for row in rows_of(measured, "askıya alma ve bakım", move).values()} == {
            None
        }


def test_overlapping_windows_counted_and_shown() -> None:
    measured = measure(
        announcement("1", published=at(R)),
        announcement("2", published=at(R + 3), event_type="listeden çıkarma", direction="olumsuz"),
        announcement("3", published=at(R + 40)),
    )
    flags = {r.sample.announcement.article_id: r.overlapping for r in measured.results}
    assert flags == {"1": True, "2": True, "3": False}
    assert [r.reason for r in measured.results] == [None, None, None]
    total = rows_of(measured, "spot listeleme", Move.UP)[TOTAL]
    assert (total.measured, total.overlapping) == (2, 1)
    # a window that starts exactly when the other ends does not overlap
    apart = measure(announcement("1", published=at(R)), announcement("2", published=at(R + 24)))
    assert [r.overlapping for r in apart.results] == [False, False]


def test_periods_split_at_cutoff() -> None:
    measured = measure(
        announcement("1", published=at(R)),
        announcement("2", published=CUTOFF, coins=()),
        announcement("3", published=CUTOFF - timedelta(seconds=1), coins=()),
    )
    assert [r.period for r in measured.results] == [BEFORE, BEFORE, AFTER]
    rows = rows_of(measured, "spot listeleme", Move.UP)
    assert (rows[BEFORE].samples, rows[AFTER].samples, rows[TOTAL].samples) == (2, 1, 3)
    assert (rows[BEFORE].announcements, rows[TOTAL].measured) == (2, 1)


# --- AC-5: base rate -------------------------------------------------------------------------


def test_base_rate_720_closes_same_rule() -> None:
    """720 kapanış sinyal; penceresi ref'i aşan 24'ü sayılmaz: 696 sinyal. Sinyal t'nin penceresi
    t+1…t+24: `p`'deki 104 yükseği önceki 24 sinyalin isabetidir (ATR orada 2)."""
    spike = R - 100
    result = only(measure(announcement(), series=candles(bounds={spike: (104.0, 99.0)})))
    assert result.base_up == Fraction(24, 696)
    assert result.base_down == Fraction(0)


def test_base_window_past_reference_excluded() -> None:
    # the spike in the last base candle: only the signal whose window ends exactly at ref counts
    result = only(measure(announcement(), series=candles(bounds={R - 1: (104.0, 99.0)})))
    assert result.base_up == Fraction(1, 696)


def test_fewer_than_720_not_measured() -> None:
    gap = candles(drop=frozenset({R - 300}))
    assert only(measure(announcement(), series=gap)).reason is Reason.FEW_CANDLES
    short = candles(first=R - 719)  # 719 candles, and no ATR at the first base signal
    assert only(measure(announcement(), series=short)).reason is Reason.FEW_CANDLES
    no_warmup = candles(first=R - 720)  # 720 candles but no ATR warm-up before them
    assert only(measure(announcement(), series=no_warmup)).reason is Reason.FEW_CANDLES
    enough = candles(first=R - 720 - 13)
    assert only(measure(announcement(), series=enough)).reason is None


def test_type_base_is_mean_of_samples() -> None:
    # the second reference's base window starts after the spike
    series = candles(R + 760, bounds={R - 100: (104.0, 99.0)})
    measured = measure(
        announcement("1", published=at(R)), announcement("2", published=at(R + 700)), series=series
    )
    bases = [r.base_up for r in measured.results]
    assert bases == [Fraction(24, 696), Fraction(0)]
    row = rows_of(measured, "spot listeleme", Move.UP)[TOTAL]
    assert row.base == Fraction(12, 696)
    assert row.hit == Fraction(0)
    assert row.difference == Fraction(-12, 696)


def test_another_sample_does_not_change_a_result() -> None:
    """Review round 1 F-3: an earlier, distant sample of the same coin (a separate price span with
    another volatility) changes neither the ATR nor the base rate of a later sample."""
    later = 3000
    early = candles(900, half=5.0)
    own = candles(
        later + 100, first=2200, bounds={later - 715 + 7 * k: (104.0, 99.0) for k in range(3)}
    )
    alone = only(measure(announcement("2", published=at(later)), series=own))
    together = measure(
        announcement("1", published=at(R)),
        announcement("2", published=at(later)),
        series=early + own,
    ).results[1]
    assert alone.reason is None and alone.base_up > 0
    assert (together.up, together.down, together.base_up, together.base_down) == (
        alone.up,
        alone.down,
        alone.base_up,
        alone.base_down,
    )


# --- AC-6: the unmeasured --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reason", "item", "prices"),
    [
        (Reason.NO_TIME, announcement(published=None), None),
        (Reason.NO_COIN, announcement(coins=()), None),
        (Reason.NO_PAIR, announcement(), {"ABC": CoinPrices(False, ())}),
        (Reason.NO_PRICES, announcement(), {"ABC": CoinPrices(True, ())}),
        (Reason.NO_PRICES, announcement(published=at(R + 2000)), None),
        (Reason.NO_ENTRY, announcement(), {"ABC": CoinPrices(True, candles(R))}),
        (Reason.FEW_CANDLES, announcement(), {"ABC": CoinPrices(True, candles(first=R - 100))}),
        (Reason.PAST_END, announcement(), {"ABC": CoinPrices(True, candles(R + 10))}),
    ],
)
def test_each_unmeasured_reason(
    reason: Reason, item: EventAnnouncement, prices: Mapping[str, CoinPrices] | None
) -> None:
    measured = measure(item, prices=prices)
    result = only(measured)
    assert result.reason is reason
    assert (result.up, result.base_up, result.entry_time) == (None, None, None)
    counts = dict(reason_counts(measured))
    assert counts[reason] == 1 and sum(counts.values()) == 1


def test_reason_order_first_wins() -> None:
    # no time and no coin: the time is checked first
    result = only(measure(announcement(published=None, coins=())))
    assert result.reason is Reason.NO_TIME
    assert [reason.value for reason in Reason] == [
        "yayın anı bilinmiyor",
        "coin yok",
        "çift yok",
        "fiyat verisi yok",
        "giriş mumu yok ya da geç",
        "mum yetmiyor",
        "pencere veri sonunu aşıyor",
    ]


def test_samples_per_coin_and_needs_merged() -> None:
    items = (
        announcement("2", coins=("ABC", "DEF", "GHI")),
        announcement("1", published=at(R + 1), coins=("ABC",)),
        announcement("3", published=None, coins=("ABC",)),
    )
    samples = event_samples(items)
    assert [(s.announcement.article_id, s.coin) for s in samples] == [
        ("2", "ABC"),
        ("2", "DEF"),
        ("2", "GHI"),
        ("1", "ABC"),
        ("3", "ABC"),
    ]
    needs = price_needs(samples)
    assert list(needs) == ["ABC", "DEF", "GHI"]
    span = sample_span(at(R))
    assert needs["ABC"] == (Span(span.start, sample_span(at(R + 1)).end),)
    assert span.start == at(R) - (720 + 16) * H and span.end == at(R) + 26 * H
