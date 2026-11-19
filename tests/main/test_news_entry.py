"""Spec 0046 giriş noktası `python -m crytobot news` ve `news status` (AC-6, AC-8, AC-9).

`run` gerçek kodu koşar: gerçek ayar yükleyici, kilit, depo, tur ve durum; yalnız saat, bekleme,
getirme ve bildirim sahtedir (ağ yok).
"""

import io
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from crytobot.__main__ import (
    COMMANDS,
    EXIT_FORCED,
    EXIT_LOG_FAILED,
    EXIT_OK,
    EXIT_REFUSED,
    NEWS_BUSY,
    USAGE,
    StoreLock,
    run,
)
from crytobot.app import StopRequest
from crytobot.news import EMPTY, NEVER, Fetched, NewsSource, load_news_config
from tests.main.test_entry import config_text

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "crytobot-news.example.toml"
FIXTURES = ROOT / "tests" / "news" / "fixtures"
START = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)
BODIES = {
    "binance-duyuru": "binance.json",
    "coindesk": "coindesk.xml",
    "cointelegraph": "coindesk.xml",
}


PERMISSION_TOML = """ai_permission_by = "Test"
ai_permission_on = 2026-11-15
ai_permission_basis = "test koşulu"
"""
# Spec 0055 (plan Risk 5): the example has no permitted source; the tests run three permitted ones
# (adresler sahte getirmeye gider, ağ yok)
TEST_SOURCES = "".join(
    f'\n[[news.sources]]\nname = "{name}"\ntype = "{kind}"\nurl = "{url}"\n{PERMISSION_TOML}'
    for name, kind, url in (
        ("binance-duyuru", "binance-duyuru", "https://example.org/binance"),
        ("coindesk", "rss", "https://www.coindesk.com/arc/outboundfeeds/rss"),
        ("cointelegraph", "rss", "https://cointelegraph.com/rss"),
    )
)


def news_text(root: Path, **changes: str) -> str:
    """Örnek dosya; yollar `root`'ta. `changes`: `[news]` anahtarı → TOML değeri. Örneğin
    kaynakları çıkarılır, yerine `TEST_SOURCES` (üç izinli kaynak) eklenir."""
    values = {
        "store_path": f'"{(root / "news.db").as_posix()}"',
        "log_path": f'"{(root / "news.log").as_posix()}"',
        **changes,
    }
    rows = []
    section = ""
    for row in EXAMPLE.read_text(encoding="utf-8").splitlines():
        if row.startswith("["):
            section = row
            if row == "[[news.sources]]":
                continue
        if section == "[[news.sources]]" and "=" in row and not row.startswith("#"):
            continue
        key = row.split("=", 1)[0].strip()
        in_news = section == "[news]"
        rows.append(f"{key} = {values[key]}" if in_news and key in values and "=" in row else row)
    return "\n".join(rows) + "\n" + TEST_SOURCES


@dataclass
class Collector:
    """Bir çalışma dizini: bot ayarı, haber ayarı, sahte saat, getirme ve bildirim."""

    root: Path
    now: datetime = START
    fetched: list[str] = field(default_factory=list)
    responses: dict[str, Fetched] = field(default_factory=dict)
    stop_after_rounds: int = 1
    on_fetch: Callable[["Collector"], None] | None = None
    stop: StopRequest = field(default_factory=StopRequest)
    waits: int = 0

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.bot_config.write_text(config_text(self.root), encoding="utf-8")
        self.write(news_text(self.root))

    @property
    def bot_config(self) -> Path:
        return self.root / "crytobot.toml"

    @property
    def news_config(self) -> Path:
        return self.root / "crytobot-news.toml"

    @property
    def store(self) -> Path:
        return self.root / "news.db"

    def write(self, text: str) -> None:
        self.news_config.write_text(text, encoding="utf-8")

    def clock(self) -> datetime:
        return self.now

    def wait(self, seconds: float) -> None:
        self.waits += 1
        self.now += timedelta(seconds=seconds)
        if self.waits >= self.stop_after_rounds:
            self.stop.request("SIGINT")

    def fetch(self, source: NewsSource, _max_bytes: int, _stopped: Callable[[], bool]) -> Fetched:
        self.fetched.append(source.url)
        if self.on_fetch is not None:
            self.on_fetch(self)
        self.now += timedelta(seconds=1)
        if source.name in self.responses:
            return self.responses[source.name]
        return Fetched(body=(FIXTURES / BODIES[source.name]).read_bytes())

    def run(self, *command: str) -> tuple[int, str]:
        out = io.StringIO()
        self.stop = StopRequest()
        self.waits = 0
        code = run(
            list(command),
            config_path=self.bot_config,
            news_config_path=self.news_config,
            console=out,
            clock=self.clock,
            stop=self.stop,
            wait=self.wait,
            news_fetch=self.fetch,
        )
        return code, out.getvalue()


