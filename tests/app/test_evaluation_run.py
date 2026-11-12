"""Spec 0042 AC-3, AC-6, AC-7: son değerlendirme koşusu (`run_evaluation`).

Küçük veride örneklem içinde 30 işlem olmaz: gerçek kural uçtan uca "aday yok" verir. Seçimin ve
paper adayının koşuya bağlanışı, kural yamanarak sınanır (kuralın kendisi
`tests/backtest/test_evaluation.py`'de). Adaylar: aynı 1h veri dosyası, tur aralığı 1h ve 2h.
"""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import CANDIDATE_GRIDS, BacktestOutcome, _evaluation
from crytobot.backtest import PASSED, CandidateResult, PartMetrics, paper_candidate
from crytobot.strategy import BreakoutSettings
from tests.app.backtest_helpers import (
    COUNT,
    Run,
    at,
    candles,
    config,
    final_setup,
    history,
    settings,
    write_history,
)
from tests.app.helpers import BTC, HOUR

SERIES = {BTC: candles(-COUNT, [10, 8, 9, 10, 10, 12, 15, 15, 15, 15, 15, 15])}  # hours -4..7
HOURS = 8
SPLIT, HOLDOUT = at(4), at(6)


def candidates(root: Path, **changes: Any) -> list[Any]:
    """1h ve 2h adayları, aynı veri dosyası ve koşullarla."""
    hourly = config(root, turn=settings((BTC,)), split_at=SPLIT, holdout_at=HOLDOUT, **changes)
    write_history(Path(hourly.data_path), history(SERIES, hours=HOURS))
    two_hourly = replace(hourly, bot=replace(hourly.bot, turn_interval=2 * HOUR))
    return [hourly, two_hourly]


def started(run: Run) -> list[str]:
    return [line for line in run.lines if line.startswith("backtest başladı:")]


def test_real_rule_end_to_end_gives_no_candidate(tmp_path: Path) -> None:
    """AC-3, AC-6: 30 işlem yok → her aday "geçmedi: örneklem içi işlem yetersiz", "aday yok";
    örneklem dışı ve saklı dönem hiç koşmaz; sınanan kombinasyon sayısı yazılır."""
    configs = candidates(tmp_path)
    grids = [[configs[0].bot.turn.strategy, replace(configs[0].bot.turn.strategy, k=Decimal(3))]]
    grids.append([configs[1].bot.turn.strategy])
    run = Run(tmp_path)
    exit_ = run.final(configs, grids)
    assert exit_.outcome is BacktestOutcome.COMPLETED, exit_.message
    report = run.report(configs[0])
    rows = report.splitlines()
    assert "sınanan kombinasyon: 3" in rows
    assert "paper adayı: aday yok" in rows
    assert rows.count("sonuç: geçmedi: örneklem içi işlem yetersiz (1 < 30)") == 2  # spec 0043 R-6
    assert "== aday: S0 1h ==" in rows and "== aday: S0 2h ==" in rows
    assert "örneklem dışı:" not in report and "saklı dönem:" not in report
    assert "BR-10 kanıtı adayı" not in report
    # three in-sample runs, no whole run: every start line ends at the split
    assert len(started(run)) == 3
    assert all("..2026-01-01T04:00:00+00:00 (örneklem içi)" in line for line in started(run))
    assert exit_.turns == 4 + 4 + 2


