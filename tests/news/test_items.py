"""Spec 0046 öğe kuralları: yayın anı (AC-3), 20 KB kesme ve geçersiz öğe (AC-4)."""

from datetime import UTC, datetime, timedelta

import pytest

from crytobot.news import TEXT_LIMIT_BYTES, RawItem
from crytobot.news._items import prepare, truncate_utf8

SEEN = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)


def raw(**changes: object) -> RawItem:
    values: dict[str, object] = {
        "item_id": "id-1",
        "link": "https://example.org/a",
        "title": "Başlık",
        "text": "<p>metin</p>",
        "published": SEEN - timedelta(hours=1),
    }
    values.update(changes)
    return RawItem(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "published",
    [None, SEEN + timedelta(minutes=5, microseconds=1), SEEN + timedelta(days=3)],
)
def test_publish_time_unknown_missing_unreadable_future(published: datetime | None) -> None:
    """AC-3: eksik/okunamaz (ayrıştırıcı `None` verir) ya da 5 dakikadan ileri → bilinmiyor; ilk
    görme anı her durumda yanıtın anı."""
    item = prepare(raw(published=published), SEEN)
    assert item is not None
    assert item.published is None
    assert item.first_seen == SEEN


def test_exactly_five_minutes_not_flagged() -> None:
    item = prepare(raw(published=SEEN + timedelta(minutes=5)), SEEN)
    assert item is not None
    assert item.published == SEEN + timedelta(minutes=5)


def test_truncation_boundaries_utf8() -> None:
    """AC-4: tam 20480 bayt işaretlenmez; fazlası kesilir; çok baytlı karakter bölünmez."""
    exact = "a" * TEXT_LIMIT_BYTES
    assert truncate_utf8(exact) == (exact, False)
    longer = "a" * (TEXT_LIMIT_BYTES + 1)
    assert truncate_utf8(longer) == ("a" * TEXT_LIMIT_BYTES, True)
    # "ş" is 2 bytes: it straddles the limit and is dropped whole
    split = "a" * (TEXT_LIMIT_BYTES - 1) + "ş"
    text, truncated = truncate_utf8(split)
    assert truncated
    assert text == "a" * (TEXT_LIMIT_BYTES - 1)
    # "€" is 3 bytes, the limit falls after its first byte or its second
    for pad in (TEXT_LIMIT_BYTES - 1, TEXT_LIMIT_BYTES - 2):
        text, truncated = truncate_utf8("a" * pad + "€" + "b")
        assert truncated and text == "a" * pad
    fits = "a" * (TEXT_LIMIT_BYTES - 3) + "€"
    assert truncate_utf8(fits) == (fits, False)

    item = prepare(raw(text="ğ" * TEXT_LIMIT_BYTES), SEEN)
    assert item is not None and item.truncated
    assert len(item.text.encode("utf-8")) == TEXT_LIMIT_BYTES


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "", "text": ""},
        {"title": "  \n", "text": "\t "},
        {"item_id": None, "link": None},
        {"item_id": "  ", "link": ""},
    ],
)
def test_empty_item_invalid(changes: dict[str, object]) -> None:
    assert prepare(raw(**changes), SEEN) is None


def test_title_or_text_alone_is_enough_and_link_is_key_without_id() -> None:
    only_text = prepare(raw(title="", item_id=None), SEEN)
    assert only_text is not None
    assert only_text.key == "link:https://example.org/a"
    assert prepare(raw(text=""), SEEN) is not None


def test_lone_surrogate_is_replaced() -> None:
    item = prepare(raw(title="a\ud800b"), SEEN)
    assert item is not None
    item.title.encode("utf-8")
