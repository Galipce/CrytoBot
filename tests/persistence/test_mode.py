"""Spec 0011 AC-9 (R-9): depo oluşturulduğu modu saklar; başka modla durum dönmez."""

from dataclasses import replace
from pathlib import Path

import pytest

from crytobot.persistence import StoreOutcome, load_store
from tests.persistence.chain import bought, loaded, opened, save, stored


@pytest.mark.parametrize(("own", "other"), [("paper", "live"), ("live", "paper")])
def test_load_in_another_mode_returns_no_state(tmp_path: Path, own: str, other: str) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, bought(opened()), own)

    result = load_store(path, other)

    assert result.outcome is StoreOutcome.MODE_MISMATCH and result.state is None
    assert result.message == "mod uyuşmuyor"
    assert loaded(path, own).mode == own


def test_save_in_another_mode_changes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    state = stored(path, opened(), "paper")
    before = path.read_bytes()

    result = save(path, replace(state, mode="live"), bought(opened()))

    assert result.outcome is StoreOutcome.MODE_MISMATCH and result.state is None
    assert path.read_bytes() == before