def test_selection_sees_only_in_sample_and_only_the_chosen_runs_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-3: seçime yalnız örneklem içi metrikler gider; yalnız seçilen kombinasyon tam koşar ve
    raporda seçilen ayar odur."""
    seen: list[list[PartMetrics]] = []

    def select(parts: list[PartMetrics]) -> int:
        seen.append(list(parts))
        return len(parts) - 1  # the last combination

    monkeypatch.setattr(_evaluation, "select_combination", select)
    monkeypatch.setattr(_evaluation, "verdict", lambda _o, _h: PASSED)
    configs = candidates(tmp_path)[:1]
    base = configs[0].bot.turn.strategy
    grid = [base, replace(base, k=Decimal(3))]
    run = Run(tmp_path)
    exit_ = run.final(configs, [grid])
    assert exit_.outcome is BacktestOutcome.COMPLETED, exit_.message
    (parts,) = seen
    assert len(parts) == 2
    for part in parts:
        assert part.last_turn is not None and part.last_turn < SPLIT
    assert len(started(run)) == 3  # two in-sample runs, one whole run
    assert started(run)[-1].endswith("..2026-01-01T08:00:00+00:00 çift=1 tur=8")
    report = run.report(configs[0])
    assert "seçilen ayar: fast=1 slow=2 rsi=2 rsi_threshold=70 atr=2 k=3 r=2" in report
    assert "strateji: S0 fast=1 slow=2 rsi=2 rsi_threshold=70 atr=2 k=3 r=2" in report
    assert "saklı dönem başı: 2026-01-01T06:00:00+00:00 (bu an ve sonrası)" in report


def test_report_names_candidate_and_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-6: geçen adaylardan tek paper adayı adlandırılır (R-4 kuralı koşudaki metriklerle);
    işaret ve dönem bölümleri yalnız onundur; sınanan kombinasyon sayısı yazılır."""
    monkeypatch.setattr(_evaluation, "select_combination", lambda parts: 0)
    monkeypatch.setattr(_evaluation, "verdict", lambda _o, _h: PASSED)
    chosen: list[Any] = []
    real = paper_candidate

    def paper(assessed: Any) -> Any:
        chosen.append(list(assessed))
        return real(assessed)

    monkeypatch.setattr(_evaluation, "paper_candidate", paper)
    configs = candidates(tmp_path)
    run = Run(tmp_path)
    exit_ = run.final(configs)
    assert exit_.outcome is BacktestOutcome.COMPLETED, exit_.message
    (assessed,) = chosen
    assert len(assessed) == 2
    expected = real(assessed)
    assert expected is not None
    label = ["S0 1h", "S0 2h"][expected]
    report = run.report(configs[0])
    rows = report.splitlines()
    assert rows[0] == "CrytoBot backtest raporu — son değerlendirme"
    assert "sınanan kombinasyon: 2" in rows
    assert f"paper adayı: {label}" in rows
    assert report.count("BR-10 kanıtı adayı") == 1
    assert rows.count("sonuç: geçti") == 2
    for title in ("örneklem içi", "örneklem dışı — BR-10 kanıtı adayı", "saklı dönem", "tüm koşu"):
        assert rows.count(f"== {title} ==") == 1
    assert f"tur aralığı: {label.split()[1]}" in rows
    assert run.lines[-1] == f"backtest tamam: rapor dosyası {configs[0].report_path}"
    assert run.lines[-2].startswith("rapor parmak izi: ")


@pytest.mark.parametrize(
    ("change", "name"),
    [
        ({"fee": Decimal("0.002")}, "fee"),
        ({"spread": Decimal("0.001")}, "spread"),
        ({"balance": Decimal(20000)}, "opening_balance"),
    ],
)
def test_different_conditions_refused_without_report(
    tmp_path: Path, change: dict[str, Any], name: str
) -> None:
    """AC-7: adayların koşulları farklıysa tur atılmaz, rapor yazılmaz, fark adıyla."""
    configs = candidates(tmp_path)
    other = configs[1]
    if "fee" in change:
        other = replace(
            other, bot=replace(other.bot, turn=replace(other.bot.turn, fee=change["fee"]))
        )
    elif "spread" in change:
        other = replace(other, spread=change["spread"])
    else:
        other = replace(other, bot=replace(other.bot, opening_balance=change["balance"]))
    run = Run(tmp_path)
    exit_ = run.final([configs[0], other])
    assert exit_.outcome is BacktestOutcome.REFUSED
    assert exit_.message == f"ayar uyuşmazlığı: {name}"
    assert run.lines == [f"backtest reddedildi: ayar uyuşmazlığı: {name}; tur atılmadı"]
    assert run.reads == [] and list(run.work.iterdir()) == []
    assert not Path(configs[0].report_path).exists()
    assert run.clock_reads == 0


