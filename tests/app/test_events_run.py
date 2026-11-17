"""Spec 0048 AC-2, AC-6, AC-8 (R-2, R-4, R-7, R-9, R-10; plan Risk 9, 10): iki koşu uçtan uca.

`World` bir çalışma dizinidir: bot ayarı, haber ayarı (arşiv ve ileriye dönük kayıt yolları),
events ayarı, dolu arşiv ve ileriye dönük kayıt. Komutlar giriş noktasının `run`'ıyla koşar; indirme
gerçek `download_event_prices`'tır, yalnız borsa, arşiv, monoton saat ve bekleme sahtedir.
"""

import io
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from crytobot.__main__ import run
from crytobot.app import (
    EventDownloadParts,
    EventInputs,
    EventMeasureParts,
    EventsOutcome,
    ForcedStop,
    load_events_config,
    run_events_download,
    run_events_measure,
)
from crytobot.calibration import GENERATED_PREFIX, EventAnnouncement
from crytobot.market_data import (
    DownloadOutcome,
    DownloadRun,
    EventPriceParts,
    PairInfo,
    PriceData,
    PriceNeed,
    PriceStore,
    StoredCandle,
    StoredSpan,
    VisionFetched,
    download_event_prices,
)
from crytobot.market_data._numbers import ms_from_utc
from crytobot.news import (
    ArchiveItem,
    ArchiveStore,
    CatalogState,
    NewsItem,
    NewsStore,
    SourceState,
)

# Self-contained helpers: the tooling self-tests copy `tests/app` alone (a sensitive module's
# tests), so this file imports nothing from other test packages.
ROOT = Path(__file__).resolve().parents[2]


def _example(name: str, section: str | None, values: dict[str, str]) -> str:
    """Örnek ayar dosyası; `section` içindeki (`None`: her yerdeki) anahtarlar `values` ile."""
    rows = []
    inside = section is None
    for row in (ROOT / name).read_text(encoding="utf-8").splitlines():
        if section is not None and row.startswith("["):
            inside = row == f"[{section}]"
        key = row.split("=", 1)[0].strip()
        rows.append(f"{key} = {values[key]}" if inside and key in values and "=" in row else row)
    return "\n".join(rows) + "\n"


def config_text(root: Path) -> str:
    """Bot örnek ayarı; depo ve kayıt yolu `root`'ta."""
    return _example(
        "crytobot.example.toml",
        None,
        {
            "store_path": f'"{(root / "bot.db").as_posix()}"',
            "log_path": f'"{(root / "bot.log").as_posix()}"',
        },
    )


def archive_text(root: Path) -> str:
    """Haber örnek ayarı; kayıt, günlük ve arşiv yolları `root`'ta."""
    return _example(
        "crytobot-news.example.toml",
        "news",
        {
            "store_path": f'"{(root / "news.db").as_posix()}"',
            "log_path": f'"{(root / "news.log").as_posix()}"',
            "archive_store_path": f'"{(root / "archive.db").as_posix()}"',
            "archive_log_path": f'"{(root / "archive.log").as_posix()}"',
        },
    )


def candle_row(open_ms: int) -> list[object]:
    """Binance klines satırı (tests/market_data/helpers.py ile aynı biçim)."""
    close_ms = open_ms + 3_600_000 - 1
    return [open_ms, "10.00", "11.00", "9.00", "10.50", "1.0", close_ms, "1.0", 1, "1", "1", "0"]


H = timedelta(hours=1)
FIRST = datetime(2024, 1, 1, tzinfo=UTC)
NOW = datetime(2024, 6, 10, 12, 30, tzinfo=UTC)
CUTOFF = "2024-04-01"
LISTING = datetime(2024, 3, 1, 9, 30, tzinfo=UTC)
DELISTING = datetime(2024, 4, 15, 0, 0, tzinfo=UTC)
TAG_SEEN = datetime(2024, 5, 1, 7, 15, tzinfo=UTC)


