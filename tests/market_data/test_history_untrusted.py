"""Spec 0023 AC-5, R-5: okumanın güvenilmez saydığı her mum, tekrar, sıra, dönem dışı mum ve
kuralları eksik çift indirmeyi durdurur; nedeni adıyla söylenir, ne dosya ne `.part` kalır."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from crytobot.market_data import HistoryResult, HistoryStop, HistoryStopReason
from tests.market_data.helpers import BTC, ETH, HOUR_MS, market
from tests.market_data.history_helpers import (
    START_MS,
    FakeHistoryExchange,
    full_history,
    leftovers,
    make_request,
    price_row,
    run_download,
)

Change = Callable[[list[list[object]]], object]
END_MS = START_MS + 2 * 24 * HOUR_MS


def replace_last(**columns: object) -> Change:
    """Sayfanın son satırında verilen sütunları değiştirir (`o`, `h`, `l`, `c`, `t`)."""
    index = {"t": 0, "o": 1, "h": 2, "l": 3, "c": 4}

    def change(rows: list[list[object]]) -> object:
        last = list(rows[-1])
        for name, value in columns.items():
            last[index[name]] = value
        return [*rows[:-1], last]

    return change


ROW_CASES: dict[str, tuple[Change, str]] = {
    "short_row": (lambda rows: [*rows[:-1], rows[-1][:3]], "malformed_response"),
    "not_a_number": (replace_last(c="abc"), "not_a_number"),
    "float_price": (replace_last(c=10.5), "not_a_number"),
    "exponent": (replace_last(c="1e3"), "not_a_number"),
    "negative": (replace_last(l="-1.0"), "not_positive"),
    "zero": (replace_last(l="0"), "not_positive"),
    "high_below_low": (replace_last(h="1.0", l="2.0", o="1.5", c="1.5"), "high_below_low"),
    "outside_range": (replace_last(c="999.0"), "price_outside_range"),
    "bad_stamp": (replace_last(t="1767225600000"), "not_a_number"),
    "off_interval": (replace_last(t=END_MS - HOUR_MS + 1), "time_off_interval"),
    "duplicate": (lambda rows: [*rows[:-1], rows[-2]], "duplicate_time"),
    "out_of_order": (lambda rows: [*rows[:-2], rows[-1], rows[-2]], "time_out_of_order"),
    "outside_request": (
        lambda rows: [*rows, price_row(END_MS, 0)][-len(rows) :],
        "outside_request",
    ),
    "not_a_list": (lambda rows: {"rows": rows}, "malformed_response"),
    "too_many": (lambda rows: [price_row(START_MS - 999 * HOUR_MS, 0), *rows], "too_many_candles"),
}


def stopped_cleanly(
    tmp_path: Path, result: HistoryResult, reason: HistoryStopReason
) -> HistoryStop:
    assert result.stop is not None and result.stop.reason is reason
    assert result.summaries == ()
    assert leftovers(tmp_path) == []
    return result.stop


@pytest.mark.parametrize("case", sorted(ROW_CASES))
def test_untrusted_candle_stops_the_download(tmp_path: Path, case: str) -> None:
    change, detail = ROW_CASES[case]
    exchange = FakeHistoryExchange(full_history(), tamper={2: change})  # ETH, after BTC is held
    result = run_download(make_request(tmp_path / "h.jsonl"), exchange)
    stop = stopped_cleanly(tmp_path, result, HistoryStopReason.UNTRUSTED_DATA)
    assert stop.pair == ETH and stop.detail == detail
    assert len(exchange.kline_requests) == 2  # nothing is asked after the stop


def second_page_change(extra_open: int) -> Change:
    """İkinci sayfanın sonuna, ilk sayfanın içinden bir açılış ekler."""

    def change(rows: list[list[object]]) -> object:
        return [*rows[1:], price_row(extra_open, 0)]

    return change


@pytest.mark.parametrize(
    ("offset", "detail"), [(0, "duplicate_time"), (HOUR_MS, "time_out_of_order")]
)
def test_page_overlapping_the_later_page_is_untrusted(
    tmp_path: Path, offset: int, detail: str
) -> None:
    """Tekrarlanan ve sırası bozuk mum sayfalar arasında da yakalanır."""
    days = 50
    end_ms = START_MS + days * 24 * HOUR_MS
    first_of_page_one = end_ms - 1000 * HOUR_MS
    exchange = FakeHistoryExchange(
        full_history((BTC,), days=days, before=1500),
        tamper={2: second_page_change(first_of_page_one + offset)},
    )
    result = run_download(make_request(tmp_path / "h.jsonl", pairs=(BTC,), days=days), exchange)
    stop = stopped_cleanly(tmp_path, result, HistoryStopReason.UNTRUSTED_DATA)
    assert stop.pair == BTC and stop.detail == detail


@pytest.mark.parametrize(
    ("changes", "detail"),
    [
        ({"precision": {"amount": "0.001"}}, "tick_not_reported"),
        ({"limits": {"amount": {"min": "0.001"}, "cost": {}}}, "rule_not_reported"),
        ({"precision": {"price": "0", "amount": "0.001"}}, "malformed_response"),
    ],
)
def test_pair_with_missing_rules_stops_before_any_candle(
    tmp_path: Path, changes: dict[str, Any], detail: str
) -> None:
    markets = {BTC: market(BTC), ETH: market(ETH, **changes)}
    exchange = FakeHistoryExchange(full_history(), markets_answer=markets)
    result = run_download(make_request(tmp_path / "h.jsonl"), exchange)
    stop = stopped_cleanly(tmp_path, result, HistoryStopReason.MISSING_RULES)
    assert stop.pair == ETH and stop.detail == detail
    assert exchange.kline_requests == []


@pytest.mark.parametrize(
    "entry",
    [
        market(BTC, symbol="ETH/USDT"),
        market(BTC, id="btc usdt"),
        "not a market",
    ],
)
def test_malformed_market_entry_is_untrusted(tmp_path: Path, entry: object) -> None:
    exchange = FakeHistoryExchange(full_history((BTC,)), markets_answer={BTC: entry})
    result = run_download(make_request(tmp_path / "h.jsonl", pairs=(BTC,)), exchange)
    stop = stopped_cleanly(tmp_path, result, HistoryStopReason.UNTRUSTED_DATA)
    assert stop.pair == BTC and stop.detail == "malformed_response"


def test_markets_answer_that_is_not_a_mapping_is_an_exchange_error(tmp_path: Path) -> None:
    exchange = FakeHistoryExchange(full_history(), markets_answer=["BTC/USDT"])
    result = run_download(make_request(tmp_path / "h.jsonl"), exchange)
    stop = stopped_cleanly(tmp_path, result, HistoryStopReason.EXCHANGE_ERROR)
    assert stop.detail == "malformed_response"
