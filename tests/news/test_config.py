"""Spec 0046 AC-9: geçersiz ayar ilk sorunun adıyla reddedilir; ham değer mesajda yok."""

import pytest

from crytobot.news import (
    BINANCE_KINDS,
    DEFAULT_KEY_ENV,
    DEFAULT_SECRET_ENV,
    STREAM_KIND,
    NewsConfig,
    load_news_config,
)
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


STREAM_URL = "wss://api.binance.com/sapi/wss"


def stream(**changes: object) -> dict[str, object]:
    table: dict[str, object] = {
        "name": "binance-akış",
        "type": "binance-akış",
        "url": STREAM_URL,
        "enabled": False,
    }
    table.update(changes)
    return table


def load_stream(raw: dict[str, object]) -> tuple[NewsConfig | None, str]:
    result = load_news_config(
        {"news": {"store_path": "n.db", "log_path": "n.log", "sources": [raw]}}
    )
    return result.config, result.message


def test_stream_source_requires_env_names() -> None:
    """Spec 0056 AC-1 (plan A-1): akış türü yalnız `wss`; ortam değişkeni adları varsayılanlı,
    verilmişse geçerli ve farklı olmalı; başka türde kabul edilmez."""
    config, message = load_stream(stream())
    assert config is not None, message
    (source,) = config.sources
    assert (source.kind, source.key_env, source.secret_env) == (
        STREAM_KIND,
        DEFAULT_KEY_ENV,
        DEFAULT_SECRET_ENV,
    )
    config, _ = load_stream(stream(api_key_env="MY_KEY", api_secret_env="MY_SECRET"))
    assert config is not None and (config.sources[0].key_env, config.sources[0].secret_env) == (
        "MY_KEY",
        "MY_SECRET",
    )
    prefix = "ayar geçersiz: news.sources[1]"
    for raw, message in (
        (stream(url="https://api.binance.com/sapi/wss"), f"{prefix}.url (wss değil)"),
        (stream(api_key_env="my key"), f"{prefix}.api_key_env"),
        (stream(api_key_env=""), f"{prefix}.api_key_env"),
        (stream(api_secret_env=5), f"{prefix}.api_secret_env"),
        (stream(api_secret_env=DEFAULT_KEY_ENV), f"{prefix}.api_secret_env (api_key_env ile aynı)"),
        (
            {
                "name": "r",
                "type": "rss",
                "url": "https://x.org/r",
                "enabled": False,
                "api_key_env": "K",
            },
            f"{prefix}.api_key_env (yalnız binance-akış)",
        ),
        (
            {"name": "r", "type": "rss", "url": STREAM_URL, "enabled": False},
            f"{prefix}.url (https değil)",
        ),
    ):
        assert load_stream(raw) == (None, message)
    assert {"binance-duyuru", STREAM_KIND} == BINANCE_KINDS
