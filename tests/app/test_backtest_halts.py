"""Spec 0025 AC-7 (R-7, R-8): simüle gün, drawdown durdurması, bildirimler.

Alım: kapanmış 10, 8, 9, 10 serisi → giriş 10, stop 8, hedef 14; dolum 10.01, miktar 49.309.
- Günlük zarar: 1. saatte fiyat 7 → stop kapanışı, kayıp ~%1.5 > günlük limit %1. Aynı gün ETH'nin
  önerileri (1., 2., 23. saat) `daily_loss_limit` ile reddedilir; ertesi gün (24. saat) ETH alınır.
- Drawdown: limit %0.5; 1. saatte fiyat 9 → kasa 9949.70, zirveden %0.50 düşüş → durdurma. ETH'nin
  sonraki önerisi `drawdown_halt` ile reddedilir; BTC'nin hedef kapanışı sürer.
"""

from decimal import Decimal
from pathlib import Path
from typing import Any

from crytobot.app import BacktestOutcome
from crytobot.persistence import load_store
from tests.app.backtest_helpers import (
    COUNT,
    Run,
    at,
    candles,
    config,
    history,
    report_lines,
    settings,
    write_history,
)
from tests.app.helpers import BTC, ETH, limits

IN, OUT, WHOLE = "örneklem içi", "örneklem dışı — BR-10 kanıtı adayı", "tüm koşu"


def flat(count: int, value: int = 10) -> list[Any]:
    return [value] * count


def run_case(root: Path, series: dict[str, Any], hours: int, **changes: Any) -> tuple[Run, Any]:
    chosen = config(root, **changes)
    write_history(Path(chosen.data_path), history(series, hours=hours))
    run = Run(root)
    exit_ = run(chosen)
    assert exit_.outcome is BacktestOutcome.COMPLETED, exit_.message
    return run, chosen


def stored(run: Run) -> Any:
    state = load_store(run.work / "backtest.db", "paper").state
    assert state is not None
    return state


def test_daily_loss_blocks_buys_until_next_simulated_day(tmp_path: Path) -> None:
    """R-7, BR-5: günlük zarar limiti simüle UTC gününe göre; ertesi günde alım sürer."""
    hours = 26
    series = {
        BTC: candles(-COUNT, [10, 8, 9, 10, 10, *flat(hours - 1, 7)]),
        # ETH proposes at hours 1, 2 (day 1, the loss limit refuses) and 23 (day 1), and 24 (day 2)
        ETH: candles(-COUNT, [*flat(2), 10, 8, 9, 10, 10, *flat(17), 10, 8, 9, 10, *flat(2)]),
    }
    turn = settings(limits=limits(daily_loss_limit=Decimal("0.01")))
    run, chosen = run_case(tmp_path, series, hours, turn=turn, split_at=at(12))
    state = stored(run)
    opened = sorted(
        (position.pair, position.opened_at)
        for position in [
            *state.ledger.positions.values(),
            *(closure.position for closure in state.ledger.closures.values()),
        ]
    )
    assert opened == [(BTC, at(0)), (ETH, at(24))]  # not at hour 2: the day's loss limit
    report = run.report(chosen)
    assert report_lines(report, IN)["günlük zarar durdurmalı gün"] == "1"
    # the split (hour 12) is inside day 1: that day counts in both parts, once in the whole run
    assert report_lines(report, OUT)["günlük zarar durdurmalı gün"] == "1"
    assert report_lines(report, WHOLE)["günlük zarar durdurmalı gün"] == "1"
    assert report_lines(report, IN)["ret (nedene göre)"] == "risk.daily_loss_limit 2"  # hours 1, 2
    assert report_lines(report, OUT)["ret (nedene göre)"] == "risk.daily_loss_limit 1"  # hour 23
    assert report_lines(report, WHOLE)["ret (nedene göre)"] == "risk.daily_loss_limit 3"
    assert report_lines(report, WHOLE)["drawdown durdurması"] == "yok"


def test_drawdown_halt_lasts_to_end_closes_continue(tmp_path: Path) -> None:
    """R-7, BR-6: durdurma başladığı turdan sonuna kadar; alım yok, kapanışlar sürer."""
    series = {
        BTC: candles(-COUNT, [10, 8, 9, 10, 10, 9, 9, 15, 15, 15]),
        # ETH proposes at hours 1, 2 and 5
        ETH: candles(-COUNT, [10, 10, 10, 8, 9, 10, 10, 8, 9, 10]),
    }
    turn = settings(limits=limits(max_drawdown=Decimal("0.005")))
    run, chosen = run_case(tmp_path, series, 6, turn=turn, split_at=at(3))
    state = stored(run)
    assert state.risk.halted
    assert [p.pair for p in state.ledger.positions.values()] == []
    (closure,) = state.ledger.closures.values()
    assert (closure.position.pair, closure.closed_at) == (BTC, at(3))  # the target still closes
    report = run.report(chosen)
    assert report_lines(report, IN)["drawdown durdurması"] == "başladı 2026-01-01T01:00:00+00:00"
    assert report_lines(report, OUT)["drawdown durdurması"] == "parça başında sürüyordu"
    assert report_lines(report, WHOLE)["drawdown durdurması"] == "başladı 2026-01-01T01:00:00+00:00"
    assert "risk.drawdown_halt" in report_lines(report, IN)["ret (nedene göre)"]
    assert "risk.drawdown_halt" in report_lines(report, OUT)["ret (nedene göre)"]


def test_notices_are_counted_never_sent(tmp_path: Path) -> None:
    """R-8: bildirimler hiçbir alıcıya gitmez, konsola da yazılmaz; türe göre sayılır."""
    series = {
        BTC: candles(-COUNT, [10, 10, 10, 10, 10, None, 10, 10]),  # no candle at hour 1
        ETH: candles(-COUNT, flat(8)),
    }
    run, chosen = run_case(tmp_path, series, 4, turn=settings(), split_at=at(2))
    report = run.report(chosen)
    # hour 1: no price (invalid); hour 2: the last closed candle is an hour old (stale)
    assert report_lines(report, IN)["gönderilmeyen durum bildirimi (türe göre)"] == "invalid_data 1"
    assert report_lines(report, OUT)["gönderilmeyen durum bildirimi (türe göre)"] == "stale_data 1"
    assert report_lines(report, WHOLE)["gönderilmeyen durum bildirimi (türe göre)"] == (
        "invalid_data 1, stale_data 1"
    )
    assert not any("durum başladı" in line or "durum bitti" in line for line in run.lines)
    assert run.lines[2].startswith("rapor parmak izi: ")  # spec 0040 CB-1
    assert len(run.lines) == 4  # start, report, fingerprint, done: nothing else reached the console
