"""Spec 0038 CB-1 (depo yarısı), plan Risk 1, 2: başlatma kayıtları ve son tur işareti."""

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from crytobot.persistence import (
    StartRecord,
    StoreOutcome,
    append_start_record,
    load_start_records,
    load_store,
    mark_turn,
    save_store,
)
from tests.persistence.chain import T0, T1, bought, loaded, opened, stored

REPORT = str(Path("rapor.json").resolve())


def proof(at: datetime = T1) -> StartRecord:
    return StartRecord(at, False, REPORT)


def trial(at: datetime = T1) -> StartRecord:
    return StartRecord(at, True, None)


def raw(path: Path, sql: str, *args: object) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(path, isolation_level=None)) as database:
        return database.execute(sql, args).fetchall()


def test_proof_and_trial_records_are_appended_in_order_with_the_revision(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, opened())

    assert append_start_record(path, proof()).outcome is StoreOutcome.SAVED
    assert append_start_record(path, trial(T1 + timedelta(hours=1))).outcome is StoreOutcome.SAVED

    result = load_start_records(path)
    assert result.outcome is StoreOutcome.LOADED
    assert result.records == (
        StartRecord(T1, False, REPORT, 1),
        StartRecord(T1 + timedelta(hours=1), True, None, 1),
    )


def test_record_revision_is_written_by_the_store_not_the_caller(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    base = stored(path, opened())
    world = bought(opened())
    save_store(path, base, world.ledger, world.execution, world.risk)

    append_start_record(path, StartRecord(T1, False, REPORT, revision=99))

    assert load_start_records(path).records[0].revision == 2


def test_appending_does_not_change_the_revision_or_the_state(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    before = stored(path, opened())

    append_start_record(path, proof())

    after = loaded(path)
    assert after.revision == before.revision
    assert after.ledger == before.ledger


def test_live_store_takes_no_start_record(tmp_path: Path) -> None:
    path = tmp_path / "canli.sqlite"
    stored(path, opened(), mode="live")

    assert append_start_record(path, proof()).outcome is StoreOutcome.MODE_MISMATCH
    assert load_start_records(path).outcome is StoreOutcome.MODE_MISMATCH
    assert raw(path, "SELECT COUNT(*) FROM starts") == [(0,)]


@pytest.mark.parametrize(
    "record",
    [
        "kayıt",
        StartRecord(T1.replace(tzinfo=None), False, REPORT),
        StartRecord(T1, True, REPORT),
        StartRecord(T1, False, None),
        StartRecord(T1, False, ""),
        StartRecord(T1, False, "göreli/rapor.json"),
        StartRecord(T1, 1, None),  # type: ignore[arg-type]
    ],
)
def test_invalid_records_are_refused_without_writing(tmp_path: Path, record: object) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, opened())

    assert append_start_record(path, record).outcome is StoreOutcome.INVALID_INPUT
    assert load_start_records(path).records == ()


def test_missing_store_is_named_for_both_calls(tmp_path: Path) -> None:
    path = tmp_path / "yok.sqlite"

    assert append_start_record(path, proof()).outcome is StoreOutcome.NOT_FOUND
    assert load_start_records(path).outcome is StoreOutcome.NOT_FOUND
    assert not path.exists()


def test_invalid_path_and_readonly_flag_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, opened())

    assert append_start_record(1, proof()).outcome is StoreOutcome.INVALID_INPUT
    assert load_start_records(1).outcome is StoreOutcome.INVALID_INPUT
    assert load_start_records(path, readonly="evet").outcome is StoreOutcome.INVALID_INPUT  # type: ignore[arg-type]


def test_store_without_the_table_has_no_records_and_gets_it_on_first_append(
    tmp_path: Path,
) -> None:
    path = tmp_path / "eski.sqlite"
    stored(path, opened())
    raw(path, "DROP TABLE starts")

    assert load_start_records(path).outcome is StoreOutcome.LOADED
    assert load_start_records(path).records == ()
    assert append_start_record(path, proof()).outcome is StoreOutcome.SAVED
    assert len(load_start_records(path).records) == 1


