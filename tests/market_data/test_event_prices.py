"""Spec 0048 AC-9 (R-3, G-1, G-6; plan Risk 7): olay fiyatlarının indirme adımı.

Hata sınıfları elle kurulmuş istisnayla değil, gerçek `ccxt.binance`'in kayıtlı HTTP yanıtlarını
eşlemesinden üretilir (conventions, spec 0036 F-1): `recorded_client` yalnız HTTP oturumunu
değiştirir. Aralık ve tek istek kuralı sahte monoton saatle sınanır.
"""

import io
import json
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
import requests

from crytobot.market_data import (
    REQUEST_TIMEOUT_S,
    DownloadOutcome,
    EventPriceParts,
    PriceNeed,
    PriceStore,
    VisionFetched,
    download_event_prices,
    missing_spans,
    month_url,
    read_prices,
)
from crytobot.market_data._client import PublicExchange
from crytobot.market_data._numbers import ms_from_utc
from tests.market_data.helpers import (
    FakeSession,
    candle_row,
    fixture,
    http_response,
    recorded_client,
)

EVENTS = Path(__file__).parent / "fixtures" / "events"
H = timedelta(hours=1)
NOW = datetime(2026, 11, 16, 10, 30, tzinfo=UTC)
T0 = datetime(2026, 11, 1, tzinfo=UTC)


def rows(start: datetime, count: int) -> list[list[object]]:
    return [candle_row(ms_from_utc(start + index * H)) for index in range(count)]


def json_response(body: object, status: int = 200) -> Any:
    return http_response(status, json.dumps(body), {"Content-Type": "application/json"})


@dataclass
class Fake:
    """Sahte monoton saat ve bekleme; satırlar ve görülen arşiv adresleri."""

    tmp: Path
    now: float = 100.0
    lines: list[str] = field(default_factory=list)
    vision_urls: list[str] = field(default_factory=list)
    vision: dict[str, VisionFetched] = field(default_factory=dict)
    stop_after: int | None = None

    def monotonic(self) -> float:
        return self.now

    def wait(self, seconds: float) -> None:
        self.now += seconds

    def stopped(self) -> bool:
        return self.stop_after is not None and len(self.lines) >= self.stop_after

    def fetch(self, url: str, timeout: float, stopped: Callable[[], bool]) -> VisionFetched:
        self.vision_urls.append(url)
        self.now += 0.2
        return self.vision.get(url, VisionFetched(missing=True))

    def parts(self, connect: Callable[[], PublicExchange], **changes: Any) -> EventPriceParts:
        values: dict[str, Any] = {
            "clock": lambda: NOW,
            "monotonic": self.monotonic,
            "wait": self.wait,
            "stopped": self.stopped,
            "say": self.lines.append,
            "connect": connect,
            "vision": self.fetch,
            **changes,
        }
        return EventPriceParts(**values)

    def run(
        self,
        needs: list[PriceNeed],
        connect: Callable[[], PublicExchange],
        gap: float = 1.0,
        **changes: Any,
    ) -> DownloadOutcome:
        store = PriceStore.open(str(self.tmp / "prices.db"))
        try:
            return download_event_prices(needs, store, self.parts(connect, **changes), gap)
        finally:
            store.close()


def client(routes: dict[str, Any]) -> tuple[PublicExchange, FakeSession]:
    base = {"exchangeInfo": json_response(fixture("exchange_info"))}
    return recorded_client({**routes, **base})


def klines_requests(session: FakeSession) -> list[str]:
    return [r["url"] for r in session.requests if "klines" in r["url"]]


def need(coin: str, start: datetime = T0, hours: int = 48) -> PriceNeed:
    return PriceNeed(coin, start, start + hours * H)


