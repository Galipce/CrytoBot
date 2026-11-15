"""Spec 0047 AC-1, AC-4, AC-5, AC-6, AC-7: arşiv çalıştırması (`run_archive`).

Sahte Binance ucu gerçek yanıtın şemasını (`fixtures/archive/`) üretir: keşif her kataloğun ilk
`pageSize` duyurusu, katalog sayfası `catalogId` + `pageNo`, son sayfadan sonrası `catalogs: []`.
Saat, monoton saat, bekleme ve durdurma sahtedir; ağ yok.
"""

import dataclasses
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest

from crytobot.app import ForcedStop
from crytobot.news import (
    PAGE_SIZE,
    ArchiveConfig,
    ArchiveOutcome,
    ArchiveParts,
    ArchiveStore,
    Fetched,
    Hop,
    fetch_source,
    load_archive_config,
    page_url,
    run_archive,
)

BASE = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
START = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures" / "archive"


def articles(prefix: int, count: int, newest: datetime = START) -> list[dict[str, object]]:
    """`count` duyuru, en yeniden en eskiye; kimlikler `prefix*10000 + n`."""
    return [
        {
            "id": prefix * 10000 + count - n,
            "code": f"c{prefix}x{count - n}",
            "title": f"Duyuru {prefix}-{count - n}",
            "type": 1,
            "releaseDate": int((newest - timedelta(hours=n)).timestamp() * 1000),
        }
        for n in range(count)
    ]


def ids(raws: list[dict[str, object]]) -> list[str]:
    return [str(raw["id"]) for raw in raws]


@dataclass
class Binance:
    """Kataloglar: kimlik → (ad, duyurular en yeniden en eskiye)."""

    catalogs: dict[int, tuple[str, list[dict[str, object]]]]

    def publish(self, catalog_id: int, *new: dict[str, object]) -> None:
        name, existing = self.catalogs[catalog_id]
        self.catalogs[catalog_id] = (name, [*new, *existing])

    def body(self, url: str) -> bytes:
        query = dict(parse_qsl(urlsplit(url).query))
        size, page = int(query["pageSize"]), int(query["pageNo"])
        selected = self.catalogs
        if "catalogId" in query:
            selected = {int(query["catalogId"]): self.catalogs[int(query["catalogId"])]}
        catalogs = []
        for catalog_id, (name, all_articles) in selected.items():
            chunk = all_articles[(page - 1) * size : page * size]
            if not chunk and "catalogId" in query:
                continue
            catalogs.append(
                {
                    "catalogId": catalog_id,
                    "parentCatalogId": None,
                    "catalogName": name,
                    "total": len(all_articles),
                    "articles": chunk,
                    "catalogs": [],
                }
            )
        return json.dumps({"code": "000000", "data": {"catalogs": catalogs}}).encode()


