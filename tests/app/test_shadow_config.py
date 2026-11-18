"""Spec 0052 R-1, R-8, AC-10 (plan step 4, Risk 6): `[shadow]` bölümü — yoksa kayıt kapalı, varsa üç
yol zorunlu, bilinmeyen anahtar ret; botun ayar yükleyicisi bölümü okumadan geçer."""

import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import ShadowConfig, load_config, load_shadow_config

EXAMPLE = Path(__file__).resolve().parents[2] / "crytobot.example.toml"
PATHS = {"record_path": "shadow.jsonl", "score_path": "score.db", "news_path": "news.db"}


def test_no_section_means_off() -> None:
    result = load_shadow_config({"bot": {}})
    assert (result.config, result.setting, result.message) == (None, None, "")


def test_valid_section() -> None:
    result = load_shadow_config({"shadow": dict(PATHS)})
    assert result.config == ShadowConfig("shadow.jsonl", "score.db", "news.db")
    assert (result.setting, result.message) == (None, "")


@pytest.mark.parametrize("key", sorted(PATHS))
def test_each_path_required(key: str) -> None:
    table = {name: value for name, value in PATHS.items() if name != key}
    result = load_shadow_config({"shadow": table})
    assert result.config is None
    assert (result.setting, result.message) == (f"shadow.{key}", f"ayar eksik: shadow.{key}")


@pytest.mark.parametrize("value", ["", "   ", 3, True, ["a"], "a\nb", "x" * 2049])
def test_invalid_path_named(value: Any) -> None:
    result = load_shadow_config({"shadow": {**PATHS, "news_path": value}})
    assert result.config is None
    assert result.message == "ayar geçersiz: shadow.news_path"


def test_unknown_key_and_bad_section() -> None:
    unknown = load_shadow_config({"shadow": {**PATHS, "window_hours": 48}})
    assert unknown.message == "bilinmeyen ayar: shadow.window_hours"
    assert load_shadow_config({"shadow": "on"}).message == "ayar geçersiz: shadow"
    assert load_shadow_config(["not", "a", "mapping"]).message == "ayar geçersiz: shadow"


def test_bot_loader_passes_the_section() -> None:
    """Bot, live ve backtest ayarı `[shadow]`'u okumadan geçer: bilinmeyen bölüm değildir."""
    document = tomllib.loads(EXAMPLE.read_text(encoding="utf-8"))
    document["shadow"] = {"anything": 1}
    result = load_config(document, datetime(2026, 11, 18, tzinfo=UTC))
    assert result.config is not None, result.message
