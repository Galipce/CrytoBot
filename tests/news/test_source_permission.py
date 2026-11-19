"""Spec 0055 CB-1, PB-3: açık kaynak AI kullanım izni kaydı ister; kayıt adıyla doğrulanır."""

from datetime import date, datetime

import pytest

from crytobot.news import NewsConfig, Permission, load_news_config, permission_in_future

PERMISSION: dict[str, object] = {
    "ai_permission_by": "Sahip",
    "ai_permission_on": date(2026, 11, 19),
    "ai_permission_basis": "Koşullar §4: AI ile işlemeye izin",
}


def source(**changes: object) -> dict[str, object]:
    table: dict[str, object] = {
        "name": "akış",
        "type": "rss",
        "url": "https://example.org/rss",
        **PERMISSION,
    }
    for key, value in changes.items():
        if value is None:
            table.pop(key, None)
        else:
            table[key] = value
    return table


def load(*sources: dict[str, object]) -> tuple[NewsConfig | None, str]:
    result = load_news_config(
        {"news": {"store_path": "n.db", "log_path": "n.log", "sources": list(sources)}}
    )
    return result.config, result.message


def test_permitted_source_loaded() -> None:
    config, message = load(source())
    assert config is not None, message
    assert config.sources[0].permission == Permission(
        "Sahip", date(2026, 11, 19), "Koşullar §4: AI ile işlemeye izin"
    )
    assert config.sources[0].permitted
    assert config.permitted_names == frozenset({"akış"})


@pytest.mark.parametrize("key", ["ai_permission_by", "ai_permission_on", "ai_permission_basis"])
def test_open_source_requires_permission(key: str) -> None:
    """Açık kaynakta kayıt yoksa ya da bir alanı eksikse ret; mesaj sırayı ve alanı söyler."""
    assert load(source(**{key: None})) == (None, f"ayar eksik: news.sources[1].{key}")


def test_open_source_without_any_permission_refused() -> None:
    bare = source(ai_permission_by=None, ai_permission_on=None, ai_permission_basis=None)
    second = dict(bare, name="ikinci")
    assert load(source(), second) == (None, "ayar eksik: news.sources[2].ai_permission_by")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"ai_permission_by": ""}, "ayar geçersiz: news.sources[1].ai_permission_by"),
        ({"ai_permission_by": "   "}, "ayar geçersiz: news.sources[1].ai_permission_by"),
        ({"ai_permission_by": 7}, "ayar geçersiz: news.sources[1].ai_permission_by"),
        ({"ai_permission_basis": ""}, "ayar geçersiz: news.sources[1].ai_permission_basis"),
        ({"ai_permission_basis": "a\nb"}, "ayar geçersiz: news.sources[1].ai_permission_basis"),
        (
            {"ai_permission_basis": "x" * 1025},
            "ayar geçersiz: news.sources[1].ai_permission_basis",
        ),
        (
            {"ai_permission_on": "2026-11-19"},
            "ayar geçersiz: news.sources[1].ai_permission_on (tarih değil)",
        ),
        (
            {"ai_permission_on": datetime(2026, 11, 19, 10, 0)},
            "ayar geçersiz: news.sources[1].ai_permission_on (tarih değil)",
        ),
        (
            {"ai_permission_on": 20261119},
            "ayar geçersiz: news.sources[1].ai_permission_on (tarih değil)",
        ),
    ],
)
def test_partial_or_invalid_permission_named(changes: dict[str, object], message: str) -> None:
    config, found = load(source(**changes))
    assert (config, found) == (None, message)
    assert "Sahip" not in found and "Koşullar" not in found  # ham değer mesajda yok


def test_closed_source_permission_optional_but_checked() -> None:
    bare = source(
        enabled=False, ai_permission_by=None, ai_permission_on=None, ai_permission_basis=None
    )
    config, message = load(bare)
    assert config is not None, message
    assert config.sources[0].permission is None
    assert not config.sources[0].permitted
    assert config.permitted_names == frozenset()
    # a closed source with a record keeps it, but is not permitted
    config, message = load(source(enabled=False))
    assert config is not None, message
    assert config.sources[0].permission is not None
    assert not config.sources[0].permitted
    # a partial record on a closed source is refused like on an open one
    assert load(source(enabled=False, ai_permission_basis=None)) == (
        None,
        "ayar eksik: news.sources[1].ai_permission_basis",
    )


def test_unknown_key_still_refused() -> None:
    assert load(source(ai_permission=True)) == (
        None,
        "bilinmeyen ayar: news.sources[1].ai_permission",
    )


def test_permission_date_future_check() -> None:
    config, message = load(source(), source(name="ikinci", ai_permission_on=date(2026, 11, 20)))
    assert config is not None, message
    assert permission_in_future(config, date(2026, 11, 20)) is None  # today is valid
    assert (
        permission_in_future(config, date(2026, 11, 19))
        == "ayar geçersiz: news.sources[2].ai_permission_on (gelecekte)"
    )


def test_stream_source_requires_permission() -> None:
    """Spec 0056 PB-2: akış kaynağına da 0055 kuralı aynen uygulanır."""
    raw = source(name="b", type="binance-akış", url="wss://api.binance.com/sapi/wss")
    config, message = load(raw)
    assert config is not None, message
    assert config.permitted_names == {"b"}
    for key in ("ai_permission_by", "ai_permission_on", "ai_permission_basis"):
        assert load(source(name="b", type="binance-akış", url="wss://x.org/w", **{key: None})) == (
            None,
            f"ayar eksik: news.sources[1].{key}",
        )
