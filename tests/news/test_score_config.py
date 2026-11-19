"""Spec 0051 AC-5, AC-8 (plan step 2, A-1): `[score]` bölümü — zorunlu alanlar, varsayılanlar,
aralıklar, günlük sınırın sabit üst sınırı; toplayıcı ve arşiv aynı dosyayı `[score]`'la da kabul
eder."""

import tomllib
from pathlib import Path
from typing import Any

import pytest

from crytobot.news import load_archive_config, load_news_config
from crytobot.news._score_config import DAILY_CALL_HARD_CAP, load_score_config
from tests.news.test_source_permission import PERMISSION

SHA = "a" * 64


def news_table() -> dict[str, Any]:
    return {
        "store_path": "news.db",
        "log_path": "news.log",
        "archive_store_path": "archive.db",
        "archive_log_path": "archive.log",
        "archive_url": "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query",
        "sources": [
            {
                "name": "binance",
                "type": "binance-duyuru",
                "url": "https://example.org/a",
                **PERMISSION,
            }
        ],
    }


def score_table(**changes: object) -> dict[str, Any]:
    table: dict[str, Any] = {
        "store_path": "score.db",
        "log_path": "score.log",
        "model": "claude-sonnet-5-5",
        "calibration_report_path": "report.txt",
        "calibration_report_sha256": SHA,
        "library_path": "library.jsonl",
        "library_sha256": "b" * 64,
    }
    for key, value in changes.items():
        if value is None:
            table.pop(key)
        else:
            table[key] = value
    return table


def document(**changes: object) -> dict[str, Any]:
    return {"news": news_table(), "score": score_table(**changes)}


def test_valid_with_defaults() -> None:
    result = load_score_config(document())
    config = result.config
    assert config is not None, result.message
    assert (config.store_path, config.log_path, config.model) == (
        "score.db",
        "score.log",
        "claude-sonnet-5-5",
    )
    assert (config.calibration_report_sha256, config.library_sha256) == (SHA, "b" * 64)
    assert (
        config.interval_minutes,
        config.max_calls_per_round,
        config.timeout_s,
        config.quota_wait_minutes,
        config.daily_call_limit,
    ) == (5, 20, 120, 60, 200)
    assert config.news.store_path == "news.db"


def test_collector_and_archive_accept_score_section() -> None:
    assert load_news_config(document()).config is not None
    assert load_archive_config(document()).config is not None
    other = {**document(), "other": {}}
    assert load_news_config(other).message == "bilinmeyen ayar: other"


@pytest.mark.parametrize(
    "key",
    [
        "store_path",
        "log_path",
        "model",
        "calibration_report_path",
        "calibration_report_sha256",
        "library_path",
        "library_sha256",
    ],
)
def test_required_named(key: str) -> None:
    assert load_score_config(document(**{key: None})).message == f"ayar eksik: score.{key}"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"model": ""}, "ayar geçersiz: score.model"),
        ({"model": "claude sonnet"}, "ayar geçersiz: score.model"),
        ({"model": 'x" & del'}, "ayar geçersiz: score.model"),
        ({"model": "m" * 65}, "ayar geçersiz: score.model"),
        ({"calibration_report_sha256": "A" * 64}, "ayar geçersiz: score.calibration_report_sha256"),
        ({"library_sha256": "a" * 63}, "ayar geçersiz: score.library_sha256"),
        ({"store_path": 5}, "ayar geçersiz: score.store_path"),
        ({"store_path": "news.db"}, "ayar geçersiz: score.store_path"),
        ({"log_path": "score.db"}, "ayar geçersiz: score.log_path"),
        ({"log_path": "news.log"}, "ayar geçersiz: score.log_path"),
        ({"interval_minutes": 0}, "ayar geçersiz: score.interval_minutes (1…1440)"),
        ({"interval_minutes": True}, "ayar geçersiz: score.interval_minutes (1…1440)"),
        ({"interval_minutes": 1.5}, "ayar geçersiz: score.interval_minutes (1…1440)"),
        ({"max_calls_per_round": 0}, "ayar geçersiz: score.max_calls_per_round (1…1000)"),
        ({"timeout_s": 0}, "ayar geçersiz: score.timeout_s (1…3600)"),
        ({"timeout_s": 3601}, "ayar geçersiz: score.timeout_s (1…3600)"),
        ({"quota_wait_minutes": 0}, "ayar geçersiz: score.quota_wait_minutes (1…1440)"),
        ({"daily_call_limit": 0}, "ayar geçersiz: score.daily_call_limit (1…1000)"),
        ({"extra": 1}, "bilinmeyen ayar: score.extra"),
    ],
)
def test_out_of_range_named(changes: dict[str, object], message: str) -> None:
    result = load_score_config(document(**changes))
    assert (result.config, result.message) == (None, message)


def test_limit_over_hard_cap_refused() -> None:
    assert DAILY_CALL_HARD_CAP == 1000
    at_cap = load_score_config(document(daily_call_limit=DAILY_CALL_HARD_CAP)).config
    assert at_cap is not None and at_cap.daily_call_limit == 1000
    over = load_score_config(document(daily_call_limit=DAILY_CALL_HARD_CAP + 1))
    assert over.message == "ayar geçersiz: score.daily_call_limit (1…1000)"


def test_section_and_news_problems_named() -> None:
    assert load_score_config({"news": news_table()}).message == "ayar eksik: score"
    assert load_score_config({"news": news_table(), "score": 3}).message == "ayar geçersiz: score"
    broken = {"news": {**news_table(), "interval_minutes": 1}, "score": score_table()}
    assert load_score_config(broken).message == "ayar geçersiz: news.interval_minutes"


def test_example_file_loads() -> None:
    example = Path(__file__).resolve().parents[2] / "crytobot-news.example.toml"
    with example.open("rb") as file:
        result = load_score_config(tomllib.load(file))
    assert result.config is not None, result.message
    assert result.config.model == "claude-sonnet-5-5"
