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
    StartRecord,
    decode_ledger,
    decode_orders,
    decode_risk,
    decode_start,
    decode_time,
    encode_entry,
    encode_orders,
    encode_risk,
    encode_risk_legacy,
    encode_start,
    encode_summary,
    order_resolution_allowed,
    start_record_problem,
)
from crytobot.persistence._reconcile import conflicts
from crytobot.portfolio import EMPTY_LEDGER, Ledger, ledger_problems
from crytobot.risk import EMPTY_STATE, RiskState, risk_state_problems

MODES = ("paper", "live")
FORMAT_VERSION = "1"
# spec 0036 R-13: a live store opened before real fills existed lacks this key and is refused
LIVE_FILLS_KEY, LIVE_FILLS = "fills", "exchange"
# R-10 allows 5 s; the rest is for the last attempt. SQLite's own timeout is not used: it adds up
# nominal sleeps, and timeout=4 took 6 s of real time on Windows (plan 0011 Risk 4).
BUSY_WAIT_S = 4.0
_BUSY_POLL_S = 0.05
_SHOWN_CONFLICTS = 3
# spec 0038: added only; an older store gets it on its first start record (no format change)
_STARTS_TABLE = (
    "CREATE TABLE IF NOT EXISTS starts(seq INTEGER PRIMARY KEY, row TEXT NOT NULL) STRICT"
)
LAST_TURN_KEY = "last_turn"  # spec 0038 plan Risk 1: paper only, monotonic, revision unchanged
_SCHEMA = (
    "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT",
    "CREATE TABLE entries(seq INTEGER PRIMARY KEY, row TEXT NOT NULL) STRICT",
    "CREATE TABLE orders(seq INTEGER PRIMARY KEY, row TEXT NOT NULL) STRICT",
    "CREATE TABLE audit(seq INTEGER PRIMARY KEY, row TEXT NOT NULL) STRICT",
    _STARTS_TABLE,
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
    LIVE_STORE_OUTDATED = "live_store_outdated"


@dataclass(frozen=True)
class StoredState:
    """Depodaki kalıcı durum: defter, emirler (dolum tahminleri dahil) ve risk durumu."""

    mode: str
    revision: int
    ledger: Ledger
    execution: ExecutionState
    risk: RiskState
    last_turn: datetime | None = None  # spec 0038: the last turn written to a paper store


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
_OUTDATED = _refusal(
    StoreOutcome.LIVE_STORE_OUTDATED,
    "eski canlı depo: gerçek dolum bilgisi taşımıyor; prepare --live ile yeniden açın",
)


def _valid_mode(mode: object) -> bool:
    return type(mode) is str and mode in MODES


def _target(path: object) -> Path | None:
    if not isinstance(path, str | os.PathLike):
        return None
    try:
        return Path(path)
    except TypeError:  # a PathLike of bytes
        return None


def _connect(target: Path, readonly: bool = False) -> sqlite3.Connection:
    """`mode=rw` var olan dosyayı açar, yoksa oluşturmaz (R-2).
    `readonly=True` ise `mode=ro` ile salt-okunur açar."""
    mode_param = "mode=ro" if readonly else "mode=rw"
    uri = target.resolve().as_uri() + f"?{mode_param}"
    connection = sqlite3.connect(uri, uri=True, timeout=0, isolation_level=None)
    try:
        if not readonly:
            # R-5, integrity: a power cut leaves one whole state, though the last commit
            # may roll back
            connection.execute("PRAGMA synchronous=FULL")
    except sqlite3.Error:  # locked or not a database; the caller's closing() has not begun yet
        connection.close()
        raise
    return connection


def _busy(error: sqlite3.Error) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    return code is not None and code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


def _waiting[T](action: Callable[[], T]) -> T:
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
    if stored_mode != mode:
        return _MODE_MISMATCH
    if mode == "live" and meta.get(LIVE_FILLS_KEY) != LIVE_FILLS:  # spec 0036 R-13
        return _OUTDATED
    return int(revision)


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
    if mode == "live":  # spec 0036 R-13: this store records the exchange's real fills
        meta[LIVE_FILLS_KEY] = LIVE_FILLS
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
    last_turn = _last_turn(meta)
    problems = _problems(ledger, execution, risk)
    if problems:
        return _refusal(StoreOutcome.UNREADABLE, f"depo okunamıyor: {problems[0]}")
    return _flagged(
        StoreOutcome.LOADED,
        StoredState(mode, header, ledger, execution, risk, last_turn),
        "depo yüklendi",
    )


def _last_turn(meta: dict[str, str]) -> datetime | None:
    text = meta.get(LAST_TURN_KEY)
    return None if text is None else decode_time(text)


def _read_from(target: Path, mode: str, readonly: bool = False) -> StoreResult:
    with closing(_connect(target, readonly=readonly)) as database:
        return _read(database, mode)


def load_store(path: object, mode: object, readonly: bool = False) -> StoreResult:
    """R-2, R-3, R-6, R-9: durumun tamamı ya da adlandırılmış sonuç; kısmi ya da boş durum yok."""
    target = _target(path)
    if target is None or not _valid_mode(mode) or not isinstance(readonly, bool):
        return _INVALID
    assert isinstance(mode, str)  # checked above
    try:
        if not target.exists():
            return _MISSING
        return _waiting(lambda: _read_from(target, mode, readonly=readonly))
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
    """R-8, spec 0012 CB-1, CB-2: gözlem zamanı geri alınmaz; aynı UTC gününde gün başı kasa metni
    değişmez; durdurma yalnız `resume`'un ürettiği biçimde kapanır; zirve başka yerde düşmez (depo
    CLI yetkisini doğrulayamaz, bu kural hatalı yazımı yakalar). Zirve sayısal karşılaştırılır
    (`1.10` → `1.1` düşüş değil); `Decimal` karşılaştırması tamdır, bağlam hassasiyetine bağlı
    değildir."""
    if stored.last_time is None:
        return True  # no observation yet: the first one sets every field
    if risk.last_time is None or risk.last_time < stored.last_time:
        return False
    if risk.day == stored.day and str(risk.day_start_equity) != str(stored.day_start_equity):
        return False
    if (stored.halted and not risk.halted) or (stored.kill_switch and not risk.kill_switch):
        return (
            str(risk.peak_equity) == str(risk.last_equity)
            and str(risk.last_equity) == str(stored.last_equity)
            and _text_of(risk.last_time) == _text_of(stored.last_time)
        )
    assert risk.peak_equity is not None and stored.peak_equity is not None  # R-6: all or none
    return risk.peak_equity >= stored.peak_equity


def _history_allows(
    stored_entries: list[str],
    stored_orders: list[str],
    stored_risk: RiskState,
    image: _Image,
    risk: RiskState,
    mode: str,
) -> bool:
    if image.entries[: len(stored_entries)] != stored_entries:
        return False
    if len(image.orders) < len(stored_orders):
        return False
    for before, after in zip(stored_orders, image.orders, strict=False):
        if before != after and not order_resolution_allowed(before, after, mode):
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
    # Spec 0030 Risk 4: allow 6-element legacy encoding if kill_switch is False.
    if meta["risk"] != encode_risk(base.risk) and not (
        not base.risk.kill_switch and meta["risk"] == encode_risk_legacy(base.risk)
    ):
        return _UNREADABLE
    stored_entries, stored_orders = _rows(database, "entries"), _rows(database, "orders")
    if not _history_allows(
        stored_entries, stored_orders, decode_risk(meta["risk"]), image, state.risk, base.mode
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
    state = StoredState(base.mode, base.revision + 1, ledger, execution, risk, base.last_turn)
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


def append_audit_record(path: object, record: object) -> StoreResult:
    """R-7: Denetim kaydını append-only olarak audit tablosuna yazar."""
    target = _target(path)
    if target is None or type(record) is not str or not record:
        return _INVALID
    try:
        if not target.exists():
            return _MISSING

        def _append() -> StoreResult:
            with closing(_connect(target)) as database:
                database.execute("BEGIN EXCLUSIVE")
                database.execute(
                    "CREATE TABLE IF NOT EXISTS audit("
                    "seq INTEGER PRIMARY KEY, row TEXT NOT NULL) STRICT"
                )
                meta = _meta(database)
                if meta.get("format_version") != FORMAT_VERSION:
                    return _UNKNOWN_VERSION
                count = database.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
                database.execute("INSERT INTO audit(seq, row) VALUES (?, ?)", (count, record))
                database.execute("COMMIT")
                return StoreResult(StoreOutcome.SAVED, None, (), "denetim kaydı eklendi")

        return _waiting(_append)
    except sqlite3.Error as error:
        return _BUSY if _busy(error) else _WRITE_FAILED
    except (CodecError, KeyError, OSError, ValueError):
        return _WRITE_FAILED


def load_audit_records(path: object) -> list[str]:
    """Test ve denetim: audit tablosundaki tüm kayıtları sıra numarasına göre döndürür."""
    target = _target(path)
    if target is None or not target.exists():
        return []
    try:
        with closing(_connect(target)) as database:
            database.execute("BEGIN")
            has_table = database.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='audit'"
            ).fetchone()
            if not has_table:
                return []
            return _rows(database, "audit")
    except (sqlite3.Error, CodecError, OSError):
        return []


@dataclass(frozen=True)
class StartRecordsResult:
    """Spec 0038: `records` yalnız LOADED'da anlamlıdır; tablosu olmayan depo boş döner."""

    outcome: StoreOutcome
    records: tuple[StartRecord, ...]
    message: str


def _start_refusal(result: StoreResult) -> StartRecordsResult:
    return StartRecordsResult(result.outcome, (), result.message)


def _append_start(target: Path, record: StartRecord) -> StoreResult:
    with closing(_connect(target)) as database:  # closing without COMMIT rolls back
        database.execute("BEGIN EXCLUSIVE")
        header = _header(_meta(database), "paper")
        if isinstance(header, StoreResult):
            return header
        database.execute(_STARTS_TABLE)
        rows = _rows(database, "starts")
        for row in rows:
            decode_start(row)  # a broken history is not extended
        stamped = StartRecord(
            record.at, record.trial, record.report_path, header, record.report_sha256
        )
        row = encode_start(stamped)
        database.execute("INSERT INTO starts(seq, row) VALUES (?, ?)", (len(rows), row))
        database.execute("COMMIT")
        return StoreResult(StoreOutcome.SAVED, None, (), "başlatma kaydı eklendi")


def append_start_record(path: object, record: object) -> StoreResult:
    """Spec 0038 CB-1: başlatma kaydını yalnız paper deposuna, o anki revizyonla ekler.

    Kaydın `revision` alanı yok sayılır, depo yazar. Güncelleme ya da silme yolu yoktur."""
    target = _target(path)
    if target is None or start_record_problem(record) is not None:
        return _INVALID
    assert isinstance(record, StartRecord)  # checked above
    if record.report_path is not None and not os.path.isabs(record.report_path):
        return _INVALID  # CB-3, G-5: compared later as an absolute path
    try:
        if not target.exists():
            return _MISSING
        return _waiting(lambda: _append_start(target, record))
    except sqlite3.Error as error:
        return _BUSY if _busy(error) else _WRITE_FAILED
    except CodecError:
        return _UNREADABLE
    except (KeyError, OSError, ValueError):
        return _WRITE_FAILED


def _read_starts(target: Path, readonly: bool) -> StartRecordsResult:
    with closing(_connect(target, readonly=readonly)) as database:
        database.execute("BEGIN")
        header = _header(_meta(database), "paper")
        if isinstance(header, StoreResult):
            return _start_refusal(header)
        has_table = database.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='starts'"
        ).fetchone()
        rows = _rows(database, "starts") if has_table else []
        records = tuple(decode_start(row) for row in rows)
        return StartRecordsResult(StoreOutcome.LOADED, records, "başlatma kayıtları yüklendi")