class TimedExchange:
    """Zaman çizelgesi tutan sahte borsa: her istek sahte saatte 0.3 s sürer."""

    def __init__(self, fake: Fake, first: datetime = T0) -> None:
        self.fake = fake
        self.first = first
        self.timeline: list[tuple[float, float]] = []
        self.active = 0
        self.most = 0
        self.lock = threading.Lock()

    def _call(self, answer: object) -> object:
        with self.lock:
            self.active += 1
            self.most = max(self.most, self.active)
        start = self.fake.now
        self.fake.now += 0.3
        with self.lock:
            self.active -= 1
        self.timeline.append((start, self.fake.now))
        return answer

    def markets(self, timeout: float) -> object:
        return self._call(
            {
                "EOS/USDT": {
                    "info": {
                        "symbol": "EOSUSDT",
                        "baseAsset": "EOS",
                        "quoteAsset": "USDT",
                        "status": "BREAK",
                    }
                }
            }
        )

    def klines(
        self, market_id: str, interval: str, limit: int, end_ms: int, timeout: float
    ) -> object:
        end = datetime.fromtimestamp((end_ms + 1) / 1000, UTC)
        count = 1000 if end - self.first > 1000 * H else int((end - self.first) / H)
        return self._call(rows(end - count * H, count))

    def ticker(self, market_id: str, timeout: float) -> object:  # pragma: no cover
        raise AssertionError("no ticker in this step")


def test_gap_and_single_flight(tmp_path: Path) -> None:
    early = datetime(2026, 8, 1, tzinfo=UTC)
    fake = Fake(tmp_path)
    exchange = TimedExchange(fake, first=early)
    outcome = fake.run([PriceNeed("EOS", early, early + 1500 * H)], lambda: exchange, gap=2.0)
    assert outcome is DownloadOutcome.COMPLETE
    timeline = exchange.timeline
    assert len(timeline) == 3  # markets, two 1000-candle pages backwards
    gaps = [later[0] - earlier[1] for earlier, later in pairwise(timeline)]
    assert all(gap >= 2.0 for gap in gaps), gaps
    assert exchange.most == 1
    data = read_prices(str(tmp_path / "prices.db"))
    assert data is not None and len(data.candles["EOSUSDT"]) == 1500


def test_hanging_request_bounded(tmp_path: Path) -> None:
    assert REQUEST_TIMEOUT_S == 30.0
    assert (
        EventPriceParts(lambda: NOW, time.monotonic, lambda s: None, lambda: False, print).timeout_s
        == 30.0
    )
    release = threading.Event()

    class Hanging(TimedExchange):
        def klines(self, *args: Any) -> object:
            release.wait(5)
            return []

    fake = Fake(tmp_path)
    began = time.monotonic()
    outcome = fake.run([need("EOS")], lambda: Hanging(fake), timeout_s=0.3)
    elapsed = time.monotonic() - began
    release.set()
    assert outcome is DownloadOutcome.FAILED
    assert elapsed < 0.3 + 2.0
    assert any("kaynak hatası: zaman aşımı" in line for line in fake.lines)


@pytest.mark.parametrize(
    ("answer", "name"),
    [
        (requests.exceptions.ConnectionError("down"), "ağ hatası ya da sunucu hatası"),
        (json_response({"code": -1000, "msg": "x"}, status=503), "ağ hatası ya da sunucu hatası"),
        (
            json_response({"code": -1100, "msg": "Illegal characters"}, status=400),
            "HTTP hata cevabı",
        ),
        (json_response({"code": -1003, "msg": "Too many"}, status=429), "hız sınırı (429)"),
        (json_response({"code": -1003, "msg": "Banned"}, status=418), "borsa yasağı (418)"),
        (json_response([["x"]]), "beklenmeyen yanıt"),
        (json_response({"not": "a list"}), "beklenmeyen yanıt"),
    ],
)
def test_error_names_exit_1_no_retry(tmp_path: Path, answer: object, name: str) -> None:
    exchange, session = client({"klines?symbol=EOSUSDT": answer})
    fake = Fake(tmp_path)

    outcome = fake.run([need("EOS")], lambda: exchange)

    assert outcome is DownloadOutcome.FAILED
    assert len(klines_requests(session)) == 1  # never the same request again
    assert any(f"durdu: kaynak hatası: {name};" in line for line in fake.lines), fake.lines
    assert fake.vision_urls == []


