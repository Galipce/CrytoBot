"""Olay fiyat verisinin SQLite deposu (spec 0048 R-3, R-9, G-6; plan Risk 7, 10).

Tablolar: borsa bilgisi anlık görüntüsü (USDT çiftleri, durumlarıyla: kapanmış ya da kaldırılmış
olanlar dahil, G-3), 1h mumlar (metin, kaynağıyla), indirilmiş aralıklar (sonucu: mum bulundu mu,
kaynağı, indirme anı) ve indirme koşuları (başlangıç, bitiş, süre, istek sayısı, saat tavanı). Bir
aralığın mumları ve kaydı tek işlemde yazılır: kesilen ya da reddedilen (eksik alan, tekrar) işlem
geri alınır, yarım aralık kalmaz.
`timeout=0` ve `closing` (conventions, spec 0011). Ölçüm deposu yalnız okur (`read_prices`, var olan
dosya `mode=rw`; dosya oluşturulmaz).
"""

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from crytobot.market_data._numbers import ms_from_utc, utc_from_ms
from crytobot.market_data._types import MarketDataError

FORMAT_VERSION: Final = "1"
SOURCE_API: Final = "api"
SOURCE_VISION: Final = "arşiv"
SOURCE_NONE: Final = "yok"

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pairs (
    base TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT NOT NULL,
    open_ms INTEGER NOT NULL,
    open TEXT NOT NULL,
    high TEXT NOT NULL,
    low TEXT NOT NULL,
    close TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (symbol, open_ms)
);
CREATE TABLE IF NOT EXISTS spans (
    symbol TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    found INTEGER NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    seconds REAL NOT NULL,
    requests INTEGER NOT NULL,
    ceiling_ms INTEGER NOT NULL
);
"""


class PriceStoreError(MarketDataError):
    """Fiyat deposu açılamıyor, okunamıyor ya da yazılamıyor."""


@dataclass(frozen=True)
class PairInfo:
    """Borsa bilgisindeki bir USDT spot çifti."""

    base: str
    symbol: str
    status: str


@dataclass(frozen=True)
class StoredCandle:
    """Kapanmış 1h mum; fiyatlar kaynağın metni."""

    open_ms: int
    open: str
    high: str
    low: str
    close: str


@dataclass(frozen=True)
class StoredSpan:
    """İndirilmiş aralık `[start, end)`: mum bulundu mu, kaynağı ve indirme anı."""

    start: datetime
    end: datetime
    found: bool
    source: str
    fetched_at: datetime | None = None


@dataclass(frozen=True)
class DownloadRun:
    started_at: datetime
    finished_at: datetime
    seconds: float
    requests: int
    ceiling: datetime


@dataclass(frozen=True)
class PriceData:
    """Ölçümün okuduğu hâl. `pairs`: anlık görüntü yoksa `None`."""

    pairs: dict[str, PairInfo] | None
    exchange_info_at: datetime | None
    candles: dict[str, tuple[StoredCandle, ...]]
    spans: dict[str, tuple[StoredSpan, ...]]
    runs: tuple[DownloadRun, ...]

    @property
    def ceiling(self) -> datetime | None:
        """Son koşunun saat tavanı: sonrası indirilemezdi (kapanmamış mum)."""
        return None if not self.runs else max(run.ceiling for run in self.runs)

    @property
    def downloaded_first(self) -> datetime | None:
        return None if not self.runs else min(run.started_at for run in self.runs)

    @property
    def downloaded_last(self) -> datetime | None:
        return None if not self.runs else max(run.finished_at for run in self.runs)

    @property
    def seconds(self) -> float:
        return sum(run.seconds for run in self.runs)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _at(ms: object) -> datetime:
    moment = utc_from_ms(ms)
    if moment is None:
        raise ValueError("bad time")
    return moment


def _check_format(connection: sqlite3.Connection) -> None:
    row = connection.execute("SELECT value FROM meta WHERE name = 'format'").fetchone()
    if row is None or row[0] != FORMAT_VERSION:
        raise PriceStoreError("fiyat deposunun biçimi tanınmıyor")


class PriceStore:
    """İndirme adımının açık bağlantısı. `open` dosyayı ve şemayı oluşturur."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @classmethod
    def open(cls, path: str) -> "PriceStore":
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(path, timeout=0, isolation_level=None)
            connection.executescript(_SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO meta (name, value) VALUES ('format', ?)", (FORMAT_VERSION,)
            )
            _check_format(connection)
        except (sqlite3.Error, OSError):
            if connection is not None:
                connection.close()
            raise PriceStoreError("fiyat deposu açılamıyor") from None
        except PriceStoreError:
            if connection is not None:
                connection.close()
            raise
        return cls(connection)

    def close(self) -> None:
        self._connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        connection = self._connection
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.Error:
            raise PriceStoreError("fiyat deposu yazılamıyor") from None
        try:
            yield
            connection.execute("COMMIT")
        except BaseException as error:  # a forced stop as well: nothing half-written
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            if isinstance(error, sqlite3.Error):
                raise PriceStoreError("fiyat deposu yazılamıyor") from None
            raise

    def pairs(self) -> dict[str, PairInfo] | None:
        try:
            return _pairs(self._connection)
        except sqlite3.Error:
            raise PriceStoreError("fiyat deposu okunamıyor") from None

    def pairs_at(self) -> datetime | None:
        """Borsa bilgisi anlık görüntüsünün anı; görüntü yoksa `None`."""
        try:
            row = self._connection.execute(
                "SELECT value FROM meta WHERE name = 'exchange_info_at'"
            ).fetchone()
            return None if row is None else datetime.fromisoformat(str(row[0]))
        except (sqlite3.Error, ValueError):
            raise PriceStoreError("fiyat deposu okunamıyor") from None

    def save_pairs(self, pairs: Sequence[PairInfo], at: datetime) -> None:
        with self._transaction():
            for pair in pairs:
                self._connection.execute(
                    "INSERT OR REPLACE INTO pairs (base, symbol, status) VALUES (?, ?, ?)",
                    (pair.base, pair.symbol, pair.status),
                )
            self._connection.execute(
                "INSERT OR REPLACE INTO meta (name, value) VALUES ('exchange_info_at', ?)",
                (_iso(at),),
            )

    def spans(self, symbol: str) -> tuple[StoredSpan, ...]:
        try:
            rows = self._connection.execute(
                "SELECT start_ms, end_ms, found, source, fetched_at FROM spans WHERE symbol = ?"
                " ORDER BY start_ms, end_ms",
                (symbol,),
            ).fetchall()
            return tuple(
                StoredSpan(_at(a), _at(b), bool(c), str(d), datetime.fromisoformat(str(e)))
                for a, b, c, d, e in rows
            )
        except (sqlite3.Error, ValueError):
            raise PriceStoreError("fiyat deposu okunamıyor") from None

    def save_span(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        candles: Sequence[StoredCandle],
        source: str,
        at: datetime,
    ) -> None:
        with self._transaction():
            # a span re-fetched over provisional rows replaces them: only a missing part is
            # fetched, so a row inside it is never a final one (review round 2 R2-1)
            self._connection.execute(
                "DELETE FROM spans WHERE symbol = ? AND start_ms >= ? AND end_ms <= ?",
                (symbol, ms_from_utc(start), ms_from_utc(end)),
            )
            for candle in candles:
                # a closed candle never changes: a re-fetched provisional span keeps the stored one
                self._connection.execute(
                    "INSERT INTO candles"
                    " (symbol, open_ms, open, high, low, close, source)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT (symbol, open_ms) DO NOTHING",
                    (
                        symbol,
                        candle.open_ms,
                        candle.open,
                        candle.high,
                        candle.low,
                        candle.close,
                        source,
                    ),
                )
            self._connection.execute(
                "INSERT INTO spans (symbol, start_ms, end_ms, found, source, fetched_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    symbol,
                    ms_from_utc(start),
                    ms_from_utc(end),
                    int(bool(candles)),
                    source,
                    _iso(at),
                ),
            )

    def record_run(self, run: DownloadRun) -> None:
        with self._transaction():
            self._connection.execute(
                "INSERT INTO runs (started_at, finished_at, seconds, requests, ceiling_ms)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    _iso(run.started_at),
                    _iso(run.finished_at),
                    run.seconds,
                    run.requests,
                    ms_from_utc(run.ceiling),
                ),
            )


