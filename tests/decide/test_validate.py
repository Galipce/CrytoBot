"""Spec 0059 AC-4: şemaya uymayan yanıt bütünüyle atılır; her tutarlılık kuralı yalnız o coini."""

import json

import pytest

from crytobot.decide import Status, check_reply
from tests.decide.helpers import buy_entry, reply, wait_entry

RANGES = {"SOL": (90.0, 110.0), "ETH": (45.0, 55.0)}


def test_valid_reply() -> None:
    checked = check_reply(reply(buy_entry("SOL", 98.0, 100.0), wait_entry("ETH")), RANGES)
    assert checked.schema_reason is None
    sol, eth = checked.decisions
    assert sol.status is Status.BUY and sol.entry_low == 98.0 and sol.valid_hours == 4
    assert sol.action == "al" and sol.reasons == ("rsi14 50 üstü", "fiyat ema50 üstünde")
    assert eth.status is Status.WAIT and eth.entry_low is None


def test_fence_stripped() -> None:
    text = "```json\n" + reply(wait_entry("SOL"), wait_entry("ETH")) + "\n```"
    assert check_reply(text, RANGES).schema_reason is None


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "bekle",
        "[]",
        json.dumps({"decisions": [wait_entry("SOL")]}),  # a coin missing
        reply(wait_entry("SOL"), wait_entry("ETH"), wait_entry("BTC")),  # an extra coin
        reply(wait_entry("SOL"), wait_entry("SOL")),  # a coin twice
        json.dumps({"decisions": [wait_entry("SOL"), wait_entry("ETH")], "note": "x"}),
        reply(wait_entry("SOL"), {**wait_entry("ETH"), "extra": 1}),  # unknown field
        reply(wait_entry("SOL"), {k: v for k, v in wait_entry("ETH").items() if k != "stop"}),
        reply(wait_entry("SOL"), {**wait_entry("ETH"), "action": "sat"}),
        reply(buy_entry("SOL", 98.0, 100.0, stop="97"), wait_entry("ETH")),  # number as text
        reply(buy_entry("SOL", 98.0, 100.0, valid_hours=2.5), wait_entry("ETH")),
        reply(buy_entry("SOL", 98.0, 100.0, confidence=True), wait_entry("ETH")),
        reply(buy_entry("SOL", 98.0, 100.0, reasons="tek metin"), wait_entry("ETH")),
        '{"decisions": [], "decisions": []}',  # duplicate key
        reply(wait_entry("SOL"), wait_entry("ETH")).replace("null", "NaN", 1),
        "x" * (64 * 1024 + 1),
    ],
)
def test_schema_violations_drop_turn(text: str | None) -> None:
    checked = check_reply(text, RANGES)
    assert checked.schema_reason is not None
    assert [d.status for d in checked.decisions] == [Status.SCHEMA, Status.SCHEMA]
    assert [d.coin for d in checked.decisions] == ["SOL", "ETH"]


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"entry_low": 101.0, "entry_high": 100.0}, "giriş bölgesi ters"),
        ({"stop": 98.0}, "stop girişin altında değil"),
        ({"target": 100.0}, "hedef girişin üstünde değil"),
        ({"stop": 71.0}, "fiyat aralık dışı"),  # below 90 * 0.8 = 72
        ({"target": 133.0}, "fiyat aralık dışı"),  # above 110 * 1.2 = 132
        ({"valid_hours": 0}, "geçerlilik aralık dışı"),
        ({"valid_hours": 5}, "geçerlilik aralık dışı"),
        ({"confidence": 0}, "güven aralık dışı"),
        ({"confidence": 6}, "güven aralık dışı"),
        ({"reasons": []}, "gerekçe"),
        ({"reasons": ["a", "b", "c", "d"]}, "gerekçe"),
        ({"reasons": [" "]}, "gerekçe"),
        ({"stop": None}, "seviye eksik"),
    ],
)
def test_each_consistency_rule_drops_only_that_coin(
    changes: dict[str, object], reason: str
) -> None:
    checked = check_reply(
        reply(buy_entry("SOL", 98.0, 100.0, **changes), wait_entry("ETH")), RANGES
    )
    assert checked.schema_reason is None
    sol, eth = checked.decisions
    assert sol.status is Status.INCONSISTENT and sol.reason == reason
    assert sol.action == "al"  # Claude's own fields are kept (R-5)
    assert eth.status is Status.WAIT


def test_edge_of_range_is_kept() -> None:
    entry = buy_entry("SOL", 98.0, 100.0, stop=72.0, target=132.0)
    checked = check_reply(reply(entry, wait_entry("ETH")), RANGES)
    assert checked.decisions[0].status is Status.BUY


def test_wait_with_too_many_reasons_inconsistent() -> None:
    entry = {**wait_entry("ETH"), "reasons": ["a", "b", "c", "d"]}
    checked = check_reply(reply(wait_entry("SOL"), entry), RANGES)
    assert checked.decisions[1].status is Status.INCONSISTENT
