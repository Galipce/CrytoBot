"""Saf öğe kuralları (spec 0046 R-3, R-4, R-5; plan Risk 6, 7, 8).

Ayrıştırılan ham öğe → haber kaydı ya da geçersiz (`None`). Anahtar: kimlik, yoksa bağlantı; ikisi
de yoksa tekrar anlaşılamaz, geçersizdir. Metin 20480 UTF-8 bayta kesilir, sınır çok baytlı bir
karakterin içindeyse karakterin başına çekilir. Yayın anı yoksa, okunamadıysa ya da ilk görme
anından 5 dakikadan kesin daha ilerideyse bilinmiyor (`None`). İlk görme anı yayın anından
türetilmez.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

TEXT_LIMIT_BYTES = 20 * 1024
FUTURE_TOLERANCE = timedelta(minutes=5)


@dataclass(frozen=True)
class RawItem:
    """Kaynağın verdiği hâliyle tek öğe. `published`: okunabildiyse UTC an, yoksa `None`."""

    item_id: str | None
    link: str | None
    title: str
    text: str
    published: datetime | None


@dataclass(frozen=True)
class NewsItem:
    """Yazılacak haber kaydı. `key`: tekrar anahtarı (`id:<kimlik>` ya da `link:<bağlantı>`)."""

    key: str
    link: str | None
    title: str
    text: str
    truncated: bool
    published: datetime | None
    first_seen: datetime


def clean(text: str) -> str:
    """Tek başına vekil (surrogate) karakterleri değiştirir: kayıt UTF-8 yazılabilmeli."""
    return text.encode("utf-8", "replace").decode("utf-8")


def truncate_utf8(text: str, limit: int = TEXT_LIMIT_BYTES) -> tuple[str, bool]:
    """Metin ve kesildi mi; tam `limit` bayt kesilmiş sayılmaz (AC-4)."""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    # the prefix of valid UTF-8 is valid but for a split last character, which is dropped
    return encoded[:limit].decode("utf-8", "ignore"), True


def publish_time(published: datetime | None, first_seen: datetime) -> datetime | None:
    if published is None or published > first_seen + FUTURE_TOLERANCE:
        return None
    return published


def _present(value: str | None) -> str | None:
    if value is None:
        return None
    value = clean(value).strip()
    return value or None


def prepare(raw: RawItem, first_seen: datetime) -> NewsItem | None:
    """Haber kaydı; başlığı ve metni boşsa ya da anahtarı yoksa `None` (geçersiz)."""
    item_id = _present(raw.item_id)
    link = _present(raw.link)
    title = clean(raw.title).strip()
    text = clean(raw.text).strip()
    if not title and not text:
        return None
    if item_id is not None:
        key = f"id:{item_id}"
    elif link is not None:
        key = f"link:{link}"
    else:
        return None
    text, truncated = truncate_utf8(text)
    return NewsItem(
        key, link, title, text, truncated, publish_time(raw.published, first_seen), first_seen
    )
