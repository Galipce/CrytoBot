"""Spec 0012: kalıcı risk durumunda sessiz değişiklik yok; meşru akışlar eskisi gibi sürer."""

import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.persistence import StoreOutcome
from crytobot.risk import RiskState, resume
from tests.persistence.chain import (
    ISTANBUL,
    T1,
    T2,
    World,
    bought,
    created,
    loaded,
    opened,
    save,
    saved,
    seen,
    snapshot,
    stored,
)

OBSERVED = seen(opened(), "10000", T1)
CHANGED_ROWS = {
    "halted_as_text": """json_set(value, '$[5]', 'evet')""",
    "peak_digit_added": """json_set(value, '$[2]', '100009')""",
    "same_value_other_text": """json_set(value, '$[2]', '10000.0')""",
    "every_field_empty": """'[null,null,null,null,null,false]'""",
}


def with_risk_row(path: Path, expression: str) -> None:
    """Depo dışından değişen risk satırı: `expression` yeni `value`'yu kurar."""
    with closing(sqlite3.connect(path)) as database:
        database.execute(f"UPDATE meta SET value = {expression} WHERE key = 'risk'")
        database.commit()


def assert_nothing_written(path: Path, before: bytes, revision: int) -> None:
    assert path.read_bytes() == before
    assert loaded(path).revision == revision


@pytest.mark.parametrize("case", list(CHANGED_ROWS))
def test_changed_risk_row_is_unreadable(tmp_path: Path, case: str) -> None:
    path = tmp_path / "depo.sqlite"
    state = stored(path, OBSERVED)
    with_risk_row(path, CHANGED_ROWS[case])
    before = path.read_bytes()

    result = save(path, state, seen(OBSERVED, "10001", T2))

    assert result.outcome is StoreOutcome.UNREADABLE and result.message == "depo okunamıyor"
    assert result.state is None
    assert path.read_bytes() == before


def test_hand_built_base_unlike_the_disk_is_unreadable(tmp_path: Path) -> None:
    """Disk sağlam, `base.risk` R-6'yı geçiyor ama diskten farklı: ayrı sonuç türü açılmaz."""
    path = tmp_path / "depo.sqlite"
    state = stored(path, OBSERVED)
    hand_built = replace(state, risk=seen(opened(), "12000", T1).risk)
    before = path.read_bytes()

    result = save(path, hand_built, seen(OBSERVED, "10001", T2))

    assert result.outcome is StoreOutcome.UNREADABLE and result.state is None
    assert_nothing_written(path, before, state.revision)


