"""İleriye dönük ölçümün okuyucuları (spec 0053 R-1, R-10, AC-9, AC-10; plan step 5).

Skor kaydı ve haber kaydı `mode=ro`, `timeout=0` ve `closing` ile açılır: kilit alınmaz, hiçbir şey
yazılmaz, skorlayıcı ve toplayıcı beklenmez (WAL; `read_score_snapshot`'un notu). Satırlar tek tek
ayrıştırılır: okunamayan (bozuk) satır raporu durdurmaz, atlanır ve sayılır. Kayıt yoksa `None`
döner (dosya oluşturulmaz); biçimi tanınmıyor ya da kayıt açılamıyorsa adlandırılmış hata.
"""

import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from crytobot.news._score_store import ScoreStoreError, _check_format
from crytobot.news._store import FORMAT_VERSION, StoreError

UNREADABLE = "skor kaydı okunamıyor"


@dataclass(frozen=True)
class ScoreRow:
    """Bir haberin sonucu: tür, an ve (skorlandıysa) model ve iki parmak izi."""

    news_id: int
    kind: str
    at: datetime
    model: str | None
    prompt_fingerprint: str | None
    context_fingerprint: str | None


@dataclass(frozen=True)
class EventRow:
    news_id: int
    coin: str
    event_type: str
    direction: str
    severity: int


@dataclass(frozen=True)
class ScoreRecord:
    """Skor kaydının ölçüme giren hâli; `skipped`: atlanan (okunamayan) satır sayısı."""

    results: tuple[ScoreRow, ...]
    events: tuple[EventRow, ...]
    skipped: int


def _uri(path: str) -> str:
    return f"{Path(path).resolve().as_uri()}?mode=ro"


def _moment(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("an")
    moment = datetime.fromisoformat(value)
    if moment.utcoffset() is None:
        raise ValueError("saat dilimi yok")
    return moment


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("metin")
    return value


def _optional(value: object) -> str | None:
    return None if value is None else _text(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise TypeError("tam sayı")
    return value


def _result(row: Sequence[object]) -> ScoreRow:
    news_id, kind, at, model, prompt, context = row
    return ScoreRow(
        _integer(news_id),
        _text(kind),
        _moment(at),
        _optional(model),
        _optional(prompt),
        _optional(context),
    )


def _event(row: Sequence[object]) -> EventRow:
    news_id, coin, event_type, direction, severity = row
    return EventRow(
        _integer(news_id), _text(coin), _text(event_type), _text(direction), _integer(severity)
    )


def read_score_record(path: str) -> ScoreRecord | None:
    """Sonuçlar ve olay skorları; satır satır, bozuk satır sayılır (R-10)."""
    if not Path(path).is_file():
        return None
    results: list[ScoreRow] = []
    events: list[EventRow] = []
    skipped = 0
    try:
        with closing(sqlite3.connect(_uri(path), uri=True, timeout=0)) as connection:
            _check_format(connection)
            for row in connection.execute(
                "SELECT news_id, kind, at, model, prompt_fingerprint, context_fingerprint"
                " FROM results ORDER BY news_id"
            ):
                try:
                    results.append(_result(row))
                except (TypeError, ValueError):
                    skipped += 1
            for row in connection.execute(
                "SELECT news_id, coin, event_type, direction, severity FROM event_scores"
                " ORDER BY id"
            ):
                try:
                    events.append(_event(row))
                except (TypeError, ValueError):
                    skipped += 1
    except sqlite3.Error:
        raise ScoreStoreError(UNREADABLE) from None
    return ScoreRecord(tuple(results), tuple(events), skipped)


def read_news_sources(path: str) -> dict[int, str] | None:
    """Haber kaydı kimliği → kaynak adı; kayıt yoksa `None`. Okunamayan satır atlanır."""
    if not Path(path).is_file():
        return None
    found: dict[int, str] = {}
    try:
        with closing(sqlite3.connect(_uri(path), uri=True, timeout=0)) as connection:
            row = connection.execute("SELECT value FROM meta WHERE name = 'format'").fetchone()
            if row is None or row[0] != FORMAT_VERSION:
                raise StoreError("haber kaydının biçimi tanınmıyor")
            for record_id, source in connection.execute("SELECT id, source FROM news"):
                if type(record_id) is int and isinstance(source, str):
                    found[record_id] = source
    except sqlite3.Error:
        raise StoreError("haber kaydı okunamıyor") from None
    return found
