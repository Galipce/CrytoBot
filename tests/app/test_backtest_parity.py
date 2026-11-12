"""Spec 0025 AC-2 (R-5): aynı mumlar, fiyat, kurallar ve ayarlarla backtest turu paper turunun
aynı kararlarını verir.

Paper tarafı okumanın yolundan geçer: aynı `MarketCandle`'lar bir `MarketRead`'e konur,
`to_turn_market` tur girdisine çevirir. Backtest tarafı veri dosyasından `TurnInputs` ile kurar.
İki taraf ayrı depolarda, aynı `run_turn` ile, aynı anlarda koşar.
"""

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import PairMarket, TurnMemory, TurnResult, run_turn, to_turn_market
from crytobot.app._backtest_inputs import TurnInputs
from crytobot.execution import PaperExchange
from crytobot.market_data import HistoryData, MarketRead, PairRead
from crytobot.risk import TradeIntent
from crytobot.strategy import (
    BreakoutSettings,
    Settings,
    TrendDipSettings,
    TrendFilterSettings,
    propose,
    required_candles,
)
from tests.app.backtest_helpers import COUNT, MARKET_RULES, at, candles, history, settings
from tests.app.helpers import BTC, ETH, HOUR, SPREAD, STRATEGY, TICK, limits, opened_store

SCENARIOS: dict[str, dict[str, Any]] = {
    # buy BTC at hour 0, its target (14) is reached at hour 2
    "buy then target": {
        BTC: candles(-COUNT, [10, 8, 9, 10, 10, 12, 15]),
        ETH: candles(-COUNT, [10, 10, 10, 10, 10, 10, 10]),
    },
    # buy at hour 0, the stop (8) is reached at hour 1; ETH proposes at hour 2
    "buy then stop": {
        BTC: candles(-COUNT, [10, 8, 9, 10, 10, 7, 7]),
        ETH: candles(-COUNT, [10, 10, 10, 8, 9, 10, 10]),
    },
    # ETH has no candle at hour 1: every buy stops in that turn
    "missing price": {
        BTC: candles(-COUNT, [10, 10, 10, 8, 9, 10, 10]),
        ETH: candles(-COUNT, [10, 10, 10, 10, 10, None, 10]),
    },
    # ETH lists at hour 1
    "late pair": {
        BTC: candles(-COUNT, [10, 8, 9, 10, 10, 10, 10]),
        ETH: candles(1, [10, 10]),
    },
}


def paper_market(data: HistoryData, moment: Any, count: int = COUNT) -> dict[str, PairMarket]:
    """Okumanın vereceği `PairRead`: aynı kapanmış mumlar, fiyat tur anının açılışı."""
    reads = []
    for pair in data.pairs:
        closed = [item for item in pair.candles if item.open_time + HOUR <= moment][-count:]
        opening = [item for item in pair.candles if item.open_time == moment]
        price = opening[0].open if opening else None
        reads.append(
            PairRead(
                pair.pair,
                tuple(closed),
                price,
                moment if price is not None else None,
                SPREAD,
                TICK,
                MARKET_RULES,
                (),
            )
        )
    return to_turn_market(MarketRead(tuple(reads), moment, None))


def decisions(result: TurnResult) -> tuple[object, ...]:
    return (
        result.outcome,
        [(o.pair, o.amount, o.fill_price, o.status) for o in result.buys],
        [(o.pair, o.amount, o.fill_price, o.status) for o in result.closes],
        [(p.pair, p.reason) for p in result.pairs],
        result.halts,
        result.message,
    )


def run(store: Path, market: Callable[[Any], dict[str, PairMarket]], **turn: Any) -> list[Any]:
    memory, exchange, seen = TurnMemory(), PaperExchange(), []
    for hour in range(3):
        result = run_turn(
            market=market(at(hour)),
            settings=settings(**turn),
            store_path=opened_store(store, at=at(-1)) if hour == 0 else store,
            now=at(hour),
            exchange=exchange,
            sink=lambda _notice: None,
            memory=memory,
        )
        seen.append(decisions(result))
    return seen


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_backtest_turn_decides_like_paper_turn(tmp_path: Path, name: str) -> None:
    data = history(SCENARIOS[name], hours=3)
    source = TurnInputs(data, settings(), COUNT, SPREAD)
    backtest = run(tmp_path / "backtest.db", source.market)
    paper = run(tmp_path / "paper.db", lambda moment: paper_market(data, moment))
    assert backtest == paper
    assert any(turn[1] or turn[2] or turn[3] for turn in backtest)  # something was decided


