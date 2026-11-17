"""Spec 0048 R-3, R-9, G-6: olay fiyat deposu — borsa bilgisi anlık görüntüsü, mumlar, indirilmiş
aralıklar, koşu kaydı; ölçümün okuması dosya oluşturmaz."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from crytobot.market_data import (
    DownloadRun,
    PairInfo,
    PriceStore,
    PriceStoreError,
    StoredCandle,
    read_pairs,
    read_prices,
)

T0 = datetime(2024, 1, 1, tzinfo=UTC)
H = timedelta(hours=1)
MS = 1_704_067_200_000  # T0


def test_roundtrip(tmp_path: Path) -> None:
    path = str(tmp_path / "p.db")
    store = PriceStore.open(path)
    try:
        assert store.pairs() is None
        store.save_pairs([PairInfo("EOS", "EOSUSDT", "BREAK")], T0)
        candles = [StoredCandle(MS, "1.0", "2.0", "0.5", "1.5")]
        store.save_span("EOSUSDT", T0, T0 + 2 * H, candles, "api", T0 + H)
        store.save_span("EOSUSDT", T0 + 5 * H, T0 + 6 * H, [], "yok", T0 + H)
        store.record_run(DownloadRun(T0, T0 + H, 12.5, 3, T0 + H))
        assert store.pairs() == {"EOS": PairInfo("EOS", "EOSUSDT", "BREAK")}
        assert [s.found for s in store.spans("EOSUSDT")] == [True, False]
    finally:
        store.close()
    data = read_prices(path)
    assert data is not None
    assert data.pairs == {"EOS": PairInfo("EOS", "EOSUSDT", "BREAK")}
    assert data.exchange_info_at == T0
    assert data.candles["EOSUSDT"] == (StoredCandle(MS, "1.0", "2.0", "0.5", "1.5"),)
    assert [(s.start, s.end, s.source) for s in data.spans["EOSUSDT"]] == [
        (T0, T0 + 2 * H, "api"),
        (T0 + 5 * H, T0 + 6 * H, "yok"),
    ]
    assert (data.seconds, data.ceiling, data.downloaded_first, data.downloaded_last) == (
        12.5,
        T0 + H,
        T0,
        T0 + H,
    )


def test_read_missing_store_creates_nothing(tmp_path: Path) -> None:
    assert read_prices(str(tmp_path / "none.db")) is None
    assert list(tmp_path.iterdir()) == []


def test_foreign_file_refused(tmp_path: Path) -> None:
    path = tmp_path / "p.db"
    connection = sqlite3.connect(path)
    connection.executescript("CREATE TABLE meta (name TEXT PRIMARY KEY, value TEXT NOT NULL);")
    connection.execute("INSERT INTO meta VALUES ('format', '99')")
    connection.commit()
    connection.close()
    with pytest.raises(PriceStoreError, match="biçimi tanınmıyor"):
        PriceStore.open(str(path))
    with pytest.raises(PriceStoreError, match="biçimi tanınmıyor"):
        read_prices(str(path))
    (tmp_path / "junk.db").write_bytes(b"junk" * 100)
    with pytest.raises(PriceStoreError):
        read_prices(str(tmp_path / "junk.db"))


def test_span_written_whole_or_not_at_all(tmp_path: Path) -> None:
    path = str(tmp_path / "p.db")
    store = PriceStore.open(path)
    try:
        bad = [
            StoredCandle(MS, "1", "1", "1", "1"),
            StoredCandle(MS + 3_600_000, cast(str, None), "1", "1", "1"),
        ]
        with pytest.raises(PriceStoreError):
            store.save_span("ABCUSDT", T0, T0 + 2 * H, bad, "api", T0)
    finally:
        store.close()
    data = read_prices(path)
    assert data is not None and data.candles == {} and data.spans == {}


def test_read_pairs_only_reads(tmp_path: Path) -> None:
    """Spec 0051 plan A-2 (review L-2): yalnız borsa bilgisi, dosya değişmez, mum okunmaz."""
    path = tmp_path / "p.db"
    assert read_pairs(str(path)) is None
    assert list(tmp_path.iterdir()) == []
    store = PriceStore.open(str(path))
    store.close()
    empty = read_pairs(str(path))
    assert empty is not None and (empty.pairs, empty.at) == ({}, None)
    store = PriceStore.open(str(path))
    store.save_pairs([PairInfo("ABC", "ABCUSDT", "TRADING")], T0)
    store.close()
    before = path.read_bytes()
    snapshot = read_pairs(str(path))
    assert snapshot is not None
    assert snapshot.pairs == {"ABC": PairInfo("ABC", "ABCUSDT", "TRADING")}
    assert snapshot.at == T0
    assert path.read_bytes() == before


def test_read_pairs_foreign_file_untouched(tmp_path: Path) -> None:
    other = tmp_path / "other.db"
    connection = sqlite3.connect(other)
    connection.execute("CREATE TABLE x (a)")
    connection.commit()
    connection.close()
    before = other.read_bytes()
    with pytest.raises(PriceStoreError):
        read_pairs(str(other))
    assert other.read_bytes() == before  # no schema written into a wrong file
    with sqlite3.connect(other) as check:
        assert [row[0] for row in check.execute("SELECT name FROM sqlite_master")] == ["x"]
