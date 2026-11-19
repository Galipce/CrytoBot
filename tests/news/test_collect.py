"""Spec 0046 toplama turu ve döngüsü (AC-1, AC-3, AC-4, AC-5, AC-8).

Gerçek ayrıştırma, gerçek depo (geçici dizinde SQLite); yalnız saat, bekleme, getirme ve bildirim
sahtedir. Kaynak yanıtları kayıtlı örneklerdir (`fixtures/`), ağ yok.
"""

import json
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from crytobot.news import (
    POSSIBLE_MISS,
    CollectionExit,
    CollectParts,
    Fetched,
    NewsConfig,
    NewsSource,
    NewsStore,
    load_news_config,
    run_collection,
    run_round,
)
from tests.news.test_source_permission import PERMISSION

FIXTURES = Path(__file__).parent / "fixtures"
START = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)
SECRET_URL = "https://feed.example.org/rss?token=SUPERSECRET123"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def source_table(name: str, kind: str = "rss", **extra: object) -> dict[str, object]:
    return {
        "name": name,
        "type": kind,
        "url": f"https://{name}.example.org/feed",
        **PERMISSION,
        **extra,
    }


def make_config(root: Path, *sources: dict[str, object], **settings: object) -> NewsConfig:
    table: dict[str, object] = {
        "store_path": str(root / "news.db"),
        "log_path": str(root / "news.log"),
        "sources": list(sources)
        or [
            source_table("binance", "binance-duyuru"),
            source_table("coindesk"),
            source_table("atom"),
        ],
        **settings,
    }
    result = load_news_config({"news": table})
    assert result.config is not None, result.message
    return result.config


BODIES = {"binance": "binance.json", "coindesk": "coindesk.xml", "atom": "atom.xml"}


@dataclass
class Clock:
    now: datetime = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@dataclass
