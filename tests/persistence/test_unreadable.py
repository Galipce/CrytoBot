"""Spec 0011 AC-6 (R-6, R-12): okunamayan vaka adlandırılır; durum dönmez, onarım yapılmaz."""

import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from crytobot.persistence import StoreOutcome, load_store
from tests.persistence.chain import full_world, stored

Edit = Callable[[sqlite3.Connection], None]


def set_field(table: str, seq: int, index: int, value: Any) -> Edit:
    def edit(database: sqlite3.Connection) -> None:
        ((text,),) = database.execute(f"SELECT row FROM {table} WHERE seq = ?", (seq,))
        row = json.loads(text)
        row[index] = value
        database.execute(f"UPDATE {table} SET row = ? WHERE seq = ?", (json.dumps(row), seq))

    return edit


def set_row(table: str, seq: int, text: Any) -> Edit:
    def edit(database: sqlite3.Connection) -> None:
        database.execute(f"UPDATE {table} SET row = ? WHERE seq = ?", (text, seq))

    return edit


def set_meta(key: str, value: Any) -> Edit:
    def edit(database: sqlite3.Connection) -> None:
        database.execute("UPDATE meta SET value = ? WHERE key = ?", (value, key))

    return edit


def set_meta_field(key: str, index: int, value: Any) -> Edit:
    def edit(database: sqlite3.Connection) -> None:
        ((text,),) = database.execute("SELECT value FROM meta WHERE key = ?", (key,))
        row = json.loads(text)
        row[index] = value
        database.execute("UPDATE meta SET value = ? WHERE key = ?", (json.dumps(row), key))

    return edit


def run(statement: str) -> Edit:
    def edit(database: sqlite3.Connection) -> None:
        database.execute(statement)

    return edit


def loose_table(database: sqlite3.Connection) -> None:
    """Metin olmayan değer: STRICT tablolar bunu kabul etmez, elle yapılmış tablo eder."""
    database.execute("DROP TABLE meta")
    database.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value)")
    database.execute("INSERT INTO meta VALUES ('format_version', 1)")


def binary_row(database: sqlite3.Connection) -> None:
    """Metin olmayan satır: STRICT tablolar bunu kabul etmez, elle yapılmış tablo eder."""
    database.execute("DROP TABLE entries")
    database.execute("CREATE TABLE entries(seq INTEGER PRIMARY KEY, row)")
    database.execute("INSERT INTO entries VALUES (0, ?)", (b"\x00\x01",))


