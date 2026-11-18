"""Spec 0053 AC-4 (örtüşme), AC-5, AC-6 (R-3, R-5, Q-3, Q-4, G-2; plan Risk 3, 4, 5e, 5f): hüküm
sırası, kesin eşik, üçlü değişimi."""

from datetime import timedelta
from fractions import Fraction

from crytobot.calibration import decide, measure_forward
from tests.calibration.forward_helpers import (
    DOWN_HIT,
    FIRST_HOUR,
    NO_COSTS,
    OTHER_TRIPLE,
    at,
    event,
    inputs,
    priced,
    result,
    scored_hour,
    spaced,
    spaced_inputs,
)

START = at(0)
DAY = timedelta(days=1)
ENOUGH = Fraction(1, 2)


def test_no_scores() -> None:
    assert decide(None, START, 0, None).line == "hüküm yok: skor yok — kalan 90 gün, 30 örnek"
    for given in (inputs(None), inputs([])):
        measured = measure_forward(given, START, {}, NO_COSTS)
        assert measured.verdict.line == "hüküm yok: skor yok — kalan 90 gün, 30 örnek"
        assert measured.table is None and measured.side is None and measured.results == ()
    assert measure_forward(inputs(None), START, {}, NO_COSTS).score_record is False
    assert measure_forward(inputs([]), START, {}, NO_COSTS).score_record is True


def test_89d23h_short_90d_passes() -> None:
    short = decide(START, START + 90 * DAY - timedelta(hours=1), 30, ENOUGH)
    assert short.kind == "hüküm yok"
    assert short.line == "hüküm yok: süre yetersiz (89/90 gün) — kalan 1 gün, 0 örnek"
    assert decide(START, START + 90 * DAY, 30, ENOUGH).kind == "olumlu"


def test_29_short_30_passes() -> None:
    short = decide(START, START + 90 * DAY, 29, ENOUGH)
    assert short.line == "hüküm yok: olay yetersiz (29/30) — kalan 0 gün, 1 örnek"
    assert decide(START, START + 90 * DAY, 30, ENOUGH).kind == "olumlu"


def test_exact_plus_5_positive() -> None:
    found = decide(START, START + 90 * DAY, 30, Fraction(5, 100))
    assert found.kind == "olumlu"
    assert found.line == "olumlu: isabet taban oranı en az 5 puan geçiyor (+5.0 ≥ +5)"


def test_plus_4_9_negative_with_value() -> None:
    found = decide(START, START + 90 * DAY, 30, Fraction(49, 1000))
    assert found.kind == "olumsuz"
    assert found.line == "olumsuz: isabet taban oranı 5 puan geçmiyor (+4.9 < +5)"
    just = decide(START, START + 90 * DAY, 30, Fraction(5, 100) - Fraction(1, 10**9))
    assert just.line == "olumsuz: isabet taban oranı 5 puan geçmiyor (+4.9 < +5)"
    below = decide(START, START + 90 * DAY, 30, Fraction(-32, 1000))
    assert below.line == "olumsuz: isabet taban oranı 5 puan geçmiyor (-3.2 < +5)"


def test_no_verdict_writes_remaining() -> None:
    found = decide(START, START + 89 * DAY, 18, None)
    assert found.line == "hüküm yok: süre yetersiz (89/90 gün) — kalan 1 gün, 12 örnek"
    assert decide(START, START + 10 * DAY, 40, None).line.endswith("kalan 80 gün, 0 örnek")


def test_full_measure_reaches_positive_verdict() -> None:
    hours, prices = spaced(30)
    results, events = spaced_inputs(hours)
    report = at(hours[-1] + 25)
    measured = measure_forward(inputs(results, events), report, {"BTC": prices}, NO_COSTS)
    assert measured.table is not None
    assert (measured.table.rates.count, measured.table.rates.down_hit) == (30, Fraction(1))
    assert measured.table.rates.down_base == 0
    assert measured.verdict.line == "olumlu: isabet taban oranı en az 5 puan geçiyor (+100.0 ≥ +5)"
    fewer = measure_forward(inputs(results[:29], events[:29]), report, {"BTC": prices}, NO_COSTS)
    assert fewer.verdict.line.startswith("hüküm yok: olay yetersiz (29/30)")


def test_overlapping_shown_not_judged() -> None:
    """G-2: ikinci örneğin giriş mumu ilkinin 24 mumluk penceresinde; üçüncüsü ilkinin
    penceresinden sonra (ilk sayılan esas, örtüşen sayılmaz ve sonraki pencereyi açmaz)."""
    hours = [FIRST_HOUR, FIRST_HOUR + 2, FIRST_HOUR + 24]
    prices = priced(FIRST_HOUR + 60, {FIRST_HOUR + 3: DOWN_HIT})
    given = inputs(
        [result(k + 1, scored_hour(h)) for k, h in enumerate(hours)],
        [event(k + 1) for k in range(3)],
    )
    measured = measure_forward(given, at(FIRST_HOUR + 60), {"BTC": prices}, NO_COSTS)
    assert [r.reason for r in measured.results] == [None, None, None]
    assert measured.overlapping == (False, True, False)
    assert measured.table is not None
    assert (measured.table.overlapping, measured.table.rates.count) == (1, 2)


def test_triple_change_resets_clock() -> None:
    hours, prices = spaced(30)
    old, old_events = spaced_inputs(hours, triple=OTHER_TRIPLE)
    new_at = hours[-1] + 1
    new = [result(100, scored_hour(new_at))]
    report = scored_hour(new_at) + 5 * DAY
    measured = measure_forward(
        inputs([*old, *new], [*old_events, event(100)]), report, {"BTC": prices}, NO_COSTS
    )
    assert measured.current == new[0].triple and measured.current_first == new[0].at
    assert measured.verdict.line == "hüküm yok: süre yetersiz (5/90 gün) — kalan 85 gün, 29 örnek"
    (previous,) = measured.old
    assert previous.judged is False and previous.triple == OTHER_TRIPLE
    assert previous.first_at == old[0].at and previous.last_at == old[-1].at


def test_old_triple_out_of_verdict() -> None:
    hours, prices = spaced(31)
    old, old_events = spaced_inputs(hours[:30], triple=OTHER_TRIPLE)
    new, new_events = spaced_inputs(hours[30:], first_id=100)
    report = at(hours[-1] + 25)
    measured = measure_forward(
        inputs([*old, *new], [*old_events, *new_events]), report, {"BTC": prices}, NO_COSTS
    )
    assert measured.table is not None and measured.table.judged is True
    assert measured.table.rates.count == 1
    assert measured.old[0].rates.count == 30
    assert measured.verdict.kind == "hüküm yok"
