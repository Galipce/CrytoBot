"""Spec 0044 AC-1 (uçtan uca), AC-2; plan Adım 6, Risk 3, 4: son değerlendirmede veri.

Fixture 0043'ün iki aralıklı düzenidir (`final_setup`): dönem 0..16. saat, örneklem dışı 8.,
saklı dönem 12. saatte başlar; ısınma 200 mum. Her yapılandırma kendi stratejisiyle koşar (`OWN`).
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from crytobot.app import BacktestConfig, BacktestOutcome
from crytobot.market_data import HistoryData, period_gaps, read_history
from tests.app.backtest_helpers import (
    FINAL_END,
    FINAL_HOLDOUT,
    FINAL_SPLIT,
    START,
    Run,
    at,
    final_history,
    final_setup,
    force_pass,
    report_lines,
    write_history,
)
from tests.app.helpers import BTC, ETH, HOUR

PERIODS = {
    "örneklem içi": (START, FINAL_SPLIT),
    "örneklem dışı": (FINAL_SPLIT, FINAL_HOLDOUT),
    "saklı dönem": (FINAL_HOLDOUT, FINAL_END),
}


def without(data: HistoryData, pair: str, drop: Callable[[datetime], bool]) -> HistoryData:
    """`pair`'in açılışı `drop`'a uyan mumları çıkarılmış kopya."""
    pairs = tuple(
        replace(item, candles=tuple(c for c in item.candles if not drop(c.open_time)))
        if item.pair == pair
        else item
        for item in data.pairs
    )
    return replace(data, pairs=pairs)


def rewrite(root: Path, interval: str, change: Callable[[HistoryData], HistoryData]) -> None:
    hours = {"1h": 1, "4h": 4}[interval]
    data = final_history(hours * HOUR, lambda _index: 10, (BTC, ETH))
    write_history(root / f"history-{interval}.jsonl", change(data))


def setup(root: Path) -> list[BacktestConfig]:
    """İki çift (BTC, ETH), iki aralık; veri dosyaları eksiksiz yazılır."""
    _, configs = final_setup(root)
    for interval in ("1h", "4h"):
        rewrite(root, interval, lambda data: data)
    return [
        replace(each, bot=replace(each.bot, turn=replace(each.bot.turn, whitelist=(BTC, ETH))))
        for each in configs
    ]


@pytest.mark.parametrize("interval", ["1h", "4h"])
@pytest.mark.parametrize("period", list(PERIODS))
def test_period_without_candles_refused(tmp_path: Path, interval: str, period: str) -> None:
    """AC-2: bir çiftin bir aralıkta bir dönemde hiç kapanmış mumu yok → `veri eksik: <çift>
    <aralık> <dönem>`; tur atılmaz, rapor yazılmaz."""
    configs = setup(tmp_path)
    start, end = PERIODS[period]
    rewrite(tmp_path, interval, lambda data: without(data, ETH, lambda at_: start <= at_ < end))
    run = Run(tmp_path)
    exit_ = run.final(configs)
    assert exit_.outcome is BacktestOutcome.REFUSED
    assert exit_.message == f"veri eksik: {ETH} {interval} {period}"
    assert exit_.turns == 0 and exit_.report is None
    assert not [line for line in run.lines if line.startswith("backtest başladı")]
    assert not Path(configs[0].report_path).exists()


def test_first_missing_is_named_in_interval_pair_period_order(tmp_path: Path) -> None:
    """Plan Risk 3: denetim sırası yapılandırma (1h, 4h), çift (dosya sırası), dönem."""
    configs = setup(tmp_path)
    late = PERIODS["saklı dönem"]
    rewrite(tmp_path, "1h", lambda data: without(data, ETH, lambda m: late[0] <= m < late[1]))
    early = PERIODS["örneklem dışı"]
    rewrite(tmp_path, "4h", lambda data: without(data, BTC, lambda m: early[0] <= m < early[1]))
    exit_ = Run(tmp_path).final(configs)
    assert exit_.message == f"veri eksik: {ETH} 1h saklı dönem"


def test_single_candle_in_period_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-2: dönemde tek kapanmış mum varsa ret yok; eksik kısım boşluktur (AC-1)."""
    force_pass(monkeypatch)
    configs = setup(tmp_path)
    keep = at(13)
    rewrite(
        tmp_path,
        "1h",
        lambda data: without(data, ETH, lambda m: FINAL_HOLDOUT <= m < FINAL_END and m != keep),
    )
    run = Run(tmp_path)
    exit_ = run.final(configs)
    assert exit_.outcome is BacktestOutcome.COMPLETED, exit_.message
    rows = run.report(configs[0]).splitlines()
    assert f"{ETH} {at(12).isoformat()} → {at(12).isoformat()} (1 mum)" in rows
    assert f"{ETH} {at(14).isoformat()} → {at(15).isoformat()} (2 mum)" in rows