# full_world entries: 0 opening, 1 fill a, 2 close a, 3 fill b;
# orders: 0 cb-a, 1 cx-a, 2 cb-b, 3 cb-c
EDITS: dict[str, Edit] = {
    "row_not_json": set_row("entries", 1, "{bozuk"),
    "row_not_a_list": set_row("entries", 1, '{"a": 1}'),
    "row_empty": set_row("entries", 1, "[]"),
    "row_kind_unknown": set_field("entries", 1, 0, "x"),
    "row_short": set_row("entries", 0, '["o"]'),
    "row_with_a_json_float": set_field("entries", 0, 2, 100.5),
    "row_with_a_json_int": set_field("entries", 0, 2, 100),
    "row_nan_constant": set_row("entries", 0, '["o", "2026-11-03T09:00:00+03:00", NaN]'),
    "row_deep_nesting": set_row("entries", 0, "[" * 100_000),
    "number_garbage": set_field("entries", 1, 4, "iki"),
    "number_underscore": set_field("entries", 1, 4, "2_50"),
    "number_spaces": set_field("entries", 1, 4, " 2.50"),
    "number_nan": set_field("entries", 1, 4, "NaN"),
    "number_infinity": set_field("entries", 1, 7, "Infinity"),
    "number_huge_exponent": set_field("entries", 1, 7, "1E+99999999999999999999"),
    "number_not_text": set_field("entries", 1, 4, None),
    "time_garbage": set_field("entries", 1, 9, "dün"),
    "time_naive": set_field("entries", 1, 9, "2026-11-03T09:01:00"),
    "time_loose_format": set_field("entries", 1, 9, "2026-11-03 09:01:00+03:00"),
    "time_not_text": set_field("entries", 1, 9, None),
    "pair_not_text": set_field("entries", 1, 3, None),
    "close_of_unknown_position": set_field("entries", 2, 1, "cb-yok"),
    "reason_unknown": set_field("entries", 2, 6, "başka"),
    "status_unknown_value": set_field("orders", 0, -6, "dolu"),
    "order_kind_unknown": set_field("orders", 0, 0, "x"),
    "order_row_not_json": set_row("orders", 0, "{bozuk"),
    "order_row_short": set_row("orders", 0, '["b"]'),
    "order_time_naive": set_field("orders", 0, -3, "2026-11-03T09:01:00"),
    "order_side_quantity_bad": set_field("orders", 0, 7, "0"),
    "balance_differs": set_meta_field("ledger", 0, "1"),
    "balance_empty": set_meta_field("ledger", 0, None),
    "balance_trailing_zero_differs": set_meta_field("ledger", 1, "0.00000"),
    "open_position_missing": set_meta_field("ledger", 2, []),
    "open_position_unknown": set_meta_field("ledger", 2, ["cb-yok"]),
    "closure_missing": set_meta_field("ledger", 3, []),
    "summary_not_json": set_meta("ledger", "{bozuk"),
    "summary_short": set_meta("ledger", "[]"),
    "fill_amount_differs_from_cost": set_field("entries", 1, 4, "3.50"),
    "row_lost": run("DELETE FROM entries WHERE seq = 3"),
    "first_row_lost": run("DELETE FROM entries WHERE seq = 0"),
    "order_lost": run("DELETE FROM orders WHERE seq = 0"),
    "risk_partly_empty": set_meta_field("risk", 2, None),
    "risk_wrong_day": set_meta_field("risk", 0, "2026-11-04"),
    "risk_loose_day": set_meta_field("risk", 0, "20261103"),
    "risk_day_not_text": set_meta_field("risk", 0, 1.5),
    "risk_day_invalid": set_meta_field("risk", 0, "2026-13-40"),
    "risk_peak_below_last": set_meta_field("risk", 2, "1"),
    "risk_halted_not_bool": set_meta_field("risk", 5, "evet"),
    "risk_not_json": set_meta("risk", "{bozuk"),
    "risk_short": set_meta("risk", "[]"),
    "unknown_without_quote": set_field("orders", 3, -2, None),
    "unknown_without_quote_fee": set_field("orders", 3, -1, None),
    "quote_on_a_filled_order": set_field("orders", 0, -2, "1"),
    "mode_invalid": set_meta("mode", "backtest"),
    "revision_invalid": set_meta("revision", "ikinci"),
    "revision_negative": set_meta("revision", "-1"),
    "version_not_a_number": set_meta("format_version", "bir"),
    "version_missing": run("DELETE FROM meta WHERE key = 'format_version'"),
    "mode_missing": run("DELETE FROM meta WHERE key = 'mode'"),
    "ledger_missing": run("DELETE FROM meta WHERE key = 'ledger'"),
    "meta_table_missing": run("DROP TABLE meta"),
    "entries_table_missing": run("DROP TABLE entries"),
    "meta_value_not_text": loose_table,
    "row_not_text": binary_row,
}


@pytest.mark.parametrize("case", list(EDITS))
def test_store_edited_badly_is_named_and_returns_no_state(tmp_path: Path, case: str) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, full_world())
    with closing(sqlite3.connect(path)) as database:
        EDITS[case](database)
        database.commit()
    before = path.read_bytes()

    result = load_store(path, "paper")

    assert result.outcome is StoreOutcome.UNREADABLE, result.message
    assert result.state is None and result.conflicts == ()
    assert result.message.startswith("depo okunamıyor")
    assert len(result.message) < 200
    assert path.read_bytes() == before  # no automatic repair


@pytest.mark.parametrize(
    "content", [b"", b"bu bir veritabani degil" * 100], ids=["empty_file", "garbage_file"]
)
def test_file_that_is_no_store_is_unreadable(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "depo.sqlite"
    path.write_bytes(content)

    result = load_store(path, "paper")

    assert result.outcome is StoreOutcome.UNREADABLE and result.state is None
    assert path.read_bytes() == content


def test_truncated_store_is_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, full_world())
    path.write_bytes(path.read_bytes()[:150])

    assert load_store(path, "paper").outcome is StoreOutcome.UNREADABLE


def test_directory_is_unreadable(tmp_path: Path) -> None:
    assert load_store(tmp_path, "paper").outcome is StoreOutcome.UNREADABLE


@pytest.mark.parametrize("version", ["2", "0", "99"])
def test_unknown_format_version_is_named(tmp_path: Path, version: str) -> None:
    """R-12: sürüm, moddan ve içerikten önce bakılır."""
    path = tmp_path / "depo.sqlite"
    stored(path, full_world())
    with closing(sqlite3.connect(path)) as database:
        database.execute("UPDATE meta SET value = ? WHERE key = 'format_version'", (version,))
        database.execute("UPDATE meta SET value = 'live' WHERE key = 'mode'")
        database.commit()

    result = load_store(path, "paper")

    assert result.outcome is StoreOutcome.UNKNOWN_VERSION and result.state is None
    assert result.message == "bilinmeyen biçim sürümü"
