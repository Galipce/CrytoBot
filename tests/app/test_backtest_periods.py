"""Spec 0042 AC-1, AC-2: varsayılan koşu yalnız örneklem içi; dönemler veri aralığında.

Mutlu yol verisi (`test_backtest_run`): tek çift BTC, 1h, dönem 0..4. saat; ayrım 2. saatte, saklı
dönem 3. saatte başlar. Varsayılan koşu yalnız 0 ve 1. saat turlarını atar; 2. saatin kapanışı
(gerçekleşen 243.11949558) ve sonrası hiçbir yerde görünmez.
"""

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import BacktestOutcome, _backtest_inputs
from tests.app.backtest_helpers import COUNT, Run, at, candles, config, history, settings
from tests.app.backtest_helpers import write_history as write
from tests.app.helpers import BTC

HAPPY = {BTC: candles(-COUNT, [10, 8, 9, 10, 10, 12, 15, 15])}
LATER_NUMBERS = (
    "243.11949558",  # the realized result of the target close at hour 2
    "10243.11949558",  # the equity after it
    "145.87228672",  # the out-of-sample net
    "14.985",  # the close's fill
)


def prepared(root: Path, **changes: Any) -> Any:
    chosen = config(root, turn=settings((BTC,)), **changes)
    write(Path(chosen.data_path), history(HAPPY, hours=4))
    return chosen


def test_default_run_shows_in_sample_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-1: turlar yalnız örneklem içinde; sonraki mumlar hiçbir tura verilmez; rapor ve konsolda
    örneklem dışı ya da saklı dönemden tek rakam yok."""
    seen: list[datetime] = []
    real_market = _backtest_inputs.TurnInputs.market

    def market(self: Any, moment: datetime) -> Any:
        seen.append(moment)
        return real_market(self, moment)

    monkeypatch.setattr(_backtest_inputs.TurnInputs, "market", market)
    chosen = prepared(tmp_path, holdout_at=at(3))
    run = Run(tmp_path)
    exit_ = run(chosen)
    assert exit_.outcome is BacktestOutcome.COMPLETED, exit_.message
    assert seen == [at(0), at(1)]  # never the split or later
    report = run.report(chosen)
    for text in (report, run.console):
        assert "örneklem dışı" not in text
        assert "saklı dönem" not in text
        assert "tüm koşu" not in text
        assert "BR-10 kanıtı adayı" not in text
        for number in LATER_NUMBERS:
            assert number not in text
    assert "== örneklem içi ==" in report
    assert run.lines[0].endswith("..2026-01-01T02:00:00+00:00 (örneklem içi) çift=1 tur=2")


@pytest.mark.parametrize(
    ("changes", "setting"),
    [
        ({"split_at": at(0)}, "backtest.split_at"),  # empty in-sample
        ({"split_at": at(4), "holdout_at": at(5)}, "backtest.split_at"),  # at the end
        ({"split_at": at(-1)}, "backtest.split_at"),  # before the data
        ({"holdout_at": at(4)}, "backtest.holdout_at"),  # empty holdout
        ({"holdout_at": at(9)}, "backtest.holdout_at"),  # past the data
    ],
)
@pytest.mark.parametrize("final", [False, True])
def test_period_outside_data_refused_without_report(
    tmp_path: Path, changes: dict[str, Any], setting: str, final: bool
) -> None:
    """AC-2: veri aralığı dışında ya da bir dönemi boş bırakan tarih adıyla reddedilir; tur yok,
    rapor yazılmaz (varsayılan ve son değerlendirme)."""
    chosen = prepared(tmp_path, **changes)
    run = Run(tmp_path)
    exit_ = run.final(chosen) if final else run(chosen)
    assert exit_.outcome is BacktestOutcome.REFUSED
    assert exit_.message.startswith(f"ayar geçersiz: {setting}")
    assert exit_.report is None and exit_.turns == 0
    assert list(run.work.iterdir()) == []
    assert not Path(chosen.report_path).exists()
    assert run.clock_reads == 0


def test_one_turn_periods_are_valid(tmp_path: Path) -> None:
    """Her dönem en az bir tur: 4 turluk veride 1 + 2 + 1."""
    chosen = prepared(tmp_path, split_at=at(1), holdout_at=at(3))
    assert Run(tmp_path)(chosen).outcome is BacktestOutcome.COMPLETED


def test_holdout_before_split_refused_by_the_run(tmp_path: Path) -> None:
    """Ayar yükleyicisini atlayan yapılandırmada da sırasız saklı dönem reddedilir."""
    chosen = replace(prepared(tmp_path), holdout_at=at(2))
    exit_ = Run(tmp_path)(chosen)
    assert exit_.outcome is BacktestOutcome.REFUSED
    assert exit_.message.startswith("ayar geçersiz: backtest.holdout_at")
