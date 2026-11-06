"""Spec 0023 AC-6, R-6: geç listelenen çift, boşluklar (doldurulmaz, sayılır), mumsuz ve olmayan
çift."""

from datetime import timedelta
from pathlib import Path

import pytest

from crytobot.market_data import HistoryResult, HistoryStop, HistoryStopReason, PairSummary
from tests.market_data.helpers import BTC, ETH, HOUR_MS, market
from tests.market_data.history_helpers import (
    START,
    START_MS,
    WARMUP,
    FakeHistoryExchange,
    at,
    full_history,
    leftovers,
    make_request,
    read_file,
    rows_between,
    run_download,
)

END_MS = START_MS + 2 * 24 * HOUR_MS
WARM_MS = START_MS - WARMUP * HOUR_MS


def without(rows: list[list[object]], *hours: int) -> list[list[object]]:
    """`hours`: dönem başından saat cinsinden çıkarılacak mumlar (eksi değer ısınmadadır)."""
    missing = {START_MS + hour * HOUR_MS for hour in hours}
    return [row for row in rows if row[0] not in missing]


def btc_summary(tmp_path: Path, rows: list[list[object]]) -> tuple[PairSummary, list[int]]:
    path = tmp_path / "h.jsonl"
    result = run_download(make_request(path, pairs=(BTC,)), FakeHistoryExchange({BTC: rows}))
    assert result.stop is None, result.stop
    (summary,) = result.summaries
    return summary, [row[1] for row in read_file(path).candles]


def stopped(tmp_path: Path, result: HistoryResult, reason: HistoryStopReason) -> HistoryStop:
    assert result.stop is not None and result.stop.reason is reason
    assert leftovers(tmp_path) == []
    return result.stop


def test_pair_listed_inside_the_period_starts_at_its_first_candle(tmp_path: Path) -> None:
    """AC-6: geç listelenen çift hata değildir; ilk mumundan başlar, öncesi boşluk sayılmaz."""
    late = rows_between(START_MS + 5 * HOUR_MS, END_MS + 3 * HOUR_MS)
    history = {**full_history((BTC,)), ETH: late}
    path = tmp_path / "h.jsonl"
    exchange = FakeHistoryExchange(history)

    result = run_download(make_request(path), exchange)

    assert result.stop is None
    eth = result.summaries[1]
    assert eth.first_open == START + timedelta(hours=5)
    assert eth.candles == 48 - 5 and eth.gaps == 0
    eth_opens = [row[1] for row in read_file(path).candles if row[0] == ETH]
    assert eth_opens[0] == START_MS + 5 * HOUR_MS
    eth_pages = [request for request in exchange.kline_requests if request["symbol"] == "ETHUSDT"]
    assert len(eth_pages) == 2 and eth_pages[1]["end_ms"] == START_MS + 5 * HOUR_MS - 1


@pytest.mark.parametrize(
    ("missing", "gaps"),
    [
        ((10,), 1),
        ((10, 11, 12), 1),
        ((10, 20), 2),
        ((0,), 1),  # the first candle of the period, warm-up candles before it
        ((-2,), 0),  # warm-up only: not inside the period
        ((-1, 0), 1),  # crossing the start
        ((47,), 1),  # the end of the period
        ((46, 47), 1),
        ((5, 46, 47), 2),
    ],
)
def test_gaps_stay_unfilled_and_are_counted(
    tmp_path: Path, missing: tuple[int, ...], gaps: int
) -> None:
    """AC-6: boşluk doldurulmaz; dönem içindeki her kopukluk bir kez sayılır (plan Risk 6)."""
    rows = without(full_history((BTC,))[BTC], *missing)
    summary, opens = btc_summary(tmp_path, rows)
    assert summary.gaps == gaps
    expected = [
        ms for ms in range(WARM_MS, END_MS, HOUR_MS) if (ms - START_MS) // HOUR_MS not in missing
    ]
    assert opens == expected
    assert summary.candles == len(expected)
    assert summary.last_open == at(expected[-1])


def test_missing_warm_up_is_not_a_gap(tmp_path: Path) -> None:
    """Çift dönem başında listelendiyse ısınma mumu yoktur; bu boşluk değildir."""
    summary, opens = btc_summary(tmp_path, rows_between(START_MS, END_MS))
    assert summary.gaps == 0 and opens[0] == START_MS and summary.first_open == START


@pytest.mark.parametrize(
    "rows",
    [
        [],
        rows_between(START_MS - 50 * HOUR_MS, START_MS),  # delisted before the period
    ],
    ids=["no_history", "only_before_the_period"],
)
def test_pair_without_candles_in_the_period_stops(tmp_path: Path, rows: list[list[object]]) -> None:
    """AC-6: dönem boyunca mumu olmayan çift indirmeyi durdurur, çift adıyla."""
    exchange = FakeHistoryExchange({**full_history((BTC,)), ETH: rows})
    result = run_download(make_request(tmp_path / "h.jsonl"), exchange)
    stop = stopped(tmp_path, result, HistoryStopReason.NO_CANDLES)
    assert stop.pair == ETH


@pytest.mark.parametrize(
    ("entry", "detail"),
    [
        (None, "not_listed"),
        (market("ETH/BTC"), "not_usdt"),
        (market(ETH, info={"isSpotTradingAllowed": False}), "not_spot"),
        (market(ETH, active=False), "not_trading"),
    ],
)
def test_pair_missing_on_the_exchange_stops_with_its_name(
    tmp_path: Path, entry: object, detail: str
) -> None:
    """AC-6: borsada olmayan ya da kullanılamayan çift; mum istenmez, dosya kalmaz."""
    markets: dict[str, object] = {BTC: market(BTC)}
    if entry is not None:
        markets[ETH] = {**entry, "symbol": ETH} if isinstance(entry, dict) else entry
    exchange = FakeHistoryExchange(full_history(), markets_answer=markets)
    result = run_download(make_request(tmp_path / "h.jsonl"), exchange)
    stop = stopped(tmp_path, result, HistoryStopReason.PAIR_UNAVAILABLE)
    assert stop.pair == ETH and stop.detail == detail
    assert exchange.kline_requests == []
