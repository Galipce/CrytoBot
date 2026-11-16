"""Spec 0048 AC-10 (R-10, G-8; plan Risk 2): `crytobot-events.toml`'un `[events]` bölümü — zorunlu
model kesim tarihi, yollar, istek aralığı, maliyetler; ilk sorun adıyla, ham değer yazılmadan."""

import tomllib
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import load_events_config
from crytobot.calibration import Costs

EXAMPLE = Path(__file__).resolve().parents[2] / "crytobot-events.example.toml"
BASE = {"price_store_path": "p.db", "report_path": "r.txt", "library_path": "l.jsonl"}


def load(**values: Any) -> Any:
    table = {**BASE, "model_cutoff": "2025-01-31", **values}
    return load_events_config({"events": {k: v for k, v in table.items() if v is not None}})


def test_defaults_and_both_date_forms() -> None:
    result = load()
    config = result.config
    assert config is not None and result.message == "ayarlar geçerli"
    assert config.model_cutoff == datetime(2025, 1, 31, tzinfo=UTC)
    assert config.request_gap_s == 1
    assert config.costs == Costs(Decimal("0.001"), Decimal("0.001"), Decimal("0.0005"))
    dated = load(model_cutoff=date(2025, 1, 31), request_gap_s=3, fee="0.002", spread=0)
    assert dated.config is not None and dated.config.model_cutoff == config.model_cutoff
    assert (dated.config.request_gap_s, dated.config.costs.fee, dated.config.costs.spread) == (
        3,
        Decimal("0.002"),
        Decimal(0),
    )


def test_example_file_needs_its_cutoff_written() -> None:
    document = tomllib.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert load_events_config(document).message == "ayar geçersiz: events.model_cutoff"
    document["events"]["model_cutoff"] = "2025-01-31"
    assert load_events_config(document).config is not None


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"model_cutoff": None}, "ayar eksik: events.model_cutoff"),
        ({"model_cutoff": "2025-13-01"}, "ayar geçersiz: events.model_cutoff"),
        ({"model_cutoff": "2025-1-31"}, "ayar geçersiz: events.model_cutoff"),
        ({"model_cutoff": "YYYY-MM-DD"}, "ayar geçersiz: events.model_cutoff"),
        ({"model_cutoff": 20250131}, "ayar geçersiz: events.model_cutoff"),
        ({"model_cutoff": datetime(2025, 1, 31, tzinfo=UTC)}, "ayar geçersiz: events.model_cutoff"),
        ({"price_store_path": None}, "ayar eksik: events.price_store_path"),
        ({"report_path": " "}, "ayar geçersiz: events.report_path"),
        ({"library_path": "r.txt"}, "ayar geçersiz: events.library_path"),
        ({"library_path": 3}, "ayar geçersiz: events.library_path"),
        ({"request_gap_s": 0}, "ayar geçersiz: events.request_gap_s"),
        ({"request_gap_s": 0.5}, "ayar geçersiz: events.request_gap_s"),
        ({"request_gap_s": True}, "ayar geçersiz: events.request_gap_s"),
        ({"fee": "1"}, "ayar geçersiz: events.fee"),
        ({"fee": 0.001}, "ayar geçersiz: events.fee"),
        ({"slippage": "1e-3"}, "ayar geçersiz: events.slippage"),
        ({"fee": "0.6", "slippage": "0.5"}, "ayar geçersiz: events.slippage"),
        ({"spread": "-0.1"}, "ayar geçersiz: events.spread"),
        ({"extra": 1}, "bilinmeyen ayar: events.extra"),
    ],
)
def test_invalid_config_refused_by_name(values: dict[str, Any], message: str) -> None:
    result = load(**values)
    assert (result.config, result.message) == (None, message)


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({}, "ayar eksik: events"),
        ({"events": "x"}, "ayar geçersiz: events"),
        ({"events": {}, "bot": {}}, "bilinmeyen ayar: bot"),
        ("not a table", "ayar geçersiz: events"),
    ],
)
def test_document_shape_refused(document: Any, message: str) -> None:
    assert load_events_config(document).message == message


def test_raw_value_never_echoed() -> None:
    secret = "2025-13-01-very-secret"
    assert secret not in load(model_cutoff=secret).message
