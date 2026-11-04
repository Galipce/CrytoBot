"""SQLite depo (spec 0011): kurulum, yükleme, tek işlemde kayıt, geçmiş ve mod kuralları.

Global durum yok: `save_store`'un `base`'i son yükleme ya da kaydın sonucudur, revizyon taşır.
Tek bekleme: yazım baştan `BEGIN EXCLUSIVE` alır, `COMMIT` ikinci kez kilit beklemez (plan Risk 4).
Yükleme de `mode=rw` açar: `mode=ro` öldürülmüş sürecin sıcak günlüğünü geri alamaz (plan Risk 3);
dosya yoksa ikisi de oluşturmaz. Mesajlar sabit metindir; yol ve ham girdi yazılmaz (R-10).
"""

import os
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from crytobot.execution import EMPTY_EXECUTION, ExecutionState, execution_problems
from crytobot.persistence._codec import (
    CodecError,
    decode_ledger,
    decode_orders,
    decode_risk,
    encode_entry,
    encode_orders,
    encode_risk,
    encode_summary,
    order_resolution_allowed,
)
from crytobot.persistence._reconcile import conflicts
from crytobot.portfolio import EMPTY_LEDGER, Ledger, ledger_problems
from crytobot.risk import EMPTY_STATE, RiskState, risk_state_problems

MODES = ("paper", "live")
FORMAT_VERSION = "1"
# R-10 allows 5 s; the rest is for the last attempt. SQLite's own timeout is not used: it adds up
# nominal sleeps, and timeout=4 took 6 s of real time on Windows (plan 0011 Risk 4).
BUSY_WAIT_S = 4.0
_BUSY_POLL_S = 0.05
_SHOWN_CONFLICTS = 3
_SCHEMA = (
    "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT",
    "CREATE TABLE entries(seq INTEGER PRIMARY KEY, row TEXT NOT NULL) STRICT",
    "CREATE TABLE orders(seq INTEGER PRIMARY KEY, row TEXT NOT NULL) STRICT",
)


class StoreOutcome(Enum):
    CREATED = "created"
    LOADED = "loaded"
    SAVED = "saved"
    INVALID_INPUT = "invalid_input"
    ALREADY_EXISTS = "already_exists"
    NOT_FOUND = "not_found"
    UNREADABLE = "unreadable"
    UNKNOWN_VERSION = "unknown_version"
    MODE_MISMATCH = "mode_mismatch"
    WRITE_FAILED = "write_failed"
    BUSY = "busy"
    STALE_WRITE = "stale_write"
    HISTORY_IMMUTABLE = "history_immutable"


@dataclass(frozen=True)
class StoredState:
    """Depodaki kalıcı durum: defter, emirler (dolum tahminleri dahil) ve risk durumu."""

    mode: str
    revision: int
    ledger: Ledger
    execution: ExecutionState
    risk: RiskState


@dataclass(frozen=True)
class StoreResult:
    """`state` yalnız CREATED, LOADED, SAVED'de dolu; `conflicts`: "mutabakat tutmuyor" işareti."""

    outcome: StoreOutcome
    state: StoredState | None
    conflicts: tuple[str, ...]
    message: str

    @property
    def reconciled(self) -> bool:
        return not self.conflicts


def _refusal(outcome: StoreOutcome, message: str) -> StoreResult:
    return StoreResult(outcome, None, (), message)


_INVALID = _refusal(StoreOutcome.INVALID_INPUT, "geçersiz girdi")
_MISSING = _refusal(StoreOutcome.NOT_FOUND, "depo yok")
_UNREADABLE = _refusal(StoreOutcome.UNREADABLE, "depo okunamıyor")
_UNKNOWN_VERSION = _refusal(StoreOutcome.UNKNOWN_VERSION, "bilinmeyen biçim sürümü")
_MODE_MISMATCH = _refusal(StoreOutcome.MODE_MISMATCH, "mod uyuşmuyor")
_WRITE_FAILED = _refusal(StoreOutcome.WRITE_FAILED, "yazılamadı")
_BUSY = _refusal(StoreOutcome.BUSY, "depo meşgul")
_STALE = _refusal(StoreOutcome.STALE_WRITE, "eski yazım")
_IMMUTABLE = _refusal(StoreOutcome.HISTORY_IMMUTABLE, "geçmiş değiştirilemez")