def load_start_records(path: object, readonly: bool = True) -> StartRecordsResult:
    """Spec 0038 CB-3: paper deposunun başlatma kayıtları sırasıyla ya da adlandırılmış sonuç.

    Okuma hatası boş listeye çevrilmez: "kayıt yok" ile "okunamıyor" ayrı sonuçlardır."""
    target = _target(path)
    if target is None or not isinstance(readonly, bool):
        return _start_refusal(_INVALID)
    try:
        if not target.exists():
            return _start_refusal(_MISSING)
        return _waiting(lambda: _read_starts(target, readonly))
    except sqlite3.Error as error:
        return _start_refusal(_BUSY if _busy(error) else _UNREADABLE)
    except (CodecError, KeyError, OSError, ValueError):
        return _start_refusal(_UNREADABLE)


def _mark(target: Path, at: datetime) -> StoreResult:
    with closing(_connect(target)) as database:  # closing without COMMIT rolls back
        database.execute("BEGIN EXCLUSIVE")
        meta = _meta(database)
        header = _header(meta, "paper")
        if isinstance(header, StoreResult):
            return header
        previous = _last_turn(meta)
        if previous is not None and at < previous:
            return _IMMUTABLE
        database.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            (LAST_TURN_KEY, at.isoformat()),
        )
        database.execute("COMMIT")
        return StoreResult(StoreOutcome.SAVED, None, (), "tur işaretlendi")


def mark_turn(path: object, at: object) -> StoreResult:
    """Spec 0038 plan Risk 1: paper deposunun son turunu yazar; revizyon artmaz, an geri gitmez."""
    target = _target(path)
    if target is None or not isinstance(at, datetime) or at.utcoffset() is None:
        return _INVALID
    try:
        if not target.exists():
            return _MISSING
        return _waiting(lambda: _mark(target, at))
    except sqlite3.Error as error:
        return _BUSY if _busy(error) else _WRITE_FAILED
    except CodecError:
        return _UNREADABLE
    except (KeyError, OSError, ValueError):
        return _WRITE_FAILED
