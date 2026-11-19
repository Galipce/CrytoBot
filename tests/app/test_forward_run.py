"""Spec 0053 AC-8, AC-9, AC-10 (R-1, R-8, R-10, G-7, G-8; plan Risk 2, 7, 8, 9): iki koşu uçtan
uca ve `app`'in ret yolları.

`World` bir çalışma dizinidir: bot ayarı (isteğe bağlı `[shadow]`), haber ayarı (`[news]`,
`[score]`), forward ayarı, dolu skor kaydı, haber kaydı ve gölge kayıt. Komutlar giriş noktasının
`run`'ıyla koşar; indirme gerçek `download_event_prices`'tır, yalnız borsa, arşiv, monoton saat ve
bekleme sahtedir.
"""

import io
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crytobot.__main__ import run
from crytobot.app import (
    ForcedStop,
    ForwardDownloadParts,
    ForwardOutcome,
    ForwardReportParts,
    ForwardSources,
    load_forward_config,
    run_forward_download,
    run_forward_report,
)
from crytobot.calibration import (
    GENERATED_PREFIX,
    SCORED,
    ForwardEvent,
    ForwardInputs,
    ScoredNews,
)
from crytobot.market_data import (
    DownloadOutcome,
    EventPriceParts,
    PairInfo,
    PriceData,
    PriceNeed,
    PriceStore,
    VisionFetched,
    download_event_prices,
)
from crytobot.market_data._numbers import ms_from_utc
from crytobot.news import (
    EventScore,
    NewsItem,
    NewsStore,
    ResultKind,
    ScoreResult,
    ScoreStore,
    SourceState,
)
from tests.app.test_events_run import ROOT, candle_row, config_text
from tests.main.test_news_entry import PERMISSION_TOML, TEST_SOURCES

ONLY_BINANCE = (
    '\n[[news.sources]]\nname = "binance-duyuru"\ntype = "binance-duyuru"\n'
    f'url = "https://example.org/binance"\n{PERMISSION_TOML}'
)

H = timedelta(hours=1)
FIRST = datetime(2026, 9, 1, tzinfo=UTC)
NOW = datetime(2026, 11, 18, 12, 30, tzinfo=UTC)
REPORT_AT = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
SCORED_1 = datetime(2026, 11, 10, 9, 15, tzinfo=UTC)
SCORED_2 = datetime(2026, 11, 12, 20, 40, tzinfo=UTC)
SCORED_3 = datetime(2026, 11, 18, 9, 30, tzinfo=UTC)  # its 24th candle closes after the report
MODEL = "claude-sonnet-5-5"


def news_text(root: Path, sources: str = TEST_SOURCES) -> str:
    """Haber örnek ayarı; `[news]` ve `[score]` yolları `root`'ta. Örneğin kaynakları çıkarılır,
    yerine `sources` (öntanımlı: üç izinli kaynak, spec 0055 plan Risk 5) eklenir."""
    values = {
        "news": {
            "store_path": root / "news.db",
            "log_path": root / "news.log",
            "archive_store_path": root / "archive.db",
            "archive_log_path": root / "archive.log",
        },
        "score": {
            "store_path": root / "score.db",
            "log_path": root / "score.log",
            "calibration_report_path": root / "events-report.txt",
            "library_path": root / "events-library.jsonl",
        },
    }
    rows = []
    section = ""
    for row in (ROOT / "crytobot-news.example.toml").read_text(encoding="utf-8").splitlines():
        if row.startswith("["):
            section = row.strip("[]")
            if section == "news.sources":
                continue
            if section == "score":  # the sources stay in front of `[score]`
                rows.append(sources)
        if section == "news.sources" and "=" in row and not row.startswith("#"):
            continue
        key = row.split("=", 1)[0].strip()
        found = values.get(section, {})
        if "=" in row and key in found:
            row = f'{key} = "{found[key].as_posix()}"'
        rows.append(row)
    return "\n".join(rows) + "\n"