def _pairs(connection: sqlite3.Connection) -> dict[str, PairInfo] | None:
    known = connection.execute("SELECT value FROM meta WHERE name = 'exchange_info_at'").fetchone()
    if known is None:
        return None
    rows = connection.execute("SELECT base, symbol, status FROM pairs ORDER BY base").fetchall()
    return {
        str(base): PairInfo(str(base), str(symbol), str(status)) for base, symbol, status in rows
    }


@dataclass(frozen=True)
class PairsSnapshot:
    """Borsa bilgisinin anlık görüntüsü: çiftler ve anı (spec 0051, plan A-2)."""

    pairs: dict[str, PairInfo]
    at: datetime | None


def read_pairs(path: str) -> PairsSnapshot | None:
    """Yalnız borsa bilgisi, mumsuz ve yalnız SELECT (spec 0051 L-2): depo yoksa `None` (dosya
    oluşturulmaz), anlık görüntü yoksa `pairs` boş ve `at` `None`; okunamıyorsa `PriceStoreError`.
    `mode=rw`: salt okuma da öldürülmüş sürecin günlüğünü geri alabilmeli (conventions, 0011)."""
    if not Path(path).is_file():
        return None
    uri = f"{Path(path).resolve().as_uri()}?mode=rw"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=0)) as connection:
            _check_format(connection)
            pairs = _pairs(connection)
            info = connection.execute(
                "SELECT value FROM meta WHERE name = 'exchange_info_at'"
            ).fetchone()
    except (sqlite3.Error, ValueError, TypeError):
        raise PriceStoreError("fiyat deposu okunamıyor") from None
    if pairs is None:
        return PairsSnapshot({}, None)
    return PairsSnapshot(pairs, None if info is None else datetime.fromisoformat(str(info[0])))