def test_gaps_reported_run_continues_no_candle_added(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-1: her aralığın her boşluğu raporda (dosyanın `period_gaps`'iyle aynı); boşluksuz aralık
    `veri boşluğu: yok`; koşu durmaz ve mum eklenmez (eksik tur sayılır, dosya aynı kalır)."""
    force_pass(monkeypatch)
    configs = setup(tmp_path)
    missing = {at(-3), at(3), at(4), at(9), at(15)}  # warm-up only, two adjacent, one, the last
    rewrite(tmp_path, "1h", lambda data: without(data, BTC, lambda m: m in missing))
    before = (tmp_path / "history-1h.jsonl").read_bytes()
    run = Run(tmp_path)
    exit_ = run.final(configs)
    assert exit_.outcome is BacktestOutcome.COMPLETED, exit_.message
    rows = run.report(configs[0]).splitlines()
    first = rows.index(next(row for row in rows if row.startswith("veri — 1h: ")))
    data = read_history(str(tmp_path / "history-1h.jsonl")).data
    assert data is not None
    (btc,) = [item for item in data.pairs if item.pair == BTC]
    expected = [
        f"{gap.pair} {gap.first.isoformat()} → {gap.last.isoformat()} ({gap.count} mum)"
        for gap in period_gaps(btc, HOUR, data.start, data.end)
    ]
    assert len(expected) == 3
    assert rows[first + 1 : first + 4] == expected
    assert rows[first] == (
        f"veri — 1h: dönem {START.isoformat()} .. {FINAL_END.isoformat()} (bitiş hariç),"
        f" saklı dönemin son mumu {(FINAL_END - HOUR).isoformat()}"
    )
    assert rows[first + 4] == ""
    assert rows[first + 5].startswith("veri — 4h: ") and rows[first + 6] == "veri boşluğu: yok"
    assert (tmp_path / "history-1h.jsonl").read_bytes() == before
    missing_turns = report_lines(run.report(configs[0]), "tüm koşu")
    assert missing_turns["fiyatı ya da verisi eksik tur (çift başına)"] != "yok"


def test_different_ends_refused(tmp_path: Path) -> None:
    """Plan Risk 4 (R-1): iki aralığın veri dosyası farklı anda biterse tur atılmaz."""
    configs = setup(tmp_path)
    shorter = FINAL_END - HOUR

    def cut(data: HistoryData) -> HistoryData:
        drop = without(without(data, BTC, lambda m: m >= shorter), ETH, lambda m: m >= shorter)
        return replace(drop, end=shorter)

    rewrite(tmp_path, "1h", cut)
    exit_ = Run(tmp_path).final(configs)
    assert exit_.outcome is BacktestOutcome.REFUSED
    assert exit_.message == "veri dosyası uyumsuz: aralıkların bitişi farklı"
    assert exit_.turns == 0 and not Path(configs[0].report_path).exists()
