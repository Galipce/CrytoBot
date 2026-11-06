"""Spec 0023 AC-4, R-4, R-8; plan Risk 7, 8: veri dosyası biçimi, var olan yol, `.part`, son ad.

Var olan dosya (okunabilir ya da bozuk), dizin ya da yarım kalmış `.part` varken indirme borsaya
çıkmadan reddeder ve hiçbir baytı değiştirmez.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crytobot.market_data import HistoryResult, HistoryStop, HistoryStopReason, _history
from crytobot.market_data._history_file import HistoryFileError, HistoryWriter, part_path
from tests.market_data.helpers import BTC
from tests.market_data.history_helpers import (
    START,
    FakeHistoryExchange,
    full_history,
    leftovers,
    make_request,
    read_file,
    rows_between,
    run_download,
)


def stopped(result: HistoryResult, reason: HistoryStopReason) -> HistoryStop:
    assert result.stop is not None and result.stop.reason is reason, result.stop
    assert result.summaries == ()
    return result.stop


@pytest.mark.parametrize(
    "content",
    [
        b'{"format":"crytobot-history","version":1}\n{"complete":true,"counts":{}}\n',
        b"\x00\xff\xfe not a data file",
        b"",
    ],
    ids=["readable", "corrupt", "empty"],
)
def test_existing_file_is_refused_without_a_call_or_a_change(
    tmp_path: Path, content: bytes
) -> None:
    """AC-4: dosya bayt bayt aynı kalır; borsaya hiçbir çağrı gitmez."""
    path = tmp_path / "h.jsonl"
    path.write_bytes(content)
    exchange = FakeHistoryExchange(full_history())

    result = run_download(make_request(path), exchange)

    stopped(result, HistoryStopReason.DATA_FILE_EXISTS)
    assert path.read_bytes() == content
    assert exchange.calls == []
    assert leftovers(tmp_path) == ["h.jsonl"]


def test_directory_at_the_path_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "h.jsonl"
    path.mkdir()
    exchange = FakeHistoryExchange(full_history())
    stopped(run_download(make_request(path), exchange), HistoryStopReason.DATA_FILE_EXISTS)
    assert exchange.calls == [] and path.is_dir()


def test_left_over_part_file_is_refused_and_kept(tmp_path: Path) -> None:
    """Plan Risk 8: var olan `.part` başka bir indirmenindir; reddedilir, silinmez."""
    path = tmp_path / "h.jsonl"
    part = part_path(path)
    part.write_bytes(b"half")
    exchange = FakeHistoryExchange(full_history())
    stopped(run_download(make_request(path), exchange), HistoryStopReason.PART_FILE_EXISTS)
    assert part.read_bytes() == b"half" and exchange.calls == []
    assert leftovers(tmp_path) == ["h.jsonl.part"]


def test_file_appearing_during_the_download_is_never_overwritten(tmp_path: Path) -> None:
    """Plan Risk 8: son ad bağlanırken hedef varsa üzerine yazılmaz; `.part` silinir."""
    path = tmp_path / "h.jsonl"

    def someone_else_writes(call: int) -> None:
        if call == 3:
            path.write_bytes(b"theirs")

    exchange = FakeHistoryExchange(full_history(), on_call=someone_else_writes)
    stopped(run_download(make_request(path), exchange), HistoryStopReason.DATA_FILE_EXISTS)
    assert path.read_bytes() == b"theirs"
    assert leftovers(tmp_path) == ["h.jsonl"]


def test_part_appearing_before_the_open_is_refused_and_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "h.jsonl"
    monkeypatch.setattr(_history, "existing", lambda _: None)
    part_path(path).write_bytes(b"other")
    stopped(
        run_download(make_request(path), FakeHistoryExchange(full_history())),
        HistoryStopReason.PART_FILE_EXISTS,
    )
    assert part_path(path).read_bytes() == b"other"


def test_missing_folder_is_a_write_failure_before_any_call(tmp_path: Path) -> None:
    path = tmp_path / "yok" / "h.jsonl"
    exchange = FakeHistoryExchange(full_history())
    stopped(run_download(make_request(path), exchange), HistoryStopReason.WRITE_FAILED)
    assert exchange.calls == [] and leftovers(tmp_path) == []


def test_write_failure_mid_download_leaves_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[str] = []
    real_write = HistoryWriter.write

    def failing_write(self: HistoryWriter, text: str) -> None:
        written.append(text)
        if len(written) == 5:
            raise HistoryFileError
        real_write(self, text)

    monkeypatch.setattr(HistoryWriter, "write", failing_write)
    path = tmp_path / "h.jsonl"
    stopped(
        run_download(make_request(path), FakeHistoryExchange(full_history())),
        HistoryStopReason.WRITE_FAILED,
    )
    assert leftovers(tmp_path) == []


class FullDisk:
    """Dolu diskteki dosya: her yazma ve kapanış `OSError`."""

    def write(self, text: str) -> int:
        raise OSError(28, "No space left on device")

    def close(self) -> None:
        raise OSError(28, "No space left on device")


def test_disk_error_while_writing_is_named(tmp_path: Path) -> None:
    writer = HistoryWriter(tmp_path / "h.jsonl")
    writer.open()
    assert writer._file is not None
    writer._file.close()
    writer._file = FullDisk()  # type: ignore[assignment]
    with pytest.raises(HistoryFileError):
        writer.write("x")
    with pytest.raises(HistoryFileError):
        writer.finish()
    writer.close()
    assert leftovers(tmp_path) == []


def test_writer_refuses_to_write_or_finish_before_open(tmp_path: Path) -> None:
    writer = HistoryWriter(tmp_path / "h.jsonl")
    with pytest.raises(HistoryFileError):
        writer.write("x")
    with pytest.raises(HistoryFileError):
        writer.finish()
    writer.close()
    assert leftovers(tmp_path) == []


def test_file_is_utf8_json_lines_with_header_candles_and_completion(tmp_path: Path) -> None:
    """Plan Risk 7: başlık, mum satırları, tamamlanma satırı; her satır tek JSON değeri."""
    path = tmp_path / "h.jsonl"
    run_download(make_request(path, pairs=(BTC,)), FakeHistoryExchange(full_history((BTC,))))
    raw = path.read_bytes()
    assert b"\r\n" not in raw and raw.endswith(b"\n")
    lines = raw.decode("utf-8").splitlines()
    assert all(json.loads(line) is not None for line in lines)
    data = read_file(path)
    assert data.header["format"] == "crytobot-history" and data.header["version"] == 1
    assert data.candles[0][0] == BTC and len(data.candles[0]) == 6
    assert data.complete == {"complete": True, "counts": {BTC: len(data.candles)}}


@pytest.mark.parametrize(
    "change",
    [
        {"pairs": ()},
        {"pairs": (BTC, BTC)},
        {"data_path": ""},
        {"end": START},
        {"start": datetime(2026, 1, 1)},  # naive on purpose
    ],
    ids=["no_pairs", "duplicate_pair", "no_path", "end_not_after_start", "naive_start"],
)
def test_invalid_request_is_refused_before_any_call(
    tmp_path: Path, change: dict[str, object]
) -> None:
    exchange = FakeHistoryExchange(full_history())
    request = replace(make_request(tmp_path / "h.jsonl"), **change)  # type: ignore[arg-type]
    stopped(run_download(request, exchange), HistoryStopReason.INPUT)
    assert exchange.calls == [] and leftovers(tmp_path) == []


def test_invalid_settings_and_non_request_are_refused(tmp_path: Path) -> None:
    exchange = FakeHistoryExchange(full_history())
    bad = make_request(tmp_path / "h.jsonl", candle_interval=timedelta(minutes=7))
    stopped(run_download(bad, exchange), HistoryStopReason.INPUT)
    stopped(run_download("request", exchange), HistoryStopReason.INPUT)  # type: ignore[arg-type]
    assert exchange.calls == []


def test_start_long_ago_has_no_negative_warm_up(tmp_path: Path) -> None:
    start = datetime(1970, 1, 1, 1, tzinfo=UTC)
    path = tmp_path / "h.jsonl"
    history = {BTC: rows_between(0, 5 * 3_600_000)}
    result = run_download(
        make_request(path, pairs=(BTC,), start=start, end=start + timedelta(hours=3)),
        FakeHistoryExchange(history),
    )
    assert result.stop is None
    assert read_file(path).header["warmup_start"] == "1970-01-01T00:00:00+00:00"