def _valid_mode(mode: object) -> bool:
    return type(mode) is str and mode in MODES


def _target(path: object) -> Path | None:
    if not isinstance(path, str | os.PathLike):
        return None
    try:
        return Path(path)
    except TypeError:  # a PathLike of bytes
        return None


def _connect(target: Path) -> sqlite3.Connection:
    """`mode=rw` var olan dosyayı açar, yoksa oluşturmaz (R-2)."""
    uri = target.resolve().as_uri() + "?mode=rw"
    connection = sqlite3.connect(uri, uri=True, timeout=0, isolation_level=None)
    try:
        # R-5, integrity: a power cut leaves one whole state, though the last commit may roll back
        connection.execute("PRAGMA synchronous=FULL")
    except sqlite3.Error:  # locked or not a database; the caller's closing() has not begun yet
        connection.close()
        raise
    return connection


def _busy(error: sqlite3.Error) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    return code is not None and code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


def _waiting(action: Callable[[], StoreResult]) -> StoreResult:
    """`action` kilit bulana ya da gerçek zamanla süre dolana kadar; süre dolunca hata yükselir."""
    deadline = time.monotonic() + BUSY_WAIT_S
    while True:
        try:
            return action()
        except sqlite3.Error as error:
            if not _busy(error) or time.monotonic() >= deadline:
                raise
        time.sleep(_BUSY_POLL_S)


def _rows(database: sqlite3.Connection, table: str) -> list[str]:
    """Sıra numaraları boşluksuz olmalı; kaybolan satır bozuk içeriktir (R-6)."""
    rows = database.execute(f"SELECT seq, row FROM {table} ORDER BY seq").fetchall()
    if any(seq != index for index, (seq, _) in enumerate(rows)):
        raise CodecError
    return [row for _, row in rows]


def _meta(database: sqlite3.Connection) -> dict[str, str]:
    meta = dict(database.execute("SELECT key, value FROM meta").fetchall())
    if not all(type(value) is str for value in meta.values()):
        raise CodecError
    return meta


def _header(meta: dict[str, str], mode: str) -> StoreResult | int:
    """Sürüm, mod ve revizyon; sorun varsa adlandırılmış sonuç. Sürüm önce gelir (R-12)."""
    try:
        version, stored_mode, revision = meta["format_version"], meta["mode"], meta["revision"]
    except KeyError:
        return _UNREADABLE
    if not (version.isascii() and version.isdigit()):
        return _UNREADABLE
    if version != FORMAT_VERSION:
        return _UNKNOWN_VERSION
    if stored_mode not in MODES or not (revision.isascii() and revision.isdigit()):
        return _UNREADABLE
    if "ledger" not in meta:
        return _UNREADABLE
    return _MODE_MISMATCH if stored_mode != mode else int(revision)


def _problems(ledger: object, execution: object, risk: object) -> list[str]:
    return ledger_problems(ledger) + execution_problems(execution) + risk_state_problems(risk)


def _flagged(outcome: StoreOutcome, state: StoredState, verb: str) -> StoreResult:
    found = conflicts(state.ledger, state.execution)
    if not found:
        return StoreResult(outcome, state, (), verb)
    shown = ", ".join(found[:_SHOWN_CONFLICTS])
    more = len(found) - _SHOWN_CONFLICTS
    suffix = f" ve {more} kimlik daha" if more > 0 else ""
    return StoreResult(outcome, state, found, f"{verb}; mutabakat tutmuyor: {shown}{suffix}")


