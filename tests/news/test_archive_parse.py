"""Spec 0047 AC-2, AC-6 (JSON yarısı): arşiv sayfasının ayrıştırılması ve arşiv kaydının kuralları.

Gerçek uçtan bir kez alınmış yanıtlar `fixtures/archive/` altındadır (2026-11-15; keşif
`pageSize=1`, 128 kataloğunun 1. ve son sayfası, son sayfadan sonraki boş yanıt). Sapmalar
sentetiktir.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crytobot.news import (
    TEXT_LIMIT_BYTES,
    ParseError,
    RawItem,
    parse_binance_page,
    prepare_archive,
)

FIXTURES = Path(__file__).parent / "fixtures" / "archive"
AT = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def page(*articles: object, **catalog: object) -> bytes:
    body: dict[str, object] = {
        "catalogId": 128,
        "catalogName": "Crypto Airdrop",
        "total": 53,
        "articles": list(articles),
        "catalogs": [],
    }
    body.update(catalog)
    return json.dumps({"code": "000000", "data": {"catalogs": [body]}}).encode()


def article(**changes: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "id": 41506,
        "code": "983a85523b36455b8d802b2c3723fa5f",
        "title": "Binance Will Support the Symbol (XYM) Airdrop",
        "type": 1,
        "releaseDate": 1607065201605,
    }
    for key, value in changes.items():
        if value is None:
            raw.pop(key)
        else:
            raw[key] = value
    return raw


def test_discovery_lists_every_catalog_with_name_and_total() -> None:
    pages = parse_binance_page(fixture("discovery.json"))
    assert [(each.catalog_id, each.name, each.total) for each in pages] == [
        (48, "New Cryptocurrency Listing", 2294),
        (49, "Latest Binance News", 4503),
        (93, "Latest Activities", 3234),
        (161, "Delisting", 446),
        (157, "Maintenance Updates", 615),
        (51, "API Updates", 81),
        (128, "Crypto Airdrop", 53),
    ]
    assert all(len(each.articles) == 1 for each in pages)


def test_recorded_catalog_pages() -> None:
    first = parse_binance_page(fixture("catalog_first.json"))
    last = parse_binance_page(fixture("catalog_last.json"))
    assert [(each.catalog_id, len(each.articles)) for each in first] == [(128, 50)]
    assert [(each.catalog_id, len(each.articles)) for each in last] == [(128, 3)]
    assert parse_binance_page(fixture("catalog_after_last.json")) == []
    oldest = last[0].articles[-1]
    assert oldest == RawItem(
        "32912",
        "https://www.binance.com/en/support/announcement/a87d145bd0644720bf93599cc5f5a3de",
        "Binance Will Support the Bella (BEL) Airdrop Program for ARPA (ARPA) Holders",
        "",
        datetime(2020, 9, 29, 12, 5, 30, 422000, tzinfo=UTC),
    )


def test_publish_unknown_missing_unreadable_future() -> None:
    """AC-2: eksik, okunamayan ya da 5 dakikadan daha ileri yayın anı bilinmiyor; kayıt yazılır."""
    future = int((AT + timedelta(minutes=5, milliseconds=1)).timestamp() * 1000)
    raws = parse_binance_page(
        page(
            article(id=1, releaseDate=None),
            article(id=2, releaseDate="2020-01-01"),
            article(id=3, releaseDate=10**20),
            article(id=4, releaseDate=True),
            article(id=5, releaseDate=future),
        )
    )[0].articles
    items = [prepare_archive(raw, AT) for raw in raws if raw is not None]
    assert [item.article_id for item in items if item is not None] == ["1", "2", "3", "4", "5"]
    assert all(item is not None and item.published is None for item in items)


def test_exactly_five_minutes_not_flagged() -> None:
    exact = int((AT + timedelta(minutes=5)).timestamp() * 1000)
    raw = parse_binance_page(page(article(releaseDate=exact)))[0].articles[0]
    assert raw is not None
    item = prepare_archive(raw, AT)
    assert item is not None and item.published == AT + timedelta(minutes=5)
    assert item.archived_at == AT


def test_missing_id_or_empty_title_invalid() -> None:
    """AC-2: kimliksiz ya da başlığı boş duyuru yazılmaz, geçersiz sayılır."""
    raws = parse_binance_page(
        page(
            article(id=None),
            article(id="41506"),
            article(id=True),
            article(title=None),
            article(title=7),
            article(id=9, title="   "),
            article(id=10),
        )
    )[0].articles
    assert raws[:5] == [None] * 5
    prepared = [None if raw is None else prepare_archive(raw, AT) for raw in raws]
    assert prepared[5] is None
    assert prepared[6] is not None and prepared[6].article_id == "10"


def test_unsafe_code_written_without_link() -> None:
    raws = parse_binance_page(page(article(code="../x?y"), article(id=2, code=None)))[0].articles
    assert [raw.link if raw is not None else "-" for raw in raws] == [None, None]


def test_title_truncated_flagged() -> None:
    """AC-2, G-6: 20 KB'ı aşan başlık 0046'nın kuralıyla kesilir, kayıt işaretlidir."""
    long_title = "ğ" * (TEXT_LIMIT_BYTES // 2 + 1)
    exact = "a" * TEXT_LIMIT_BYTES
    raws = parse_binance_page(page(article(title=long_title), article(id=2, title=exact)))
    items = [prepare_archive(raw, AT) for raw in raws[0].articles if raw is not None]
    first, second = items
    assert first is not None and first.truncated
    assert len(first.title.encode("utf-8")) <= TEXT_LIMIT_BYTES
    assert second is not None and not second.truncated and second.title == exact


@pytest.mark.parametrize(
    ("body", "name"),
    [
        (b"{not json", "bad_json"),
        (b"\xff\xfe", "bad_json"),
        (b"[]", "bad_schema"),
        (b'{"data": {}}', "bad_schema"),
        (b'{"data": {"catalogs": {}}}', "bad_schema"),
        (b'{"data": {"catalogs": [1]}}', "bad_schema"),
        (page("not an object"), "bad_schema"),
        (page(catalogId="128"), "bad_schema"),
        (page(catalogName=""), "bad_schema"),
        (page(catalogName="x" * 129), "bad_schema"),
        (page(catalogName="a\nb"), "bad_schema"),
        (page(total=-1), "bad_schema"),
        (page(total=None), "bad_schema"),
        (page(articles=None), "bad_schema"),
        (page(catalogs=[{"catalogId": 1}]), "bad_schema"),
        (page(catalogs={}), "bad_schema"),
    ],
)
def test_schema_errors(body: bytes, name: str) -> None:
    with pytest.raises(ParseError) as raised:
        parse_binance_page(body)
    assert raised.value.name == name


def test_same_catalog_twice_is_bad_schema() -> None:
    one = json.loads(page(article()))["data"]["catalogs"][0]
    body = json.dumps({"data": {"catalogs": [one, one]}}).encode()
    with pytest.raises(ParseError):
        parse_binance_page(body)


def test_deep_json_is_bad_json() -> None:
    with pytest.raises(ParseError) as raised:
        parse_binance_page(b"[" * 100_000 + b"]" * 100_000)
    assert raised.value.name == "bad_json"