@pytest.mark.parametrize(
    "row",
    [
        "{}",
        '{"at":"x","kind":"proof","report":null,"revision":"1"}',
        '{"at":"2026-01-01T00:00:00+00:00","kind":"proof","report":null,"revision":"1"}',
        '{"at":"2026-01-01T00:00:00+00:00","kind":"other","report":null,"revision":"1"}',
        '{"at":"2026-01-01T00:00:00+00:00","kind":"trial","report":null,"revision":1}',
        '{"at":"2026-01-01T00:00:00+00:00","kind":"trial","report":null,"revision":"-1"}',
        '{"kind":"trial","at":"2026-01-01T00:00:00+00:00","report":null,"revision":"1"}',
        "[]",
    ],
)
def test_broken_record_is_unreadable_not_an_empty_history(tmp_path: Path, row: str) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, opened())
    raw(path, "INSERT INTO starts(seq, row) VALUES (0, ?)", row)

    assert load_start_records(path).outcome is StoreOutcome.UNREADABLE
    assert append_start_record(path, proof()).outcome is StoreOutcome.UNREADABLE
    assert raw(path, "SELECT COUNT(*) FROM starts") == [(1,)]


def test_a_gap_in_the_records_is_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, opened())
    append_start_record(path, proof())
    append_start_record(path, proof())
    raw(path, "DELETE FROM starts WHERE seq = 0")

    assert load_start_records(path).outcome is StoreOutcome.UNREADABLE


def test_readonly_read_leaves_the_file_untouched(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, opened())
    append_start_record(path, proof())
    before = path.read_bytes()

    assert load_start_records(path, readonly=True).outcome is StoreOutcome.LOADED
    assert load_store(path, "paper", readonly=True).outcome is StoreOutcome.LOADED

    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["depo.sqlite"]


def test_writable_read_is_also_available(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, opened())
    append_start_record(path, trial())

    assert load_start_records(path, readonly=False).records[0].trial is True


# --- mark_turn (plan Risk 1) ----------------------------------------------------------------


def test_mark_turn_is_loaded_and_keeps_the_revision(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    before = stored(path, opened())
    assert before.last_turn is None

    assert mark_turn(path, T1).outcome is StoreOutcome.SAVED

    after = loaded(path)
    assert after.last_turn == T1
    assert after.revision == before.revision


def test_save_after_mark_turn_is_not_a_stale_write_and_keeps_the_mark(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    base = stored(path, opened())
    mark_turn(path, T1)
    world = bought(opened())

    saved = save_store(path, base, world.ledger, world.execution, world.risk)

    assert saved.outcome is StoreOutcome.SAVED
    assert loaded(path).last_turn == T1


def test_mark_turn_is_monotonic(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, opened())
    mark_turn(path, T1)

    assert mark_turn(path, T0).outcome is StoreOutcome.HISTORY_IMMUTABLE
    assert mark_turn(path, T1).outcome is StoreOutcome.SAVED
    assert loaded(path).last_turn == T1


@pytest.mark.parametrize("at", [T1.replace(tzinfo=None), "2026-01-01", None])
def test_mark_turn_refuses_a_moment_without_zone(tmp_path: Path, at: object) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, opened())

    assert mark_turn(path, at).outcome is StoreOutcome.INVALID_INPUT
    assert mark_turn(1, T1).outcome is StoreOutcome.INVALID_INPUT


def test_mark_turn_never_writes_a_live_store_or_creates_a_file(tmp_path: Path) -> None:
    live = tmp_path / "canli.sqlite"
    stored(live, opened(), mode="live")

    assert mark_turn(live, T1).outcome is StoreOutcome.MODE_MISMATCH
    assert loaded(live, mode="live").last_turn is None
    assert mark_turn(tmp_path / "yok.sqlite", T1).outcome is StoreOutcome.NOT_FOUND
    assert not (tmp_path / "yok.sqlite").exists()


def test_broken_turn_mark_makes_the_store_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, opened())
    raw(path, "INSERT INTO meta VALUES ('last_turn', '2026-01-01')")

    assert load_store(path, "paper").outcome is StoreOutcome.UNREADABLE
    assert mark_turn(path, T1).outcome is StoreOutcome.UNREADABLE
