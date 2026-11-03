"""Spec 0011 AC-1, AC-2 (R-1, R-2): depo yalnız kurulumla oluşur; olmayan depoda boş durum yok."""

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from crytobot.execution import EMPTY_EXECUTION
from crytobot.persistence import StoreOutcome, create_store, load_store
from crytobot.portfolio import EMPTY_LEDGER
from crytobot.risk import EMPTY_STATE
from tests.persistence.chain import loaded


class BytesPath:
    def __fspath__(self) -> bytes:
        return b"depo"


@pytest.mark.parametrize("mode", ["paper", "live"])
def test_create_starts_empty_in_its_mode(tmp_path: Path, mode: str) -> None:
    path = tmp_path / "depo.sqlite"

    result = create_store(path, mode)

    assert result.outcome is StoreOutcome.CREATED
    assert result.state is not None and result.state.mode == mode
    state = loaded(path, mode)
    assert state.ledger.entries == () and state.ledger == EMPTY_LEDGER
    assert state.execution == EMPTY_EXECUTION
    assert state.risk == EMPTY_STATE
    assert state.revision == 0


def test_create_twice_keeps_the_content(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    create_store(path, "paper")
    before = path.read_bytes()

    result = create_store(path, "live")

    assert result.outcome is StoreOutcome.ALREADY_EXISTS and result.state is None
    assert result.message == "depo zaten var"
    assert path.read_bytes() == before


def test_create_on_any_other_file_leaves_it_alone(tmp_path: Path) -> None:
    path = tmp_path / "notlar.txt"
    path.write_bytes(b"notlarim")

    assert create_store(path, "paper").outcome is StoreOutcome.ALREADY_EXISTS
    assert path.read_bytes() == b"notlarim"


def test_create_on_a_directory_is_already_there(tmp_path: Path) -> None:
    assert create_store(tmp_path, "paper").outcome is StoreOutcome.ALREADY_EXISTS


def test_create_losing_a_race_is_already_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Denetimle açış arasında dosya oluşursa `O_EXCL` yakalar, içeriğe dokunulmaz."""
    path = tmp_path / "depo.sqlite"
    path.write_bytes(b"baskasinin")
    monkeypatch.setattr("os.path.lexists", lambda _path: False)

    assert create_store(path, "paper").outcome is StoreOutcome.ALREADY_EXISTS
    assert path.read_bytes() == b"baskasinin"


def test_create_without_parent_creates_no_directory(tmp_path: Path) -> None:
    parent = tmp_path / "yok"

    result = create_store(parent / "depo.sqlite", "paper")

    assert result.outcome is StoreOutcome.WRITE_FAILED and result.message == "yazılamadı"
    assert not parent.exists()


def test_create_with_an_impossible_name_is_write_failed(tmp_path: Path) -> None:
    assert create_store(f"{tmp_path}/a\0b", "paper").outcome is StoreOutcome.WRITE_FAILED


@pytest.mark.parametrize("mode", ["backtest", "PAPER", "", None, 1, ["paper"]])
def test_create_refuses_other_modes_and_writes_nothing(tmp_path: Path, mode: Any) -> None:
    path = tmp_path / "depo.sqlite"

    result = create_store(path, mode)

    assert result.outcome is StoreOutcome.INVALID_INPUT and result.state is None
    assert result.message == "geçersiz girdi"
    assert not path.exists()


@pytest.mark.parametrize("path", [None, 1, BytesPath()], ids=["none", "int", "bytes"])
def test_create_and_load_refuse_what_is_no_path(path: Any) -> None:
    assert create_store(path, "paper").outcome is StoreOutcome.INVALID_INPUT
    assert load_store(path, "paper").outcome is StoreOutcome.INVALID_INPUT


def test_create_failure_leaves_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_target: Path) -> sqlite3.Connection:
        raise sqlite3.OperationalError("disk dolu")

    monkeypatch.setattr("crytobot.persistence._store._connect", fail)
    path = tmp_path / "depo.sqlite"

    assert create_store(path, "paper").outcome is StoreOutcome.WRITE_FAILED
    assert not path.exists()


def test_missing_store_leaves_no_file(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"

    result = load_store(path, "paper")

    assert result.outcome is StoreOutcome.NOT_FOUND and result.state is None
    assert result.message == "depo yok"
    assert not path.exists()


def test_load_with_an_invalid_mode_is_invalid_input(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    create_store(path, "paper")

    assert load_store(path, "backtest").outcome is StoreOutcome.INVALID_INPUT
