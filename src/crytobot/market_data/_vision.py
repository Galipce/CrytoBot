"""Binance'in herkese açık geçmiş veri arşivi: aylık 1h mum dosyaları (spec 0048 R-3, G-1; plan
Risk 7).

Adres `https://data.binance.vision/data/spot/monthly/klines/<SYM>/1h/<SYM>-1h-<YYYY-MM>.zip`. Yalnız
`https`; en çok 3 yönlendirme; yanıt en çok 8 MB; türü `application/zip` ya da
`application/octet-stream`; 404 "o ay yok"tur. İstek daemon iş parçacığında koşar, toplam süre
sınırlıdır (ad çözümleme dahil; conventions, spec 0039). Zip tek CSV taşır; satırlar başlıksız
Binance mum satırlarıdır. Açılış damgası 10^14'ten büyükse mikrosaniyedir (arşiv 2025'ten beri),
değilse milisaniye; saat başı olmayan damga, eksik alan, sayı olmayan fiyat ya da tutarsız mum biçim
hatasıdır (`VisionFormatError`). Hata yalnız adıyla döner; istisna metni satıra girmez.
"""

import csv
import http.client
import io
import ssl
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from typing import Final
from urllib.parse import urljoin, urlsplit

from crytobot.market_data._numbers import exact_decimal
from crytobot.market_data._price_store import StoredCandle
from crytobot.market_data._types import MarketDataError

BASE_URL: Final = "https://data.binance.vision/data/spot/monthly/klines"
USER_AGENT: Final = "Mozilla/5.0 (compatible; price-fetch/1.0)"
MAX_BYTES: Final = 8 * 1024 * 1024
MAX_REDIRECTS: Final = 3
HOUR_MS: Final = 3_600_000
MICROSECONDS_ABOVE: Final = 10**14
_CHUNK: Final = 64 * 1024
_PIECE_S: Final = 1.0
_REDIRECTS: Final = frozenset({301, 302, 303, 307, 308})
_TYPES: Final = ("application/zip", "application/octet-stream")


class VisionFormatError(MarketDataError):
    """Arşiv dosyası beklenen biçimde değil."""


@dataclass(frozen=True)
class VisionHop:
    """Tek HTTP yanıtı: durum, `Location`, `Content-Type`, gövde okuyucu."""

    status: int
    location: str | None
    content_type: str | None
    read: Callable[[int], bytes]
    close: Callable[[], None] = lambda: None


VisionTransport = Callable[[str, float], VisionHop]


@dataclass(frozen=True)
class VisionFetched:
    """`body` (zip), `missing` (404: o ay yok) ya da `error` (hata adı)."""

    body: bytes | None = None
    missing: bool = False
    error: str | None = None


def month_url(symbol: str, year: int, month: int) -> str:
    stem = f"{symbol}-1h-{year:04d}-{month:02d}"
    return f"{BASE_URL}/{symbol}/1h/{stem}.zip"


def https_transport(url: str, timeout: float) -> VisionHop:
    parts = urlsplit(url)
    connection = http.client.HTTPSConnection(
        parts.hostname or "",
        parts.port or 443,
        timeout=timeout,
        context=ssl.create_default_context(),
    )
    connection.request(
        "GET",
        parts.path or "/",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/zip, application/octet-stream",
            "Accept-Encoding": "identity",
            "Connection": "close",
        },
    )
    response = connection.getresponse()
    return VisionHop(
        response.status,
        response.getheader("Location"),
        response.getheader("Content-Type"),
        response.read,
        connection.close,
    )


def _read_body(hop: VisionHop, max_bytes: int) -> VisionFetched:
    chunks: list[bytes] = []
    size = 0
    while size <= max_bytes:
        chunk = hop.read(min(_CHUNK, max_bytes + 1 - size))
        if not chunk:
            return VisionFetched(body=b"".join(chunks))
        chunks.append(chunk)
        size += len(chunk)
    return VisionFetched(error="too_large")


