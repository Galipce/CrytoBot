"""Spec 0043 AC-7 (R-3, R-5; plan Risk 9, A-2): 1h + 4h, 72 kombinasyonluk uçtan uca son
değerlendirme. Süresi ~15-20 s olduğundan `slow`'dur (full profil); `tests/tooling` kopya projesine
girmez (`tests/tooling/conftest.py`, Known trap).
"""

from pathlib import Path

import pytest

from crytobot.app import BacktestOutcome
from tests.app.backtest_helpers import Run, final_setup, force_pass

LABELS = [f"{name} {interval}" for interval in ("1h", "4h") for name in ("S0", "S1", "S2", "S3")]


def started(run: Run) -> list[str]:
    return [line for line in run.lines if line.startswith("backtest başladı:")]


@pytest.mark.slow  # plan Risk 9: 72 combinations, about 15-20 s
def test_two_intervals_72_combinations_one_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-7: 1h + 4h, her aday ve aralıkta R-3 ızgarası tam; rapor `sınanan kombinasyon: 72` ve
    bütün aday ve aralıklar arasından tek paper adayı. Seçim ve hüküm sabitlenir (`force_pass`);
    örneklem içi koşu sayısı 72, tam koşu adayı başına bir."""
    _, configs = final_setup(tmp_path)
    force_pass(monkeypatch)
    run = Run(tmp_path)
    exit_ = run.final(list(configs), None)
    assert exit_.outcome is BacktestOutcome.COMPLETED, exit_.message
    rows = run.report(configs[0]).splitlines()
    assert "sınanan kombinasyon: 72" in rows
    assert [row[len("== aday: ") : -3] for row in rows if row.startswith("== aday: ")] == LABELS
    (paper,) = [row for row in rows if row.startswith("paper adayı: ")]
    assert paper.removeprefix("paper adayı: ") in LABELS
    assert run.lines[0] == "backtest son değerlendirme başladı: aday=8 kombinasyon=72"
    assert len(started(run)) == 72 + 8
