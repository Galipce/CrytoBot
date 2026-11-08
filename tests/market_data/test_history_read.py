"""Spec 0025 AC-5 (dosya kısmı), plan Risk 5: veri dosyasını okumak.

Dosya gerçek indirmeyle (0023, sahte borsa) yazılır; bozuk hâller satırları değiştirerek üretilir.
"""

import json
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.market_data import HistoryReadProblem, read_history
from tests.market_data.helpers import BTC, ETH, HOUR
from tests.market_data.history_helpers import (
    DOWNLOADED_AT,
    START,
    WARMUP,
    FakeHistoryExchange,
    full_history,
    make_request,
    run_download,
)

Lines = list[Any]


@pytest.fixture
def data_file(tmp_path: Path) -> Path:
    path = tmp_path / "history.jsonl"
    result = run_download(make_request(path, days=1), FakeHistoryExchange(full_history(days=1)))
    assert result.stop is None, result.stop
    return path


def lines(path: Path) -> Lines:
    return [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]


def rewrite(path: Path, change: Callable[[Lines], Lines]) -> None:
    rows = change(lines(path))
    text = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows
    )
    path.write_text(text, encoding="utf-8")


def recount(rows: Lines) -> Lines:
    """Tamamlanma satırının sayımlarını mum satırlarına göre yeniden yazar."""
    counts = {pair["pair"]: 0 for pair in rows[0]["pairs"]}
    for row in rows[1:-1]:
        counts[row[0]] = counts.get(row[0], 0) + 1
    return [*rows[:-1], {"complete": True, "counts": counts}]


def test_reads_the_downloaded_file(data_file: Path) -> None:
    read = read_history(str(data_file))

    assert read.problem is None
    data = read.data
    assert data is not None
    assert (data.start, data.end, data.downloaded_at) == (
        START,
        START + timedelta(days=1),
        DOWNLOADED_AT,
    )
    assert data.warmup_start == START - WARMUP * HOUR
    assert data.candle_interval == HOUR
    assert data.exchange == "binance"
    assert [pair.pair for pair in data.pairs] == [BTC, ETH]
    btc = data.pairs[0]
    assert btc.tick == Decimal("0.01")
    assert (btc.rules.amount_step, btc.rules.min_amount, btc.rules.min_notional) == (
        Decimal("0.001"),
        Decimal("0.001"),
        Decimal(5),
    )
    assert len(btc.candles) == WARMUP + 24
    assert btc.candles[0].open_time == data.warmup_start
    assert btc.candles[-1].open_time == data.end - HOUR
    assert btc.candles[0].open == Decimal("107.10000000")  # 7th row of the history, its text


def test_reading_writes_nothing(data_file: Path) -> None:
    before = data_file.read_bytes()
    read_history(str(data_file))
    assert data_file.read_bytes() == before
    assert sorted(p.name for p in data_file.parent.iterdir()) == [data_file.name]


def test_missing_file(tmp_path: Path) -> None:
    read = read_history(str(tmp_path / "yok.jsonl"))
    assert (read.data, read.problem) == (None, HistoryReadProblem.MISSING)