def create_store(path: object, mode: object) -> StoreResult:
    """R-1: depoyu yalnız bu çağrı oluşturur; üst dizin oluşturulmaz, var olan dosyaya dokunmaz."""
    target = _target(path)
    if target is None or not _valid_mode(mode):
        return _INVALID
    assert isinstance(mode, str)  # checked above
    if os.path.lexists(target):
        return _refusal(StoreOutcome.ALREADY_EXISTS, "depo zaten var")
    try:
        os.close(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    except FileExistsError:
        return _refusal(StoreOutcome.ALREADY_EXISTS, "depo zaten var")
    except (OSError, ValueError):
        return _WRITE_FAILED
    meta = {
        "format_version": FORMAT_VERSION,
        "mode": mode,
        "revision": "0",
        "ledger": encode_summary(EMPTY_LEDGER),
        "risk": encode_risk(EMPTY_STATE),
    }
    try:
        with closing(_connect(target)) as database:
            database.execute("BEGIN EXCLUSIVE")
            for statement in _SCHEMA:
                database.execute(statement)
            database.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
            database.execute("COMMIT")
    except (sqlite3.Error, OSError):  # a kill here leaves an unreadable file (plan 0011 Risk 6)
        with suppress(OSError):
            target.unlink(missing_ok=True)
        return _WRITE_FAILED
    state = StoredState(mode, 0, EMPTY_LEDGER, EMPTY_EXECUTION, EMPTY_STATE)
    return StoreResult(StoreOutcome.CREATED, state, (), "depo oluşturuldu")


def _read(database: sqlite3.Connection, mode: str) -> StoreResult:
    database.execute("BEGIN")  # every table from one moment
    meta = _meta(database)
    header = _header(meta, mode)
    if isinstance(header, StoreResult):
        return header
    ledger = decode_ledger(_rows(database, "entries"), meta["ledger"])
    execution = decode_orders(_rows(database, "orders"))
    risk = decode_risk(meta["risk"])
    problems = _problems(ledger, execution, risk)
    if problems:
        return _refusal(StoreOutcome.UNREADABLE, f"depo okunamıyor: {problems[0]}")
    return _flagged(
        StoreOutcome.LOADED,
        StoredState(mode, header, ledger, execution, risk),
        "depo yüklendi",
    )


def _read_from(target: Path, mode: str) -> StoreResult:
    with closing(_connect(target)) as database:
        return _read(database, mode)


def load_store(path: object, mode: object) -> StoreResult:
    """R-2, R-3, R-6, R-9: durumun tamamı ya da adlandırılmış sonuç; kısmi ya da boş durum yok."""
    target = _target(path)
    if target is None or not _valid_mode(mode):
        return _INVALID
    assert isinstance(mode, str)  # checked above
    try:
        if not target.exists():
            return _MISSING
        return _waiting(lambda: _read_from(target, mode))
    except sqlite3.Error as error:
        return _BUSY if _busy(error) else _UNREADABLE
    except (CodecError, KeyError, OSError, ValueError):
        return _UNREADABLE


@dataclass(frozen=True)
class _Image:
    """Yazılacak durumun metni; R-8 de bunun üstünden karşılaştırır: `Decimal("1.10") ==
    Decimal("1.1")` sessiz değişikliği kaçırırdı."""

    entries: list[str]
    orders: list[str]
    summary: str
    risk: str


def _text_of(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat()


def _risk_allows(stored: RiskState, risk: RiskState) -> bool:
    """R-8: gözlem zamanı geri alınmaz; durdurma yalnız `resume`'un ürettiği biçimde kapanır (depo
    CLI yetkisini doğrulayamaz, bu kural hatalı yazımı yakalar)."""
    if stored.last_time is not None and (
        risk.last_time is None or risk.last_time < stored.last_time
    ):
        return False
    if stored.halted and not risk.halted:
        return (
            str(risk.peak_equity) == str(risk.last_equity)
            and str(risk.last_equity) == str(stored.last_equity)
            and _text_of(risk.last_time) == _text_of(stored.last_time)
        )
    return True


def _history_allows(
    stored_entries: list[str],
    stored_orders: list[str],
    stored_risk: RiskState,
    image: _Image,
    risk: RiskState,
) -> bool:
    if image.entries[: len(stored_entries)] != stored_entries:
        return False
    if len(image.orders) < len(stored_orders):
        return False
    for before, after in zip(stored_orders, image.orders, strict=False):
        if before != after and not order_resolution_allowed(before, after):
            return False
    return _risk_allows(stored_risk, risk)


def _write(
    database: sqlite3.Connection,
    stored_entries: list[str],
    stored_orders: list[str],
    image: _Image,
    revision: int,
) -> None:
    """Yalnız yeni ve değişen satırlar; hepsi çağıranın tek işleminde (R-5)."""
    entries, orders = image.entries, image.orders
    database.executemany(
        "INSERT INTO entries(seq, row) VALUES (?, ?)",
        ((i, entries[i]) for i in range(len(stored_entries), len(entries))),
    )
    database.executemany(
        "UPDATE orders SET row = ? WHERE seq = ?",
        (
            (after, i)
            for i, (before, after) in enumerate(zip(stored_orders, orders, strict=False))
            if before != after
        ),
    )
    database.executemany(
        "INSERT INTO orders(seq, row) VALUES (?, ?)",
        ((i, orders[i]) for i in range(len(stored_orders), len(orders))),
    )
    database.executemany(
        "UPDATE meta SET value = ? WHERE key = ?",
        ((str(revision), "revision"), (image.summary, "ledger"), (image.risk, "risk")),
    )


def _save(
    database: sqlite3.Connection, base: StoredState, image: _Image, state: StoredState
) -> StoreResult:
    database.execute("BEGIN EXCLUSIVE")
    meta = _meta(database)
    header = _header(meta, base.mode)
    if isinstance(header, StoreResult):
        return header
    if header != base.revision:
        return _STALE
    # At this revision base is what the disk holds. The summary is overwritten below and R-6 repairs
    # nothing; comparing text decodes no row (plan 0011 Risk 8).
    if meta["ledger"] != encode_summary(base.ledger):
        return _UNREADABLE
    # Spec 0012 CB-3: the same for the risk row. From here on the row is valid base.risk's text.
    if meta["risk"] != encode_risk(base.risk):
        return _UNREADABLE
    stored_entries, stored_orders = _rows(database, "entries"), _rows(database, "orders")
    if not _history_allows(
        stored_entries, stored_orders, decode_risk(meta["risk"]), image, state.risk
    ):
        return _IMMUTABLE
    _write(database, stored_entries, stored_orders, image, state.revision)
    database.execute("COMMIT")
    return _flagged(StoreOutcome.SAVED, state, "depo kaydedildi")


def _save_to(target: Path, base: StoredState, image: _Image, state: StoredState) -> StoreResult:
    with closing(_connect(target)) as database:  # closing without COMMIT rolls back
        return _save(database, base, image, state)


def save_store(
    path: object, base: object, ledger: object, execution: object, risk: object
) -> StoreResult:
    """R-5, R-8, R-10: üç durumu tek işlemde yazar ya da depoyu değiştirmeden adlandırır.

    Spec 0012 sonuç sırası: geçersiz girdi (burada, G/Ç yok) → eski yazım → depo okunamıyor → geçmiş
    değiştirilemez (`_save`, tek işlemde)."""
    target = _target(path)
    if target is None or not isinstance(base, StoredState):
        return _INVALID
    problems = _problems(ledger, execution, risk)
    if problems:
        return _refusal(StoreOutcome.INVALID_INPUT, f"geçersiz girdi: {problems[0]}")
    base_problems = risk_state_problems(base.risk)
    if base_problems:  # the prefix: what needs fixing is the base, not the new state
        return _refusal(StoreOutcome.INVALID_INPUT, f"geçersiz girdi: base: {base_problems[0]}")
    assert isinstance(ledger, Ledger)  # checked by _problems
    assert isinstance(execution, ExecutionState) and isinstance(risk, RiskState)
    image = _Image(
        [encode_entry(entry) for entry in ledger.entries],
        encode_orders(execution),
        encode_summary(ledger),
        encode_risk(risk),
    )
    state = StoredState(base.mode, base.revision + 1, ledger, execution, risk)
    try:
        if not target.exists():
            return _MISSING
        return _waiting(lambda: _save_to(target, base, image, state))
    except sqlite3.Error as error:
        return _BUSY if _busy(error) else _WRITE_FAILED
    except CodecError:
        return _UNREADABLE
    except (KeyError, OSError, ValueError):
        return _WRITE_FAILED