class Harness:
    """Sahte etkiler: `responses[ad]` bir `Fetched` ya da onu üreten işlev."""

    root: Path
    config: NewsConfig
    clock: Clock = field(default_factory=Clock)
    responses: dict[str, Fetched | Callable[[], Fetched]] = field(default_factory=dict)
    fetched: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    waits: list[float] = field(default_factory=list)
    stop_after_waits: int | None = 0
    telegram: bool = True
    requested: bool = False
    fetch_seconds: float = 2.0

    def fetch(self, source: NewsSource, max_bytes: int) -> Fetched:
        self.fetched.append(source.url)
        assert max_bytes == self.config.max_response_kb * 1024
        self.clock.advance(self.fetch_seconds)
        response = self.responses.get(source.name)
        if response is None:
            return Fetched(body=fixture(BODIES[source.name]))
        return response() if callable(response) else response

    def wait(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.clock.advance(seconds)
        if self.stop_after_waits is not None and len(self.waits) > self.stop_after_waits:
            self.requested = True

    def parts(self) -> CollectParts:
        return CollectParts(
            self.clock,
            self.wait,
            lambda: self.requested,
            self.fetch,
            self.lines.append,
            self.notices.append if self.telegram else None,
        )

    def store(self) -> Iterator[NewsStore]:
        store = NewsStore.open(self.config.store_path)
        try:
            yield store
        finally:
            store.close()

    def round(self) -> bool:
        for store in self.store():
            return run_round(self.config, store, self.parts())
        raise AssertionError

    def collect(self) -> CollectionExit:
        for store in self.store():
            return run_collection(self.config, store, self.parts())
        raise AssertionError

    def rows(self, where: str = "1") -> list[dict[str, Any]]:
        with sqlite3.connect(self.config.store_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(f"SELECT * FROM news WHERE {where} ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def summary(self, name: str) -> str:
        found = [row for row in self.lines if row.startswith(f"kaynak={name} ")]
        return found[-1]


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path, make_config(tmp_path))


def test_three_sources_one_round_all_fields(harness: Harness) -> None:
    """AC-1: üç tür tek turda; her kayıtta bütün alanlar, HTML olduğu gibi, UTC anlar."""
    assert harness.round()
    rows = harness.rows()
    assert {row["source"] for row in rows} == {"binance", "coindesk", "atom"}
    binance = harness.rows("source = 'binance'")[0]
    assert binance["key"] == "id:289917"
    assert binance["title"].startswith("Binance Futures Will Launch")
    assert binance["link"] == (
        "https://www.binance.com/en/support/announcement/e7a88ff576b541608d0845f3b666ec66"
    )
    assert binance["published_at"] == "2026-11-11T09:45:18.328000+00:00"  # 1794390318328 ms
    assert binance["first_seen_at"] == (START + timedelta(seconds=2)).isoformat()
    coindesk = harness.rows("source = 'coindesk'")[0]
    assert coindesk["key"] == "id:8dd3e265-033e-4c68-84a6-9f4605bdb788"
    assert coindesk["body"].startswith("XRP tanked")
    assert coindesk["published_at"] == "2026-11-15T02:50:57+00:00"
    atom = harness.rows("source = 'atom'")[0]
    assert atom["key"] == "id:urn:uuid:1225c695-cfb8-4ebb-aaaa-80da344efa6a"
    assert atom["link"] == "https://example.org/haber/ethereum-yukseltme"
    assert atom["body"] == "<p>Geliştiriciler <b>yükseltme</b> tarihini duyurdu.</p>"
    assert atom["published_at"] == "2026-11-15T05:30:00+00:00"
    assert atom["first_seen_at"] == (START + timedelta(seconds=6)).isoformat()
    for row in rows:
        assert row["title"] and row["link"] and row["first_seen_at"].endswith("+00:00")


def test_disabled_source_not_queried(tmp_path: Path) -> None:
    harness = Harness(
        tmp_path,
        make_config(tmp_path, source_table("coindesk"), source_table("atom", enabled=False)),
    )
    assert harness.round()
    assert harness.fetched == ["https://coindesk.example.org/feed"]
    assert not any(row.startswith("kaynak=atom") for row in harness.lines)
    for store in harness.store():
        assert store.state("atom").last_error is None


def test_summary_counts_new_duplicate_invalid(harness: Harness) -> None:
    """AC-1: geçersiz (boş başlık + metin, anahtarsız) sayılır, yazılmaz; aynı yanıtta iki kez
    gelen anahtar ikinci kez tekrardır."""
    feed = (
        b'<?xml version="1.0"?><rss version="2.0"><channel>'
        b"<item><guid>a</guid><title>A</title></item>"
        b"<item><guid>a</guid><title>A again</title></item>"
        b"<item><guid>b</guid><title> </title><description>  </description></item>"
        b"<item><title>no key</title></item>"
        b"<item><link>https://example.org/c</link><title>C</title></item>"
        b"</channel></rss>"
    )
    harness.responses["coindesk"] = Fetched(body=feed)
    assert harness.round()
    assert harness.summary("coindesk") == "kaynak=coindesk yeni=2 tekrar=1 geçersiz=2"
    binance = f"kaynak=binance yeni=6 tekrar=0 geçersiz=0 {POSSIBLE_MISS}"
    assert harness.summary("binance") == binance
    assert harness.summary("atom") == "kaynak=atom yeni=2 tekrar=0 geçersiz=0"
    assert [row["key"] for row in harness.rows("source = 'coindesk'")] == [
        "id:a",
        "link:https://example.org/c",
    ]
    assert harness.rows("key = 'id:a'")[0]["title"] == "A"


def _binance(*ids: int) -> Fetched:
    articles = [
        {"id": each, "code": f"c{each}", "title": f"t{each}", "type": 1, "releaseDate": 0}
        for each in ids
    ]
    body = {"code": "000000", "data": {"catalogs": [{"catalogId": 1, "articles": articles}]}}
    return Fetched(body=json.dumps(body).encode())


def test_possible_miss_only_when_whole_page_new(tmp_path: Path) -> None:
    """AC-1 (G-3): bütün öğeler yeniyse uyarı; en az biri önceden kayıtlıysa yok. RSS'te yok."""
    harness = Harness(tmp_path, make_config(tmp_path, source_table("binance", "binance-duyuru")))
    harness.responses["binance"] = _binance(1, 2)
    harness.round()
    assert harness.summary("binance").endswith(POSSIBLE_MISS)
    harness.responses["binance"] = _binance(3, 4, 2)
    harness.round()
    assert harness.summary("binance") == "kaynak=binance yeni=2 tekrar=1 geçersiz=0"
    harness.responses["binance"] = _binance(5, 5)  # a repeat within the page is not a stored one
    harness.round()
    assert harness.summary("binance").endswith(POSSIBLE_MISS)

    rss = Harness(tmp_path / "rss", make_config(tmp_path, source_table("coindesk")))
    rss.round()
    assert POSSIBLE_MISS not in rss.summary("coindesk")


def test_first_seen_is_response_time(harness: Harness) -> None:
    """AC-3 (G-2): ilk görme anı turun başı değil, o kaynağın yanıtının alındığı an; yayın anı
    bilinmeyen kayıtta da öyle."""
    harness.fetch_seconds = 7.0
    harness.responses["coindesk"] = Fetched(
        body=b'<rss version="2.0"><channel><item><guid>x</guid><title>T</title>'
        b"<pubDate>tomorrow</pubDate></item></channel></rss>"
    )
    harness.round()
    seen = {row["source"]: row["first_seen_at"] for row in harness.rows()}
    assert seen == {
        "binance": (START + timedelta(seconds=7)).isoformat(),
        "coindesk": (START + timedelta(seconds=14)).isoformat(),
        "atom": (START + timedelta(seconds=21)).isoformat(),
    }
    assert harness.rows("source = 'coindesk'")[0]["published_at"] is None


@pytest.mark.parametrize(
    "fetched",
    [
        Fetched(error="too_large"),
        Fetched(error="bad_type"),
        Fetched(error="redirect_http"),
        Fetched(error="too_many_redirects"),
        Fetched(body=b"<rss><channel><item><title>A</title></item>"),  # bad_xml
        Fetched(body=b'<!DOCTYPE r [<!ENTITY e "x">]><rss><channel/></rss>'),  # xml_entity
    ],
)
def test_source_error_writes_nothing(harness: Harness, fetched: Fetched) -> None:
    """AC-4: kaynak hatasında o kaynaktan o tur hiçbir kayıt yazılmaz; diğerleri yazılır."""
    harness.responses["coindesk"] = fetched
    harness.round()
    assert harness.rows("source = 'coindesk'") == []
    assert harness.summary("coindesk").startswith("kaynak=coindesk hata=")
    assert harness.rows("source = 'atom'") != []


def test_item_links_never_fetched(harness: Harness) -> None:
    """AC-4: yalnız kaynak adreslerine istek gider; haber bağlantıları indirilmez."""
    harness.round()
    harness.round()
    assert set(harness.fetched) == {source.url for source in harness.config.sources}
    assert len(harness.fetched) == 6


def test_failing_source_isolated_and_retried(harness: Harness) -> None:
    """AC-5: ağ hatası, zaman aşımı, HTTP hatası yalnız o kaynağı etkiler; sonraki turda yeniden
    denenir."""
    for error in ("network_error", "timeout", "http_503"):
        harness.responses["binance"] = Fetched(error=error)
        harness.round()
        assert harness.summary("binance") == f"kaynak=binance hata={error}"
        assert harness.summary("atom").startswith("kaynak=atom yeni=")
    del harness.responses["binance"]
    harness.round()
    assert harness.summary("binance").startswith("kaynak=binance yeni=6")
    assert harness.fetched.count("https://binance.example.org/feed") == 4


def test_error_name_and_time_recorded(harness: Harness) -> None:
    harness.responses["atom"] = Fetched(error="timeout")
    harness.round()
    for store in harness.store():
        state = store.state("atom")
        assert state.last_error == "timeout"
        assert state.last_error_at == START + timedelta(seconds=6)
        assert state.last_success_at is None
        assert store.state("coindesk").last_success_at == START + timedelta(seconds=4)


def test_no_secret_in_store_or_lines(tmp_path: Path) -> None:
    """AC-5: sorgu dizgesindeki sır ne kayda ne satırlara girer (hata yalnız adıyla)."""
    config = make_config(
        tmp_path, {"name": "gizli", "type": "rss", "url": SECRET_URL, **PERMISSION}
    )
    harness = Harness(tmp_path, config)
    harness.responses["gizli"] = Fetched(error="http_401")
    harness.collect()
    harness.responses["gizli"] = Fetched(body=fixture("coindesk.xml"))
    harness.requested = False
    harness.collect()
    assert all("SUPERSECRET" not in row and "token" not in row for row in harness.lines)
    assert b"SUPERSECRET" not in Path(config.store_path).read_bytes()


def test_interval_rounds(tmp_path: Path) -> None:
    """AC-8: turlar `interval_minutes` aralıkla başlar; bekleme turun süresini düşer."""
    harness = Harness(tmp_path, make_config(tmp_path, interval_minutes=5))
    harness.stop_after_waits = 2
    assert harness.collect() is CollectionExit.STOPPED
    assert harness.waits == [300 - 6] * 3
    assert harness.lines[0] == "başladı: kaynak=3/3 aralık=5dk kayıt=" + str(tmp_path / "news.db")
    assert harness.lines[-1] == "durdu: durdurma isteği tur_sayısı=3"
    assert sum(row.startswith("kaynak=atom ") for row in harness.lines) == 3


def test_stop_mid_round_no_partial_record(harness: Harness) -> None:
    """AC-8: durdurma turun ortasında gelirse terk edilen kaynak yazılmaz; yazılan kaynaklar tam."""

    def stop_now() -> Fetched:
        harness.requested = True
        return Fetched(abandoned=True)

    harness.responses["coindesk"] = stop_now
    assert harness.collect() is CollectionExit.STOPPED
    assert {row["source"] for row in harness.rows()} == {"binance"}
    assert len(harness.rows("source = 'binance'")) == 6
    assert "https://atom.example.org/feed" not in harness.fetched
    assert harness.lines[-1] == "durdu: durdurma isteği tur_sayısı=0"
    for store in harness.store():
        assert store.state("coindesk").last_success_at is None


class Forced(BaseException):
    """İkinci Ctrl+C'nin (`ForcedStop`) yerine: `except Exception` onu yutmaz."""


def test_forced_stop_rolls_back(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-8: zorla durdurma kaynağın yazımının ortasında gelirse işlem geri alınır."""
    original = NewsStore._insert
    calls = {"n": 0}

    def insert(self: NewsStore, source: str, item: object) -> bool:
        calls["n"] += 1
        if calls["n"] == 3:
            raise Forced
        return original(self, source, item)  # type: ignore[arg-type]

    monkeypatch.setattr(NewsStore, "_insert", insert)
    with pytest.raises(Forced):
        harness.round()
    monkeypatch.undo()
    assert harness.rows() == []
    for store in harness.store():
        assert store.state("binance").last_success_at is None
    assert harness.round()  # the store is not left locked or half-open
    assert len(harness.rows("source = 'binance'")) == 6


def test_store_failure_stops_with_line(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_args: object) -> bool:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(NewsStore, "_insert", broken)
    assert harness.collect() is CollectionExit.STORE_FAILED
    assert harness.lines[-1] == "durdu: haber kaydı yazılamıyor tur_sayısı=0"
