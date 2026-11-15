"""Arşiv çalıştırması (spec 0047 R-1, R-4, R-5, R-7; plan Risk 4, 6, 7, 8, 10).

Kararlar burada; gerçek etkiler (UTC saat, monoton saat, bekleme, durdurma, getirme, satır
yazıcısı) `ArchiveParts` ile gelir. Önce keşif (`pageSize=1`): kataloglar ve bildirdikleri
toplamlar yanıttan okunur, ayarda ya da kodda katalog listesi yoktur (G-7). Sonra katalog katalog,
en yeniden en eskiye 50'şerlik sayfalar. Tamamlanmamış katalog kayıtlı sıradaki sayfadan sürer
(R-4); tamam katalog 1. sayfadan okunur ve arşive *bu katalogla* yazılmış, *bu çalıştırmada
yazılmamış* bir kimliğe ulaşınca, o sayfanın kalan yenileri yazıldıktan sonra bırakılır (plan Risk
7, A-3). 50'den az duyurulu
ya da boş sayfa kataloğun sonudur.

Aynı anda tek istek; bir yanıtın bitişinden sonrakinin başlangıcına en az `request_gap_s` saniye,
monoton saatle (R-5). İlk kaynak hatası o kataloğun satırına adıyla yazılır, çalıştırma eksik
biter; yineleme yok, sonraki kataloglara geçilmez. Durdurma her istekten önce, bekleme ve getirme
sırasında aranır; terk edilen yanıt yazılmaz. Arşive alınma anı yanıtın tamamı okunduktan sonra
saatten alınır. Satırlarda URL, sorgu ve istisna metni yoktur; Telegram bağlanmaz (G-8).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from crytobot.news._archive_store import (
    ArchiveItem,
    ArchiveStore,
    CatalogState,
    prepare_archive,
)
from crytobot.news._config import ArchiveConfig
from crytobot.news._fetch import Fetched
from crytobot.news._items import RawItem
from crytobot.news._parse import CatalogPage, ParseError, parse_binance_page

PAGE_SIZE = 50
UNKNOWN = "yok"
_PAGE_KEYS = ("type", "catalogId", "pageNo", "pageSize")


@dataclass(frozen=True)
class ArchiveParts:
    """Arşivin gerçek etkileri. `fetch(url, max_bytes)`; `wait` durdurma isteğinde erken döner."""

    clock: Callable[[], datetime]
    monotonic: Callable[[], float]
    wait: Callable[[float], None]
    stopped: Callable[[], bool]
    fetch: Callable[[str, int], Fetched]
    say: Callable[[str], None]


class ArchiveOutcome(Enum):
    COMPLETE = "complete"  # exit 0
    FAILED = "failed"  # a source error: exit 1
    STOPPED = "stopped"  # a stop request: exit 4


def page_url(base: str, catalog_id: int | None, page: int, size: int) -> str:
    """Ayardaki adresin sorgusu sayfa parametreleriyle birleşir; aynı adlar üzerine yazılır."""
    parts = urlsplit(base)
    query = [(key, value) for key, value in parse_qsl(parts.query, True) if key not in _PAGE_KEYS]
    query.append(("type", "1"))
    if catalog_id is not None:
        query.append(("catalogId", str(catalog_id)))
    query += [("pageNo", str(page)), ("pageSize", str(size))]
    return urlunsplit(parts._replace(query=urlencode(query)))


@dataclass
class CatalogRun:
    """Bir kataloğun bu çalıştırmadaki sayaçları (özet satırı)."""

    name: str
    new: int = 0
    duplicate: int = 0
    invalid: int = 0
    oldest: datetime | None = None
    complete: bool = False
    error: str | None = None

    @property
    def line(self) -> str:
        oldest = UNKNOWN if self.oldest is None else self.oldest.isoformat()
        text = (
            f"arşiv katalog={self.name} yeni={self.new} tekrar={self.duplicate}"
            f" geçersiz={self.invalid} en_eski={oldest} {'tamam' if self.complete else 'eksik'}"
        )
        return text if self.error is None else f"{text} hata={self.error}"


class _Stopped(Exception):
    """Durdurma isteği: çalıştırma yazmadan döner (çıkış 4)."""


class _Run:
    def __init__(self, config: ArchiveConfig, store: ArchiveStore, parts: ArchiveParts) -> None:
        self.config = config
        self.store = store
        self.parts = parts
        self.last_end: float | None = None
        self.written: set[str] = set()  # ids written in this run (plan Risk 7)

    def request(self, url: str) -> tuple[Fetched, datetime]:
        """Tek istek: aralık beklenir, durdurmaya bakılır; yanıt ve arşive alınma anı."""
        if self.last_end is not None:
            left = self.config.request_gap_s - (self.parts.monotonic() - self.last_end)
            if left > 0 and not self.parts.stopped():
                self.parts.wait(left)
        if self.parts.stopped():
            raise _Stopped
        try:
            fetched = self.parts.fetch(url, self.config.max_response_bytes)
        finally:
            self.last_end = self.parts.monotonic()
        if fetched.abandoned or self.parts.stopped():
            raise _Stopped
        return fetched, self.parts.clock()

    def pages(self, fetched: Fetched) -> list[CatalogPage]:
        if fetched.body is None:
            raise ParseError(fetched.error or "network_error")
        return parse_binance_page(fetched.body)

    def discover(self) -> list[CatalogState]:
        fetched, at = self.request(page_url(self.config.url, None, 1, 1))
        pages = self.pages(fetched)
        if not pages:
            raise ParseError("bad_schema")  # no catalogs at all would be a silent gap
        saved = self.store.states()
        states = []
        for page in pages:
            previous = saved.get(page.catalog_id, CatalogState(page.catalog_id, page.name))
            states.append(replace(previous, name=page.name, reported_total=page.total, listed=True))
        self.store.discover(states, at)
        return states

    def catalog(self, state: CatalogState, result: CatalogRun) -> None:
        """Kataloğu okur; kaynak hatasında `ParseError`, durdurmada `_Stopped`. Tamam katalogun
        yeniden okuması bilinen kimliğe ulaşmadan bir sonraki sayfaya geçerken katalog aynı
        işlemde eksik olur: yarıda kalırsa sonraki çalıştırma o sayfadan sona kadar okur, yeni
        duyuru kaybolmaz (plan A-1)."""
        refresh = state.complete
        page = 1 if refresh else state.next_page
        while True:
            fetched, at = self.request(page_url(self.config.url, state.catalog_id, page, PAGE_SIZE))
            try:
                articles = self._articles(self.pages(fetched), state.catalog_id)
            except ParseError as error:
                self.store.save_state(replace(state, last_error=error.name, last_run_at=at))
                raise
            items = [None if raw is None else prepare_archive(raw, at) for raw in articles]
            valid = [item for item in items if item is not None]
            stored = self.store.existing([item.article_id for item in valid])
            # only a record this catalog wrote in an earlier run stops it (plan A-3)
            known = any(
                stored.get(item.article_id) == state.catalog_id
                and item.article_id not in self.written
                for item in valid
            )
            finished = len(articles) < PAGE_SIZE or (refresh and known)
            state = replace(
                state,
                next_page=1 if finished else page + 1,
                complete=finished,
                last_error=None,
                last_run_at=at,
            )
            written = self.store.write_page(state.catalog_id, state.name, valid, state)
            self._count(result, items, valid, written)
            result.complete = state.complete
            if finished:
                return
            page += 1

    def _articles(self, pages: list[CatalogPage], catalog_id: int) -> list[RawItem | None]:
        if not pages:
            return []  # after the last page (plan Risk 4)
        if len(pages) != 1 or pages[0].catalog_id != catalog_id:
            raise ParseError("bad_schema")
        return pages[0].articles

    def _count(
        self,
        result: CatalogRun,
        items: Sequence[ArchiveItem | None],
        valid: Sequence[ArchiveItem],
        written: Sequence[bool],
    ) -> None:
        for item, was_written in zip(valid, written, strict=True):
            if was_written:
                result.new += 1
                self.written.add(item.article_id)
            else:
                result.duplicate += 1
            if item.published is not None and (
                result.oldest is None or item.published < result.oldest
            ):
                result.oldest = item.published
        result.invalid += len(items) - len(valid)


def _final(states: Sequence[CatalogState], done: set[int]) -> str:
    """Bu çalıştırmada sonuna (ya da bilinen kimliğe) ulaşılmayan katalog sayısıyla."""
    missing = len(states) - len(done)
    return "arşiv: tamam" if missing == 0 else f"arşiv: eksik ({missing} katalog)"


def run_archive(config: ArchiveConfig, store: ArchiveStore, parts: ArchiveParts) -> ArchiveOutcome:
    """Arşivi doldurur (R-1); kaynak hatasında ya da durdurmada yazılmışlar kalır (R-4)."""
    current = _Run(config, store, parts)
    try:
        states = current.discover()
    except _Stopped:
        parts.say("arşiv: eksik (durdurma isteği)")
        return ArchiveOutcome.STOPPED
    except ParseError as error:
        parts.say(f"arşiv keşif hata={error.name}")
        parts.say("arşiv: eksik (keşif)")
        return ArchiveOutcome.FAILED
    parts.say(f"arşiv keşif katalog={len(states)}")
    done: set[int] = set()
    for state in states:
        result = CatalogRun(state.name, complete=state.complete)
        try:
            current.catalog(state, result)
        except _Stopped:
            result.complete = False  # review L-1: a stopped catalog is not up to date either
            parts.say(result.line)
            parts.say(_final(states, done))
            return ArchiveOutcome.STOPPED
        except ParseError as error:
            result.error = error.name
            result.complete = False  # review I-1: a catalog that ends in an error is not up to date
            parts.say(result.line)
            parts.say(_final(states, done))
            return ArchiveOutcome.FAILED
        done.add(state.catalog_id)
        parts.say(result.line)
    parts.say(_final(states, done))
    return ArchiveOutcome.COMPLETE
