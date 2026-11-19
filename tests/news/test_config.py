"""Spec 0046 AC-9: geçersiz ayar ilk sorunun adıyla reddedilir; ham değer mesajda yok."""

import pytest

from crytobot.news import load_news_config
from tests.news.test_source_permission import PERMISSION

SOURCE = {
    "name": "coindesk",
    "type": "rss",
    "url": "https://www.coindesk.com/arc/outboundfeeds/rss",
    **PERMISSION,
}


def document(**changes: object) -> dict[str, object]:
    table: dict[str, object] = {
        "store_path": "news.db",
        "log_path": "news.log",
        "sources": [dict(SOURCE)],
    }
    for key, value in changes.items():
        if value is None:
            table.pop(key, None)
        else:
            table[key] = value
    return {"news": table}


def with_source(**changes: object) -> dict[str, object]:
    source: dict[str, object] = dict(SOURCE)
    for key, value in changes.items():
        if value is None:
            source.pop(key)
        else:
            source[key] = value
    return document(sources=[source])


def test_defaults() -> None:
    result = load_news_config(document())
    assert result.config is not None, result.message
    config = result.config
    assert (config.interval_minutes, config.max_response_kb, config.source_alert_hours) == (
        15,
        2048,
        6,
    )
    assert config.max_response_bytes == 2048 * 1024
    assert config.sources[0].enabled is True
    assert config.sources[0].kind == "rss"


def test_lowest_interval_accepted() -> None:
    assert load_news_config(document(interval_minutes=5)).config is not None


@pytest.mark.parametrize(
    ("doc", "message"),
    [
        ({}, "ayar eksik: news"),
        ({"news": {}, "bot": {}}, "bilinmeyen ayar: bot"),
        (document(sources=None), "ayar eksik: news.sources"),
        (document(sources=[]), "ayar eksik: news.sources"),
        (document(sources="x"), "ayar geçersiz: news.sources"),
        (with_source(type="atom"), "ayar geçersiz: news.sources[1].type (bilinmeyen tür)"),
        (
            document(sources=[dict(SOURCE), dict(SOURCE)]),
            "ayar geçersiz: news.sources[2].name (aynı ad iki kez)",
        ),
        (with_source(url=None), "ayar eksik: news.sources[1].url"),
        (with_source(url="http://x.org/rss"), "ayar geçersiz: news.sources[1].url (https değil)"),
        (with_source(url="ftp://x.org/rss"), "ayar geçersiz: news.sources[1].url (https değil)"),
        (with_source(url="https:///rss"), "ayar geçersiz: news.sources[1].url (https değil)"),
        (with_source(url=""), "ayar geçersiz: news.sources[1].url"),
        (with_source(name=None), "ayar eksik: news.sources[1].name"),
        (with_source(name=""), "ayar geçersiz: news.sources[1].name"),
        (with_source(name="a\nb"), "ayar geçersiz: news.sources[1].name"),
        (with_source(type=None), "ayar eksik: news.sources[1].type"),
        (with_source(enabled="yes"), "ayar geçersiz: news.sources[1].enabled"),
        (with_source(extra=1), "bilinmeyen ayar: news.sources[1].extra"),
        (document(interval_minutes=4), "ayar geçersiz: news.interval_minutes"),
        (document(interval_minutes=0), "ayar geçersiz: news.interval_minutes"),
        (document(interval_minutes=True), "ayar geçersiz: news.interval_minutes"),
        (document(interval_minutes="15"), "ayar geçersiz: news.interval_minutes"),
        (document(max_response_kb=0), "ayar geçersiz: news.max_response_kb"),
        (document(max_response_kb=-1), "ayar geçersiz: news.max_response_kb"),
        (document(source_alert_hours=0), "ayar geçersiz: news.source_alert_hours"),
        (document(source_alert_hours=-6), "ayar geçersiz: news.source_alert_hours"),
        (document(store_path=None), "ayar eksik: news.store_path"),
        (document(log_path=None), "ayar eksik: news.log_path"),
        (document(log_path="news.db"), "ayar geçersiz: news.log_path"),
        (document(unknown=1), "bilinmeyen ayar: news.unknown"),
    ],
)
def test_invalid_config_refused_by_name(doc: dict[str, object], message: str) -> None:
    result = load_news_config(doc)
    assert result.config is None
    assert result.message == message


def test_message_never_carries_the_value() -> None:
    result = load_news_config(with_source(url="http://x.org/rss?token=SECRET"))
    assert "SECRET" not in result.message
