"""Spec 0053 AC-2, AC-3, AC-4 (R-2, Q-1, Q-2, G-3, G-5; plan Risk 2): giriş mumu, isabet, taban
oran,
ölçülmeme nedenleri. İsabet ve taban oran 0048'in çekirdeğiyle (`measure_reference`) ölçülür."""

from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction

import pytest

from crytobot.calibration import (
    CoinPrices,
    Costs,
    ForwardReason,
    ForwardResult,
    measure_forward,
)
from tests.calibration.forward_helpers import (
    BOTH,
    DOWN_HIT,
    FIRST_HOUR,
    NO_COSTS,
    STOP_UP,
    UP_HIT,
    at,
    event,
    inputs,
    priced,
    result,
    scored_hour,
)

H = FIRST_HOUR
REPORT = at(H + 25)


def one(
    prices: CoinPrices | None,
    scored: datetime | None = None,
    report: datetime = REPORT,
    costs: Costs = NO_COSTS,
) -> ForwardResult:
    given = inputs([result(1, scored or scored_hour(H))], [event(1)])
    table = {} if prices is None else {"BTC": prices}
    return measure_forward(given, report, table, costs).results[0]


def test_entry_strictly_after_score() -> None:
    found = one(priced(H + 30), scored=at(H))
    assert found.reason is None and found.entry_time == at(H + 1)
    later = one(priced(H + 30), scored=scored_hour(H))
    assert later.entry_time == at(H + 1) and later.entry_price == 100.0


def test_entry_later_than_1h_unmeasured() -> None:
    found = one(priced(H + 30, missing=[H + 1]))
    assert found.reason is ForwardReason.NO_ENTRY
    assert found.entry_time is None and found.down is None


def test_down_hit_24th_yes_25th_no() -> None:
    assert one(priced(H + 30, {H + 24: DOWN_HIT})).down is True
    assert one(priced(H + 30, {H + 25: DOWN_HIT}), report=at(H + 40)).down is False


def test_stop_first_and_both_bounds_miss() -> None:
    assert one(priced(H + 30, {H + 3: DOWN_HIT})).down is True
    assert one(priced(H + 30, {H + 3: STOP_UP, H + 4: DOWN_HIT})).down is False
    assert one(priced(H + 30, {H + 3: BOTH})).down is False


def test_cost_floor_target() -> None:
    """2xATR = 4; maliyetin alt sınırı 100 x (2·0.02 + 0.01) / 0.98 ≈ 5.1 > 4: hedef 94.9."""
    shallow = priced(H + 30, {H + 3: (100.0, 101.0, 95.5, 100.0)})
    costly = Costs(Decimal("0.02"), Decimal(0), Decimal("0.01"))
    assert one(shallow).down is True
    assert one(shallow, costs=costly).down is False
    assert one(priced(H + 30, {H + 3: (100.0, 101.0, 94.8, 100.0)}), costs=costly).down is True


def test_up_hit_mirror() -> None:
    up = one(priced(H + 30, {H + 3: UP_HIT}))
    assert (up.up, up.down) == (True, False)
    stopped = one(priced(H + 30, {H + 3: (100.0, 101.0, 97.0, 100.0), H + 4: UP_HIT}))
    assert stopped.up is False


def test_base_720_before_score() -> None:
    """Konum 500'deki düşüş mumu 476…499 sinyallerinin penceresindedir; sayılan sinyaller
    81…775 (açılışı `[skor - 720 s, skor)` içinde, penceresi skor anını aşmayan): 695."""
    found = one(priced(H + 30, {500: DOWN_HIT}))
    assert found.base_down == Fraction(24, 695)
    assert found.base_up == 0


def test_base_window_past_score_excluded() -> None:
    """Konum 800'deki mum yalnız penceresi skor anını aşan sinyallerin içindedir."""
    found = one(priced(H + 30, {H: DOWN_HIT}))
    assert found.reason is None and found.base_down == 0


def test_719_candles_few() -> None:
    found = one(priced(H + 30, missing=[400]))
    assert found.reason is ForwardReason.FEW_CANDLES and found.base_down is None


def test_set_base_is_mean() -> None:
    """Küme taban oranı örnek taban oranlarının ortalamasıdır (AC-3)."""
    prices = priced(H + 60, {95: DOWN_HIT})
    given = inputs(
        [result(1, scored_hour(H)), result(2, scored_hour(H + 30))], [event(1), event(2)]
    )
    measured = measure_forward(given, at(H + 60), {"BTC": prices}, NO_COSTS)
    bases = [r.base_down for r in measured.results]
    assert all(b is not None for b in bases) and bases[0] != bases[1]
    assert measured.table is not None
    assert measured.table.rates.down_base == (bases[0] + bases[1]) / 2  # type: ignore[operator]


@pytest.mark.parametrize(
    ("prices", "report", "reason"),
    [
        (None, REPORT, ForwardReason.NO_PAIR),
        (CoinPrices(False, ()), REPORT, ForwardReason.NO_PAIR),
        (priced(H + 30), REPORT - timedelta(seconds=1), ForwardReason.PENDING),
        (CoinPrices(True, ()), REPORT, ForwardReason.NO_PRICES),
        (priced(H + 30, missing=[H + 1]), REPORT, ForwardReason.NO_ENTRY),
        (priced(H + 30, missing=[400]), REPORT, ForwardReason.FEW_CANDLES),
    ],
)
def test_unmeasured_reasons_counted(
    prices: CoinPrices | None, report: datetime, reason: ForwardReason
) -> None:
    given = inputs([result(1, scored_hour(H))], [event(1)])
    measured = measure_forward(given, report, {} if prices is None else {"BTC": prices}, NO_COSTS)
    assert measured.results[0].reason is reason
    assert measured.table is not None
    counts = dict(measured.table.unmeasured)
    assert counts[reason] == 1 and sum(counts.values()) == 1


def test_pending_before_prices_and_pair_before_pending() -> None:
    """Plan Risk 2: `çift yok` → `ölçüm bekliyor` → `fiyat verisi yok`."""
    early = REPORT - timedelta(seconds=1)
    assert one(CoinPrices(True, ()), report=early).reason is ForwardReason.PENDING
    assert one(CoinPrices(False, ()), report=early).reason is ForwardReason.NO_PAIR


def test_unmeasured_in_no_rate() -> None:
    prices = {"BTC": priced(H + 60, {H + 3: DOWN_HIT}, missing=[H + 31])}
    given = inputs(
        [result(1, scored_hour(H)), result(2, scored_hour(H + 30))], [event(1), event(2)]
    )
    measured = measure_forward(given, at(H + 60), prices, NO_COSTS)
    assert [r.reason for r in measured.results] == [None, ForwardReason.NO_ENTRY]
    assert measured.table is not None
    rates = measured.table.rates
    assert (rates.count, rates.down_hit) == (1, Fraction(1))
    assert measured.table.samples == 2


def test_candles_after_report_time_unused() -> None:
    """Look-ahead: rapor anından sonraki mum (ve 24. mumdan sonraki mum) girdiye girmez."""
    plain = one(priced(H + 30))
    with_later = one(priced(H + 30, {H + 25: DOWN_HIT, H + 26: UP_HIT}))
    assert plain == with_later