def test_vision_errors_named(tmp_path: Path) -> None:
    exchange, _ = client({"klines?symbol=EOSUSDT": json_response(fixture("error_bad_symbol"), 400)})
    fake = Fake(tmp_path, vision={month_url("EOSUSDT", 2026, 11): VisionFetched(error="http_429")})
    assert fake.run([need("EOS")], lambda: exchange) is DownloadOutcome.FAILED
    assert any("kaynak hatası: hız sınırı (429)" in line for line in fake.lines)
    fake = Fake(tmp_path, vision={month_url("EOSUSDT", 2026, 11): VisionFetched(body=b"junk")})
    assert fake.run([need("EOS")], lambda: exchange) is DownloadOutcome.FAILED
    assert any("beklenmeyen yanıt (arşiv biçimi)" in line for line in fake.lines)


def test_downloaded_kept_rerun_fetches_missing(tmp_path: Path) -> None:
    routes = {
        "klines?symbol=BTCUSDT": json_response(rows(T0, 48)),
        "klines?symbol=ETHUSDT": json_response({"code": -1003}, status=429),
    }
    exchange, session = client(routes)
    fake = Fake(tmp_path)
    assert fake.run([need("BTC"), need("ETH")], lambda: exchange) is DownloadOutcome.FAILED
    data = read_prices(str(tmp_path / "prices.db"))
    assert data is not None and len(data.candles["BTCUSDT"]) == 48 and "ETHUSDT" not in data.spans
    assert len(klines_requests(session)) == 2

    routes["klines?symbol=ETHUSDT"] = json_response(rows(T0, 48))
    again, second = client(routes)
    fake = Fake(tmp_path)
    assert fake.run([need("BTC"), need("ETH")], lambda: again) is DownloadOutcome.COMPLETE
    urls = [r["url"] for r in second.requests]
    assert len(urls) == 1 and "symbol=ETHUSDT" in urls[0]  # no exchange info, no BTC again
    data = read_prices(str(tmp_path / "prices.db"))
    assert data is not None and len(data.candles["ETHUSDT"]) == 48 and len(data.runs) == 2


def test_exchange_info_refreshed_for_a_coin_not_in_snapshot(tmp_path: Path) -> None:
    """Review round 1 F-4: a coin listed after the first download is found on a later run with one
    more exchange-information request; a snapshot holding every needed coin is not re-requested."""
    store = PriceStore.open(str(tmp_path / "prices.db"))
    try:
        store.save_pairs([], NOW - 30 * 24 * H)  # an old snapshot without BTC
    finally:
        store.close()
    exchange, session = client({"klines?symbol=BTCUSDT": json_response(rows(T0, 48))})
    fake = Fake(tmp_path)
    assert fake.run([need("BTC")], lambda: exchange) is DownloadOutcome.COMPLETE
    infos = [r["url"] for r in session.requests if "exchangeInfo" in r["url"]]
    assert len(infos) == 1
    assert any(
        line.startswith("borsa bilgisi yenilendi: görüntüde olmayan 1 coin") for line in fake.lines
    )
    data = read_prices(str(tmp_path / "prices.db"))
    assert data is not None and data.pairs is not None and "BTC" in data.pairs
    assert len(data.candles["BTCUSDT"]) == 48 and data.exchange_info_at == NOW

    again, second = client({})
    assert Fake(tmp_path).run([need("BTC")], lambda: again) is DownloadOutcome.COMPLETE
    assert second.requests == []  # every coin in the snapshot, every span stored

    # a coin missing from the snapshot whose spans all end before it: not re-requested
    third, asked = client({})
    old = PriceNeed("XYZ", T0 - 100 * H, T0 - 50 * H)
    assert Fake(tmp_path).run([old], lambda: third) is DownloadOutcome.COMPLETE
    assert asked.requests == []