def test_risk_refusals_match(tmp_path: Path) -> None:
    """Ret nedenleri de aynıdır: tek açık pozisyon sınırında ikinci alım reddedilir."""
    data = history(
        {
            BTC: candles(-COUNT, [10, 8, 9, 10, 10, 10, 10]),
            ETH: candles(-COUNT, [10, 8, 9, 10, 10, 10, 10]),
        },
        hours=3,
    )
    narrow = {"limits": limits(max_open_positions=1)}
    source = TurnInputs(data, settings(**narrow), COUNT, SPREAD)
    backtest = run(tmp_path / "backtest.db", source.market, **narrow)
    paper = run(tmp_path / "paper.db", lambda moment: paper_market(data, moment), **narrow)
    assert backtest == paper
    assert [reason.value for _, reason in backtest[0][3]] == ["position_limit"]


# --- spec 0043 AC-2 (R-1): her aday backtest ve paper turunda aynı öneriyi üretir ---

CANDIDATE_SCENARIOS: dict[str, tuple[Settings, list[Any]]] = {
    # every series proposes a buy at hour 0 (the last closed candle is hour -1)
    "S0": (STRATEGY, [10, 8, 9, 10, 10, 12, 15]),
    "S1": (
        TrendFilterSettings(1, 2, 2, Decimal(70), 2, Decimal(2), Decimal(2), 4),
        [12, 8, 9, 10, 10, 12, 15],
    ),
    "S2": (
        BreakoutSettings(3, 2, Decimal(2), Decimal(2)),
        [(10, 11, 9, 10), (10, 12, 9, 10), (10, 11, 9, 10), (12.5, 13, 9, 12.5), 12.5, 13, 15],
    ),
    "S3": (
        TrendDipSettings(2, Decimal(51), 2, Decimal(2), Decimal(2)),
        [100] * 196 + [120, 118, 116, 115, 115, 120, 130],
    ),
}


@pytest.mark.parametrize("name", sorted(CANDIDATE_SCENARIOS))
def test_each_candidate_same_proposal_backtest_and_paper(tmp_path: Path, name: str) -> None:
    """AC-2: aynı mumlar ve ayarla aday, backtest ve paper turunda aynı öneriyi (giriş, stop,
    hedef) ve aynı kararları verir; öneri gerçekten vardır."""
    strategy, values = CANDIDATE_SCENARIOS[name]
    warm = count = len(values) - 3  # every warm candle is read (R-4: enough for the candidate)
    assert count >= required_candles(strategy)
    data = history(
        {BTC: candles(-warm, values), ETH: candles(-warm, [10] * len(values))},
        hours=3,
        count=warm,
    )
    source = TurnInputs(data, settings(strategy=strategy), count, SPREAD)
    proposals = []
    for hour in range(3):
        sides = []
        for market in (source.market(at(hour)), paper_market(data, at(hour), count)):
            item = market[BTC]
            sides.append(
                propose(
                    pair=BTC,
                    candles=item.candles,  # type: ignore[arg-type]
                    position_open=False,
                    tick=item.tick,  # type: ignore[arg-type]
                    settings=strategy,
                )
            )
        assert sides[0] == sides[1]
        proposals.append(sides[0])
    assert isinstance(proposals[0], TradeIntent)  # a buy at hour 0: the comparison is not empty
    backtest = run(tmp_path / "backtest.db", source.market, strategy=strategy)
    paper = run(
        tmp_path / "paper.db",
        lambda moment: paper_market(data, moment, count),
        strategy=strategy,
    )
    assert backtest == paper
    assert backtest[0][1]  # the buy was placed