def _follow(url: str, transport: VisionTransport, remaining: Callable[[], float]) -> VisionFetched:
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if urlsplit(current).scheme != "https":
            return VisionFetched(error="redirect_http")
        hop = transport(current, max(remaining(), 0.001))
        try:
            if hop.status in _REDIRECTS and hop.location:
                current = urljoin(current, hop.location)
                continue
            if hop.status == 404:
                return VisionFetched(missing=True)
            if hop.status != 200:
                return VisionFetched(error=f"http_{hop.status}")
            media = (hop.content_type or "").split(";", 1)[0].strip().lower()
            if media not in _TYPES:
                return VisionFetched(error="bad_type")
            return _read_body(hop, MAX_BYTES)
        finally:
            hop.close()
    return VisionFetched(error="too_many_redirects")


def _attempt(url: str, transport: VisionTransport, remaining: Callable[[], float]) -> VisionFetched:
    try:
        return _follow(url, transport, remaining)
    except TimeoutError:
        return VisionFetched(error="timeout")
    except (OSError, http.client.HTTPException, ValueError):
        return VisionFetched(error="network_error")


def fetch_month(
    url: str,
    *,
    transport: VisionTransport = https_transport,
    budget_s: float = 30.0,
    monotonic: Callable[[], float] = time.monotonic,
    stopped: Callable[[], bool] = lambda: False,
) -> VisionFetched:
    """Aylık dosyanın gövdesi; en çok `budget_s` saniye. Durdurma isteğinde terk edilir
    (`error="stopped"`)."""
    deadline = monotonic() + budget_s
    result: list[VisionFetched] = []
    done = threading.Event()

    def remaining() -> float:
        return deadline - monotonic()

    def work() -> None:
        try:
            result.append(_attempt(url, transport, remaining))
        except Exception:  # never a traceback on stderr
            result.append(VisionFetched(error="network_error"))
        finally:
            done.set()

    threading.Thread(target=work, name="price-vision", daemon=True).start()
    while not done.is_set():
        if stopped():
            return VisionFetched(error="stopped")
        left = remaining()
        if left <= 0:
            return VisionFetched(error="timeout")
        done.wait(min(_PIECE_S, left))
    return result[0]


def _price(text: str) -> str:
    if exact_decimal(text) is None:
        raise VisionFormatError("fiyat sayı değil")
    return text


def _candle(row: list[str]) -> StoredCandle:
    if len(row) < 6:
        raise VisionFormatError("eksik alan")
    raw = row[0].strip()
    if not raw.isdigit():
        raise VisionFormatError("açılış damgası sayı değil")
    stamp = int(raw)
    if stamp > MICROSECONDS_ABOVE:
        if stamp % 1000:
            raise VisionFormatError("açılış damgası saat başı değil")
        stamp //= 1000
    if stamp % HOUR_MS:
        raise VisionFormatError("açılış damgası saat başı değil")
    open_, high, low, close = (_price(value.strip()) for value in row[1:5])
    numbers = [exact_decimal(value) for value in (open_, high, low, close)]
    o, h, lo, c = (value for value in numbers if value is not None)
    if not (0 < lo <= min(o, c) and max(o, c) <= h):
        raise VisionFormatError("tutarsız mum")
    return StoredCandle(stamp, open_, high, low, close)


def parse_month(body: bytes) -> list[StoredCandle]:
    """Zip'teki tek CSV'nin mumları, açılış sırasıyla."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
        names = archive.namelist()
        if len(names) != 1 or not names[0].lower().endswith(".csv"):
            raise VisionFormatError("zip tek CSV taşımıyor")
        text = archive.read(names[0]).decode("utf-8")
    except (zipfile.BadZipFile, UnicodeDecodeError, OSError, RuntimeError, ValueError):
        raise VisionFormatError("zip okunamıyor") from None
    candles = [_candle(row) for row in csv.reader(io.StringIO(text)) if row]
    opens = [candle.open_ms for candle in candles]
    if any(later <= earlier for earlier, later in pairwise(opens)):
        raise VisionFormatError("açılışlar artmıyor")
    return candles