@pytest.fixture
def collector(tmp_path: Path) -> Collector:
    return Collector(tmp_path)


def test_example_news_config_is_valid() -> None:
    with EXAMPLE.open("rb") as file:
        result = load_news_config(tomllib.load(file))
    assert result.config is not None, result.message
    # spec 0055 CB-5 supersedes the old "binance-duyuru, rss, rss" list (0046/AC-9); spec 0056
    # AC-11 adds the closed official stream
    assert [(source.name, source.kind) for source in result.config.sources] == [
        ("binance-duyuru", "binance-duyuru"),
        ("binance-akış", "binance-akış"),
    ]


def test_example_config_has_no_unverified_open_source() -> None:
    """Spec 0055 CB-5: CoinDesk ve Cointelegraph yok, izinsiz açık kaynak yok, alanlar yorumda,
    yorumdaki RSS örneği adres içermez."""
    text = EXAMPLE.read_text(encoding="utf-8")
    with EXAMPLE.open("rb") as file:
        result = load_news_config(tomllib.load(file))
    assert result.config is not None, result.message
    assert all(not source.enabled for source in result.config.sources)
    assert result.config.permitted_names == frozenset()
    assert "coindesk" not in text.lower() and "cointelegraph" not in text.lower()
    for key in ("ai_permission_by", "ai_permission_on", "ai_permission_basis"):
        assert f"#   {key}" in text and f"# {key} = " in text
    assert '# url = "https://<akış adresi>"' in text


def test_real_news_config_is_ignored_by_git() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "crytobot-news.toml" in ignored


def test_commands_listed() -> None:
    assert ["news"] in COMMANDS and ["news", "status"] in COMMANDS
    assert "news" in USAGE


def test_collects_and_stops_cleanly(collector: Collector) -> None:
    code, console = collector.run("news")
    assert code == EXIT_OK
    assert " haber kaynak=binance-duyuru yeni=6 tekrar=0 geçersiz=0" in console
    assert " haber kaynak=cointelegraph yeni=3" in console
    log = (collector.root / "news.log").read_text(encoding="utf-8")
    assert "haber kaynak=coindesk yeni=3" in log
    assert "durdu: durdurma isteği tur_sayısı=1" in log
    assert not (collector.root / "bot.db").exists()  # the bot store is never created


def test_second_collector_refused(collector: Collector) -> None:
    """AC-8: aynı haber kaydına ikinci toplayıcı — başka yazımla da — reddedilir, istek gitmez."""
    lock = StoreLock(str(collector.store.resolve()))
    assert lock.acquire() is None
    try:
        code, console = collector.run("news")
        assert code == EXIT_REFUSED
        assert console.strip() == f"news: reddedildi: {NEWS_BUSY}"
        assert collector.fetched == []
        assert not (collector.root / "news.log").exists()
    finally:
        lock.release()


def test_second_collector_refused_other_spelling(
    collector: Collector, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(collector.root)
    lock = StoreLock(str(collector.store.resolve()))
    assert lock.acquire() is None
    try:
        collector.write(news_text(collector.root, store_path='"./news.db"'))
        code, console = collector.run("news")
        assert (code, console.strip()) == (EXIT_REFUSED, f"news: reddedildi: {NEWS_BUSY}")
    finally:
        lock.release()


def test_collector_runs_beside_bot_lock(collector: Collector) -> None:
    """Bot kilidinden ayrıdır: bot çalışırken toplama açılır."""
    bot_lock = StoreLock(str(collector.root / "bot.db"))
    assert bot_lock.acquire() is None
    try:
        assert collector.run("news")[0] == EXIT_OK
    finally:
        bot_lock.release()


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"interval_minutes": "4"}, "ayar geçersiz: news.interval_minutes"),
        ({"max_response_kb": "0"}, "ayar geçersiz: news.max_response_kb"),
        ({"source_alert_hours": "-1"}, "ayar geçersiz: news.source_alert_hours"),
    ],
)
def test_invalid_config_no_request(
    collector: Collector, changes: dict[str, str], message: str
) -> None:
    """AC-9: geçersiz ayarda ağa çıkılmaz, hiçbir dosya oluşmaz; mesaj hatanın adını verir."""
    collector.write(news_text(collector.root, **changes))
    code, console = collector.run("news")
    assert (code, console.strip()) == (EXIT_REFUSED, f"news: reddedildi: {message}")
    assert collector.fetched == []
    assert not collector.store.exists()
    assert not (collector.root / "news.log").exists()


