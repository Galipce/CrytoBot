"""Spec 0046 getirme: yönlendirme, `http` düşüşü, boyut, tür, HTTP hataları (AC-4), takılan ad
çözümleme bütçeyle sınırlı (AC-5). Sahte transport; ağ yok."""

import itertools
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from crytobot.news import Fetched, Hop, fetch_source
from crytobot.news._fetch import https_transport

URL = "https://feed.example.org/rss?token=SECRET"
KB = 1024


def body_reader(data: bytes) -> Callable[[int], bytes]:
    position = [0]

    def read(size: int) -> bytes:
        chunk = data[position[0] : position[0] + size]
        position[0] += len(chunk)
        return chunk

    return read


@dataclass
class Fake:
    """URL → yanıt; her isteği kaydeder."""

    hops: dict[str, Hop] = field(default_factory=dict)
    requested: list[str] = field(default_factory=list)
    closed: int = 0

    def __call__(self, url: str, timeout: float) -> Hop:
        self.requested.append(url)
        hop = self.hops[url]
        return Hop(hop.status, hop.location, hop.content_type, hop.read, self._close)

    def _close(self) -> None:
        self.closed += 1


def ok(data: bytes = b"<rss/>", content_type: str | None = "application/rss+xml") -> Hop:
    return Hop(200, None, content_type, body_reader(data))


def moved(location: str, status: int = 301) -> Hop:
    return Hop(status, location, "text/plain", body_reader(b""))


def fetch(fake: Fake, kind: str = "rss", max_bytes: int = 4 * KB) -> Fetched:
    return fetch_source(URL, kind, max_bytes, transport=fake)


def test_body_returned() -> None:
    fake = Fake({URL: ok(b"<rss>x</rss>")})
    assert fetch(fake) == Fetched(body=b"<rss>x</rss>")
    assert fake.closed == 1


def test_size_type_redirect_errors() -> None:
    """AC-4: sınır, tür, yönlendirme kuralları; bağlantılar izlenmez (tek URL zinciri)."""
    exact = Fake({URL: ok(b"a" * 4 * KB)})
    assert fetch(exact).body == b"a" * 4 * KB
    assert fetch(Fake({URL: ok(b"a" * (4 * KB + 1))})).error == "too_large"
    assert fetch(Fake({URL: ok(content_type=None)})).error == "bad_type"
    assert fetch(Fake({URL: ok(content_type="text/html; charset=utf-8")})).error == "bad_type"
    assert fetch(Fake({URL: ok(content_type="application/xml")}), "binance-duyuru").error == (
        "bad_type"
    )
    assert fetch(Fake({URL: ok(b"{}", "application/json;charset=UTF-8")}), "binance-duyuru") == (
        Fetched(body=b"{}")
    )
    for content_type in ("text/xml", "application/atom+xml", "Application/XML; charset=utf-8"):
        assert fetch(Fake({URL: ok(content_type=content_type)})).body == b"<rss/>"

    assert fetch(Fake({URL: moved("http://feed.example.org/rss")})).error == "redirect_http"
    chain = Fake(
        {
            URL: moved("/a", 308),  # relative Location (CoinDesk)
            "https://feed.example.org/a": moved("https://other.example.org/b", 302),
            "https://other.example.org/b": moved("https://other.example.org/c", 307),
            "https://other.example.org/c": ok(),
        }
    )
    assert fetch(chain).body == b"<rss/>"
    assert len(chain.requested) == 4
    assert chain.closed == 4
    four = Fake(
        {
            URL: moved("https://x.example.org/1"),
            "https://x.example.org/1": moved("https://x.example.org/2"),
            "https://x.example.org/2": moved("https://x.example.org/3"),
            "https://x.example.org/3": moved("https://x.example.org/4"),
            "https://x.example.org/4": ok(),
        }
    )
    assert fetch(four).error == "too_many_redirects"
    assert "https://x.example.org/4" not in four.requested


@pytest.mark.parametrize(
    ("hop", "error"),
    [
        (Hop(404, None, "text/html", body_reader(b"")), "http_404"),
        (Hop(503, None, "text/html", body_reader(b"")), "http_503"),
        (Hop(301, None, "text/html", body_reader(b"")), "http_301"),  # no Location
    ],
)
def test_http_errors_named(hop: Hop, error: str) -> None:
    assert fetch(Fake({URL: hop})).error == error


@pytest.mark.parametrize(
    ("raised", "error"),
    [
        (TimeoutError("read timed out " + URL), "timeout"),
        (TimeoutError(), "timeout"),
        (ConnectionResetError("reset " + URL), "network_error"),
        (socket.gaierror("name or service not known"), "network_error"),
        (RuntimeError("unexpected " + URL), "network_error"),
    ],
)
def test_transport_errors_named_without_text(raised: Exception, error: str) -> None:
    def transport(_url: str, _timeout: float) -> Hop:
        raise raised

    assert fetch_source(URL, "rss", KB, transport=transport) == Fetched(error=error)


def test_hanging_resolution_bounded_by_budget() -> None:
    """AC-5: takılan ad çözümleme (transport hiç dönmez) bütçeyle biter; süre enjekte saatle
    sınanır, gerçek saat yalnız üst sınır (conventions, spec 0039 F-5)."""
    entered = threading.Event()
    never = threading.Event()

    def hanging(_url: str, _timeout: float) -> Hop:
        entered.set()
        never.wait()
        raise AssertionError

    ticks = itertools.count(0.0, 15.0)  # each look at the clock is 15 s later

    started = time.monotonic()
    result = fetch_source(
        URL, "rss", KB, transport=hanging, budget_s=30.0, monotonic=lambda: next(ticks)
    )
    assert result == Fetched(error="timeout")
    assert entered.is_set()
    assert time.monotonic() - started < 5  # waits in pieces of at most 1 s of real time
    never.set()


def test_hanging_request_real_budget_upper_bound() -> None:
    never = threading.Event()

    def hanging(_url: str, _timeout: float) -> Hop:
        never.wait()
        raise AssertionError

    started = time.monotonic()
    assert fetch_source(URL, "rss", KB, transport=hanging, budget_s=0.3) == Fetched(error="timeout")
    assert time.monotonic() - started < 1.5
    never.set()


def test_stop_abandons_request() -> None:
    never = threading.Event()

    def hanging(_url: str, _timeout: float) -> Hop:
        never.wait()
        raise AssertionError

    calls = {"n": 0}

    def stopped() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    result = fetch_source(URL, "rss", KB, transport=hanging, stopped=stopped, budget_s=30.0)
    assert result == Fetched(abandoned=True)
    never.set()


def test_timeout_passed_is_remaining_budget() -> None:
    """Her yönlendirme adımı bütçenin kalanını alır: zincir toplamda 30 s'yi aşamaz."""
    seen: list[float] = []
    now = [100.0]

    def transport(url: str, timeout: float) -> Hop:
        seen.append(timeout)
        now[0] += 6.0  # the clock moves only while a hop is in flight
        return ok() if url.endswith("/b") else moved("/b")

    result = fetch_source(
        URL, "rss", KB, transport=transport, budget_s=30.0, monotonic=lambda: now[0]
    )
    assert result.body == b"<rss/>"
    assert seen == [30.0, 24.0]


@pytest.mark.filterwarnings("ignore:A test tried to use socket:UserWarning")
def test_real_transport_blocked_in_tests() -> None:
    """Testler ağa çıkamaz: gerçek transport da engellenir, hata adı `network_error`."""
    result = fetch_source(URL, "rss", KB, transport=https_transport, budget_s=5.0)
    assert result == Fetched(error="network_error")
