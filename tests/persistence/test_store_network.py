"""Spec 0041 CB-4, G-1: canlı depo açıldığı ağı kaydeder; kaydı olmayan depo mainnet'tir."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from crytobot.persistence import (
    StoreOutcome,
    bind_network,
    create_store,
    load_store,
    save_store,
)
from crytobot.portfolio import open_ledger

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def _meta(path: Path) -> dict[str, str]:
    with closing(sqlite3.connect(path)) as database:
        return dict(database.execute("SELECT key, value FROM meta").fetchall())


def _drop_network(path: Path) -> None:
    """0041 öncesi canlı depo: `network` anahtarı yok."""
    with closing(sqlite3.connect(path)) as database:
        database.execute("DELETE FROM meta WHERE key = 'network'")
        database.commit()


@pytest.mark.parametrize("network", ["mainnet", "testnet"])
def test_network_recorded_on_create(tmp_path: Path, network: str) -> None:
    path = tmp_path / "live.db"

    created = create_store(path, "live", network)

    assert created.outcome is StoreOutcome.CREATED
    assert created.state is not None and created.state.network == network
    assert _meta(path)["network"] == network
    loaded = load_store(path, "live")
    assert loaded.state is not None and loaded.state.network == network


def test_network_survives_a_save(tmp_path: Path) -> None:
    path = tmp_path / "live.db"
    created = create_store(path, "live", "testnet")
    assert created.state is not None
    ledger = open_ledger(created.state.ledger, Decimal(1000), NOW).ledger

    saved = save_store(path, created.state, ledger, created.state.execution, created.state.risk)

    assert saved.state is not None and saved.state.network == "testnet"
    loaded = load_store(path, "live")
    assert loaded.state is not None and loaded.state.network == "testnet"


def test_create_without_network_writes_no_key(tmp_path: Path) -> None:
    """Paper deposu ve ağ verilmeyen çağrı bugünkü gibidir; ağ okununca mainnet'tir."""
    path = tmp_path / "paper.db"

    create_store(path, "paper")

    assert "network" not in _meta(path)
    loaded = load_store(path, "paper")
    assert loaded.state is not None and loaded.state.network == "mainnet"


def test_unknown_network_is_refused_on_create(tmp_path: Path) -> None:
    path = tmp_path / "live.db"

    assert create_store(path, "live", "devnet").outcome is StoreOutcome.INVALID_INPUT
    assert create_store(path, "live", True).outcome is StoreOutcome.INVALID_INPUT
    assert not path.exists()


def test_store_without_network_reads_mainnet(tmp_path: Path) -> None:
    """G-1: 0041 öncesi canlı depo mainnet sayılır; okumak bir şey yazmaz."""
    path = tmp_path / "live.db"
    create_store(path, "live", "mainnet")
    _drop_network(path)

    loaded = load_store(path, "live")

    assert loaded.state is not None and loaded.state.network == "mainnet"
    assert "network" not in _meta(path)


def test_unreadable_network_value_is_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "live.db"
    create_store(path, "live", "mainnet")
    with closing(sqlite3.connect(path)) as database:
        database.execute("UPDATE meta SET value = 'devnet' WHERE key = 'network'")
        database.commit()

    assert load_store(path, "live").outcome is StoreOutcome.UNREADABLE
    assert bind_network(path, "mainnet").outcome is StoreOutcome.UNREADABLE


def test_bind_network_writes_only_when_missing(tmp_path: Path) -> None:
    path = tmp_path / "live.db"
    create_store(path, "live", "mainnet")
    _drop_network(path)
    revision = _meta(path)["revision"]

    first = bind_network(path, "mainnet")

    assert first.outcome is StoreOutcome.SAVED
    assert _meta(path)["network"] == "mainnet"
    assert _meta(path)["revision"] == revision  # binding is not a state change

    again = bind_network(path, "mainnet")
    assert again.outcome is StoreOutcome.SAVED
    assert _meta(path)["network"] == "mainnet"


def test_bind_network_refuses_another_network(tmp_path: Path) -> None:
    path = tmp_path / "live.db"
    create_store(path, "live", "testnet")
    before = path.read_bytes()

    refused = bind_network(path, "mainnet")

    assert refused.outcome is StoreOutcome.NETWORK_MISMATCH
    assert refused.message == "depo ağı uyuşmuyor: depo=testnet ayar=mainnet"
    assert path.read_bytes() == before


def test_unrecorded_store_cannot_be_bound_to_testnet(tmp_path: Path) -> None:
    """G-1: kaydı olmayan depo mainnet'tir; testnet'e bağlanmaz, kayıt yazılmaz."""
    path = tmp_path / "live.db"
    create_store(path, "live", "mainnet")
    _drop_network(path)

    refused = bind_network(path, "testnet")

    assert refused.outcome is StoreOutcome.NETWORK_MISMATCH
    assert refused.message == "depo ağı uyuşmuyor: depo=mainnet ayar=testnet"
    assert "network" not in _meta(path)


def test_bind_network_refuses_bad_input_and_paper_store(tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"
    assert bind_network(missing, "mainnet").outcome is StoreOutcome.NOT_FOUND
    assert not missing.exists()
    assert bind_network(tmp_path / "x.db", "devnet").outcome is StoreOutcome.INVALID_INPUT
    paper = tmp_path / "paper.db"
    create_store(paper, "paper")
    assert bind_network(paper, "mainnet").outcome is StoreOutcome.MODE_MISMATCH
    assert "network" not in _meta(paper)
