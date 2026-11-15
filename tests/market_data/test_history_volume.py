"""Spec 0045 plan Risk 1: indirme hacmi de yazar (sürüm 2); bozuk hacim güvenilmeyen veridir."""

from collections.abc import Callable
from pathlib import Path

import pytest

from crytobot.market_data import HistoryStopReason, read_history
from tests.market_data.helpers import BTC
from tests.market_data.history_helpers import (
    FakeHistoryExchange,
    full_history,
    leftovers,
    make_request,
    read_file,
    run_download,
)

Change = Callable[[list[list[object]]], object]


def test_volume_is_the_seventh_column_with_the_exchange_text(tmp_path: Path) -> None:
    history = full_history((BTC,))
    history[BTC][-8][5] = "0.00100000"
    path = tmp_path / "h.jsonl"

    result = run_download(make_request(path, pairs=(BTC,)), FakeHistoryExchange(history))

    assert result.stop is None
    data = read_file(path)
    assert data.header["version"] == 2
    assert all(len(row) == 7 and type(row[6]) is str for row in data.candles)
    by_open = {row[1]: row[6] for row in data.candles}
    assert by_open[history[BTC][-8][0]] == "0.00100000"  # trailing zeros kept
    read = read_history(str(path))
    assert read.data is not None and read.data.pairs[0].volumes is not None


def _last_volume(value: object) -> Change:
    def change(rows: list[list[object]]) -> object:
        return [*rows[:-1], [*rows[-1][:5], value, *rows[-1][6:]]]

    return change


@pytest.mark.parametrize(
    "change",
    [
        _last_volume("-1"),
        _last_volume("abc"),
        _last_volume(12.5),
        _last_volume("1e3"),
        lambda rows: [*rows[:-1], rows[-1][:5]],  # no volume column
    ],
    ids=["negative", "not_a_number", "float", "exponent", "missing"],
)
def test_bad_volume_stops_the_download_untrusted(tmp_path: Path, change: Change) -> None:
    exchange = FakeHistoryExchange(full_history((BTC,)), tamper={1: change})
    path = tmp_path / "h.jsonl"

    result = run_download(make_request(path, pairs=(BTC,)), exchange)

    assert result.stop is not None
    assert (result.stop.reason, result.stop.pair, result.stop.detail) == (
        HistoryStopReason.UNTRUSTED_DATA,
        BTC,
        "bad_volume",
    )
    assert leftovers(tmp_path) == []