def test_unreadable_file(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_bytes(b"\xff\xfe\x00bozuk")
    assert read_history(str(path)).problem is HistoryReadProblem.UNREADABLE
    assert read_history(str(tmp_path)).problem is HistoryReadProblem.UNREADABLE  # a directory


def test_incomplete_without_complete_line(data_file: Path) -> None:
    rewrite(data_file, lambda rows: rows[:-1])
    read = read_history(str(data_file))
    assert (read.data, read.problem) == (None, HistoryReadProblem.INCOMPLETE)


def test_header_only_is_incomplete(data_file: Path) -> None:
    rewrite(data_file, lambda rows: rows[:1])
    assert read_history(str(data_file)).problem is HistoryReadProblem.INCOMPLETE


def _header(**changes: Any) -> Callable[[Lines], Lines]:
    def change(rows: Lines) -> Lines:
        return [{**rows[0], **changes}, *rows[1:]]

    return change


def _first_pair(**changes: Any) -> Callable[[Lines], Lines]:
    def change(rows: Lines) -> Lines:
        pairs = [{**rows[0]["pairs"][0], **changes}, *rows[0]["pairs"][1:]]
        return [{**rows[0], "pairs": pairs}, *rows[1:]]

    return change


def _candle(index: int, value: Any) -> Callable[[Lines], Lines]:
    def change(rows: Lines) -> Lines:
        rows[index] = value(rows[index]) if callable(value) else value
        return rows

    return change


CORRUPT: dict[str, Callable[[Lines], Lines]] = {
    "format": _header(format="baska"),
    "version": _header(version=2),
    "interval": _header(candle_interval="7m"),
    "exchange": _header(exchange=""),
    "start not UTC": _header(start="2026-01-01T03:00:00+03:00"),
    "start not a time": _header(start="dün"),
    "end before start": _header(end="2025-12-01T00:00:00+00:00"),
    "warmup after start": _header(warmup_start="2026-01-02T00:00:00+00:00"),
    "no pairs": _header(pairs=[]),
    "pairs not a list": _header(pairs="BTC/USDT"),
    "duplicate pair": lambda rows: [{**rows[0], "pairs": [rows[0]["pairs"][0]] * 2}, *rows[1:]],
    "tick zero": _first_pair(tick="0"),
    "tick not plain": _first_pair(tick="1e-2"),
    "pair not text": _first_pair(pair=7),
    "header not object": lambda rows: [[1, 2], *rows[1:]],
    "candle short": _candle(1, lambda row: row[:5]),
    "candle pair unknown": _candle(1, lambda row: ["XRP/USDT", *row[1:]]),
    "candle time not int": _candle(1, lambda row: [row[0], str(row[1]), *row[2:]]),
    "pair order": lambda rows: [rows[0], rows[-2], *rows[1:-2], rows[-1]],
    "counts": lambda rows: [*rows[:-1], {"complete": True, "counts": {BTC: 1, ETH: 1}}],
    "counts missing pair": lambda rows: [*rows[:-1], {"complete": True, "counts": {BTC: 27}}],
    "complete not true": lambda rows: [*rows[:-1], {**rows[-1], "complete": False}],
    "line after complete": lambda rows: [*rows, rows[1]],
    "candle after end": lambda rows: recount(
        [*rows[:-1], [ETH, rows[-2][1] + 3_600_000, *rows[-2][2:]], rows[-1]]
    ),
    "candle before warm-up": lambda rows: recount(
        [rows[0], [BTC, rows[1][1] - 3_600_000, *rows[1][2:]], *rows[1:]]
    ),
}


@pytest.mark.parametrize("case", sorted(CORRUPT))
def test_corrupt_file(data_file: Path, case: str) -> None:
    rewrite(data_file, CORRUPT[case])
    read = read_history(str(data_file))
    assert (read.data, read.problem) == (None, HistoryReadProblem.CORRUPT), case


@pytest.mark.parametrize("text", ["", "\n", "{bozuk\n", "[1,2\n"])
def test_not_json_is_corrupt(tmp_path: Path, text: str) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text(text, encoding="utf-8")
    assert read_history(str(path)).problem is HistoryReadProblem.CORRUPT


def _prices(index: int, open_: str, high: str, low: str, close: str) -> Callable[[Lines], Lines]:
    return _candle(index, lambda row: [row[0], row[1], open_, high, low, close])


def _time(index: int, delta_ms: int) -> Callable[[Lines], Lines]:
    return _candle(index, lambda row: [row[0], row[1] + delta_ms, *row[2:]])


UNTRUSTED: dict[str, tuple[Callable[[Lines], Lines], str]] = {
    "high below low": (_prices(2, "10", "9", "11", "10"), "high_below_low"),
    "outside range": (_prices(2, "12", "11", "9", "10"), "price_outside_range"),
    "zero": (_prices(2, "0", "11", "9", "10"), "not_positive"),
    "negative": (_prices(2, "10", "11", "-9", "10"), "not_positive"),
    "not a number": (_prices(2, "on", "11", "9", "10"), "not_a_number"),
    "duplicate time": (_time(3, -3_600_000), "duplicate_time"),
    "out of order": (_time(3, -7_200_000), "time_out_of_order"),
    "off interval": (_time(3, 1_000), "time_off_interval"),
    "negative time": (_candle(2, lambda row: [row[0], -1, *row[2:]]), "not_a_number"),
}


@pytest.mark.parametrize("case", sorted(UNTRUSTED))
def test_untrusted_candle_names_pair_and_reason(data_file: Path, case: str) -> None:
    """R-3: 0017'nin güvenilmez saydığı her mum güvenilmeyen veridir; neden adıyla döner."""
    change, reason = UNTRUSTED[case]
    rewrite(data_file, change)
    read = read_history(str(data_file))
    assert (read.data, read.problem, read.pair, read.detail) == (
        None,
        HistoryReadProblem.UNTRUSTED,
        BTC,
        reason,
    )


def test_structure_is_judged_before_values(data_file: Path) -> None:
    """Güvenilmeyen mum ve eksik tamamlanma satırı birlikte: önce dosyanın yapısı."""
    rewrite(data_file, lambda rows: _prices(2, "10", "9", "11", "10")(rows)[:-1])
    assert read_history(str(data_file)).problem is HistoryReadProblem.INCOMPLETE


def test_gap_is_not_untrusted(data_file: Path) -> None:
    """R-6: boşluk doldurulmaz, güvenilmezlik değildir."""
    rewrite(data_file, lambda rows: recount([*rows[:5], *rows[6:]]))
    read = read_history(str(data_file))
    assert read.problem is None and read.data is not None
    assert len(read.data.pairs[0].candles) == WARMUP + 24 - 1


def test_pair_without_candles_reads(data_file: Path) -> None:
    rewrite(
        data_file,
        lambda rows: recount(
            [row for row in rows if not (isinstance(row, list) and row[0] == ETH)]
        ),
    )
    read = read_history(str(data_file))
    assert read.data is not None
    assert read.data.pairs[1].candles == ()
