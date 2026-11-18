"""Spec 0053 R-10, AC-10 (plan Risk 6): `crytobot-forward.toml` `[forward]` yükleyicisi — üç yol
zorunlu ve farklı, istek aralığı, maliyetler; ilk sorun adıyla, ham değer yazılmadan."""

import tomllib
from decimal import Decimal
from pathlib import Path

import pytest

from crytobot.app import load_forward_config

ROOT = Path(__file__).resolve().parents[2]
BASE = {
    "price_store_path": "p.db",
    "report_path": "r.txt",
    "samples_path": "s.jsonl",
}


def test_example_file_is_valid() -> None:
    with open(ROOT / "crytobot-forward.example.toml", "rb") as file:
        document = tomllib.load(file)
    result = load_forward_config(document)
    assert result.config is not None, result.message
    assert result.config.request_gap_s == 1
    costs = result.config.costs
    assert (costs.fee, costs.slippage, costs.spread) == (
        Decimal("0.001"),
        Decimal("0.001"),
        Decimal("0.0005"),
    )


def test_defaults() -> None:
    result = load_forward_config({"forward": dict(BASE)})
    assert result.config is not None and result.message == "ayarlar geçerli"
    assert (result.config.price_store_path, result.config.report_path) == ("p.db", "r.txt")
    assert result.config.samples_path == "s.jsonl"
    assert result.config.request_gap_s == 1
    assert result.config.costs.fee == Decimal("0.001")


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ([], "ayar geçersiz: forward"),
        ({}, "ayar eksik: forward"),
        ({"forward": 3}, "ayar geçersiz: forward"),
        ({"forward": dict(BASE), "events": {}}, "bilinmeyen ayar: events"),
        ({"forward": {**BASE, "x": 1}}, "bilinmeyen ayar: forward.x"),
        (
            {"forward": {"report_path": "r", "samples_path": "s"}},
            "ayar eksik: forward.price_store_path",
        ),
        ({"forward": {**BASE, "report_path": "p.db"}}, "ayar geçersiz: forward.report_path"),
        ({"forward": {**BASE, "samples_path": "r.txt"}}, "ayar geçersiz: forward.samples_path"),
        ({"forward": {**BASE, "samples_path": "  "}}, "ayar geçersiz: forward.samples_path"),
        ({"forward": {**BASE, "report_path": 7}}, "ayar geçersiz: forward.report_path"),
        ({"forward": {**BASE, "request_gap_s": 0}}, "ayar geçersiz: forward.request_gap_s"),
        ({"forward": {**BASE, "request_gap_s": 1.5}}, "ayar geçersiz: forward.request_gap_s"),
        ({"forward": {**BASE, "request_gap_s": True}}, "ayar geçersiz: forward.request_gap_s"),
        ({"forward": {**BASE, "fee": "1"}}, "ayar geçersiz: forward.fee"),
        ({"forward": {**BASE, "fee": "-0.1"}}, "ayar geçersiz: forward.fee"),
        ({"forward": {**BASE, "spread": "abc"}}, "ayar geçersiz: forward.spread"),
        ({"forward": {**BASE, "fee": "0.6", "slippage": "0.4"}}, "ayar geçersiz: forward.slippage"),
    ],
)
def test_refusals_named(document: object, message: str) -> None:
    result = load_forward_config(document)
    assert result.config is None
    assert result.message == message


def test_costs_and_gap_read() -> None:
    result = load_forward_config(
        {"forward": {**BASE, "request_gap_s": 3, "fee": "0.002", "slippage": 0, "spread": "0"}}
    )
    assert result.config is not None
    assert result.config.request_gap_s == 3
    assert (result.config.costs.fee, result.config.costs.slippage) == (Decimal("0.002"), 0)
