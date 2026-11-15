"""Spec 0047 AC-10 (R-9): geçersiz arşiv ayarı ağa çıkmadan, hatanın adıyla reddedilir; toplayıcı
arşiv anahtarlarını tanır ama kullanmaz (plan Risk 1)."""

import pytest

from crytobot.news import load_archive_config, load_news_config

URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
SOURCE = {"name": "coindesk", "type": "rss", "url": "https://www.coindesk.com/rss"}


def document(**changes: object) -> dict[str, object]:
    table: dict[str, object] = {
        "store_path": "news.db",
        "log_path": "news.log",
        "archive_store_path": "archive.db",
        "archive_log_path": "archive.log",
        "archive_url": URL,
        "sources": [dict(SOURCE)],
    }
    for key, value in changes.items():
        if value is None:
            table.pop(key, None)
        else:
            table[key] = value
    return {"news": table}


def test_valid_archive_config_and_defaults() -> None:
    result = load_archive_config(document())
    assert result.config is not None, result.message
    config = result.config
    assert (config.store_path, config.log_path, config.url) == ("archive.db", "archive.log", URL)
    assert config.request_gap_s == 1
    assert config.max_response_bytes == 2048 * 1024
    assert config.news.store_path == "news.db"


def test_gap_of_one_and_more_accepted() -> None:
    config = load_archive_config(document(archive_request_gap_s=3)).config
    assert config is not None and config.request_gap_s == 3


def test_collector_knows_archive_keys_but_ignores_them() -> None:
    """Toplayıcı arşiv anahtarlarını bilinmeyen saymaz, değerlerini denetlemez."""
    assert load_news_config(document()).config is not None
    loose = document(archive_url="ftp://x", archive_request_gap_s=0)
    assert load_news_config(loose).config is not None
    assert load_news_config(document(archive_store_path=None)).config is not None


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"archive_store_path": None}, "ayar eksik: news.archive_store_path"),
        ({"archive_log_path": None}, "ayar eksik: news.archive_log_path"),
        ({"archive_url": None}, "ayar eksik: news.archive_url"),
        ({"archive_store_path": ""}, "ayar geçersiz: news.archive_store_path"),
        ({"archive_store_path": 3}, "ayar geçersiz: news.archive_store_path"),
        ({"archive_log_path": "  "}, "ayar geçersiz: news.archive_log_path"),
        ({"archive_url": "http://binance.com/x"}, "ayar geçersiz: news.archive_url (https değil)"),
        ({"archive_url": "https://"}, "ayar geçersiz: news.archive_url (https değil)"),
        ({"archive_url": ""}, "ayar geçersiz: news.archive_url"),
        ({"archive_request_gap_s": 0}, "ayar geçersiz: news.archive_request_gap_s"),
        ({"archive_request_gap_s": -5}, "ayar geçersiz: news.archive_request_gap_s"),
        ({"archive_request_gap_s": 1.5}, "ayar geçersiz: news.archive_request_gap_s"),
        ({"archive_request_gap_s": True}, "ayar geçersiz: news.archive_request_gap_s"),
        ({"archive_request_gap_s": "1"}, "ayar geçersiz: news.archive_request_gap_s"),
        # the archive cannot be the forward store, its log, or its own log (literal spelling here)
        ({"archive_store_path": "news.db"}, "ayar geçersiz: news.archive_store_path"),
        ({"archive_store_path": "news.log"}, "ayar geçersiz: news.archive_store_path"),
        ({"archive_log_path": "news.db"}, "ayar geçersiz: news.archive_log_path"),
        ({"archive_log_path": "news.log"}, "ayar geçersiz: news.archive_log_path"),
        ({"archive_log_path": "archive.db"}, "ayar geçersiz: news.archive_log_path"),
        # the whole file must be valid: a collector problem refuses the archive too
        ({"interval_minutes": 1}, "ayar geçersiz: news.interval_minutes"),
        ({"sources": None}, "ayar eksik: news.sources"),
        ({"archive_extra": 1}, "bilinmeyen ayar: news.archive_extra"),
    ],
)
def test_invalid_archive_config_refused_by_name(changes: dict[str, object], message: str) -> None:
    result = load_archive_config(document(**changes))
    assert (result.config, result.message) == (None, message)


def test_raw_value_never_in_message() -> None:
    secret = "https://user:hunter2@example.com/x?token=abc"
    result = load_archive_config(document(archive_store_path="news.db", archive_url=secret))
    assert result.config is None
    assert "hunter2" not in result.message and "token" not in result.message
