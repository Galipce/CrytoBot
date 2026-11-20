"""Spec 0060 AC-1: ayar - eksik ve geçersiz alanlar, ön kayıtlı sayılar ayarlanamaz."""

import tomllib
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.app._llm_paper_config import (
    LIMITS,
    MEASUREMENT_END,
    MEASUREMENT_START,
    PREREGISTERED_KEYS,
    RANDOM_REPEATS,
    RANDOM_SEED,
    load_llm_paper_config,
)

EXAMPLE = Path(__file__).resolve().parents[2] / "crytobot-llm-paper.example.toml"


def document(**changes: Any) -> dict[str, Any]:
    with open(EXAMPLE, "rb") as file:
        data = tomllib.load(file)
    for key, value in changes.items():
        if value is None:
            data["llm_paper"].pop(key)
        else:
            data["llm_paper"][key] = value
    return data


def test_example_loads() -> None:
    result = load_llm_paper_config(document())
    assert result.config is not None, result.message
    assert len(set(result.config.outputs)) == 4


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"decide_store_path": None}, "ayar eksik: llm_paper.decide_store_path"),
        ({"trades_path": ""}, "ayar geçersiz: llm_paper.trades_path"),
        ({"rules_path": 3}, "ayar geçersiz: llm_paper.rules_path"),
        ({"request_gap_s": 0}, "ayar geçersiz: llm_paper.request_gap_s"),
        ({"request_gap_s": True}, "ayar geçersiz: llm_paper.request_gap_s"),
        ({"other": 1}, "bilinmeyen ayar: llm_paper.other"),
    ],
)
def test_missing_and_invalid_named(changes: dict[str, Any], message: str) -> None:
    assert load_llm_paper_config(document(**changes)).message == message


def test_same_output_paths_refused() -> None:
    data = document()
    data["llm_paper"]["report_path"] = data["llm_paper"]["trades_path"]
    assert load_llm_paper_config(data).message == "ayar geçersiz: llm_paper.trades_path"


@pytest.mark.parametrize("key", PREREGISTERED_KEYS)
def test_preregistered_keys_refused(key: str) -> None:
    result = load_llm_paper_config(document(**{key: 1}))
    assert result.config is None
    assert result.message == f"ön kayıtlı, ayarlanamaz: llm_paper.{key} (spec 0060)"


def test_preregistered_numbers_match_spec() -> None:
    """Spec 0060 C-4, C-5, C-6: sabitler spec'teki sayılardır (bot ayarından okunmaz)."""
    assert MEASUREMENT_START.isoformat() == "2026-11-22T00:00:00+00:00"  # spec 0061 CB-5
    assert MEASUREMENT_END.isoformat() == "2027-02-20T00:00:00+00:00"
    assert (RANDOM_SEED, RANDOM_REPEATS) == (60, 1000)
    assert (LIMITS.per_trade_risk, LIMITS.daily_loss_limit, LIMITS.max_drawdown) == (
        Decimal("0.01"),
        Decimal("0.03"),
        Decimal("0.15"),
    )
    assert (LIMITS.max_open_positions, LIMITS.profit_cost_multiple) == (5, Decimal("2"))