def test_condition_drift_between_runs_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-7: koşullar değerlendirme sırasında değişirse (burada ikinci koşu başka komisyonla) koşu
    rapor yazmadan reddeder."""
    real = _evaluation._combination
    calls: list[datetime] = []

    def drifting(config: Any, setting: Any) -> Any:
        made = real(config, setting)
        calls.append(config.split_at)
        if len(calls) == 2:
            turn = replace(made.bot.turn, fee=Decimal("0.002"))
            return replace(made, bot=replace(made.bot, turn=turn))
        return made

    monkeypatch.setattr(_evaluation, "_combination", drifting)
    configs = candidates(tmp_path)
    run = Run(tmp_path)
    exit_ = run.final(configs)
    assert exit_.outcome is BacktestOutcome.REFUSED
    assert exit_.message == "ayar uyuşmazlığı: fee"
    assert run.lines[-1] == "backtest reddedildi: ayar uyuşmazlığı: fee; rapor yazılmadı"
    assert not Path(configs[0].report_path).exists()
    assert run.clock_reads == 0
    assert "CrytoBot backtest raporu" not in run.console


def test_empty_evaluation_refused(tmp_path: Path) -> None:
    run = Run(tmp_path)
    assert run.final([]).message == "değerlendirilecek aday yok"
    configs = candidates(tmp_path)
    assert run.final(configs, [[]]).outcome is BacktestOutcome.REFUSED


def test_evaluation_report_exists_refused_before_reading(tmp_path: Path) -> None:
    configs = candidates(tmp_path)
    Path(configs[0].report_path).write_text("eski", encoding="utf-8")
    run = Run(tmp_path)
    exit_ = run.final(configs)
    assert exit_.outcome is BacktestOutcome.REFUSED
    assert "rapor dosyası var" in exit_.message
    assert run.reads == []
    assert Path(configs[0].report_path).read_text(encoding="utf-8") == "eski"


def test_stop_during_evaluation_writes_no_report(tmp_path: Path) -> None:
    configs = candidates(tmp_path)
    run = Run(tmp_path)

    def write(text: str) -> None:
        run.lines.append(text)
        if text.startswith("backtest başladı:"):
            run.stop.request("SIGINT")

    exit_ = run.final(configs, write=write)
    assert exit_.outcome is BacktestOutcome.STOPPED
    assert not Path(configs[0].report_path).exists()
    assert run.lines[-1] == "backtest durdu: durdurma isteği; rapor yazılmadı"


# --- spec 0043 AC-7, AC-8, AC-10 (R-3…R-6; plan Risk 5, 9) ---


def test_config_strategy_does_not_change_grid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-7: ayardaki strateji (burada S2) ızgarayı değiştirmez; her aralık S0…S3'ün R-3
    ızgarasıyla, bu sırayla. Koşu casusla kısaltılır: ızgarayı alan `candidate` kayıt tutar."""
    s2 = BreakoutSettings(7, 3, Decimal(1), Decimal(1))
    _, configs = final_setup(tmp_path, strategy=s2)
    assert all(config.bot.turn.strategy == s2 for config in configs)
    seen: list[tuple[str, tuple[Any, ...]]] = []

    def spy(self: Any, config: Any, data: Any, grid: Any) -> Any:
        interval = "1h" if config.bot.turn_interval == HOUR else "4h"
        seen.append((interval, tuple(grid)))
        verdict_line = "geçmedi: örneklem içi işlem yetersiz (0 < 30)"
        result = CandidateResult(grid[0].name, interval, None, None, None, None, verdict_line)
        return result, None, config

    monkeypatch.setattr(_evaluation._Evaluation, "candidate", spy)
    run = Run(tmp_path)
    exit_ = run.final(list(configs), None)
    assert exit_.outcome is BacktestOutcome.COMPLETED, exit_.message
    expected = [(interval, grid) for interval in ("1h", "4h") for grid in CANDIDATE_GRIDS]
    assert seen == expected
    assert "sınanan kombinasyon: 72" in run.report(configs[0]).splitlines()


def test_final_candle_count_below_grid_refused(tmp_path: Path) -> None:
    """AC-8, R-4: mum sayısı en uzun ızgara göstergesine (200) yetmezse ret; veri okunmaz, tur
    atılmaz, rapor yazılmaz."""
    _, configs = final_setup(tmp_path)
    short = [
        replace(each, bot=replace(each.bot, read=replace(each.bot.read, candle_count=199)))
        for each in configs
    ]
    run = Run(tmp_path)
    exit_ = run.final(short, None)
    assert exit_.outcome is BacktestOutcome.REFUSED
    assert exit_.message == "ayar geçersiz: market.candle_count"
    assert (run.reads, exit_.turns, started(run)) == ([], 0, [])
    assert not Path(configs[0].report_path).exists()


def test_not_enough_trades_line_has_count(tmp_path: Path) -> None:
    """AC-10, R-6: "örneklem içi işlem yetersiz" satırı ızgaranın en yüksek işlem sayısını yazar;
    rapor ve konsol aynı satırı taşır."""
    configs = candidates(tmp_path)
    strategy = configs[0].bot.turn.strategy
    run = Run(tmp_path)
    exit_ = run.final([configs[0]], [[strategy, replace(strategy, k=Decimal(3))]])
    assert exit_.outcome is BacktestOutcome.COMPLETED, exit_.message
    line = "geçmedi: örneklem içi işlem yetersiz (1 < 30)"
    assert f"sonuç: {line}" in run.report(configs[0]).splitlines()
    assert f"backtest aday S0 1h: {line}" in run.lines
