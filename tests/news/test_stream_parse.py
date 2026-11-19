"""Spec 0056 AC-3, AC-4 (plan A-1): resmi duyuru akışının iletisi.

Fikstür `fixtures/stream/doc-example.json` Binance belgesindeki örnektir ("Announcements", Full
Response Example); gerçek ileti yoklamada görülünce yanına eklenir (plan A-2).
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crytobot.news._items import prepare
from crytobot.news._parse import CONTROL, parse_stream_message

DOC = (Path(__file__).parent / "fixtures" / "stream" / "doc-example.json").read_text(
    encoding="utf-8"
)
LIMIT = 2048 * 1024
SEEN = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


def message(**inner: object) -> str:
    data = {
        "catalogId": 48,
        "catalogName": "New Cryptocurrency Listing",
        "publishDate": 1795000000000,
    }
    data.update(
        {"title": "Binance Will List ABC", "body": "Binance will list ABC.", "disclaimer": "d"}
    )
    data.update(inner)
    return json.dumps({"type": "DATA", "topic": "com_announcement_en", "data": json.dumps(data)})


def test_doc_example_read() -> None:
    raw = parse_stream_message(DOC, LIMIT)
    assert raw is not None and not isinstance(raw, str)
    digest = hashlib.sha256(b"Notice of...").hexdigest()[:16]
    assert raw.item_id == f"akış:1753257631403:{digest}"
    assert (raw.title, raw.text, raw.link) == ("Notice of...", "This is...", None)
    assert raw.published == datetime.fromtimestamp(1753257631403 / 1000, UTC)
    item = prepare(raw, SEEN)
    assert item is not None and item.key == f"id:akış:1753257631403:{digest}"
    assert "Trade on-the-go" not in item.text  # the disclaimer is not the announcement


def test_same_announcement_same_key() -> None:
    first, second = parse_stream_message(message(), LIMIT), parse_stream_message(message(), LIMIT)
    other = parse_stream_message(message(title="Binance Will List XYZ"), LIMIT)
    assert first == second and first != other


def test_control_messages_are_not_announcements() -> None:
    register = '{"type":"COMMAND","subType":"REGISTER","data":"SUCCESS","code":"00000000"}'
    assert parse_stream_message(register, LIMIT) == CONTROL


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"type":"DATA","topic":"com_announcement_zh","data":"{}"}',
        '{"type":"PUSH","topic":"com_announcement_en","data":"{}"}',
        '{"type":"DATA","topic":"com_announcement_en","data":{"title":"x"}}',
        '{"type":"DATA","topic":"com_announcement_en","data":"not json"}',
        message(title=5),
        message(title=None),
        message(body=["x"]),
    ],
)
def test_invalid_messages_counted(text: str) -> None:
    assert parse_stream_message(text, LIMIT) is None


def test_over_limit_invalid() -> None:
    text = message(body="x" * 100)
    assert parse_stream_message(text, len(text.encode()) - 1) is None
    assert parse_stream_message(text, len(text.encode())) is not None


@pytest.mark.parametrize("publish", ["yesterday", None, True, 10**30])
def test_bad_publish_time_unknown(publish: object) -> None:
    raw = parse_stream_message(message(publishDate=publish), LIMIT)
    assert raw is not None and not isinstance(raw, str)
    assert raw.published is None and raw.title == "Binance Will List ABC"


def test_future_publish_time_unknown_after_prepare() -> None:
    later = int(SEEN.timestamp() * 1000) + 10 * 60 * 1000
    raw = parse_stream_message(message(publishDate=later), LIMIT)
    assert raw is not None and not isinstance(raw, str)
    item = prepare(raw, SEEN)
    assert item is not None and item.published is None and item.first_seen == SEEN