def test_invalid_source_no_request(collector: Collector) -> None:
    text = news_text(collector.root).replace(
        'url = "https://cointelegraph.com/rss"', 'url = "http://cointelegraph.com/rss"'
    )
    collector.write(text)
    code, console = collector.run("news")
    assert code == EXIT_REFUSED
    assert console.strip() == "news: reddedildi: ayar geçersiz: news.sources[3].url (https değil)"
    assert collector.fetched == []


@pytest.mark.parametrize(
    ("key", "path", "message"),
    [
        ("store_path", "bot.db", "ayar geçersiz: news.store_path"),
        ("store_path", "bot.log", "ayar geçersiz: news.store_path"),
        ("log_path", "bot.log", "ayar geçersiz: news.log_path"),
        ("log_path", "bot.db", "ayar geçersiz: news.log_path"),
        ("log_path", "./news.db", "ayar geçersiz: news.log_path"),
    ],
)
def test_bot_files_refused_any_spelling(
    collector: Collector, monkeypatch: pytest.MonkeyPatch, key: str, path: str, message: str
) -> None:
    monkeypatch.chdir(collector.root)
    collector.write(news_text(collector.root, **{key: f'"{path}"'}))
    if key == "log_path":
        collector.write(news_text(collector.root, store_path='"news.db"', log_path=f'"{path}"'))
    code, console = collector.run("news")
    assert (code, console.strip()) == (EXIT_REFUSED, f"news: reddedildi: {message}")
    assert collector.fetched == []


def test_missing_news_config(collector: Collector) -> None:
    collector.news_config.unlink()
    code, console = collector.run("news")
    assert (code, console.strip()) == (
        EXIT_REFUSED,
        "news: reddedildi: ayar dosyası yok: crytobot-news.toml",
    )


def test_missing_bot_config_is_fine(collector: Collector) -> None:
    collector.bot_config.unlink()
    assert collector.run("news")[0] == EXIT_OK


def test_status_makes_no_request(collector: Collector) -> None:
    """AC-6: durum komutu ağa çıkmaz, kilit almaz (toplayıcı çalışırken de açılır)."""
    collector.responses["coindesk"] = Fetched(error="http_503")
    collector.run("news")
    collector.fetched.clear()
    lock = StoreLock(str(collector.store.resolve()))
    assert lock.acquire() is None
    try:
        code, console = collector.run("news", "status")
    finally:
        lock.release()
    assert code == EXIT_OK
    assert collector.fetched == []
    rows = console.splitlines()
    assert rows[0] == (
        f"kaynak=binance-duyuru son_başarı={(START + timedelta(seconds=1)).isoformat()}"
        " son_hata=yok kayıt=6"
    )
    assert rows[1] == (
        f"kaynak=coindesk son_başarı={NEVER}"
        f" son_hata=http_503@{(START + timedelta(seconds=2)).isoformat()} kayıt=0"
    )
    assert rows[3].startswith("toplam: kayıt=9 boyut=")


def test_status_empty_store_exit_0(collector: Collector) -> None:
    code, console = collector.run("news", "status")
    assert code == EXIT_OK
    assert console.splitlines()[-1] == f"{EMPTY} boyut=0 bayt"
    assert not collector.store.exists()


def test_status_unreadable_store_exit_1(collector: Collector) -> None:
    collector.store.write_bytes(b"not sqlite" * 100)
    code, console = collector.run("news", "status")
    assert (code, console.strip()) == (EXIT_REFUSED, "news: reddedildi: haber kaydı okunamıyor")


def test_unopenable_store_refused(collector: Collector) -> None:
    collector.store.write_bytes(b"not sqlite" * 100)
    code, console = collector.run("news")
    assert code == EXIT_REFUSED
    assert console.strip().endswith("haber reddedildi: haber kaydı açılamıyor")
    assert collector.fetched == []


