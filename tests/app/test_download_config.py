"""Spec 0023 AC-3, R-2: indirme ayarları; ilk sorunlu ayar adıyla, ham değer yazılmaz.

Eşlem `tomllib`'in verdiği biçimdir; dosyanın okunması ve "dosya yok / okunamıyor" giriş
noktasındadır (`tests/main/test_download_entry.py`). Burada dosyaya, borsaya ve depoya dokunulmaz.
Bu dosya `tests/tooling` kopyasına girer: yalnız `tests/app`'ten import eder.
"""

from datetime import UTC, date, datetime, timedelta, timezone
from datetime import time as clock_time
from typing import Any

import pytest

from crytobot.app import load_download_config
from tests.app.test_config import BASE, document

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 2, 1, tzinfo=UTC)
HISTORY: dict[str, Any] = {"data_path": "history.jsonl", "start": START, "end": END}


def download_document(**changes: Any) -> dict[str, Any]:
    """`changes`: `"bölüm.anahtar"` → değer (`None` siler); `history=None` bölümü siler."""
    history_changes = {k: v for k, v in changes.items() if k.startswith("history.")}
    bot_changes = {k: v for k, v in changes.items() if k not in history_changes and k != "history"}
    values: dict[str, Any] = document(**bot_changes)
    if "history" in changes:
        if changes["history"] is not None:
            values["history"] = changes["history"]
        return values
    history = dict(HISTORY)
    for name, value in history_changes.items():
        key = name.split(".", 1)[1]
        if value is None:
            history.pop(key, None)
        else:
            history[key] = value
    values["history"] = history
    return values


def refused(changes: dict[str, Any], now: datetime = NOW) -> str:
    result = load_download_config(download_document(**changes), now)
    assert result.config is None
    assert result.setting is not None
    return result.message


def test_valid_settings_give_the_request() -> None:
    result = load_download_config(download_document(), NOW)
    assert result.config is not None, result.message
    request = result.config.request()
    assert request.data_path == "history.jsonl"
    assert request.pairs == tuple(BASE["turn"]["whitelist"])
    assert request.start == START and request.end == END
    assert request.settings.candle_interval == timedelta(hours=1)
    assert request.settings.candle_count == BASE["market"]["candle_count"]
    assert request.settings.call_timeout == timedelta(seconds=BASE["market"]["call_timeout"])


def test_offset_zero_is_utc() -> None:
    plus_zero = START.replace(tzinfo=timezone(timedelta(0)))
    result = load_download_config(download_document(**{"history.start": plus_zero}), NOW)
    assert result.config is not None and result.config.start == START
    assert result.config.start.tzinfo is UTC


@pytest.mark.parametrize("key", ["data_path", "start", "end"])
def test_each_missing_setting_is_named(key: str) -> None:
    """AC-3: varsayılan yoktur."""
    assert refused({f"history.{key}": None}) == f"ayar eksik: history.{key}"


def test_missing_section_is_named() -> None:
    assert refused({"history": None}) == "ayar eksik: history"


@pytest.mark.parametrize("value", ["history", ["a"], 1])
def test_section_that_is_not_a_table_is_invalid(value: object) -> None:
    assert refused({"history": value}) == "ayar geçersiz: history"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("data_path", ""),
        ("data_path", 5),
        ("data_path", ["history.jsonl"]),
        ("data_path", BASE["bot"]["store_path"]),  # R-1: never the paper store
        ("data_path", BASE["bot"]["log_path"]),  # R-1: never the bot's log
        ("start", "2026-01-01T00:00:00Z"),
        ("start", date(2026, 1, 1)),
        ("start", datetime(2026, 1, 1)),  # a TOML local date-time: no zone
        ("start", START.replace(tzinfo=timezone(timedelta(hours=3)))),
        ("start", clock_time(0, 0)),
        ("start", 1767225600),
        ("start", START + timedelta(minutes=30)),  # not on a turn boundary
        ("start", START + timedelta(microseconds=1)),
        ("end", "2026-02-01T00:00:00Z"),
        ("end", datetime(2026, 2, 1)),
        ("end", END.replace(tzinfo=timezone(timedelta(hours=-5)))),
        ("end", START),  # equal to the start
        ("end", START - timedelta(hours=1)),  # before the start
        ("end", END + timedelta(minutes=1)),  # not on a turn boundary
        ("end", NOW + timedelta(hours=1)),  # after the download moment
    ],
)
def test_each_invalid_setting_is_named_without_its_value(key: str, value: object) -> None:
    message = refused({f"history.{key}": value})
    assert message == f"ayar geçersiz: history.{key}"


def test_end_at_the_download_moment_is_accepted() -> None:
    now = datetime(2026, 2, 1, tzinfo=UTC)
    assert load_download_config(download_document(), now).config is not None


def test_boundary_follows_the_turn_interval() -> None:
    """Sınır tur aralığınındır: 4 saatlik turda saat başı yetmez."""
    four_hours = {"bot.turn_interval": "4h", "history.start": START + timedelta(hours=1)}
    assert refused(four_hours) == "ayar geçersiz: history.start"
    on_boundary = {"bot.turn_interval": "4h", "history.start": START + timedelta(hours=4)}
    assert load_download_config(download_document(**on_boundary), NOW).config is not None


def test_unknown_key_in_the_section_is_refused() -> None:
    message = refused({"history.mode": "live"})
    assert message == "bilinmeyen ayar: history.mode"


def test_first_problem_wins_in_file_order() -> None:
    """Sıra: bot ayarları → data_path → start → end → bilinmeyen anahtar (plan Risk 10)."""
    everything = {
        "history.data_path": "",
        "history.start": "x",
        "history.end": "x",
        "history.extra": 1,
    }
    assert refused({"market.read_budget": 3600, **everything}) == (
        "ayar geçersiz: market.read_budget"
    )
    assert refused(everything) == "ayar geçersiz: history.data_path"
    assert refused({k: v for k, v in everything.items() if k != "history.data_path"}) == (
        "ayar geçersiz: history.start"
    )
    assert refused({"history.end": "x", "history.extra": 1}) == "ayar geçersiz: history.end"


def test_bot_problem_is_named_before_a_missing_section() -> None:
    assert refused({"bot.store_path": None, "history": None}) == "ayar eksik: bot.store_path"


def test_document_that_is_not_a_mapping_is_refused() -> None:
    result = load_download_config(["history"], NOW)
    assert result.config is None and result.message == "ayar geçersiz: ayar dosyası"
