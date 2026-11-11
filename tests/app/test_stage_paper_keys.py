"""Spec 0038 CB-2, CB-4 ayar hataları, PB-1: `[stage]` paper kanıtı anahtarları."""

from typing import Any

import pytest

from crytobot.app import load_stage_config


def stage(**extra: object) -> dict[str, Any]:
    table: dict[str, object] = {
        "report_path": "rapor.txt",
        "approved_by": "Galip Badem",
        "approved_at": "2026-11-08T12:00:00Z",
        "live_approved_by": "Galip Badem",
        "live_approved_at": "2026-11-09T12:00:00Z",
    }
    table.update(extra)
    return {"stage": table}


def test_live_reads_the_paper_keys_with_defaults() -> None:
    res = load_stage_config(stage(paper_store_path="  paper.sqlite "), mode="live")

    assert res.config is not None, res.message
    assert res.config.paper_store_path == "paper.sqlite"
    assert res.config.paper_min_days == 14
    assert res.config.paper_min_trades == 10


def test_live_reads_values_at_the_floor() -> None:
    res = load_stage_config(
        stage(paper_store_path="p.sqlite", paper_min_days=7, paper_min_trades=5), mode="live"
    )

    assert res.config is not None
    assert (res.config.paper_min_days, res.config.paper_min_trades) == (7, 5)


def test_live_requires_the_paper_store_path() -> None:
    res = load_stage_config(stage(), mode="live")

    assert res.config is None
    assert res.setting == "stage.paper_store_path"
    assert res.message == "ayar eksik: stage.paper_store_path"


@pytest.mark.parametrize("value", ["", "   ", 3, True, ["p.sqlite"], None])
def test_live_refuses_a_paper_store_path_that_is_not_text(value: object) -> None:
    res = load_stage_config(stage(paper_store_path=value), mode="live")

    assert res.config is None
    assert res.message == "ayar geçersiz: stage.paper_store_path"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("paper_min_days", 6),
        ("paper_min_days", 0),
        ("paper_min_days", -14),
        ("paper_min_days", 14.0),
        ("paper_min_days", "14"),
        ("paper_min_days", True),
        ("paper_min_trades", 4),
        ("paper_min_trades", 0),
        ("paper_min_trades", -1),
        ("paper_min_trades", 10.5),
        ("paper_min_trades", "10"),
        ("paper_min_trades", True),
    ],
)
def test_live_refuses_thresholds_below_the_floor_or_not_whole(key: str, value: object) -> None:
    res = load_stage_config(stage(paper_store_path="p.sqlite", **{key: value}), mode="live")

    assert res.config is None
    assert res.setting == f"stage.{key}"
    assert res.message == f"ayar geçersiz: stage.{key}"


def test_paper_store_path_is_checked_after_the_existing_live_keys() -> None:
    document = stage(paper_store_path=3)
    del document["stage"]["live_approved_at"]

    res = load_stage_config(document, mode="live")

    assert res.setting == "stage.live_approved_at"


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"paper_store_path": "p.sqlite", "paper_min_days": 30, "paper_min_trades": 20},
        {"paper_store_path": 3, "paper_min_days": 1, "paper_min_trades": "x"},
    ],
)
def test_paper_mode_neither_requires_nor_checks_the_paper_keys(extra: dict[str, object]) -> None:
    """PB-1: paper başlatma bu alanları aramaz; varlıkları ya da değerleri onu bozmaz."""
    res = load_stage_config(stage(**extra), mode="paper")

    assert res.config is not None, res.message
    assert res.config.paper_store_path is None
    assert (res.config.paper_min_days, res.config.paper_min_trades) == (14, 10)