class Exchange:
    """Sahte genel piyasa verisi: ABC (TRADING) ve DEF (BREAK) çiftleri, düz mumlar."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def markets(self, timeout: float) -> object:
        self.calls.append("markets")
        pairs = {"ABC": "TRADING", "DEF": "BREAK"}
        return {
            f"{base}/USDT": {
                "info": {
                    "symbol": f"{base}USDT",
                    "baseAsset": base,
                    "quoteAsset": "USDT",
                    "status": status,
                }
            }
            for base, status in pairs.items()
        }

    def klines(
        self, market_id: str, interval: str, limit: int, end_ms: int, timeout: float
    ) -> object:
        self.calls.append(f"klines {market_id}")
        first = ms_from_utc(FIRST)
        last = (end_ms // 3_600_000) * 3_600_000
        start = max(first, last - (limit - 1) * 3_600_000)
        return [candle_row(ms) for ms in range(start, last + 1, 3_600_000)]

    def ticker(self, market_id: str, timeout: float) -> object:  # pragma: no cover
        raise AssertionError("no ticker")


@dataclass
class World:
    root: Path
    console: io.StringIO = field(default_factory=io.StringIO)
    exchange: Exchange = field(default_factory=Exchange)
    downloads: int = 0
    now: datetime = NOW
    forward: bool = True
    cutoff: str = CUTOFF

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.out.mkdir(exist_ok=True)
        (self.root / "crytobot.toml").write_text(config_text(self.root), encoding="utf-8")
        (self.root / "crytobot-news.toml").write_text(archive_text(self.root), encoding="utf-8")
        self.write_events()
        self.fill_archive()
        if self.forward:
            self.fill_forward()

    @property
    def out(self) -> Path:
        return self.root / "out"

    @property
    def report(self) -> Path:
        return self.out / "report.txt"

    @property
    def library(self) -> Path:
        return self.out / "library.jsonl"

    @property
    def prices(self) -> Path:
        return self.out / "prices.db"

    def write_events(self, **changes: str) -> None:
        values = {
            "price_store_path": f'"{self.prices.as_posix()}"',
            "report_path": f'"{self.report.as_posix()}"',
            "library_path": f'"{self.library.as_posix()}"',
            "model_cutoff": f'"{self.cutoff}"',
            **changes,
        }
        body = "".join(f"{key} = {value}\n" for key, value in values.items() if value)
        (self.root / "crytobot-events.toml").write_text(f"[events]\n{body}", encoding="utf-8")

    def fill_archive(self) -> None:
        store = ArchiveStore.open(str(self.root / "archive.db"))
        items = [
            ("1", "Binance Will List ABC (ABC)", LISTING),
            ("2", "Binance Will Delist DEF on 2024-04-20", DELISTING),
            ("3", "Weekly Report", LISTING),
            ("4", "Binance Will List XYZ (XYZ)", LISTING),
            ("6", "Binance Will List QQQ (QQQ)", None),
        ]
        try:
            rows = [ArchiveItem(a, None, t, False, p, FIRST) for a, t, p in items]
            store.write_page(48, "New Cryptocurrency Listing", rows, CatalogState(48, "x"))
        finally:
            store.close()

    def fill_forward(self) -> None:
        store = NewsStore.open(str(self.root / "news.db"))
        try:
            store.write(
                "binance-duyuru",
                [
                    NewsItem("id:1", None, "x", "", False, LISTING, LISTING + 5 * H),
                    NewsItem(
                        "id:5",
                        None,
                        "Binance Will Extend the Monitoring Tag to Include ABC",
                        "",
                        False,
                        None,
                        TAG_SEEN,
                    ),
                ],
                SourceState(last_success_at=FIRST),
            )
            store.write(
                "coindesk",
                [
                    NewsItem(
                        "id:9", None, "Binance Will List ZZZ (ZZZ)", "", False, LISTING, LISTING
                    )
                ],
                SourceState(last_success_at=FIRST),
            )
        finally:
            store.close()

    def vision(self, url: str, timeout: float, stopped: Callable[[], bool]) -> VisionFetched:
        return VisionFetched(missing=True)

    def download(
        self, needs: Sequence[PriceNeed], store: PriceStore, parts: EventPriceParts, gap: float
    ) -> DownloadOutcome:
        self.downloads += 1
        moment = [0.0]

        def wait(seconds: float) -> None:
            moment[0] += seconds

        fake = replace(
            parts,
            connect=lambda: self.exchange,
            vision=self.vision,
            monotonic=lambda: moment[0],
            wait=wait,
        )
        return download_event_prices(needs, store, fake, gap)

    def run(self, *argv: str, clock: Callable[[], datetime] | None = None) -> int:
        self.console = io.StringIO()
        return run(
            list(argv),
            config_path=self.root / "crytobot.toml",
            news_config_path=self.root / "crytobot-news.toml",
            events_config_path=self.root / "crytobot-events.toml",
            console=self.console,
            clock=clock or (lambda: self.now),
            events_download=self.download,
        )

    @property
    def text(self) -> str:
        return self.console.getvalue()


def test_end_to_end_reasons_and_marks(tmp_path: Path) -> None:
    world = World(tmp_path)
    assert world.run("events", "download") == 0, world.text
    assert world.run("events", "measure") == 0, world.text
    import json

    records = [json.loads(line) for line in world.library.read_text("utf-8").splitlines()[1:]]
    by_id = {(r["article_id"], r["coin"]): r for r in records}
    assert by_id[("1", "ABC")]["origin"] == "ikisi" and by_id[("1", "ABC")]["reason"] is None
    assert by_id[("1", "ABC")]["first_seen"] == (LISTING + 5 * H).isoformat()
    assert by_id[("2", "DEF")]["reason"] is None  # a closed (BREAK) pair is measured
    assert by_id[("3", None)]["reason"] == "coin yok"
    assert by_id[("4", "XYZ")]["reason"] == "çift yok"
    assert by_id[("6", "QQQ")]["reason"] == "yayın anı bilinmiyor"
    tag = by_id[("5", "ABC")]
    assert (tag["origin"], tag["reference_from_first_seen"], tag["reason"]) == (
        "ileriye dönük",
        True,
        None,
    )
    assert ("9", "ZZZ") not in by_id  # RSS is not read
    assert (by_id[("1", "ABC")]["period"], by_id[("2", "DEF")]["period"]) == (
        "kesimden önce",
        "kesimden sonra",
    )
    report = world.report.read_text("utf-8")
    assert "  çift yok: 1\n" in report and "  yayın anı bilinmiyor: 1\n" in report
    # the price data's record counts from the store (review round 1 F-6, round 2 R2-1): exact,
    # three 762-candle spans of two pairs, none empty
    assert "kayıt: USDT çifti=2 mumlu çift=2 mum=2286 aralık=3 boş aralık=0" in report, report
    assert "events measure: rapor parmak izi:" in world.text
    assert "events measure: ölçülemeyen: yayın anı bilinmiyor=1 coin yok=1 çift yok=1" in world.text


def test_no_forward_store_said_archive_only(tmp_path: Path) -> None:
    world = World(tmp_path, forward=False)
    assert world.run("events", "download") == 0, world.text
    assert world.run("events", "measure") == 0, world.text
    report = world.report.read_text("utf-8")
    assert (
        f"ileriye dönük kayıt yok: {(tmp_path / 'news.db').as_posix()} (yalnız arşivle)" in report
    )
    assert not (tmp_path / "news.db").exists()


def test_two_runs_byte_identical_but_generated_line(tmp_path: Path) -> None:
    world = World(tmp_path)
    assert world.run("events", "download") == 0, world.text
    assert world.run("events", "measure") == 0, world.text
    first_report, first_library = world.report.read_bytes(), world.library.read_bytes()
    world.report.rename(world.out / "report-1.txt")
    world.library.rename(world.out / "library-1.jsonl")
    later = NOW + timedelta(days=3)
    assert world.run("events", "measure", clock=lambda: later) == 0, world.text
    assert world.library.read_bytes() == first_library
    first, second = first_report.decode().splitlines(), world.report.read_text("utf-8").splitlines()
    differing = [(a, b) for a, b in zip(first, second, strict=True) if a != b]
    assert len(differing) == 1 and all(line.startswith(GENERATED_PREFIX) for line in differing[0])


def test_measure_makes_no_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = World(tmp_path)
    assert world.run("events", "download") == 0, world.text
    calls = list(world.exchange.calls)

    def no_network(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    assert world.run("events", "measure") == 0, world.text
    assert world.exchange.calls == calls and world.downloads == 1


def test_rerun_download_asks_nothing(tmp_path: Path) -> None:
    world = World(tmp_path)
    assert world.run("events", "download") == 0, world.text
    calls = len(world.exchange.calls)
    assert world.run("events", "download") == 0, world.text
    assert len(world.exchange.calls) == calls
    assert "events download: tamam: fiyat verisi indirildi" in world.text


# --- the runs with fake parts (branches of `app`) -----------------------------------------------


def config() -> Any:
    result = load_events_config(
        {
            "events": {
                "price_store_path": "p",
                "report_path": "r",
                "library_path": "l",
                "model_cutoff": CUTOFF,
            }
        }
    )
    assert result.config is not None
    return result.config


def inputs(*items: EventAnnouncement) -> EventInputs:
    return EventInputs(
        items, (("spot listeleme", "olumlu"),), "a.db", len(items), "n.db", None, "f" * 64
    )


def item(article: str = "1", **values: Any) -> EventAnnouncement:
    base: dict[str, Any] = {
        "origin": "arşiv",
        "catalog": "c",
        "title": "t",
        "published": LISTING,
        "first_seen": None,
        "event_type": "spot listeleme",
        "direction": "olumlu",
        "coins": ("ABC",),
        "pattern": "t",
    }
    return EventAnnouncement(article, **{**base, **values})


def prices(*, spans: bool = True, pairs: bool = True) -> PriceData:
    start = LISTING - 760 * H
    candles = tuple(
        StoredCandle(ms_from_utc(start + i * H), "10.00", "11.00", "9.00", "10.50")
        for i in range(800)
    )
    covered = (StoredSpan(start, start + 800 * H, True, "api"),) if spans else ()
    return PriceData(
        {"ABC": PairInfo("ABC", "ABCUSDT", "TRADING")} if pairs else None,
        NOW,
        {"ABCUSDT": candles},
        {"ABCUSDT": covered},
        (DownloadRun(NOW, NOW, 1.0, 2, NOW),) if pairs else (),
    )


@dataclass
class Parts:
    written: dict[str, str] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)
    existing: set[str] = field(default_factory=set)
    writable: bool = True

    def measure(self, given: Any = None, priced: Any = None) -> EventMeasureParts:
        return EventMeasureParts(
            lambda: inputs(item()) if given is None else given,
            lambda: prices() if priced is None else priced,
            lambda path: path in self.existing,
            self.write_file,
            self.lines.append,
            lambda: NOW,
        )

    def write_file(self, path: str, text: str) -> bool:
        if self.writable:
            self.written[path] = text
        return self.writable


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (DownloadOutcome.COMPLETE, EventsOutcome.COMPLETED),
        (DownloadOutcome.FAILED, EventsOutcome.FAILED),
        (DownloadOutcome.STOPPED, EventsOutcome.STOPPED),
    ],
)
def test_download_outcomes(outcome: DownloadOutcome, expected: EventsOutcome) -> None:
    seen: list[tuple[PriceNeed, ...]] = []
    lines: list[str] = []

    def download(needs: tuple[PriceNeed, ...]) -> DownloadOutcome:
        seen.append(needs)
        return outcome

    parts = EventDownloadParts(lambda: inputs(item(), item("2", coins=())), download, lines.append)
    assert run_events_download(config(), parts).outcome is expected
    assert [need.coin for need in seen[0]] == ["ABC"]
    assert lines[0] == "events download: başladı: duyuru=2 örnek=2 coin=1 aralık=1"


@pytest.mark.parametrize(
    ("given", "message"),
    [
        ("arşiv okunamıyor", "arşiv okunamıyor"),
        (inputs(item(direction="belki")), "bilinmeyen beklenen yön"),
        (
            replace(inputs(item()), types=(("spot listeleme", "belki"),)),
            "bilinmeyen beklenen yön",
        ),
    ],
)
def test_inputs_refused(given: Any, message: str) -> None:
    lines: list[str] = []
    parts = EventDownloadParts(lambda: given, lambda needs: DownloadOutcome.COMPLETE, lines.append)
    result = run_events_download(config(), parts)
    assert (result.outcome, result.message) == (EventsOutcome.REFUSED, message)
    assert lines == [f"events download: reddedildi: {message}"]


@pytest.mark.parametrize(
    ("priced", "message"),
    [
        ("fiyat deposu okunamıyor", "fiyat deposu okunamıyor"),
        (prices(pairs=False), "borsa bilgisi indirilmemiş; önce events download"),
        (prices(spans=False), "fiyat verisi eksik: 1 aralık indirilmemiş; önce events download"),
    ],
)
def test_measure_refused_without_prices(priced: Any, message: str) -> None:
    parts = Parts()
    result = run_events_measure(config(), parts.measure(priced=priced))
    assert (result.outcome, result.message) == (EventsOutcome.REFUSED, message)
    assert parts.written == {}


def test_measure_refused_no_price_store() -> None:
    parts = Parts()
    measure = replace(parts.measure(), prices=lambda: None)
    result = run_events_measure(config(), measure)
    assert result.message == "fiyat verisi yok: p; önce events download"


def test_measure_never_overwrites() -> None:
    for path in ("r", "l"):
        parts = Parts(existing={path})
        result = run_events_measure(config(), parts.measure())
        assert (result.outcome, result.message) == (
            EventsOutcome.REFUSED,
            f"dosya var: {path}; üzerine yazılmaz",
        )
        assert parts.written == {}


def test_measure_written_and_not_written() -> None:
    parts = Parts()
    assert run_events_measure(config(), parts.measure()).outcome is EventsOutcome.COMPLETED
    assert set(parts.written) == {"r", "l"}
    assert any(line.startswith("events measure: kütüphane parmak izi: ") for line in parts.lines)
    assert any("spot listeleme yükseliş (ana): ölçülen=1 fark=" in line for line in parts.lines)
    failing = Parts(writable=False)
    result = run_events_measure(config(), failing.measure())
    assert (result.outcome, result.message) == (
        EventsOutcome.NOT_WRITTEN,
        "kütüphane yazılamadı: l",
    )


def test_report_not_written_names_the_library_left() -> None:
    """Review round 1 F-8: the library is written first; a report write failure names the file
    left behind, which refuses the next run until deleted."""

    @dataclass
    class ReportFails(Parts):
        def write_file(self, path: str, text: str) -> bool:
            if path == "r":
                return False
            self.written[path] = text
            return True

    parts = ReportFails()
    result = run_events_measure(config(), parts.measure())
    assert (result.outcome, result.message) == (
        EventsOutcome.NOT_WRITTEN,
        "rapor yazılamadı: r; kütüphane yazıldı: l, silinmeden yeniden koşulamaz",
    )
    assert set(parts.written) == {"l"}


def test_unexpected_error_named_and_forced_stop_raised() -> None:
    parts = Parts()

    def broken() -> Any:
        raise RuntimeError("secret text")

    result = run_events_measure(config(), replace(parts.measure(), inputs=broken))
    assert (result.outcome, result.message) == (
        EventsOutcome.FAILED,
        "beklenmeyen hata: RuntimeError",
    )
    assert "secret" not in "".join(parts.lines)

    def forced() -> Any:
        raise ForcedStop

    with pytest.raises(ForcedStop):
        run_events_measure(config(), replace(parts.measure(), inputs=forced))
    assert parts.lines[-1] == "events measure: durdu: zorla durdurma"


def test_pair_missing_from_store_is_no_pair() -> None:
    parts = Parts()
    given = inputs(item(), item("2", coins=("NOPE",)))
    assert (
        run_events_measure(config(), parts.measure(given=given)).outcome is EventsOutcome.COMPLETED
    )
    assert '"coin":"NOPE"' in parts.written["l"] and '"reason":"çift yok"' in parts.written["l"]