@dataclass
class Harness:
    root: Path
    binance: Binance
    url: str = BASE
    gap: int = 1
    now: datetime = START
    mono: float = 100.0
    lines: list[str] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)
    spans: list[tuple[float, float]] = field(default_factory=list)
    waits: list[float] = field(default_factory=list)
    stop: bool = False
    in_flight: bool = False
    # (request index, url) -> a response instead of the fake's body, or None
    hook: Callable[[int, str], Fetched | None] | None = None
    fetcher: Callable[[str, int], Fetched] | None = None

    @property
    def store_path(self) -> Path:
        return self.root / "archive.db"

    @property
    def config(self) -> ArchiveConfig:
        document = {
            "news": {
                "store_path": str(self.root / "news.db"),
                "log_path": str(self.root / "news.log"),
                "archive_store_path": str(self.store_path),
                "archive_log_path": str(self.root / "archive.log"),
                "archive_url": self.url,
                "archive_request_gap_s": self.gap,
                "sources": [{"name": "b", "type": "binance-duyuru", "url": BASE}],
            }
        }
        result = load_archive_config(document)
        assert result.config is not None, result.message
        return result.config

    def fetch(self, url: str, max_bytes: int) -> Fetched:
        assert not self.in_flight  # one request at a time (R-5)
        self.in_flight = True
        start = self.mono
        self.requests.append(url)
        self.mono += 0.25
        self.now += timedelta(seconds=0.25)
        try:
            if self.fetcher is not None:
                return self.fetcher(url, max_bytes)
            if self.hook is not None:
                replaced = self.hook(len(self.requests) - 1, url)
                if replaced is not None:
                    return replaced
            return Fetched(body=self.binance.body(url))
        finally:
            self.spans.append((start, self.mono))
            self.in_flight = False

    def wait(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.mono += seconds
        self.now += timedelta(seconds=seconds)

    def parts(self) -> ArchiveParts:
        return ArchiveParts(
            lambda: self.now,
            lambda: self.mono,
            self.wait,
            lambda: self.stop,
            self.fetch,
            self.lines.append,
        )

    def run(self) -> ArchiveOutcome:
        self.lines.clear()
        self.requests.clear()
        self.stop = False
        store = ArchiveStore.open(str(self.store_path))
        try:
            return run_archive(self.config, store, self.parts())
        finally:
            store.close()

    def rows(self) -> list[dict[str, object]]:
        with sqlite3.connect(self.store_path) as connection:
            connection.row_factory = sqlite3.Row
            found = [dict(row) for row in connection.execute("SELECT * FROM archive ORDER BY id")]
        connection.close()
        return found

    def archived(self) -> list[str]:
        return [str(row["article_id"]) for row in self.rows()]

    def state(self, catalog_id: int) -> tuple[int, bool, str | None]:
        with sqlite3.connect(self.store_path) as connection:
            row = connection.execute(
                "SELECT next_page, complete, last_error FROM catalog_state WHERE catalog_id = ?",
                (catalog_id,),
            ).fetchone()
        connection.close()
        return int(row[0]), bool(row[1]), row[2]

    def pages_of(self, catalog_id: int) -> list[int]:
        found = []
        for url in self.requests:
            query = dict(parse_qsl(urlsplit(url).query))
            if query.get("catalogId") == str(catalog_id):
                found.append(int(query["pageNo"]))
        return found


A, B, C = 48, 161, 128


@pytest.fixture
def two(tmp_path: Path) -> Harness:
    """A: 120 duyuru (50 + 50 + 20), B: 50 duyuru (50 + boş)."""
    binance = Binance({A: ("Listing", articles(1, 120)), B: ("Delisting", articles(2, 50))})
    return Harness(tmp_path, binance)


def test_full_run_two_catalogs_multi_page(two: Harness) -> None:
    """AC-1: her duyuru bir kez; her katalog en eski sayfaya kadar okunur ve tamamdır; çıkış 0."""
    assert two.run() is ArchiveOutcome.COMPLETE
    expected = ids(two.binance.catalogs[A][1]) + ids(two.binance.catalogs[B][1])
    assert two.archived() == expected
    assert two.pages_of(A) == [1, 2, 3]
    assert two.pages_of(B) == [1, 2]
    assert two.state(A)[1:] == (True, None) and two.state(B)[1:] == (True, None)
    assert two.lines[-1] == "arşiv: tamam"


def test_catalogs_from_response_not_config(two: Harness) -> None:
    """AC-1, G-7: kataloglar keşif yanıtından; sonradan eklenen katalog kendiliğinden okunur.
    Ayardaki adresin sayfa parametreleri üzerine yazılır."""
    two.url = f"{BASE}?type=9&pageSize=20&catalogId=1&lang=en"
    assert two.run() is ArchiveOutcome.COMPLETE
    discovery = dict(parse_qsl(urlsplit(two.requests[0]).query))
    assert discovery == {"lang": "en", "type": "1", "pageNo": "1", "pageSize": "1"}
    page = dict(parse_qsl(urlsplit(two.requests[1]).query))
    assert page == {"lang": "en", "type": "1", "catalogId": str(A), "pageNo": "1", "pageSize": "50"}
    two.binance.catalogs[C] = ("Airdrop", articles(3, 3))
    assert two.run() is ArchiveOutcome.COMPLETE
    assert two.pages_of(C) == [1]
    assert ids(two.binance.catalogs[C][1])[0] in two.archived()


def test_record_fields_and_archive_origin(two: Harness) -> None:
    """AC-1, R-2: kaynak, katalog adı, kimlik, bağlantı, başlık, UTC yayın ve arşive alınma anı,
    "arşivden" işareti; ilk görme anı yok."""
    two.run()
    row = two.rows()[0]
    assert "first_seen_at" not in row
    published = datetime.fromisoformat(str(row["published_at"]))
    archived = datetime.fromisoformat(str(row["archived_at"]))
    assert row["source"] == "binance-duyuru"
    assert (row["catalog_id"], row["catalog_name"]) == (A, "Listing")
    assert row["article_id"] == "10120"
    assert row["link"] == "https://www.binance.com/en/support/announcement/c1x120"
    assert row["title"] == "Duyuru 1-120"
    assert published == START and published.utcoffset() == timedelta(0)
    assert archived.utcoffset() == timedelta(0)
    assert START < archived < START + timedelta(minutes=1)  # the response's time, not published
    assert row["origin"] == "archive" and row["truncated"] == 0


def test_stop_mid_page_no_partial_exit_4(two: Harness) -> None:
    """AC-4: sayfa okunurken durdurma isteği — o sayfa yazılmaz, öncekiler kalır, sonuç durdu."""

    def stop_on_second_page(index: int, url: str) -> Fetched | None:
        if index == 2:  # discovery, A p1, A p2
            two.stop = True
        return None

    two.hook = stop_on_second_page
    assert two.run() is ArchiveOutcome.STOPPED
    assert two.archived() == ids(two.binance.catalogs[A][1])[:PAGE_SIZE]
    assert two.state(A) == (2, False, None)
    assert two.lines[-2:] == [
        "arşiv katalog=Listing yeni=50 tekrar=0 geçersiz=0"
        f" en_eski={(START - timedelta(hours=49)).isoformat()} eksik",
        "arşiv: eksik (2 katalog)",
    ]


def test_abandoned_fetch_is_a_stop(two: Harness) -> None:
    two.hook = lambda index, url: Fetched(abandoned=True) if index == 1 else None
    assert two.run() is ArchiveOutcome.STOPPED
    assert two.archived() == []


def test_stop_before_discovery_and_during_gap(two: Harness) -> None:
    two.hook = lambda index, url: Fetched(abandoned=True)
    assert two.run() is ArchiveOutcome.STOPPED
    assert two.lines == ["arşiv: eksik (durdurma isteği)"]

    two.hook = None
    original = two.wait

    def stop_while_waiting(seconds: float) -> None:
        original(seconds)
        two.stop = True

    two.wait = stop_while_waiting  # type: ignore[method-assign]
    assert two.run() is ArchiveOutcome.STOPPED
    assert len(two.requests) == 1  # the stop is seen after the wait, before the next request


def test_forced_stop_rolls_back_exit_130(two: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-4: ikinci Ctrl+C (`ForcedStop`) sayfanın yazımında — sayfa ve durumu geri alınır."""
    store = ArchiveStore.open(str(two.store_path))
    insert = store._insert
    stop_at = ids(two.binance.catalogs[A][1])[60]

    def forced(catalog_id: int, name: str, item: object) -> bool:
        if getattr(item, "article_id", None) == stop_at:
            raise ForcedStop
        return insert(catalog_id, name, item)  # type: ignore[arg-type]

    monkeypatch.setattr(store, "_insert", forced)
    try:
        with pytest.raises(ForcedStop):
            run_archive(two.config, store, two.parts())
    finally:
        store.close()
    assert two.archived() == ids(two.binance.catalogs[A][1])[:PAGE_SIZE]
    assert two.state(A) == (2, False, None)


def test_resume_from_saved_page_no_rerequest(two: Harness) -> None:
    """AC-4: sonraki çalıştırma kaldığı sayfadan sürer, önceki sayfaları istemez."""
    two.hook = lambda index, url: setattr(two, "stop", True) if index == 3 else None
    assert two.run() is ArchiveOutcome.STOPPED  # A p1, p2 written; A p3 abandoned
    assert two.state(A) == (3, False, None)
    two.hook = None
    assert two.run() is ArchiveOutcome.COMPLETE
    assert two.pages_of(A) == [3]
    assert two.pages_of(B) == [1, 2]
    assert sorted(two.archived()) == sorted(
        ids(two.binance.catalogs[A][1]) + ids(two.binance.catalogs[B][1])
    )


def test_source_error_then_resume(two: Harness) -> None:
    """AC-4, AC-5: kaynak hatası yazılmışları bırakır; sonraki çalıştırma o sayfadan sürer."""
    two.hook = lambda index, url: Fetched(error="timeout") if index == 2 else None
    assert two.run() is ArchiveOutcome.FAILED
    assert two.state(A) == (2, False, "timeout")
    assert two.lines[-2].endswith(" eksik hata=timeout")
    assert two.lines[-1] == "arşiv: eksik (2 katalog)"
    two.hook = None
    assert two.run() is ArchiveOutcome.COMPLETE
    assert two.pages_of(A) == [2, 3]
    assert two.state(A) == (1, True, None)


def test_page_shift_skips_nothing(two: Harness) -> None:
    """AC-4, G-2: okuma sürerken (ve iki çalıştırma arasında) başa eklenen duyurular sayfaları
    kaydırır; hiçbir duyuru atlanmaz, yalnız tekrar olur."""
    original = list(two.binance.catalogs[A][1])

    def publish_after_first_page(index: int, url: str) -> Fetched | None:
        if index == 2:
            two.binance.publish(A, *articles(5, 3, START + timedelta(days=1)))
            two.stop = True  # and stop: the shift is seen again across runs
        return None

    two.hook = publish_after_first_page
    two.run()
    two.binance.publish(A, *articles(6, 10, START + timedelta(days=2)))
    two.hook = None
    assert two.run() is ArchiveOutcome.COMPLETE
    assert set(ids(original)) <= set(two.archived())
    assert two.lines[1].startswith("arşiv katalog=Listing yeni=70 tekrar=13 ")
    assert two.run() is ArchiveOutcome.COMPLETE  # the refresh brings the published ones
    assert set(ids(two.binance.catalogs[A][1])) <= set(two.archived())


def test_complete_catalog_rerun_stops_at_known_id(two: Harness) -> None:
    """AC-4: tamam katalog en yeniden okunur, arşivde bulunan kimliğe ulaşınca bırakılır."""
    two.run()
    new = articles(7, 2, START + timedelta(days=1))
    two.binance.publish(A, *new)
    assert two.run() is ArchiveOutcome.COMPLETE
    assert two.pages_of(A) == [1] and two.pages_of(B) == [1]
    assert set(ids(new)) <= set(two.archived())
    assert two.lines[1].startswith("arşiv katalog=Listing yeni=2 tekrar=48 geçersiz=0 ")
    assert two.lines[1].endswith(" tamam")
    assert two.lines[-1] == "arşiv: tamam"


def test_cross_catalog_duplicate_does_not_stop_early(two: Harness) -> None:
    """Plan Risk 7: bu çalıştırmada başka katalogdan yazılmış kimlik durma nedeni değildir."""
    two.run()
    shared = articles(8, 1, START + timedelta(days=3))
    only_b = articles(9, 60, START + timedelta(days=2))
    two.binance.publish(A, *shared)
    two.binance.publish(B, *shared, *only_b)
    assert two.run() is ArchiveOutcome.COMPLETE
    assert set(ids(only_b)) <= set(two.archived())
    assert two.pages_of(B) == [1, 2]
    assert two.archived().count(ids(shared)[0]) == 1
    assert [row["catalog_id"] for row in two.rows() if row["article_id"] == ids(shared)[0]] == [A]


def test_cross_catalog_id_from_earlier_run_does_not_stop_early(two: Harness) -> None:
    """Review round 1 M-1, plan A-3: önceki bir çalıştırmada başka katalogdan yazılmış kimlik tamam
    kataloğu erken durdurmaz; boşluk kalmaz."""
    two.run()
    only_b = articles(9, 60, START - timedelta(minutes=2))
    shared = articles(8, 1, START - timedelta(minutes=1))
    two.binance.publish(B, *only_b)
    two.binance.publish(A, *shared)
    two.binance.publish(B, *shared)
    two.hook = lambda index, url: Fetched(error="http_503") if index == 2 else None  # B p1
    assert two.run() is ArchiveOutcome.FAILED  # A wrote the shared id, B never saw it
    assert ids(shared)[0] in two.archived()
    two.hook = None
    assert two.run() is ArchiveOutcome.COMPLETE
    assert set(ids(only_b)) <= set(two.archived())
    assert two.pages_of(B) == [1, 2]
    assert two.lines[2].startswith("arşiv katalog=Delisting yeni=60 tekrar=")
    assert two.run() is ArchiveOutcome.COMPLETE  # B now stops at its own record
    assert two.pages_of(B) == [1]


def test_refresh_error_on_first_page_line_says_incomplete(two: Harness) -> None:
    """Review round 1 I-1: hatayla biten katalog satırı `eksik` yazar (son satırla tutarlı)."""
    two.run()
    two.hook = lambda index, url: Fetched(error="http_503") if index == 1 else None  # A p1
    assert two.run() is ArchiveOutcome.FAILED
    assert two.lines[-2:] == [
        "arşiv katalog=Listing yeni=0 tekrar=0 geçersiz=0 en_eski=yok eksik hata=http_503",
        "arşiv: eksik (2 katalog)",
    ]


def test_refresh_stopped_line_says_incomplete(two: Harness) -> None:
    """Review round 2 L-1: durdurmayla biten katalog satırı da `eksik` yazar."""
    two.run()
    two.hook = lambda index, url: setattr(two, "stop", True) if index == 1 else None  # A p1
    assert two.run() is ArchiveOutcome.STOPPED
    assert two.lines[-2:] == [
        "arşiv katalog=Listing yeni=0 tekrar=0 geçersiz=0 en_eski=yok eksik",
        "arşiv: eksik (2 katalog)",
    ]
    assert two.state(A)[1] is True  # the stored state is untouched: the next run refreshes


def test_invalid_article_on_full_page_does_not_end_catalog(tmp_path: Path) -> None:
    """VERIFY F-1: sayfa boyu geçersiz duyurularla sayılır; dolu sayfadaki tek geçersiz duyuru
    kataloğu erken bitirmez (eski duyurular kaybolmaz)."""
    raws = articles(1, 120)
    raws[10] = dict(raws[10], title="")
    harness = Harness(tmp_path, Binance({A: ("Listing", raws)}))
    assert harness.run() is ArchiveOutcome.COMPLETE
    assert harness.pages_of(A) == [1, 2, 3]
    assert len(harness.archived()) == 119
    assert harness.lines[1].startswith("arşiv katalog=Listing yeni=119 tekrar=0 geçersiz=1 ")


def test_interrupted_refresh_resumes_to_the_end(two: Harness) -> None:
    """Plan A-1: tamam katalogun yeniden okuması yarıda kalırsa katalog eksik olur ve sonraki
    çalıştırma o sayfadan sona kadar okur; yeni duyuru kaybolmaz."""
    two.run()
    new = articles(4, 60, START + timedelta(days=1))
    two.binance.publish(A, *new)
    two.hook = lambda index, url: Fetched(error="http_503") if index == 2 else None
    assert two.run() is ArchiveOutcome.FAILED  # A p1 (50 new) written, A p2 fails
    assert two.state(A) == (2, False, "http_503")
    assert two.lines[-2].startswith("arşiv katalog=Listing yeni=50 ")
    assert two.lines[-2].endswith(" eksik hata=http_503")
    two.binance.publish(A, *articles(3, 55, START + timedelta(days=2)))  # shifts page 2 again
    two.hook = None
    assert two.run() is ArchiveOutcome.COMPLETE
    assert two.pages_of(A) == [2, 3, 4, 5]  # to the end, no early stop
    assert set(ids(new)) <= set(two.archived())
    assert two.state(A) == (1, True, None)


def test_request_gap_and_single_flight(two: Harness) -> None:
    """AC-5: bir yanıtın bitişinden sonrakinin başlangıcına en az `archive_request_gap_s`."""
    two.gap = 3
    assert two.run() is ArchiveOutcome.COMPLETE
    assert len(two.spans) == 6
    for (_, end), (start, _) in zip(two.spans, two.spans[1:], strict=False):
        assert start - end >= 3
    assert two.waits == [3] * 5


def test_slow_response_needs_no_extra_wait(two: Harness) -> None:
    def slow(index: int, url: str) -> Fetched | None:
        two.mono += 0.5
        return None

    two.hook = slow
    two.run()
    assert two.waits == [1] * 5  # the gap runs from the end of the response


@pytest.mark.parametrize(
    "failure",
    [
        Fetched(error="network_error"),
        Fetched(error="timeout"),
        Fetched(error="http_500"),
        Fetched(error="http_429"),
        Fetched(body=b'{"data": {"catalogs": [{"catalogId": 1}]}}'),
        Fetched(body=b"{"),
    ],
)
def test_error_names_exit_1_no_retry(two: Harness, failure: Fetched) -> None:
    """AC-5: hata adını veren satır, sonuç hata (çıkış 1), aynı istek yinelenmez, sonraki
    kataloğa geçilmez."""
    two.hook = lambda index, url: failure if index == 2 else None
    assert two.run() is ArchiveOutcome.FAILED
    name = failure.error or ("bad_schema" if failure.body != b"{" else "bad_json")
    assert two.lines[-2].endswith(f" hata={name}")
    assert len(two.requests) == 3 and len(set(two.requests)) == 3
    assert two.pages_of(B) == []
    assert two.lines[-1] == "arşiv: eksik (2 katalog)"


def test_wrong_catalog_in_page_is_bad_schema(two: Harness) -> None:
    other = two.binance.body(page_url(BASE, B, 1, PAGE_SIZE))
    two.hook = lambda index, url: Fetched(body=other) if index == 1 else None
    assert two.run() is ArchiveOutcome.FAILED
    assert two.lines[-2].endswith(" hata=bad_schema")
    assert two.archived() == []


@pytest.mark.parametrize(
    ("failure", "line"),
    [
        (Fetched(error="http_429"), "arşiv keşif hata=http_429"),
        (Fetched(body=b'{"data": {"catalogs": []}}'), "arşiv keşif hata=bad_schema"),
    ],
)
def test_discovery_error(two: Harness, failure: Fetched, line: str) -> None:
    two.hook = lambda index, url: failure
    assert two.run() is ArchiveOutcome.FAILED
    assert two.lines == [line, "arşiv: eksik (keşif)"]
    assert len(two.requests) == 1


def test_no_telegram() -> None:
    """AC-5, G-8: arşivin etkileri arasında bildirim yok (giriş: test_news_archive_entry)."""
    names = {each.name for each in dataclasses.fields(ArchiveParts)}
    assert names == {"clock", "monotonic", "wait", "stopped", "fetch", "say"}


class Transport:
    """`fetch_source`'un gerçek kuralları: keşif geçerli, katalog sayfası senaryo."""

    def __init__(self, binance: Binance, scenario: Callable[[str], Hop]) -> None:
        self.binance = binance
        self.scenario = scenario
        self.urls: list[str] = []

    def __call__(self, url: str, _timeout: float) -> Hop:
        self.urls.append(url)
        if "catalogId" not in url:
            return hop(200, body=self.binance.body(url))
        return self.scenario(url)


def hop(
    status: int,
    *,
    body: bytes = b"",
    location: str | None = None,
    content_type: str = "application/json",
) -> Hop:
    data = [body]

    def read(_n: int) -> bytes:
        return data.pop(0) if data else b""

    return Hop(status, location, content_type, read)


@pytest.mark.parametrize(
    ("scenario", "name"),
    [
        (lambda url: hop(302, location="http://www.binance.com/x"), "redirect_http"),
        (lambda url: hop(302, location=f"{url}&again=1"), "too_many_redirects"),
        (lambda url: hop(200, body=b"x" * (2048 * 1024 + 1)), "too_large"),
        (lambda url: hop(200, body=b"{}", content_type="text/html"), "bad_type"),
        (lambda url: hop(200, body=b"<html>"), "bad_json"),
    ],
)
def test_transport_rules_are_source_errors(
    two: Harness, scenario: Callable[[str], Hop], name: str
) -> None:
    """AC-6: 0046 R-5'in kaynak kuralları aynı getiriciyle geçerlidir."""
    transport = Transport(two.binance, scenario)
    two.fetcher = lambda url, max_bytes: fetch_source(
        url, "binance-duyuru", max_bytes, transport=transport
    )
    assert two.run() is ArchiveOutcome.FAILED
    assert two.lines[-2].endswith(f" hata={name}")
    assert two.archived() == []


def test_article_links_never_fetched(two: Harness) -> None:
    """AC-6: duyuru bağlantılarına istek gitmez; her istek ayardaki uca."""
    two.run()
    assert all(url.split("?", 1)[0] == BASE for url in two.requests)
    assert not any("/support/announcement/" in url for url in two.requests)


def test_summary_lines_counts_oldest_complete(two: Harness) -> None:
    """AC-7: katalog başına doğru yeni/tekrar/geçersiz, en eski yayın anı, tamam/eksik."""
    name, raws = two.binance.catalogs[B]
    broken = [dict(raws[0], id=None), dict(raws[1], title=""), dict(raws[2], releaseDate=None)]
    duplicate_of_a = dict(two.binance.catalogs[A][1][0])
    two.binance.catalogs[B] = (name, [*broken, duplicate_of_a, *raws[3:10]])
    assert two.run() is ArchiveOutcome.COMPLETE
    oldest_a = (START - timedelta(hours=119)).isoformat()
    oldest_b = (START - timedelta(hours=9)).isoformat()
    assert two.lines == [
        "arşiv keşif katalog=2",
        f"arşiv katalog=Listing yeni=120 tekrar=0 geçersiz=0 en_eski={oldest_a} tamam",
        f"arşiv katalog=Delisting yeni=8 tekrar=1 geçersiz=2 en_eski={oldest_b} tamam",
        "arşiv: tamam",
    ]


def test_oldest_unknown_when_no_time(tmp_path: Path) -> None:
    raws = [dict(raw, releaseDate=None) for raw in articles(1, 2)]
    harness = Harness(tmp_path, Binance({A: ("Listing", raws)}))
    harness.run()
    assert harness.lines[1] == "arşiv katalog=Listing yeni=2 tekrar=0 geçersiz=0 en_eski=yok tamam"


def test_final_line_complete_or_incomplete(two: Harness) -> None:
    """AC-7: en sonda tüm arşivin tamam ya da eksik olduğu."""
    two.hook = lambda index, url: Fetched(error="http_500") if index == 5 else None  # B p2
    assert two.run() is ArchiveOutcome.FAILED
    assert two.lines[-1] == "arşiv: eksik (1 katalog)"
    two.hook = None
    assert two.run() is ArchiveOutcome.COMPLETE
    assert two.lines[-1] == "arşiv: tamam"


def test_no_secret_in_store_or_lines(two: Harness) -> None:
    """AC-7: sorgudaki sır hiçbir satıra ve kayda girmez (hata yolunda da)."""
    two.url = f"{BASE}?token=SECRET-TOKEN"
    two.hook = lambda index, url: Fetched(error="http_401") if index == 3 else None
    two.run()
    assert "SECRET-TOKEN" in two.requests[0]  # the owner's own address is used as given
    assert not any("SECRET" in line or "token" in line for line in two.lines)
    assert b"SECRET" not in two.store_path.read_bytes()
    assert not any(BASE in line for line in two.lines)


def test_recorded_fixture_catalog_end_to_end(tmp_path: Path) -> None:
    """Kayıtlı gerçek yanıtlar: keşif, 128'in 1. (50) ve 2. (3) sayfası; kısa sayfa sondur."""
    discovery = json.loads((FIXTURES / "discovery.json").read_bytes())
    only_128 = [each for each in discovery["data"]["catalogs"] if each["catalogId"] == C]
    discovery["data"]["catalogs"] = only_128
    bodies = {
        "disc": json.dumps(discovery).encode(),
        "1": (FIXTURES / "catalog_first.json").read_bytes(),
        "2": (FIXTURES / "catalog_last.json").read_bytes(),
    }
    harness = Harness(tmp_path, Binance({}))

    def recorded(url: str, _max_bytes: int) -> Fetched:
        query = dict(parse_qsl(urlsplit(url).query))
        return Fetched(body=bodies["disc" if "catalogId" not in query else query["pageNo"]])

    harness.fetcher = recorded
    assert harness.run() is ArchiveOutcome.COMPLETE
    assert len(harness.archived()) == 53
    assert harness.lines[1].startswith("arşiv katalog=Crypto Airdrop yeni=53 tekrar=0 geçersiz=0")
    assert harness.lines[1].endswith(" tamam")