def test_forced_stop_exit_130(collector: Collector) -> None:
    def force(current: Collector) -> None:
        current.stop.request("SIGINT")
        current.stop.request("SIGINT")

    collector.on_fetch = force
    code, _ = collector.run("news")
    assert code == EXIT_FORCED
    # the lock is released: a new collector opens
    collector.on_fetch = None
    assert collector.run("news")[0] == EXIT_OK


def test_log_unwritable_exit_3(collector: Collector) -> None:
    (collector.root / "logdir").mkdir()
    collector.write(
        news_text(collector.root, log_path=f'"{(collector.root / "logdir").as_posix()}"')
    )
    code, console = collector.run("news")
    assert code == EXIT_LOG_FAILED
    assert "kayıt dosyası yazılamıyor: toplama durdu" in console


def test_telegram_shutdown_reason_in_news_log(collector: Collector) -> None:
    """Review round 1 F-4: gerçek `ReportingService`; kalıcı hata (401) Telegram'ı kapatır, neden
    haber kaydı satırındadır, token hiçbir satırda yoktur."""
    from crytobot.reporting import ReportingService, TelegramConfig

    service = ReportingService(
        TelegramConfig(enabled=True, bot_token="123:SECRETTOKEN", chat_id="42"),
        transport=lambda _url, _payload: (401, '{"ok":false,"description":"Unauthorized"}'),
    )
    text = news_text(collector.root, source_alert_hours="1")
    collector.write(text.replace("interval_minutes = 15", "interval_minutes = 30"))
    collector.responses["coindesk"] = Fetched(error="http_503")
    collector.stop_after_rounds = 4
    out = io.StringIO()
    collector.stop = StopRequest()
    code = run(
        ["news"],
        config_path=collector.bot_config,
        news_config_path=collector.news_config,
        console=out,
        clock=collector.clock,
        stop=collector.stop,
        wait=collector.wait,
        news_fetch=collector.fetch,
        reporter=service,
    )
    assert code == EXIT_OK
    log = (collector.root / "news.log").read_text(encoding="utf-8")
    assert "bildirim=giriş" in log
    assert "telegram devre dışı (" in log
    assert "SECRETTOKEN" not in log and "SECRETTOKEN" not in out.getvalue()


def test_future_permission_date_refused(collector: Collector) -> None:
    """Spec 0055 CB-1, plan Risk 2: izin tarihi UTC bugünden sonra olamaz; yerel saatte aynı gün
    olsa bile. Ağa çıkılmaz, kayıt oluşmaz."""
    collector.now = datetime(2026, 11, 15, 1, 0, tzinfo=timezone(timedelta(hours=3)))
    for command in (("news",), ("news", "status")):
        code, console = collector.run(*command)
        assert (code, console.strip()) == (
            EXIT_REFUSED,
            "news: reddedildi: ayar geçersiz: news.sources[1].ai_permission_on (gelecekte)",
        )
    assert collector.fetched == []
    assert not collector.store.exists()


def test_example_config_stream_closed_documented() -> None:
    """Spec 0056 AC-11: akış kaynağı kapalı ve izin kaydısız; yorumda iki değişkenin adı, yalnız
    okuma kuralı ve iznin sahibe ait olduğu; `.env.example` yalnız adları taşır."""
    text = EXAMPLE.read_text(encoding="utf-8")
    with EXAMPLE.open("rb") as file:
        result = load_news_config(tomllib.load(file))
    assert result.config is not None, result.message
    (stream,) = [s for s in result.config.sources if s.kind == "binance-akış"]
    assert (stream.enabled, stream.permission, stream.url) == (
        False,
        None,
        "wss://api.binance.com/sapi/wss",
    )
    for needle in ("BINANCE_NEWS_API_KEY", "BINANCE_NEWS_API_SECRET", "Enable Reading"):
        assert needle in text
    assert "izin kararı sahibindir" in text
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    values = {
        name.strip(): value.strip()
        for name, value in (
            row.split("=", 1) for row in env_example.splitlines() if "=" in row and row[0] != "#"
        )
    }
    assert values["BINANCE_NEWS_API_KEY"].startswith("your_")
    assert values["BINANCE_NEWS_API_SECRET"].startswith("your_")