def month_zip(start: datetime, count: int) -> bytes:
    lines = [
        f"{ms_from_utc(start + index * H)},1.0,1.1,0.9,1.0,10,0,0,0,0,0,0" for index in range(count)
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("EOSUSDT-1h.csv", "\n".join(lines) + "\n")
    return buffer.getvalue()


def test_unpublished_archive_month_fetched_again(tmp_path: Path) -> None:
    """Review round 1 F-5: a span with no candles because the month's archive was not yet out is
    fetched again on a later run; a span from a long-settled month is not."""
    bad = {"klines?symbol=EOSUSDT": json_response(fixture("error_bad_symbol"), 400)}
    november = month_url("EOSUSDT", 2026, 11)
    exchange, _ = client(bad)
    first = Fake(tmp_path)  # 2026-11-16: November's file is not out
    assert first.run([need("EOS")], lambda: exchange) is DownloadOutcome.COMPLETE
    assert first.vision_urls == [november]
    data = read_prices(str(tmp_path / "prices.db"))
    assert data is not None and [s.source for s in data.spans["EOSUSDT"]] == ["yok"]

    later = datetime(2027, 2, 3, tzinfo=UTC)
    again, _ = client(bad)
    second = Fake(tmp_path, vision={november: VisionFetched(body=month_zip(T0, 48))})
    assert second.run([need("EOS")], lambda: again, clock=lambda: later) is DownloadOutcome.COMPLETE
    assert second.vision_urls == [november]
    data = read_prices(str(tmp_path / "prices.db"))
    assert data is not None and len(data.candles["EOSUSDT"]) == 48

    # fetched in February: November is settled, nothing is asked again
    third, asked = client({})
    final = Fake(tmp_path)
    assert final.run([need("EOS")], lambda: third, clock=lambda: later) is DownloadOutcome.COMPLETE
    assert asked.requests == [] and final.vision_urls == []


def test_no_key_no_personal_data(tmp_path: Path) -> None:
    exchange, session = client(
        {"klines?symbol=EOSUSDT": json_response(fixture("error_bad_symbol"), 400)}
    )
    fake = Fake(tmp_path)
    assert fake.run([need("EOS")], lambda: exchange) is DownloadOutcome.COMPLETE
    for request in session.requests:
        headers = {**session.headers, **(request.get("headers") or {})}
        assert not any("apikey" in key.lower() or "x-mbx" in key.lower() for key in headers)
        assert "signature" not in request["url"] and "apiKey" not in request["url"]
        assert request["method"] == "GET"
    from crytobot.market_data._vision import USER_AGENT

    assert "@" not in USER_AGENT and "crytobot" not in USER_AGENT.lower()
    assert all(url.startswith("https://data.binance.vision/") for url in fake.vision_urls)


def test_no_pair_no_price_data_continues(tmp_path: Path) -> None:
    exchange, session = client({"klines?symbol=BTCUSDT": json_response(rows(T0, 48))})
    fake = Fake(tmp_path)
    assert fake.run([need("XYZ"), need("BTC")], lambda: exchange) is DownloadOutcome.COMPLETE
    assert "XYZ: USDT spot çifti yok; fiyat verisi yok" in fake.lines
    assert [u for u in klines_requests(session) if "XYZ" in u] == []
    data = read_prices(str(tmp_path / "prices.db"))
    assert data is not None and data.pairs is not None
    assert "EOS" in data.pairs and data.pairs["EOS"].status == "BREAK"  # a closed pair is a pair
    assert "ETHBTC" not in {pair.symbol for pair in data.pairs.values()}


def test_vision_fallback_then_none(tmp_path: Path) -> None:
    jan = datetime(2023, 1, 1, tzinfo=UTC)
    zipped = (EVENTS / "vision_bnxusdt_1h_2023-01.zip").read_bytes()
    exchange, _ = client(
        {
            "klines?symbol=EOSUSDT": json_response(fixture("error_bad_symbol"), 400),
            "klines?symbol=ETHUSDT": json_response([]),
        }
    )
    fake = Fake(tmp_path, vision={month_url("EOSUSDT", 2023, 1): VisionFetched(body=zipped)})

    outcome = fake.run(
        [PriceNeed("EOS", jan, jan + 24 * H), PriceNeed("ETH", jan, jan + 24 * H)], lambda: exchange
    )

    assert outcome is DownloadOutcome.COMPLETE
    assert fake.vision_urls == [month_url("EOSUSDT", 2023, 1), month_url("ETHUSDT", 2023, 1)]
    data = read_prices(str(tmp_path / "prices.db"))
    assert data is not None
    assert len(data.candles["EOSUSDT"]) == 24
    assert [(s.found, s.source) for s in data.spans["EOSUSDT"]] == [(True, "arşiv")]
    assert [(s.found, s.source) for s in data.spans["ETHUSDT"]] == [(False, "yok")]
    assert any(
        line.startswith("ETH: ") and line.endswith("fiyat verisi yok") for line in fake.lines
    )


def test_overlapping_ranges_fetched_once(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    exchange = TimedExchange(fake)
    needs = [PriceNeed("EOS", T0, T0 + 100 * H), PriceNeed("EOS", T0 + 50 * H, T0 + 150 * H)]
    assert fake.run(needs, lambda: exchange) is DownloadOutcome.COMPLETE
    assert len(exchange.timeline) == 2  # markets and one page for the union
    data = read_prices(str(tmp_path / "prices.db"))
    assert data is not None and len(data.candles["EOSUSDT"]) == 150
    assert [(s.start, s.end) for s in data.spans["EOSUSDT"]] == [(T0, T0 + 150 * H)]


def test_total_duration_recorded(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    exchange = TimedExchange(fake)
    assert fake.run([need("EOS")], lambda: exchange, gap=1.0) is DownloadOutcome.COMPLETE
    data = read_prices(str(tmp_path / "prices.db"))
    assert data is not None and len(data.runs) == 1
    run = data.runs[0]
    assert run.requests == 2 and run.seconds == pytest.approx(0.3 + 1.0 + 0.3)
    assert run.ceiling == datetime(2026, 11, 16, 10, tzinfo=UTC)
    assert fake.lines[-1] == "toplam süre: 1.6 s, istek: 2"


def test_stop_request_keeps_downloaded(tmp_path: Path) -> None:
    fake = Fake(tmp_path, stop_after=2)
    exchange = TimedExchange(fake)
    outcome = fake.run(
        [need("EOS"), PriceNeed("EOS", T0 + 200 * H, T0 + 300 * H)], lambda: exchange
    )
    assert outcome is DownloadOutcome.STOPPED
    data = read_prices(str(tmp_path / "prices.db"))
    assert data is not None and len(data.spans["EOSUSDT"]) == 1


def test_only_closed_candles_requested(tmp_path: Path) -> None:
    fake = Fake(tmp_path)
    exchange = TimedExchange(fake)
    start = datetime(2026, 11, 16, 0, tzinfo=UTC)
    assert (
        fake.run([PriceNeed("EOS", start, start + 48 * H)], lambda: exchange)
        is DownloadOutcome.COMPLETE
    )
    data = read_prices(str(tmp_path / "prices.db"))
    assert data is not None
    assert [(s.start, s.end) for s in data.spans["EOSUSDT"]] == [(start, start + 10 * H)]


def test_missing_spans() -> None:
    from crytobot.market_data import StoredSpan

    stored = [StoredSpan(T0 + 10 * H, T0 + 20 * H, True, "api")]
    assert missing_spans([(T0, T0 + 30 * H)], stored) == [
        (T0, T0 + 10 * H),
        (T0 + 20 * H, T0 + 30 * H),
    ]
    assert missing_spans([(T0 + 12 * H, T0 + 15 * H)], stored) == []
    assert missing_spans([(T0, T0 + 5 * H), (T0 + 3 * H, T0 + 8 * H)], []) == [(T0, T0 + 8 * H)]
