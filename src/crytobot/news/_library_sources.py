"""Örnek kütüphanesinin kaynakları (spec 0048 R-2, Q-5; plan Risk 6).

Arşivin (0047) bütün kayıtları ve ileriye dönük kaydın (0046) `binance-duyuru` türü kaynaklarından
`id:<kimlik>` anahtarlı kayıtları okunur; RSS kayıtları okunmaz. Aynı Binance duyuru kimliği iki
kaynakta da varsa tek duyurudur: kaynak işareti "ikisi", başlık, katalog ve yayın anı arşivden
(arşivde yayın anı yoksa ileriye dönükten), ilk görme anı ileriye dönükten. İleriye dönük kayıtta
aynı kimlik birden çok kaynakta görüldüyse en erken ilk görme anı alınır.

Var olan dosyalar `mode=rw` açılır, yalnız SELECT yapılır, `timeout=0` (0047 plan A-2): toplayıcı ya
da arşiv komutu yazarken de WAL okuması çalışır; dosya oluşturulmaz. Arşiv yoksa
`ArchiveStoreError`; ileriye dönük kayıt yoksa `forward_records` `None`'dır.
"""

import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from crytobot.news._archive_store import FORMAT_VERSION as ARCHIVE_FORMAT
from crytobot.news._archive_store import ArchiveStoreError, open_existing
from crytobot.news._labels import RULES_FINGERPRINT, label
from crytobot.news._store import FORMAT_VERSION as NEWS_FORMAT

FROM_ARCHIVE: Final = "arşiv"
FROM_FORWARD: Final = "ileriye dönük"
FROM_BOTH: Final = "ikisi"


@dataclass(frozen=True)
class LibraryAnnouncement:
    """Bir duyuru ve etiketi (Terimler: Duyuru). `catalog`: yalnız arşivde bilinir."""

    article_id: str
    origin: str
    catalog: str | None
    title: str
    published: datetime | None
    first_seen: datetime | None
    event_type: str
    direction: str
    coins: tuple[str, ...]


@dataclass(frozen=True)
class LibrarySources:
    announcements: tuple[LibraryAnnouncement, ...]
    archive_records: int
    forward_records: int | None
    rules_fingerprint: str


@dataclass
class _Row:
    origin: str
    catalog: str | None
    title: str
    published: datetime | None
    first_seen: datetime | None


def _moment(text: object) -> datetime | None:
    return None if text is None else datetime.fromisoformat(str(text))


def _format(connection: sqlite3.Connection, expected: str) -> bool:
    row = connection.execute("SELECT value FROM meta WHERE name = 'format'").fetchone()
    return row is not None and row[0] == expected


def _archive_rows(path: str) -> dict[str, _Row]:
    if not Path(path).is_file():
        raise ArchiveStoreError("arşiv yok")
    try:
        with closing(open_existing(path)) as connection:
            if not _format(connection, ARCHIVE_FORMAT):
                raise ArchiveStoreError("arşivin biçimi tanınmıyor")
            rows = connection.execute(
                "SELECT article_id, catalog_name, title, published_at FROM archive"
            ).fetchall()
    except (sqlite3.Error, ValueError):
        raise ArchiveStoreError("arşiv okunamıyor") from None
    try:
        return {
            str(article): _Row(FROM_ARCHIVE, str(catalog), str(title), _moment(published), None)
            for article, catalog, title, published in rows
        }
    except ValueError:
        raise ArchiveStoreError("arşiv okunamıyor") from None


def _forward_rows(path: str, sources: Sequence[str]) -> dict[str, _Row] | None:
    if not Path(path).is_file():
        return None
    if not sources:
        return {}
    marks = ", ".join("?" for _ in sources)
    try:
        with closing(open_existing(path)) as connection:
            if not _format(connection, NEWS_FORMAT):
                raise ArchiveStoreError("haber kaydının biçimi tanınmıyor")
            rows = connection.execute(
                "SELECT key, title, published_at, first_seen_at FROM news"
                f" WHERE source IN ({marks}) AND key LIKE 'id:%' ORDER BY id",
                tuple(sources),
            ).fetchall()
        found: dict[str, _Row] = {}
        for key, title, published, first_seen in rows:
            article = str(key)[3:]
            seen = _moment(first_seen)
            known = found.get(article)
            if known is None or (
                seen is not None and known.first_seen is not None and seen < known.first_seen
            ):
                found[article] = _Row(FROM_FORWARD, None, str(title), _moment(published), seen)
    except (sqlite3.Error, ValueError):
        raise ArchiveStoreError("haber kaydı okunamıyor") from None
    return found


def read_library_sources(
    archive_path: str, forward_path: str, binance_sources: Sequence[str]
) -> LibrarySources:
    """İki kaynağın birleşimi, kimlik sırasıyla; her duyuru başlığıyla etiketlenir."""
    archive = _archive_rows(archive_path)
    forward = _forward_rows(forward_path, binance_sources)
    merged = dict(archive)
    for article, row in (forward or {}).items():
        known = merged.get(article)
        if known is None:
            merged[article] = row
            continue
        known.origin = FROM_BOTH
        known.first_seen = row.first_seen
        if known.published is None:
            known.published = row.published
    announcements = []
    for article in sorted(merged):
        row = merged[article]
        tag = label(row.title)
        announcements.append(
            LibraryAnnouncement(
                article,
                row.origin,
                row.catalog,
                row.title,
                row.published,
                row.first_seen,
                tag.event_type,
                tag.direction,
                tag.coins,
            )
        )
    return LibrarySources(
        tuple(announcements),
        len(archive),
        None if forward is None else len(forward),
        RULES_FINGERPRINT,
    )
