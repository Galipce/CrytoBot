"""Spec 0023 AC-1, AC-2: çok sayfalı indirme, ısınma, birebir değer, başlık; yalnız açık uçlar."""

from datetime import timedelta
from pathlib import Path

from crytobot.market_data import HistoryStopReason
from tests.market_data.helpers import BTC, ETH, HOUR_MS, market
from tests.market_data.history_helpers import (
    DOWNLOADED_AT,
    START,
    START_MS,
    WARMUP,
    FakeHistoryExchange,
    full_history,
    leftovers,
    make_request,
    read_file,
    rows_between,
    run_download,
)

DAYS = 50  # 1200 candles: more than one page of 1000
END_MS = START_MS + DAYS * 24 * HOUR_MS
WARM_MS = START_MS - WARMUP * HOUR_MS


def expected_lines(pair: str, rows: list[list[object]]) -> list[list[object]]:
    return [[pair, row[0], *row[1:5]] for row in rows if WARM_MS <= row[0] < END_MS]  # type: ignore[operator]


def test_multi_page_download_writes_every_closed_candle_exactly(tmp_path: Path) -> None:
    """AC-1, R-3: ısınma dahil dönemin bütün mumları, borsanın metniyle, çift sırasıyla."""
    history = full_history(days=DAYS, before=1500, after=20)
    exchange = FakeHistoryExchange(history)
    path = tmp_path / "history.jsonl"

    result = run_download(make_request(path, days=DAYS), exchange)

    assert result.stop is None
    data = read_file(path)
    assert data.candles == expected_lines(BTC, history[BTC]) + expected_lines(ETH, history[ETH])
    assert len([row for row in data.candles if row[0] == BTC]) == DAYS * 24 + WARMUP
    # 8 decimals and trailing zeros stay as the exchange wrote them
    assert data.candles[0][2:6] == history[BTC][1500 - WARMUP][1:5]
    assert all(type(text) is str for row in data.candles for text in row[2:])
    pages = [request for request in exchange.kline_requests if request["symbol"] == "BTCUSDT"]
    assert len(pages) == 2
    assert pages[0] == {"symbol": "BTCUSDT", "interval": "1h", "limit": 1000, "end_ms": END_MS - 1}
    assert pages[1]["end_ms"] == END_MS - 1000 * HOUR_MS - 1
    assert pages[1]["limit"] == DAYS * 24 + WARMUP - 1000
    assert leftovers(tmp_path) == ["history.jsonl"]


def test_header_carries_rules_tick_interval_period_and_moment(tmp_path: Path) -> None:
    """AC-1: başlık çift kurallarını, fiyat adımını, aralığı, dönemi ve indirme anını taşır."""
    path = tmp_path / "h.jsonl"
    run_download(make_request(path), FakeHistoryExchange(full_history()))

    data = read_file(path)
    assert data.header == {
        "format": "crytobot-history",
        "version": 1,
        "exchange": "binance",
        "candle_interval": "1h",
        "start": "2026-01-01T00:00:00+00:00",
        "end": "2026-01-03T00:00:00+00:00",
        "warmup_start": "2025-12-31T21:00:00+00:00",
        "downloaded_at": DOWNLOADED_AT.isoformat(),
        "pairs": [
            {
                "pair": pair,
                "market_id": pair.replace("/", ""),
                "tick": "0.01",
                "amount_step": "0.001",
                "min_amount": "0.001",
                "min_notional": "5",
            }
            for pair in (BTC, ETH)
        ],
    }
    assert data.complete == {"complete": True, "counts": {BTC: 48 + WARMUP, ETH: 48 + WARMUP}}


def test_rules_keep_plain_digits(tmp_path: Path) -> None:
    """Küçük adımlar `1E-8` değil borsanın düz metniyle yazılır."""
    small = market(BTC, precision={"price": "0.00000001", "amount": "0.10000000"})
    exchange = FakeHistoryExchange(full_history((BTC,)), markets_answer={BTC: small})
    path = tmp_path / "h.jsonl"
    run_download(make_request(path, pairs=(BTC,)), exchange)
    (pair,) = read_file(path).header["pairs"]
    assert pair["tick"] == "0.00000001" and pair["amount_step"] == "0.10000000"


def test_summary_names_first_last_count_and_gaps(tmp_path: Path) -> None:
    """AC-1: özet her çift için ilk ve son mumu, sayıyı ve boşluğu verir."""
    result = run_download(make_request(tmp_path / "h.jsonl"), FakeHistoryExchange(full_history()))
    assert [summary.pair for summary in result.summaries] == [BTC, ETH]
    for summary in result.summaries:
        assert summary.first_open == START - timedelta(hours=WARMUP)
        assert summary.last_open == START + timedelta(days=2) - timedelta(hours=1)
        assert summary.candles == 48 + WARMUP
        assert summary.gaps == 0
    assert result.downloaded_at == DOWNLOADED_AT


def test_candle_open_at_the_download_moment_is_not_written(tmp_path: Path) -> None:
    """AC-1, plan Risk 5: bitişi aşan (indirme anında açık) mum dosyaya girmez."""
    end = START + timedelta(days=1, minutes=30)
    history = {BTC: rows_between(START_MS - 10 * HOUR_MS, START_MS + 25 * HOUR_MS)}
    path = tmp_path / "h.jsonl"

    result = run_download(
        make_request(path, pairs=(BTC,), end=end), FakeHistoryExchange(history), clock=lambda: end
    )

    assert result.stop is None
    opens = [row[1] for row in read_file(path).candles]
    assert max(opens) == START_MS + 23 * HOUR_MS  # closes at 24:00, before the end at 24:30
    assert START_MS + 24 * HOUR_MS not in opens


def test_only_candle_and_rule_calls(tmp_path: Path) -> None:
    """AC-2, R-1: sahte borsa yalnız piyasa (kural) ve mum çağrısı görür; emir ve hesap yok."""
    exchange = FakeHistoryExchange(full_history(days=DAYS, before=1500))
    run_download(make_request(tmp_path / "h.jsonl", days=DAYS), exchange)
    assert exchange.calls[0] == "markets"
    assert {call.split(" ")[0] for call in exchange.calls} == {"markets", "klines"}
    assert exchange.calls.count("markets") == 1


def test_end_after_the_download_moment_is_refused_before_any_call(tmp_path: Path) -> None:
    """R-2: indirme kendi sınırını da korur: bitiş indirme anından sonra olamaz."""
    exchange = FakeHistoryExchange(full_history())
    result = run_download(
        make_request(tmp_path / "h.jsonl"), exchange, clock=lambda: START + timedelta(days=1)
    )
    assert result.stop is not None and result.stop.reason is HistoryStopReason.INPUT
    assert result.stop.detail == "end"
    assert exchange.calls == [] and leftovers(tmp_path) == []
