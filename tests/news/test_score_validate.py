"""Spec 0051 AC-3 (plan step 5, Risk 5): şemaya uymayan yanıt bütünüyle "şema dışı"; şemaya uyan
yanıtta her ret nedeni yalnız o olay skorunu reddeder, nedeni sayılır, geçerliler kalır."""

import json
from typing import Any

import pytest

from crytobot.news._score_store import EventScore
from crytobot.news._score_validate import (
    BAD_DIRECTION,
    BAD_ITEM,
    BAD_ROOT,
    BAD_SEVERITY,
    BAD_TYPE,
    DUPLICATE,
    EMPTY_QUOTE,
    NAME_NOT_QUOTED,
    NO_PAIR,
    NOT_JSON,
    NOT_VERBATIM,
    REPLY_LIMIT_BYTES,
    TOO_LARGE,
    TOO_MANY,
    check_reply,
)

TITLE = "Binance Will Delist ABC and XYZ on 2026-12-01"
BODY = "Binance will delist  Alpha Coin (ABC)\nand XYZ.\nUsers should withdraw."
PAIRS = frozenset({"ABC", "XYZ", "BTC"})


def event(**changes: object) -> dict[str, Any]:
    item: dict[str, Any] = {
        "coin": "ABC",
        "name": "Alpha Coin",
        "event_type": "listeden çıkarma",
        "direction": "olumsuz",
        "severity": 2,
        "quote": "Binance will delist Alpha Coin (ABC) and XYZ.",
    }
    item.update(changes)
    return item


def reply(*items: object) -> str:
    return json.dumps({"events": list(items)}, ensure_ascii=False)


def test_valid_scores_and_whitespace_relaxation() -> None:
    xyz = event(coin="XYZ", name="XYZ", quote="Delist ABC and XYZ", severity=3)
    checked = check_reply(reply(event(), xyz), False, TITLE, BODY, PAIRS)
    assert checked.schema_reason is None and checked.rejections == ()
    assert checked.scores == (
        EventScore(
            "ABC",
            "Alpha Coin",
            "listeden çıkarma",
            "olumsuz",
            2,
            "Binance will delist Alpha Coin (ABC) and XYZ.",
        ),
        EventScore("XYZ", "XYZ", "listeden çıkarma", "olumsuz", 3, "Delist ABC and XYZ"),
    )  # the double space and the line break in BODY count as one space; the title is quotable
    empty = check_reply('{"events": []}', False, TITLE, BODY, PAIRS)
    assert (empty.scores, empty.rejections, empty.schema_reason) == ((), (), None)


@pytest.mark.parametrize(
    ("text", "overflow", "reason"),
    [
        ("not json", False, NOT_JSON),
        ('```json\n{"events": []}\n```', False, NOT_JSON),
        ('{"events": [], "events": []}', False, NOT_JSON),
        ('{"events": [{"coin": NaN}]}', False, NOT_JSON),
        ("[]", False, BAD_ROOT),
        ('{"events": {}}', False, BAD_ROOT),
        ('{"events": [], "note": "x"}', False, BAD_ROOT),
        (reply(*[event(coin=f"C{i}") for i in range(21)]), False, TOO_MANY),
        (reply({k: v for k, v in event().items() if k != "quote"}), False, BAD_ITEM),
        (reply({**event(), "confidence": 1}), False, BAD_ITEM),
        (reply(event(), "text"), False, BAD_ITEM),
        ('{"events": []}' + " " * REPLY_LIMIT_BYTES, False, TOO_LARGE),
        ('{"events": []}', True, TOO_LARGE),
        (None, False, TOO_LARGE),
    ],
    ids=[
        "unparseable",
        "code-fence",
        "duplicate-key",
        "nan",
        "root-list",
        "events-object",
        "extra-root-field",
        "21-scores",
        "missing-field",
        "extra-field",
        "item-not-object",
        "over-16kb",
        "process-overflow",
        "no-text",
    ],
)
def test_schema_rejects(text: str | None, overflow: bool, reason: str) -> None:
    checked = check_reply(text, overflow, TITLE, BODY, PAIRS)
    assert checked.schema_reason == reason
    assert checked.scores == () and checked.rejections == ()


