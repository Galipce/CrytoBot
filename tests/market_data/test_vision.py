"""Spec 0048 AC-9 (R-3, G-1; plan Risk 7): herkese açık geçmiş veri arşivi — kayıtlı aylık
zip'ler (ms ve µs damgalı), iletim kuralları, biçim hataları. Kayıtların kaynağı
`fixtures/events/README.md`."""

import io
import threading
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from crytobot.market_data import VisionHop, fetch_month, month_url, parse_month
from crytobot.market_data._vision import MAX_BYTES, USER_AGENT, VisionFormatError

EVENTS = Path(__file__).parent / "fixtures" / "events"


def hop(
    status: int,
    body: bytes = b"",
    content_type: str | None = "application/zip",
    location: str | None = None,
) -> VisionHop:
    stream = io.BytesIO(body)
    return VisionHop(status, location, content_type, stream.read)


def transport(*hops: VisionHop, seen: list[str] | None = None) -> Callable[[str, float], VisionHop]:
    queue = list(hops)

    def send(url: str, timeout: float) -> VisionHop:
        if seen is not None:
            seen.append(url)
        return queue.pop(0)

    return send


def zipped(text: str, name: str = "X-1h-2024-01.csv") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, text)
    return buffer.getvalue()


def test_ms_and_us_timestamps() -> None:
    ms = parse_month((EVENTS / "vision_bnxusdt_1h_2023-01.zip").read_bytes())
    us = parse_month((EVENTS / "vision_btcusdt_1h_2025-02.zip").read_bytes())
    assert (len(ms), len(us)) == (48, 48)
    assert ms[0].open_ms == 1672531200000 and ms[1].open_ms == 1672531200000 + 3_600_000
    assert (ms[0].open, ms[0].high, ms[0].low, ms[0].close) == (
        "71.20000000",
        "71.20000000",
        "70.90000000",
        "70.90000000",
    )
    # 2025 files stamp microseconds: the same hour grid in milliseconds
    assert us[0].open_ms == 1738368000000 and us[-1].open_ms == 1738368000000 + 47 * 3_600_000
    assert us[0].close == "102494.94000000"


def test_month_url() -> None:
    assert month_url("EOSUSDT", 2023, 1) == (
        "https://data.binance.vision/data/spot/monthly/klines/EOSUSDT/1h/EOSUSDT-1h-2023-01.zip"
    )


def test_transport_rules() -> None:
    body = (EVENTS / "vision_bnxusdt_1h_2023-01.zip").read_bytes()
    url = month_url("BNXUSDT", 2023, 1)
    seen: list[str] = []
    redirected = fetch_month(
        url, transport=transport(hop(302, location="/other.zip"), hop(200, body), seen=seen)
    )
    assert redirected.body == body and seen[1] == "https://data.binance.vision/other.zip"
    missing = (EVENTS / "vision_404.xml").read_bytes()
    assert fetch_month(url, transport=transport(hop(404, missing, "application/xml"))).missing
    assert fetch_month(url, transport=transport(hop(429))).error == "http_429"
    assert fetch_month(url, transport=transport(hop(403))).error == "http_403"
    assert fetch_month(url, transport=transport(hop(200, body, "text/html"))).error == "bad_type"
    octet = fetch_month(url, transport=transport(hop(200, body, "application/octet-stream")))
    assert octet.body == body
    http = fetch_month(url, transport=transport(hop(301, location="http://x/a.zip")))
    assert http.error == "redirect_http"
    loop = transport(*(hop(302, location="/a.zip") for _ in range(4)))
    assert fetch_month(url, transport=loop).error == "too_many_redirects"
    big = fetch_month(url, transport=transport(hop(200, b"x" * (MAX_BYTES + 1))))
    assert big.error == "too_large"
    exact = fetch_month(url, transport=transport(hop(200, b"x" * MAX_BYTES)))
    assert exact.body is not None and len(exact.body) == MAX_BYTES
    assert USER_AGENT == "Mozilla/5.0 (compatible; price-fetch/1.0)"


def test_network_errors_named() -> None:
    def broken(url: str, timeout: float) -> VisionHop:
        raise OSError("dns failure with a secret in it")

    def slow(url: str, timeout: float) -> VisionHop:
        raise TimeoutError

    assert fetch_month("https://x/a.zip", transport=broken).error == "network_error"
    assert fetch_month("https://x/a.zip", transport=slow).error == "timeout"


def test_hanging_transfer_bounded_and_stoppable() -> None:
    release = threading.Event()

    def hang(url: str, timeout: float) -> VisionHop:
        release.wait(5)
        return hop(200)

    began = time.monotonic()
    assert fetch_month("https://x/a.zip", transport=hang, budget_s=0.3).error == "timeout"
    assert time.monotonic() - began < 2.0
    assert fetch_month("https://x/a.zip", transport=hang, stopped=lambda: True).error == "stopped"
    release.set()


@pytest.mark.parametrize(
    "text",
    [
        "1672531200000,71.2,71.2,70.9\n",  # too few fields
        "abc,71.2,71.2,70.9,70.9,1\n",  # stamp not a number
        "1672531200001,71.2,71.2,70.9,70.9,1\n",  # not on the hour
        "1672531200000001,71.2,71.2,70.9,70.9,1\n",  # microseconds, not on the hour
        "1672531200000,1e3,71.2,70.9,70.9,1\n",  # price not plain
        "1672531200000,71.2,70.0,70.9,70.9,1\n",  # high below open
        "1672531200000,0,0,0,0,1\n",  # not positive
        "1672534800000,1,1,1,1,1\n1672531200000,1,1,1,1,1\n",  # not increasing
    ],
)
def test_format_errors(text: str) -> None:
    with pytest.raises(VisionFormatError):
        parse_month(zipped(text))


def test_zip_shape_errors() -> None:
    with pytest.raises(VisionFormatError):
        parse_month(b"not a zip")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.csv", "")
        archive.writestr("b.csv", "")
    with pytest.raises(VisionFormatError):
        parse_month(buffer.getvalue())
    with pytest.raises(VisionFormatError):
        parse_month(zipped("x", name="readme.txt"))