class Exchange:
    """Sahte genel piyasa verisi: BTC ve ETH çiftleri, düz mumlar."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def markets(self, timeout: float) -> object:
        self.calls.append("markets")
        return {
            f"{base}/USDT": {
                "info": {
                    "symbol": f"{base}USDT",
                    "baseAsset": base,
                    "quoteAsset": "USDT",
                    "status": "TRADING",
                }
            }
            for base in ("BTC", "ETH")
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


def shadow_row(at: datetime, pair: str, state: str, buy: str, reason: str = "") -> str:
    return json.dumps(
        {
            "version": "1",
            "turn_at": at.isoformat(),
            "pair": pair,
            "whitelist": ["BTC/USDT", "ETH/USDT"],
            "state": state,
            "reason": reason or "olumsuz olay yok",
            "events": [],
            "missing": None,
            "held": None,
            "technical_buy": buy,
            "technical_reason": None,
            "risk": None,
            "order": None,
        },
        ensure_ascii=False,
    )


@dataclass
class World:
    root: Path
    console: io.StringIO = field(default_factory=io.StringIO)
    exchange: Exchange = field(default_factory=Exchange)
    downloads: int = 0
    shadow: bool = True
    scores: bool = True

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.out.mkdir(exist_ok=True)
        self.write_bot()
        (self.root / "crytobot-news.toml").write_text(news_text(self.root), encoding="utf-8")
        self.write_forward()
        self.fill_news()
        if self.scores:
            self.fill_scores()
        if self.shadow:
            self.fill_shadow()

    @property
    def out(self) -> Path:
        return self.root / "out"

    @property
    def report(self) -> Path:
        return self.out / "report.txt"

    @property
    def samples(self) -> Path:
        return self.out / "samples.jsonl"

    @property
    def prices(self) -> Path:
        return self.out / "prices.db"

    @property
    def shadow_path(self) -> Path:
        return self.root / "shadow.jsonl"

    def write_bot(self, **changes: str) -> None:
        text = config_text(self.root)
        if self.shadow:
            values = {
                "record_path": f'"{self.shadow_path.as_posix()}"',
                "score_path": f'"{(self.root / "score.db").as_posix()}"',
                "news_path": f'"{(self.root / "news.db").as_posix()}"',
            }
            text += "\n[shadow]\n" + "".join(f"{k} = {v}\n" for k, v in values.items())
        if "stage" in changes:
            text += f"\n[stage]\npaper_store_path = {changes['stage']}\n"
        (self.root / "crytobot.toml").write_text(text, encoding="utf-8")

    def write_forward(self, **changes: str) -> None:
        values = {
            "price_store_path": f'"{self.prices.as_posix()}"',
            "report_path": f'"{self.report.as_posix()}"',
            "samples_path": f'"{self.samples.as_posix()}"',
            **changes,
        }
        body = "".join(f"{key} = {value}\n" for key, value in values.items() if value)
        (self.root / "crytobot-forward.toml").write_text(f"[forward]\n{body}", encoding="utf-8")

    def fill_news(self) -> None:
        store = NewsStore.open(str(self.root / "news.db"))
        try:
            store.write(
                "binance-duyuru",
                [
                    NewsItem("a", None, "BTC hack", "", False, SCORED_1, SCORED_1),
                    NewsItem("b", None, "ETH halt", "", False, SCORED_2, SCORED_2),
                ],
                SourceState(last_success_at=FIRST),
            )
            store.write(
                "coindesk",
                [NewsItem("c", None, "BTC again", "", False, SCORED_3, SCORED_3)],
                SourceState(last_success_at=FIRST),
            )
        finally:
            store.close()

    def fill_scores(self) -> None:
        store = ScoreStore.open(str(self.root / "score.db"), FIRST)

        def scored(news_id: int, at: datetime, *scores: EventScore) -> ScoreResult:
            return ScoreResult(news_id, ResultKind.SCORED, at, MODEL, "pp", "cc", scores)

        try:
            store.write_result(
                scored(
                    1,
                    SCORED_1,
                    EventScore("BTC", "Bitcoin", "hack", "olumsuz", 3, "q"),
                    EventScore("SOL", "Solana", "hack", "olumsuz", 2, "q"),
                    EventScore("ETH", "Ether", "hack", "olumlu", 3, "q"),
                )
            )
            store.write_result(
                scored(2, SCORED_2, EventScore("ETH", "Ether", "zincir", "olumsuz", 2, "q"))
            )
            store.write_result(
                scored(3, SCORED_3, EventScore("BTC", "Bitcoin", "dava", "olumsuz", 2, "q"))
            )
        finally:
            store.close()

    def fill_shadow(self) -> None:
        rows = [
            shadow_row(SCORED_1 - H, "BTC/USDT", "bastırılmazdı", "var"),
            shadow_row(SCORED_1 - H, "ETH/USDT", "filtre yok", "yok", "skorlayıcı durmuş"),
        ]
        self.shadow_path.write_text("".join(row + "\n" for row in rows), encoding="utf-8")

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
            forward_config_path=self.root / "crytobot-forward.toml",
            console=self.console,
            clock=clock or (lambda: NOW),
            wait=lambda seconds: None,
            events_download=self.download,
        )

    @property
    def text(self) -> str:
        return self.console.getvalue()


def _without_generated(text: str) -> str:
    return "\n".join(row for row in text.splitlines() if not row.startswith(GENERATED_PREFIX))


def test_download_then_report(tmp_path: Path) -> None:
    world = World(tmp_path)
    assert world.run("forward", "download") == 0, world.text
    assert 'forward download: başladı: örnek=4 teknik "al"=1 coin=3' in world.text
    assert "SOL: USDT spot çifti yok; fiyat verisi yok" in world.text
    assert world.text.rstrip().endswith("forward download: tamam: fiyat verisi indirildi")
    assert world.run("forward", "report", "--at", REPORT_AT.isoformat()) == 0, world.text
    assert "forward report: hüküm: hüküm yok: süre yetersiz (8/90 gün)" in world.text
    text = world.report.read_text(encoding="utf-8")
    assert "ölçülmeyen: çift yok=0 ölçüm bekliyor=1" in text
    assert "kaynak: binance-duyuru=2" in text
    assert f"gölge kayıt: {world.shadow_path.as_posix()} bozuk satır=0" in text
    rows = [json.loads(row) for row in world.samples.read_text(encoding="utf-8").splitlines()]
    assert [(row.get("coin"), row.get("reason")) for row in rows[1:]] == [
        ("BTC", None),
        ("SOL", "çift yok"),
        ("ETH", None),
        ("BTC", "ölçüm bekliyor"),
    ]
    assert [row.get("source") for row in rows[1:]] == [
        "binance-duyuru",
        "binance-duyuru",
        "binance-duyuru",
        "rss",
    ]


def test_two_runs_byte_identical(tmp_path: Path) -> None:
    world = World(tmp_path)
    assert world.run("forward", "download") == 0, world.text
    at = REPORT_AT.isoformat()
    assert world.run("forward", "report", "--at", at) == 0, world.text
    first = (world.report.read_text(encoding="utf-8"), world.samples.read_bytes())
    later = NOW + timedelta(minutes=7)
    assert world.run("forward", "report", "--at", at, clock=lambda: later) == 0, world.text
    second = (world.report.read_text(encoding="utf-8"), world.samples.read_bytes())
    assert first[0] != second[0]  # the generation line differs
    assert _without_generated(first[0]) == _without_generated(second[0])
    assert first[1] == second[1]
    assert not [path for path in world.out.iterdir() if path.suffix == ".tmp"]


def test_torn_shadow_line_counted(tmp_path: Path) -> None:
    world = World(tmp_path)
    with open(world.shadow_path, "a", encoding="utf-8") as file:
        file.write('{"turn_at": "2026-11-1')
    assert world.run("forward", "download") == 0, world.text
    assert world.run("forward", "report", "--at", REPORT_AT.isoformat()) == 0, world.text
    text = world.report.read_text(encoding="utf-8")
    assert "bozuk satır=1" in text
    assert "satır=2 tur=1" in text


def test_no_shadow_section_and_no_scores(tmp_path: Path) -> None:
    """G-7: skor kaydı yokken rapor yazılır ve `hüküm yok: skor yok` der; fiyat verisi okunmaz."""
    world = World(tmp_path, shadow=False, scores=False)
    assert world.run("forward", "report") == 0, world.text
    assert "forward report: hüküm: hüküm yok: skor yok — kalan 90 gün, 30 örnek" in world.text
    text = world.report.read_text(encoding="utf-8")
    assert f"skor kaydı yok: {(tmp_path / 'score.db').as_posix()}" in text
    assert "gölge kayıt yok: bot ayarında [shadow] yok" in text
    assert not world.prices.exists() and not (tmp_path / "score.db").exists()


# --- `app` ret yolları, sahte parçalarla ---------------------------------------------------


CONFIG = load_forward_config(
    {"forward": {"price_store_path": "p.db", "report_path": "r.txt", "samples_path": "s.jsonl"}}
).config
assert CONFIG is not None


def sources(*, with_sample: bool = True) -> ForwardSources:
    results = (ScoredNews(1, SCORED, SCORED_1, (MODEL, "pp", "cc")),) if with_sample else ()
    events = (ForwardEvent(1, "BTC", "hack", "olumsuz", 2),) if with_sample else ()
    inputs = ForwardInputs(results, events, {}, None, ("BTC/USDT",))
    return ForwardSources(inputs, "score.db", 0, "news.db", None, 0)


@dataclass
class Fake:
    found: ForwardSources | str = field(default_factory=sources)
    prices: PriceData | str | None = None
    written: dict[str, str] = field(default_factory=dict)
    refuse_write: str | None = None
    lines: list[str] = field(default_factory=list)
    outcome: DownloadOutcome = DownloadOutcome.COMPLETE
    needs: list[tuple[PriceNeed, ...]] = field(default_factory=list)
    error: BaseException | None = None

    def write_file(self, path: str, text: str) -> bool:
        if path == self.refuse_write:
            return False
        self.written[path] = text
        return True

    def read_sources(self) -> ForwardSources | str:
        if self.error is not None:
            raise self.error
        return self.found

    def report_parts(self) -> ForwardReportParts:
        return ForwardReportParts(
            self.read_sources, lambda: self.prices, self.write_file, self.lines.append, lambda: NOW
        )

    def download(self, needs: tuple[PriceNeed, ...]) -> DownloadOutcome:
        self.needs.append(needs)
        return self.outcome

    def download_parts(self) -> ForwardDownloadParts:
        return ForwardDownloadParts(
            self.read_sources, self.download, self.lines.append, lambda: NOW
        )


def empty_prices(pairs: dict[str, PairInfo] | None) -> PriceData:
    return PriceData(pairs, None, {}, {}, ())


@pytest.mark.parametrize(
    ("fake", "at", "message"),
    [
        (Fake(), NOW + timedelta(seconds=1), "rapor anı gelecekte"),
        (Fake(found="skor kaydı okunamıyor"), None, "skor kaydı okunamıyor"),
        (Fake(), None, "fiyat verisi yok: p.db; önce forward download"),
        (Fake(prices="fiyat deposu okunamıyor"), None, "fiyat deposu okunamıyor"),
        (
            Fake(prices=empty_prices(None)),
            None,
            "borsa bilgisi indirilmemiş; önce forward download",
        ),
        (
            Fake(prices=empty_prices({"BTC": PairInfo("BTC", "BTCUSDT", "TRADING")})),
            None,
            "fiyat verisi eksik: 1 aralık indirilmemiş; önce forward download",
        ),
    ],
)
def test_report_refusals_write_nothing(fake: Fake, at: datetime | None, message: str) -> None:
    assert CONFIG is not None
    exit_ = run_forward_report(CONFIG, fake.report_parts(), at)
    assert (exit_.outcome, exit_.message) == (ForwardOutcome.REFUSED, message)
    assert fake.written == {}
    assert fake.lines == [f"forward report: reddedildi: {message}"]


def test_report_pair_missing_needs_no_spans_and_pending_needs_none() -> None:
    """Çifti olmayan coin `çift yok` olur, aralığı istenmez; bekleyen örnek veriye bakmaz."""
    assert CONFIG is not None
    fake = Fake(prices=empty_prices({}))
    assert run_forward_report(CONFIG, fake.report_parts()).outcome is ForwardOutcome.COMPLETED
    assert '"reason":"çift yok"' in fake.written["s.jsonl"]
    pending = Fake(prices=empty_prices({"BTC": PairInfo("BTC", "BTCUSDT", "TRADING")}))
    early = SCORED_1 + 10 * H
    assert run_forward_report(CONFIG, pending.report_parts(), early).outcome.value == "completed"
    assert '"reason":"ölçüm bekliyor"' in pending.written["s.jsonl"]


@pytest.mark.parametrize(
    ("refused", "message"),
    [("s.jsonl", "örnek dosyası yazılamadı: s.jsonl"), ("r.txt", "rapor yazılamadı: r.txt")],
)
def test_report_not_written(refused: str, message: str) -> None:
    assert CONFIG is not None
    fake = Fake(found=sources(with_sample=False), refuse_write=refused)
    exit_ = run_forward_report(CONFIG, fake.report_parts())
    assert (exit_.outcome, exit_.message) == (ForwardOutcome.NOT_WRITTEN, message)
    assert fake.lines == [f"forward report: durdu: {message}"]


def test_unexpected_error_named_by_type_and_forced_stop_raised() -> None:
    assert CONFIG is not None
    fake = Fake(error=KeyError("secret"))
    exit_ = run_forward_report(CONFIG, fake.report_parts())
    assert (exit_.outcome, exit_.message) == (ForwardOutcome.FAILED, "beklenmeyen hata: KeyError")
    assert "secret" not in "".join(fake.lines)
    forced = Fake(error=ForcedStop())
    with pytest.raises(ForcedStop):
        run_forward_download(CONFIG, forced.download_parts())
    assert forced.lines == ["forward download: durdu: zorla durdurma"]


@pytest.mark.parametrize(
    ("outcome", "expected", "line"),
    [
        (DownloadOutcome.COMPLETE, ForwardOutcome.COMPLETED, "tamam: fiyat verisi indirildi"),
        (DownloadOutcome.FAILED, ForwardOutcome.FAILED, "durdu: kaynak hatası"),
        (DownloadOutcome.STOPPED, ForwardOutcome.STOPPED, "durdu: durdurma isteği"),
    ],
)
def test_download_outcomes(outcome: DownloadOutcome, expected: ForwardOutcome, line: str) -> None:
    assert CONFIG is not None
    fake = Fake(outcome=outcome)
    assert run_forward_download(CONFIG, fake.download_parts()).outcome is expected
    (needs,) = fake.needs
    assert [need.coin for need in needs] == ["BTC"]
    assert fake.lines[-1] == f"forward download: {line}"


def test_download_without_needs_and_refused_sources() -> None:
    assert CONFIG is not None
    fake = Fake(found=sources(with_sample=False))
    exit_ = run_forward_download(CONFIG, fake.download_parts())
    assert exit_.message == "tamam: indirilecek aralık yok" and fake.needs == []
    refused = Fake(found="haber kaydı okunamıyor")
    assert run_forward_download(CONFIG, refused.download_parts()).outcome is ForwardOutcome.REFUSED


def test_unpermitted_from_config(tmp_path: Path) -> None:
    """Spec 0055 CB-4: ayarda olmayan (`coindesk`) ya da kapalı (`binance-duyuru`) kaynağın haberi
    örnek olmaz; raporda kaynak adına göre "izinsiz kaynak, hüküm dışı" satırında sayılır."""
    world = World(tmp_path)
    news = world.root / "crytobot-news.toml"
    news.write_text(news_text(world.root, ONLY_BINANCE), encoding="utf-8")
    assert world.run("forward", "download") == 0, world.text
    assert 'forward download: başladı: örnek=3 teknik "al"=1 coin=3' in world.text
    assert world.run("forward", "report", "--at", REPORT_AT.isoformat()) == 0, world.text
    text = world.report.read_text(encoding="utf-8")
    assert "izinsiz kaynak, hüküm dışı: coindesk=1" in text
    rows = [json.loads(row) for row in world.samples.read_text(encoding="utf-8").splitlines()]
    assert {row.get("source") for row in rows[1:]} == {"binance-duyuru"}
    news.write_text(news_text(world.root, ONLY_BINANCE + "enabled = false\n"), encoding="utf-8")
    assert world.run("forward", "report", "--at", REPORT_AT.isoformat()) == 0, world.text
    text = world.report.read_text(encoding="utf-8")
    assert "izinsiz kaynak, hüküm dışı: binance-duyuru=3 coindesk=1" in text
    assert "güncel üçlü: yok" in text


def test_future_permission_date_refused(tmp_path: Path) -> None:
    """Spec 0055 CB-1: rapor da izin tarihi UTC bugünden sonraki ayarı reddeder."""
    world = World(tmp_path)
    early = datetime(2026, 11, 14, 23, 59, tzinfo=UTC)
    assert world.run("forward", "report", clock=lambda: early) != 0
    assert world.text.strip() == (
        "forward report: reddedildi: ayar geçersiz: news.sources[1].ai_permission_on (gelecekte)"
    )
    assert not world.report.exists()


def test_unknown_news_source_not_permitted(tmp_path: Path) -> None:
    """Spec 0055 CB-4, review M-1: haber kaydında olmayan haberin skoru (kaynağı kanıtlanamaz)
    örnek olmaz; `bilinmiyor` adıyla sayılır."""
    world = World(tmp_path)
    store = ScoreStore.open(str(world.root / "score.db"), FIRST)
    try:
        store.write_result(
            ScoreResult(
                99,
                ResultKind.SCORED,
                SCORED_2,
                MODEL,
                "pp",
                "cc",
                (EventScore("BTC", "Bitcoin", "hack", "olumsuz", 3, "q"),),
            )
        )
    finally:
        store.close()
    assert world.run("forward", "download") == 0, world.text
    assert 'forward download: başladı: örnek=4 teknik "al"=1 coin=3' in world.text
    assert world.run("forward", "report", "--at", REPORT_AT.isoformat()) == 0, world.text
    text = world.report.read_text(encoding="utf-8")
    assert "izinsiz kaynak, hüküm dışı: bilinmiyor=1" in text
    rows = [json.loads(row) for row in world.samples.read_text(encoding="utf-8").splitlines()]
    assert 99 not in {row.get("news_id") for row in rows[1:]}


def test_no_news_record_nothing_permitted(tmp_path: Path) -> None:
    """Review M-1: haber kaydı yoksa hiçbir skorun kaynağı kanıtlanamaz: örnek yok, hüküm yok."""
    world = World(tmp_path)
    (world.root / "news.db").unlink()
    assert world.run("forward", "download") == 0, world.text
    assert 'forward download: başladı: örnek=0 teknik "al"=1' in world.text
    assert world.run("forward", "report", "--at", REPORT_AT.isoformat()) == 0, world.text
    text = world.report.read_text(encoding="utf-8")
    assert "izinsiz kaynak, hüküm dışı: bilinmiyor=4" in text
    assert "hüküm: hüküm yok: skor yok" in text
    assert "güncel üçlü: yok" in text
