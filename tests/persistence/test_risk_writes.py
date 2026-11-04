"""Spec 0012: kalıcı risk durumunda sessiz değişiklik yok; meşru akışlar eskisi gibi sürer."""

import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.persistence import StoreOutcome
from crytobot.risk import RiskState
from tests.persistence.chain import (
    T1,
    T2,
    bought,
    created,
    loaded,
    opened,
    save,
    seen,
    stored,
)

OBSERVED = seen(opened(), "10000", T1)
CHANGED_ROWS = {
    "halted_as_text": """json_set(value, '$[5]', 'evet')""",
    "peak_digit_added": """json_set(value, '$[2]', '100009')""",
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
