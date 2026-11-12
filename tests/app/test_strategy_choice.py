"""Spec 0043 AC-1 (R-1, K-4): ayarda strateji seçimi yoksa S0 ve bugünkü davranış aynen sürer.

Ayar yükleyicisi adsız ve `name = "S0"` belgelerden aynı ayarı kurar; ikisiyle koşan backtest aynı
raporu (işlemler ve metrikler), paper turları aynı kararları verir. Strateji periyotları küçük
fixture'a yeten değerlerdir (R-4).
"""

from pathlib import Path
from typing import Any

from crytobot.app import BacktestOutcome, load_config
from crytobot.app._backtest_inputs import TurnInputs
from crytobot.strategy import Settings, StrategySettings
from tests.app.backtest_helpers import COUNT, Run, candles, config, history, settings, write_history
from tests.app.helpers import BTC, ETH, SPREAD
from tests.app.test_backtest_parity import paper_market
from tests.app.test_backtest_parity import run as paper_turns
from tests.app.test_config import NOW, document

SMALL = {
    "strategy.fast_period": 1,
    "strategy.slow_period": 2,
    "strategy.rsi_period": 2,
    "strategy.atr_period": 2,
    "market.candle_count": COUNT,
}
SERIES = {
    BTC: candles(-COUNT, [10, 8, 9, 10, 10, 12, 15, 15]),
    ETH: candles(-COUNT, [10, 10, 10, 8, 9, 10, 10, 10]),
}


def loaded(**changes: Any) -> Settings:
    result = load_config(document(**SMALL, **changes), NOW)
    assert result.config is not None, result.message
    return result.config.turn.strategy


def backtest_report(root: Path, strategy: Settings) -> str:
    root.mkdir()
    chosen = config(root, turn=settings((BTC, ETH), strategy=strategy))
    write_history(Path(chosen.data_path), history(SERIES, hours=4))
    run = Run(root)
    outcome = run(chosen)
    assert outcome.outcome is BacktestOutcome.COMPLETED, outcome.message
    return run.report(chosen)


def test_no_name_equals_explicit_s0(tmp_path: Path) -> None:
    implicit, explicit = loaded(), loaded(**{"strategy.name": "S0"})
    assert isinstance(implicit, StrategySettings)  # the type every S0 test already runs
    assert implicit == explicit
    # backtest: same trades and metrics, byte for byte
    first = backtest_report(tmp_path / "adsiz", implicit)
    second = backtest_report(tmp_path / "s0", explicit)
    assert first == second
    # paper: same decisions turn by turn
    data = history(SERIES, hours=3)
    for name, strategy in (("adsiz", implicit), ("s0", explicit)):
        source = TurnInputs(data, settings((BTC, ETH), strategy=strategy), COUNT, SPREAD)
        backtest = paper_turns(tmp_path / f"{name}-b.db", source.market, strategy=strategy)
        paper = paper_turns(
            tmp_path / f"{name}-p.db",
            lambda moment: paper_market(data, moment),
            strategy=strategy,
        )
        assert backtest == paper
        assert any(turn[1] for turn in paper)  # a buy was decided
    left = paper_turns(tmp_path / "x.db", lambda m: paper_market(data, m), strategy=implicit)
    right = paper_turns(tmp_path / "y.db", lambda m: paper_market(data, m), strategy=explicit)
    assert left == right