def test_stale_revision_wins_over_a_changed_risk_row(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    state = stored(path, OBSERVED)
    saved_ahead = save(path, state, seen(OBSERVED, "10001", T2))
    assert saved_ahead.outcome is StoreOutcome.SAVED
    with_risk_row(path, CHANGED_ROWS["peak_digit_added"])
    before = path.read_bytes()

    result = save(path, state, seen(OBSERVED, "10002", T2))

    assert result.outcome is StoreOutcome.STALE_WRITE and result.message == "eski yazım"
    assert path.read_bytes() == before


def _not_risk_state() -> object:
    return "x" * 1_000_000


def _partly_empty() -> RiskState:
    return replace(OBSERVED.risk, peak_equity=None)


def _peak_below_last() -> RiskState:
    return replace(OBSERVED.risk, last_equity=Decimal("10001"))


@pytest.mark.parametrize(
    ("make", "problem"),
    [
        (_not_risk_state, "risk durumu değil"),
        (_partly_empty, "alanlar kısmen boş"),
        (_peak_below_last, "zirve son kasanın altında"),
    ],
    ids=["not_a_risk_state", "partly_empty", "peak_below_last"],
)
def test_invalid_base_risk_is_invalid_input(
    tmp_path: Path, make: Callable[[], Any], problem: str
) -> None:
    path = tmp_path / "depo.sqlite"
    state = stored(path, OBSERVED)
    invalid = replace(state, risk=make())
    before = path.read_bytes()

    result = save(path, invalid, seen(OBSERVED, "10001", T2))

    assert result.outcome is StoreOutcome.INVALID_INPUT and result.state is None
    assert result.message == f"geçersiz girdi: base: {problem}"
    assert_nothing_written(path, before, state.revision)


def test_invalid_input_comes_before_any_store_access(tmp_path: Path) -> None:
    """Dosya yok, sonuç yine "geçersiz girdi": `base.risk` G/Ç olmadan denetlenir."""
    state = created(tmp_path / "depo.sqlite")
    invalid = replace(state, risk=_partly_empty())

    result = save(tmp_path / "olmayan.sqlite", invalid, bought(opened()))

    assert result.outcome is StoreOutcome.INVALID_INPUT


def lifted(world: World) -> World:
    return replace(world, risk=resume(world.risk, "cli").state)


def risk_changed(world: World, **fields: Any) -> World:
    return replace(world, risk=replace(world.risk, **fields))


PEAK_ABOVE_LAST = seen(seen(opened(), "11000", T1), "10000", T2)
HALTED = seen(seen(opened(), "10000", T1), "5000", T2)
AT_THE_PEAK = seen(opened(), "11000", T1)
SMALL = seen(seen(opened(), "1.10", T1), "1.00", T2)
# 20:30 and 22:00 UTC on 3 November: the local day changes, the UTC day does not
LATE_LOCAL = datetime(2026, 11, 3, 23, 30, tzinfo=ISTANBUL)
AFTER_LOCAL_MIDNIGHT = datetime(2026, 11, 4, 1, 0, tzinfo=ISTANBUL)
# 23:30 UTC on 3 November and 00:30 UTC on 4 November: the UTC day changes, the local day does not
BEFORE_UTC_MIDNIGHT = datetime(2026, 11, 4, 2, 30, tzinfo=ISTANBUL)
AFTER_UTC_MIDNIGHT = datetime(2026, 11, 4, 3, 30, tzinfo=ISTANBUL)
NEXT_DAY = timedelta(days=1)


def assert_immutable(path: Path, on_disk: World, write: World) -> None:
    state = stored(path, on_disk)
    before = path.read_bytes()

    result = save(path, state, write)

    assert result.outcome is StoreOutcome.HISTORY_IMMUTABLE, result.message
    assert result.state is None and result.message == "geçmiş değiştirilemez"
    assert_nothing_written(path, before, state.revision)


LOWERED_PEAKS: dict[str, tuple[World, World]] = {
    "no_halt": (PEAK_ABOVE_LAST, risk_changed(PEAK_ABOVE_LAST, peak_equity=Decimal("10500"))),
    "no_halt_down_to_the_last_equity": (
        PEAK_ABOVE_LAST,
        risk_changed(PEAK_ABOVE_LAST, peak_equity=Decimal("10000")),
    ),
    "smallest_drop": (SMALL, risk_changed(SMALL, peak_equity=Decimal("1.09"))),
    "halt_starts_in_the_same_write": (
        PEAK_ABOVE_LAST,
        risk_changed(PEAK_ABOVE_LAST, peak_equity=Decimal("10500"), halted=True),
    ),
    "during_a_halt": (HALTED, risk_changed(HALTED, peak_equity=Decimal("6000"))),
    "halt_never_written": (AT_THE_PEAK, lifted(seen(AT_THE_PEAK, "8000", T2))),
    "new_utc_day_no_halt": (
        PEAK_ABOVE_LAST,
        risk_changed(seen(PEAK_ABOVE_LAST, "10100", T2 + NEXT_DAY), peak_equity=Decimal("10500")),
    ),
    "new_utc_day_during_a_halt": (
        HALTED,
        risk_changed(seen(HALTED, "5100", T2 + NEXT_DAY), peak_equity=Decimal("6000")),
    ),
}


@pytest.mark.parametrize("case", list(LOWERED_PEAKS))
def test_lowered_peak_is_refused(tmp_path: Path, case: str) -> None:
    assert_immutable(tmp_path / "depo.sqlite", *LOWERED_PEAKS[case])


def test_halt_never_written_keeps_the_peak_and_halts_again(tmp_path: Path) -> None:
    """Constraints: diskteki zirve korunur, sonraki gözlem yeniden durdurur."""
    path = tmp_path / "depo.sqlite"
    state = stored(path, AT_THE_PEAK)
    assert save(path, state, lifted(seen(AT_THE_PEAK, "8000", T2))).state is None

    restored = loaded(path)
    again = seen(World(restored.ledger, restored.execution, restored.risk), "8000", T2)

    assert str(restored.risk.peak_equity) == "11000"
    assert again.risk.halted is True


def test_peak_with_the_same_value_is_not_a_drop(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    state = stored(path, SMALL)
    write = risk_changed(SMALL, peak_equity=Decimal("1.1"))

    saved(path, state, write)

    assert str(loaded(path).risk.peak_equity) == "1.1"


CHANGED_DAY_STARTS: dict[str, tuple[World, World]] = {
    "no_halt": (
        PEAK_ABOVE_LAST,
        risk_changed(PEAK_ABOVE_LAST, day_start_equity=Decimal("10500")),
    ),
    "during_a_halt": (HALTED, risk_changed(HALTED, day_start_equity=Decimal("9000"))),
    "halt_closing": (HALTED, risk_changed(lifted(HALTED), day_start_equity=Decimal("9000"))),
    "same_value_other_text": (SMALL, risk_changed(SMALL, day_start_equity=Decimal("1.1"))),
    "same_utc_day_after_local_midnight": (
        seen(opened(), "10000", LATE_LOCAL),
        risk_changed(
            seen(seen(opened(), "10000", LATE_LOCAL), "10100", AFTER_LOCAL_MIDNIGHT),
            day_start_equity=Decimal("10100"),
        ),
    ),
}


@pytest.mark.parametrize("case", list(CHANGED_DAY_STARTS))
def test_changed_day_start_is_refused(tmp_path: Path, case: str) -> None:
    assert_immutable(tmp_path / "depo.sqlite", *CHANGED_DAY_STARTS[case])


def test_first_observation_has_no_day_start_rule(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    state = stored(path, opened())
    write = risk_changed(seen(opened(), "10000", T1), day_start_equity=Decimal("9000"))

    saved(path, state, write)

    assert snapshot(loaded(path)) == snapshot(write)


def test_first_matching_outcome_wins(tmp_path: Path) -> None:
    """geçersiz girdi → eski yazım → depo okunamıyor → geçmiş değiştirilemez."""
    path = tmp_path / "depo.sqlite"
    stale = stored(path, HALTED)
    ahead = saved(path, stale, seen(HALTED, "5100", T2))
    forbidden = risk_changed(seen(HALTED, "5100", T2), peak_equity=Decimal("6000"))
    assert save(path, ahead, forbidden).outcome is StoreOutcome.HISTORY_IMMUTABLE

    assert save(path, stale, forbidden).outcome is StoreOutcome.STALE_WRITE

    with_risk_row(path, CHANGED_ROWS["peak_digit_added"])
    assert save(path, ahead, forbidden).outcome is StoreOutcome.UNREADABLE

    # lowers the peak under the last equity: R-6 answers before anything else is looked at
    under_the_last = risk_changed(forbidden, peak_equity=Decimal("5000"))
    for base in (stale, ahead):
        result = save(path, base, under_the_last)
        assert result.outcome is StoreOutcome.INVALID_INPUT
        assert result.message == "geçersiz girdi: zirve son kasanın altında"

    invalid_base = replace(stale, risk=_partly_empty())
    result = save(path, invalid_base, forbidden)
    assert result.outcome is StoreOutcome.INVALID_INPUT
    assert result.message == "geçersiz girdi: base: alanlar kısmen boş"
    # the new state is looked at first
    result = save(path, invalid_base, under_the_last)
    assert result.message == "geçersiz girdi: zirve son kasanın altında"


OBSERVE_FLOWS: dict[str, list[tuple[str, datetime]]] = {
    "new_peak": [("10000", T1), ("11000", T2)],
    "below_the_peak": [("10000", T1), ("9000", T2)],
    "second_observation_at_the_same_time": [("10000", T1), ("10500", T1), ("9500", T1)],
    "new_utc_day": [("10000", T1), ("9500", T1 + NEXT_DAY)],
    "new_utc_day_same_local_day": [("10000", BEFORE_UTC_MIDNIGHT), ("9500", AFTER_UTC_MIDNIGHT)],
    "new_day_during_a_halt": [("10000", T1), ("5000", T2), ("5100", T2 + NEXT_DAY)],
}


@pytest.mark.parametrize("case", list(OBSERVE_FLOWS))
def test_observe_flow_is_accepted_and_restored(tmp_path: Path, case: str) -> None:
    path = tmp_path / "depo.sqlite"
    world = opened()
    state = stored(path, world)
    for equity, at in OBSERVE_FLOWS[case]:
        world = seen(world, equity, at)
        state = saved(path, state, world)
        assert snapshot(loaded(path)) == snapshot(world)


def test_new_day_during_a_halt_keeps_the_halt_and_the_peak(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    state = stored(path, HALTED)

    saved(path, state, seen(HALTED, "5100", T2 + NEXT_DAY))

    risk = loaded(path).risk
    assert risk.halted is True
    assert str(risk.day_start_equity) == "5100" and str(risk.peak_equity) == "10000"


def test_new_utc_day_renews_the_day_start_on_the_same_local_day(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    world = seen(opened(), "10000", BEFORE_UTC_MIDNIGHT)
    state = stored(path, world)

    saved(path, state, seen(world, "9500", AFTER_UTC_MIDNIGHT))

    assert str(loaded(path).risk.day_start_equity) == "9500"


def test_resume_lowers_the_peak_and_is_restored(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    state = stored(path, HALTED)
    world = lifted(HALTED)

    state = saved(path, state, world)

    restored = loaded(path).risk
    assert restored.halted is False
    assert str(restored.peak_equity) == "5000" and str(restored.day_start_equity) == "10000"
    saved(path, state, seen(world, "5100", T2))


OUT_OF_SCOPE: dict[str, tuple[World, World]] = {
    "peak_raised_without_observe": (
        PEAK_ABOVE_LAST,
        risk_changed(PEAK_ABOVE_LAST, peak_equity=Decimal("12000")),
    ),
    "halt_started_by_hand": (AT_THE_PEAK, risk_changed(AT_THE_PEAK, halted=True)),
    "day_start_value_on_a_new_day": (
        AT_THE_PEAK,
        risk_changed(seen(AT_THE_PEAK, "10000", T1 + NEXT_DAY), day_start_equity=Decimal("7000")),
    ),
}


@pytest.mark.parametrize("case", list(OUT_OF_SCOPE))
def test_out_of_scope_writes_stay_accepted(tmp_path: Path, case: str) -> None:
    path = tmp_path / "depo.sqlite"
    on_disk, write = OUT_OF_SCOPE[case]

    saved(path, stored(path, on_disk), write)

    assert snapshot(loaded(path)) == snapshot(write)


def test_store_written_before_this_spec_loads_and_saves(tmp_path: Path) -> None:
    """Format 1 satır metni bu spec'te değişmedi: metin elle yazılır, kod üretmez."""
    path = tmp_path / "depo.sqlite"
    stored(path, opened())
    row = '["2026-11-03","10000.50","11000.50","2026-11-03T09:01:00+03:00","10000.00",false]'
    with_risk_row(path, f"'{row}'")

    state = loaded(path)
    assert str(state.risk.day_start_equity) == "10000.50" and state.risk.halted is False

    world = World(state.ledger, state.execution, state.risk)
    saved(path, state, seen(world, "10500", T2))
    assert str(loaded(path).risk.peak_equity) == "11000.50"
