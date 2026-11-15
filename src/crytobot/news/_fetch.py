"""Tek kaynak isteği (spec 0046 R-5, R-6; plan Risk 5, 6, 11, 12, 14).

Yalnız `https`; en çok 3 yönlendirme, `http`'ye düşen yönlendirme `redirect_http`, fazlası
`too_many_redirects`. Yanıt en çok `max_bytes` bayt (`Content-Length` beklenmez; bir bayt fazlası
okununca `too_large`), türü kaynağın türüne uymalı (`bad_type`). İstek daemon iş parçacığında koşar:
`urlopen`/soket süresi ad çözümlemeyi kapsamaz (conventions, spec 0039), bütçe toplamdır ve ≤1 s'lik
parçalarla beklenir; durdurma isteğinde istek terk edilir. Hata yalnız adıyla döner: URL ve istisna
metni hiçbir satıra ve kayda girmez (sorgu dizgesindeki sır).
"""

import http.client
import ssl
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

USER_AGENT = "Mozilla/5.0 (compatible; news-collector/1.0)"
BUDGET_S = 30.0
MAX_REDIRECTS = 3
_PIECE_S = 1.0
_CHUNK = 64 * 1024
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_EXPECTED = {"rss": ("xml",), "binance-duyuru": ("application/json",)}


@dataclass(frozen=True)
class Fetched:
    """Bir kaynağın yanıtı: `body` ya da `error` (hata adı). `abandoned`: durdurma isteğiyle
    terk edildi (kaynak yazılmaz)."""

    body: bytes | None = None
    error: str | None = None
    abandoned: bool = False


@dataclass(frozen=True)
class Hop:
    """Tek HTTP yanıtı: durum, `Location`, `Content-Type`, gövde okuyucu (en çok n bayt; boş bayt
    gövdenin sonu)."""

    status: int
    location: str | None
    content_type: str | None
    read: Callable[[int], bytes]
    close: Callable[[], None] = lambda: None


# (url, timeout_s) -> Hop; the real one opens one HTTPS connection per hop
Transport = Callable[[str, float], Hop]


def https_transport(url: str, timeout: float) -> Hop:
    parts = urlsplit(url)
    host = parts.hostname or ""
    connection = http.client.HTTPSConnection(
        host, parts.port or 443, timeout=timeout, context=ssl.create_default_context()
    )
    target = parts.path or "/"
    if parts.query:
        target = f"{target}?{parts.query}"
    connection.request(
        "GET",
        target,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, application/rss+xml, application/atom+xml, */*",
            "Accept-Encoding": "identity",
            "Connection": "close",
        },
    )
    response = connection.getresponse()
    return Hop(
        response.status,
        response.getheader("Location"),
        response.getheader("Content-Type"),
        response.read,
        connection.close,
    )


def _expected_type(kind: str, content_type: str | None) -> bool:
    if content_type is None:
        return False
    media = content_type.split(";", 1)[0].strip().lower()
    return any(word in media for word in _EXPECTED[kind])


def _read_body(hop: Hop, max_bytes: int) -> Fetched:
    chunks: list[bytes] = []
    size = 0
    while size <= max_bytes:
        chunk = hop.read(min(_CHUNK, max_bytes + 1 - size))
        if not chunk:
            return Fetched(body=b"".join(chunks))
        chunks.append(chunk)
        size += len(chunk)
    return Fetched(error="too_large")


def _follow(
    url: str,
    kind: str,
    max_bytes: int,
    transport: Transport,
    remaining: Callable[[], float],
) -> Fetched:
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if urlsplit(current).scheme != "https":
            return Fetched(error="redirect_http")
        hop = transport(current, max(remaining(), 0.001))
        try:
            if hop.status in _REDIRECTS and hop.location:
                current = urljoin(current, hop.location)
                continue
            if hop.status != 200:
                return Fetched(error=f"http_{hop.status}")
            if not _expected_type(kind, hop.content_type):
                return Fetched(error="bad_type")
            return _read_body(hop, max_bytes)
        finally:
            hop.close()
    return Fetched(error="too_many_redirects")


def _attempt(
    url: str, kind: str, max_bytes: int, transport: Transport, remaining: Callable[[], float]
) -> Fetched:
    try:
        return _follow(url, kind, max_bytes, transport, remaining)
    except TimeoutError:  # socket.timeout is TimeoutError
        return Fetched(error="timeout")
    except (OSError, http.client.HTTPException, ValueError):
        # ssl errors are OSError; ValueError: a malformed Location or port
        return Fetched(error="network_error")


def fetch_source(
    url: str,
    kind: str,
    max_bytes: int,
    *,
    stopped: Callable[[], bool] = lambda: False,
    transport: Transport = https_transport,
    budget_s: float = BUDGET_S,
    monotonic: Callable[[], float] = time.monotonic,
) -> Fetched:
    """Kaynağın gövdesi; en çok `budget_s` saniye (ad çözümleme dahil, AC-5)."""
    deadline = monotonic() + budget_s
    result: list[Fetched] = []
    done = threading.Event()

    def remaining() -> float:
        return deadline - monotonic()

    def work() -> None:
        try:
            result.append(_attempt(url, kind, max_bytes, transport, remaining))
        except Exception:  # never a traceback on stderr: it could carry the URL (plan Risk 12)
            result.append(Fetched(error="network_error"))
        finally:
            done.set()

    threading.Thread(target=work, name="news-fetch", daemon=True).start()
    while not done.is_set():
        if stopped():
            return Fetched(abandoned=True)
        left = remaining()
        if left <= 0:
            return Fetched(error="timeout")
        done.wait(min(_PIECE_S, left))
    return result[0]
