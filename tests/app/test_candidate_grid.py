"""Spec 0043 AC-7 (R-3): son değerlendirmenin ızgarası tam olarak spec'tekidir; ayardan okunmaz.

Beklenen küme spec'in metninden elle yazıldı; kodun sabitlerinden türetilmez.
"""

import ast
import inspect
from decimal import Decimal

from crytobot.app import CANDIDATE_GRIDS, _grid
from crytobot.strategy import (
    BreakoutSettings,
    StrategySettings,
    TrendDipSettings,
    TrendFilterSettings,
    required_candles,
)

K = (Decimal("1.5"), Decimal(2), Decimal(3))


def test_grid_is_exactly_r3() -> None:
    """Dört aday S0…S3 sırasıyla, her biri 9 kombinasyon; eksik ya da fazla yok."""
    s0, s1, s2, s3 = CANDIDATE_GRIDS
    assert len(CANDIDATE_GRIDS) == 4
    assert [len(grid) for grid in CANDIDATE_GRIDS] == [9, 9, 9, 9]
    assert set(s0) == {
        StrategySettings(fast, slow, 14, Decimal(70), 14, k, Decimal(2))
        for fast, slow in ((9, 21), (12, 26), (20, 50))
        for k in K
    }
    assert set(s1) == {
        TrendFilterSettings(12, 26, 14, Decimal(70), 14, k, Decimal(2), trend)
        for trend in (100, 150, 200)
        for k in K
    }
    assert set(s2) == {
        BreakoutSettings(window, 14, k, Decimal(2)) for window in (20, 55, 100) for k in K
    }
    assert set(s3) == {
        TrendDipSettings(14, Decimal(threshold), 14, k, Decimal(2))
        for threshold in (30, 35, 40)
        for k in K
    }
    for grid, name in zip(CANDIDATE_GRIDS, ("S0", "S1", "S2", "S3"), strict=True):
        assert len(set(grid)) == 9  # no duplicate combination
        assert {setting.name for setting in grid} == {name}
    assert sum(len(grid) for grid in CANDIDATE_GRIDS) * 2 == 72  # 1h + 4h (R-3)


def test_grid_needs_200_candles() -> None:
    """R-4: en uzun ızgara göstergesi S3'ün ve S1'in 200 mumluk ortalaması."""
    needs = [required_candles(setting) for grid in CANDIDATE_GRIDS for setting in grid]
    assert max(needs) == 200


def test_grid_reads_no_setting() -> None:
    """AC-7: ızgara modülü yalnız `strategy`'yi ve `decimal`'i import eder; ayar, dosya ya da
    ortam okumaz."""
    tree = ast.parse(inspect.getsource(_grid))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported |= {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imported == {"decimal", "crytobot.strategy"}