def test_twenty_scores_are_within_schema() -> None:
    items = [event(coin=f"C{i}") for i in range(20)]
    checked = check_reply(reply(*items), False, TITLE, BODY, PAIRS)
    assert checked.schema_reason is None
    assert checked.rejections == ((NO_PAIR, 20),)


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        (event(quote=""), EMPTY_QUOTE),
        (event(quote="   \n "), EMPTY_QUOTE),
        (event(quote=None), EMPTY_QUOTE),
        (event(quote="binance will delist Alpha Coin (ABC)"), NOT_VERBATIM),  # case
        (event(quote="Alpha Coin is delisted"), NOT_VERBATIM),
        (event(quote="Delist ABC and XYZ on 2026-12-01 Binance will"), NOT_VERBATIM),
        (event(name="Alpha"), None),  # partial name inside the quote is still inside: valid
        (event(name="Beta Coin"), NAME_NOT_QUOTED),
        (event(name="alpha coin"), NAME_NOT_QUOTED),
        (event(name=""), NAME_NOT_QUOTED),
        (event(name=7), NAME_NOT_QUOTED),
        (event(coin="QQQ", name="Alpha Coin"), NO_PAIR),
        (event(coin="abc"), NO_PAIR),
        (event(coin=1), NO_PAIR),
        (event(event_type="listing"), BAD_TYPE),
        (event(event_type="Listeden çıkarma"), BAD_TYPE),
        (event(direction="negative"), BAD_DIRECTION),
        (event(direction=None), BAD_DIRECTION),
        (event(severity="2"), BAD_SEVERITY),
        (event(severity=4), BAD_SEVERITY),
        (event(severity=0), BAD_SEVERITY),
        (event(severity=2.0), BAD_SEVERITY),
        (event(severity=True), BAD_SEVERITY),
    ],
)
def test_single_rejections(bad: dict[str, Any], reason: str | None) -> None:
    good = event(coin="XYZ", name="XYZ", quote="Delist ABC and XYZ")
    checked = check_reply(reply(good, bad), False, TITLE, BODY, PAIRS)
    assert checked.schema_reason is None
    kept = [score.coin for score in checked.scores]
    if reason is None:
        assert kept == ["XYZ", "ABC"] and checked.rejections == ()
    else:
        assert kept == ["XYZ"]  # only the bad score is rejected
        assert checked.rejections == ((reason, 1),)


def test_duplicate_coin_second_and_later() -> None:
    checked = check_reply(
        reply(event(), event(severity=3), event(name="ABC"), event(coin="XYZ", name="XYZ")),
        False,
        TITLE,
        BODY,
        PAIRS,
    )
    assert [(score.coin, score.severity) for score in checked.scores] == [("ABC", 2), ("XYZ", 2)]
    assert checked.rejections == ((DUPLICATE, 2),)


def test_reasons_counted_together() -> None:
    checked = check_reply(
        reply(
            event(severity=9),
            event(coin="XYZ", severity=9),
            event(coin="BTC", quote="x"),
            event(coin="QQQ", name="XYZ", quote="and XYZ"),
        ),
        False,
        TITLE,
        BODY,
        PAIRS,
    )
    assert checked.scores == ()
    assert dict(checked.rejections) == {BAD_SEVERITY: 2, NOT_VERBATIM: 1, NO_PAIR: 1}
    assert list(checked.rejections) == sorted(checked.rejections)  # one order, every run


def test_overflow_size_is_the_read_size() -> None:
    checked = check_reply(None, True, TITLE, BODY, PAIRS, read_size=65536)
    assert (checked.schema_reason, checked.size) == (TOO_LARGE, 65536)