def read_prices(path: str) -> PriceData | None:
    """Ölçüm: depo yoksa `None` (dosya oluşturulmaz); okunamıyorsa `PriceStoreError`."""
    if not Path(path).is_file():
        return None
    uri = f"{Path(path).resolve().as_uri()}?mode=rw"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=0)) as connection:
            _check_format(connection)
            pairs = _pairs(connection)
            info = connection.execute(
                "SELECT value FROM meta WHERE name = 'exchange_info_at'"
            ).fetchone()
            candles: dict[str, list[StoredCandle]] = {}
            for symbol, *values in connection.execute(
                "SELECT symbol, open_ms, open, high, low, close FROM candles"
                " ORDER BY symbol, open_ms"
            ):
                open_ms, open_, high, low, close = values
                candles.setdefault(str(symbol), []).append(
                    StoredCandle(int(open_ms), str(open_), str(high), str(low), str(close))
                )
            spans: dict[str, list[StoredSpan]] = {}
            for symbol, start, end, found, source, fetched in connection.execute(
                "SELECT symbol, start_ms, end_ms, found, source, fetched_at FROM spans"
                " ORDER BY symbol, start_ms, end_ms"
            ):
                spans.setdefault(str(symbol), []).append(
                    StoredSpan(
                        _at(start),
                        _at(end),
                        bool(found),
                        str(source),
                        datetime.fromisoformat(str(fetched)),
                    )
                )
            runs = tuple(
                DownloadRun(
                    datetime.fromisoformat(str(started)),
                    datetime.fromisoformat(str(finished)),
                    float(seconds),
                    int(requests),
                    _at(ceiling),
                )
                for started, finished, seconds, requests, ceiling in connection.execute(
                    "SELECT started_at, finished_at, seconds, requests, ceiling_ms FROM runs"
                    " ORDER BY rowid"
                )
            )
    except (sqlite3.Error, ValueError, TypeError):
        raise PriceStoreError("fiyat deposu okunamıyor") from None
    return PriceData(
        pairs,
        None if info is None else datetime.fromisoformat(str(info[0])),
        {symbol: tuple(items) for symbol, items in candles.items()},
        {symbol: tuple(items) for symbol, items in spans.items()},
        runs,
    )
