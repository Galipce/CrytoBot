"""Spec 0053 AC-1 (R-2, G-1; plan Risk 5): örnek seçimi ve skor anındaki beyaz liste."""

from datetime import timedelta

import pytest

from crytobot.calibration import ForwardEvent, ScoredNews, forward_samples
from tests.calibration.forward_helpers import (
    TRIPLE,
    at,
    event,
    inputs,
    result,
    turn,
)

REPORT = at(5000)


@pytest.mark.parametrize(
    ("direction", "severity", "sampled"),
    [
        ("olumsuz", 2, True),
        ("olumsuz", 3, True),
        ("olumsuz", 1, False),
        ("olumlu", 3, False),
        ("belirsiz", 3, False),
    ],
)
def test_negative_severity_2_3_only(direction: str, severity: int, sampled: bool) -> None:
    found = forward_samples(
        inputs([result(1, at(900))], [event(1, severity=severity, direction=direction)]), REPORT
    )
    assert bool(found) is sampled
    if sampled:
        (sample,) = found
        assert (sample.news_id, sample.coin, sample.severity, sample.scored_at) == (
            1,
            "BTC",
            severity,
            at(900),
        )
        assert sample.triple == TRIPLE and sample.source == "bilinmiyor"


def test_score_after_report_time_ignored() -> None:
    given = inputs(
        [result(1, REPORT), result(2, REPORT + timedelta(seconds=1))], [event(1), event(2)]
    )
    assert [s.news_id for s in forward_samples(given, REPORT)] == [1]


def test_only_scored_results_count_and_one_sample_per_coin() -> None:
    """Plan Risk 5a: aynı haber ve coin için en yüksek şiddet, eşitlikte alfabe; "skorlandı" dışı
    sonucun skoru örnek olmaz."""
    events: list[ForwardEvent] = [
        event(1, severity=2, kind="hack"),
        event(1, severity=3, kind="zincir durdu"),
        event(1, severity=3, kind="dava"),
        event(1, coin="ETH"),
        event(2),
    ]
    stale = ScoredNews(2, "bayat", at(901), None)
    found = forward_samples(inputs([result(1, at(900)), stale], events, sources={1: "rss"}), REPORT)
    assert [(s.coin, s.severity, s.event_type, s.source) for s in found] == [
        ("BTC", 3, "dava", "rss"),
        ("ETH", 2, "hack", "rss"),
    ]


def test_whitelist_from_last_turn_equal_counts() -> None:
    shadow = [
        turn(at(890), whitelist=("BTC/USDT",)),
        turn(at(900), pair="SOL/USDT", whitelist=("SOL/USDT",)),
        turn(at(901), whitelist=("BTC/USDT",)),
    ]
    given = inputs([result(1, at(900))], [event(1, "BTC"), event(1, "SOL")], shadow=shadow)
    found = {s.coin: s.whitelisted for s in forward_samples(given, REPORT)}
    assert found == {"BTC": False, "SOL": True}


def test_whitelist_from_config_without_turns() -> None:
    events = [event(1, "BTC"), event(1, "SOL")]
    for shadow in (None, [turn(at(950), whitelist=("SOL/USDT",))]):
        given = inputs([result(1, at(900))], events, shadow=shadow, whitelist=("BTC/USDT",))
        found = {s.coin: s.whitelisted for s in forward_samples(given, REPORT)}
        assert found == {"BTC": True, "SOL": False}
