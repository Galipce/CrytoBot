"""Spec 0045 AC-4: olağandışı mum kuralları (a)…(d) tek tek; tam eşik işaretlenmez (plan Risk 8).

Bütün mumlar düzdür (boy 2): bir önceki mumun ATR(14)'ü tam 2'dir.
"""

from collections.abc import Mapping

from crytobot.calibration import Direction, outcomes, tally, unusual_flags
from tests.calibration.helpers import BTC, NO_COSTS, flat_series, period

PAIRS = (BTC, "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT")
AT = 30


def flags_of(
    changes: Mapping[str, Mapping[int, tuple[float, float, float, float]]],
    **volumes: Mapping[int, float],
) -> dict[str, tuple[str, ...]]:
    series = {
        pair: flat_series(60, changes.get(pair, {}), pair=pair, volumes=volumes.get(pair))
        for pair in PAIRS
    }
    return unusual_flags(
        {pair: item.candles for pair, item in series.items()},
        {pair: item.volumes for pair, item in series.items()},
    )


def test_rule_a_range_above_four_atr() -> None:
    assert flags_of({BTC: {AT: (100, 104.1, 96, 100)}})[BTC][AT] == "a"
    assert flags_of({BTC: {AT: (100, 104, 96, 100)}})[BTC][AT] == ""  # exactly 8


def test_rule_b_volume_above_five_times_mean() -> None:
    spike = {AT: 5.0001}
    exact = {AT: 5.0}
    assert flags_of({}, **{BTC: spike})[BTC][AT] == "b"
    assert flags_of({}, **{BTC: exact})[BTC][AT] == ""
    assert flags_of({}, **{BTC: {10: 100.0}})[BTC][10] == ""  # fewer than 20 candles before


def test_rule_c_body_above_three_atr_and_two_thirds_back() -> None:
    rise = (100, 106.5, 100, 106.5)  # body 6.5 > 6, range 6.5 < 8
    hold = (106.5, 107, 106, 106.5)  # stays up: takes nothing back
    held = {AT + step: hold for step in range(1, 6)}
    back = (106.5, 106.5, 102, 102.1)  # closes 4.4 below: at least 2/3 of 6.5 (4.333)
    assert flags_of({BTC: {**held, AT: rise, AT + 3: back}})[BTC][AT] == "c"
    assert flags_of({BTC: {**held, AT: rise}})[BTC][AT] == ""
    assert flags_of({BTC: {**held, AT: rise, AT + 4: back}})[BTC][AT] == ""  # after 3 candles
    shallow = (106.5, 106.5, 102.5, 102.5)  # 4.0 back: less than 2/3
    assert flags_of({BTC: {**held, AT: rise, AT + 1: shallow}})[BTC][AT] == ""
    exact_body = (100, 106, 100, 106)  # body exactly 6
    assert flags_of({BTC: {AT: exact_body, AT + 1: (106, 106, 100, 100)}})[BTC][AT] == ""
    fall = (106.5, 106.5, 100, 100)
    up_again = (100, 104.5, 100, 104.4)
    assert flags_of({BTC: {AT: fall, AT + 2: up_again}})[BTC][AT] == "c"


def test_rule_d_four_of_five_pairs_above_three_atr() -> None:
    wide = (100, 103.1, 97, 100)  # range 6.1 > 6, below 8: only (d)
    four = {pair: {AT: wide} for pair in PAIRS[:4]}
    found = flags_of(four)
    assert [found[pair][AT] for pair in PAIRS] == ["d", "d", "d", "d", ""]
    three = {pair: {AT: wide} for pair in PAIRS[:3]}
    assert all(flags_of(three)[pair][AT] == "" for pair in PAIRS)
    exact = {pair: {AT: (100, 103, 97, 100)} for pair in PAIRS}  # exactly 6
    assert all(flags_of(exact)[pair][AT] == "" for pair in PAIRS)


def test_rules_a_to_d_flagged_separately() -> None:
    """Bir mum birden çok kuralla işaretlenebilir; harfler ayrı ayrı yazılır."""
    big = (100, 108.5, 100, 108.5)  # range 8.5 > 8 (a), body 8.5 > 6 (c), wide (d)
    hold = (108.5, 109, 108, 108.5)
    changes = {pair: {AT: big, **{AT + step: hold for step in (1, 2, 3)}} for pair in PAIRS}
    changes[BTC][AT + 1] = (108.5, 108.5, 100, 100)  # BTC gives the move back: (c)
    found = flags_of(changes, **{BTC: {AT: 10.0}})
    assert found[BTC][AT] == "abcd"
    assert found["ETH/USDT"][AT] == "ad"


def test_exact_threshold_not_flagged() -> None:
    found = flags_of({BTC: {AT: (100, 104, 96, 100)}}, **{"ETH/USDT": {AT: 5.0}})
    assert found[BTC][AT] == "" and found["ETH/USDT"][AT] == ""


def test_unusual_candles_kept_in_measurement() -> None:
    """R-8: olağandışı mum veriden çıkarılmaz: isabeti yine sayılır, yalnız temiz kümede yoktur."""
    target = (100, 104, 99, 100)  # reaches the 104 target of the signal at 20
    series = flat_series(60, {AT: target}, volumes={AT: 50.0})
    flags = flags_of({BTC: {AT: target}}, **{BTC: {AT: 50.0}})[BTC]
    assert flags[AT] == "b"
    results = outcomes(series, NO_COSTS, flags)
    assert len(results.series.candles) == 60
    found = tally(results, period(0, 60), Direction.BUY, [20])
    assert (found.all.signals, found.all.hits) == (1, 1)
    assert found.clean.signals == 0
