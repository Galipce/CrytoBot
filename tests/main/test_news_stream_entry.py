"""Spec 0056 giriş noktası: `news` ve `news status` açık ya da kapalı akış kaynağıyla (AC-1, AC-2,
AC-7, AC-8, AC-10, PB-1).

`run` gerçek kodu koşar (ayar, kilit, depo, tur, akış yöneticisi ve iş parçacığı); yalnız saat,
toplayıcı beklemesi, RSS getirme, akış bağlantısı ve yetki yanıtı sahtedir (ağ yok). Anahtarlar
değeri bilinen sahte dizgilerdir; çıktıların hepsi onlara karşı taranır.
"""

import io
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crytobot.__main__ import EXIT_FORCED, EXIT_OK, EXIT_REFUSED, NewsStreamIO, run
from crytobot.app import StopRequest
from crytobot.news import ConnectionLost, Fetched, NewsSource, StreamKeys
from tests.main.test_entry import config_text
from tests.news.test_stream_parse import message

START = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
FIXTURES = Path(__file__).resolve().parents[1] / "news" / "fixtures"
KEY = "FAKEKEY-0123456789abcdefFAKEKEY"
SECRET = "FAKESECRET-9876543210fedcbaFAKESECRET"
PERMISSION = 'ai_permission_by = "Test"\nai_permission_on = 2026-11-19\nai_permission_basis = "t"\n'
READ_ONLY = {"enableReading": True, "enableWithdrawals": False, "ipRestrict": False}
REGISTER = '{"type":"COMMAND","subType":"REGISTER","data":"SUCCESS","code":"00000000"}'


def stream_block(enabled: bool = True) -> str:
    return (
        '\n[[news.sources]]\nname = "akış"\ntype = "binance-akış"\n'
        'url = "wss://api.binance.com/sapi/wss"\n'
        f"enabled = {'true' if enabled else 'false'}\n{PERMISSION if enabled else ''}"
    )


def rss_block() -> str:
    return (
        '\n[[news.sources]]\nname = "coindesk"\ntype = "rss"\n'
        f'url = "https://www.coindesk.com/arc/outboundfeeds/rss"\n{PERMISSION}'
    )


@dataclass
class FakeSocket:
    """Betikli bağlantı: iletiler sırayla, sonra sessiz; `close` kaydedilir."""

    script: list[str]
    closed: bool = False
    hold: threading.Event | None = None  # set: recv hangs until released (a stuck connection)

    def recv(self, timeout: float) -> str | None:
        time.sleep(0.01)
        if self.hold is not None and not self.script:
            self.hold.wait(10)
        if self.closed:
            raise ConnectionLost("kapandı")
        return self.script.pop(0) if self.script else None

    def ping(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


@dataclass
class World:
    root: Path
    sources: str = ""
    env: dict[str, str] = field(
        default_factory=lambda: {"BINANCE_NEWS_API_KEY": KEY, "BINANCE_NEWS_API_SECRET": SECRET}
    )
    permissions: dict[str, object] = field(default_factory=lambda: dict(READ_ONLY))
    script: list[str] = field(default_factory=lambda: [REGISTER, message()])
    connect_error: str | None = None
    now: datetime = START
    rounds_before_stop: int = 2
    force: bool = False
    stop: StopRequest = field(default_factory=StopRequest)
    sockets: list[FakeSocket] = field(default_factory=list)
    restriction_calls: int = 0
    fetched: list[str] = field(default_factory=list)
    waits: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    hold: threading.Event | None = None
    restrictions_block: threading.Event | None = None
    restrictions_error: Exception | None = None
    check_timeout_s: float = 40.0
    first_fetch_at: float | None = None

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "crytobot.toml").write_text(config_text(self.root), encoding="utf-8")
        self.write(self.sources or stream_block())

    def write(self, sources: str) -> None:
        text = (
            "[news]\n"
            f'store_path = "{(self.root / "news.db").as_posix()}"\n'
            f'log_path = "{(self.root / "news.log").as_posix()}"\n'
            f"{sources}"
        )
        (self.root / "crytobot-news.toml").write_text(text, encoding="utf-8")

    def clock(self) -> datetime:
        with self.lock:
            return self.now

    def wait(self, seconds: float) -> None:
        time.sleep(0.3)  # the stream thread delivers its messages in real time
        self.waits += 1
        with self.lock:
            self.now += timedelta(seconds=seconds)
        if self.waits >= self.rounds_before_stop:
            self.stop.request("SIGINT")

    def fetch(self, source: NewsSource, max_bytes: int, stopped: object) -> Fetched:
        self.fetched.append(source.name)
        if self.first_fetch_at is None:
            self.first_fetch_at = time.monotonic()
        if self.force:
            self.stop.request("SIGINT")
            self.stop.request("SIGINT")
        return Fetched(body=(FIXTURES / "coindesk.xml").read_bytes())

    def restrictions(self, url: str, keys: StreamKeys, now_ms: int) -> bytes | None:
        assert keys.values == (KEY, SECRET) and url.startswith("wss://")
        self.restriction_calls += 1
        if self.restrictions_block is not None:
            self.restrictions_block.wait(10)  # a stuck request (name lookup)
        if self.restrictions_error is not None:
            raise self.restrictions_error
        return json.dumps(self.permissions).encode()

    def connect(self, url: str, keys: StreamKeys, now_ms: int) -> FakeSocket:
        if self.connect_error is not None:
            raise ConnectionLost(self.connect_error)
        socket_ = FakeSocket(list(self.script), hold=self.hold)
        self.sockets.append(socket_)
        return socket_

    def run(self, *command: str) -> tuple[int, str]:
        out = io.StringIO()
        self.stop = StopRequest() if not self.stop.requested else self.stop
        code = run(
            list(command),
            config_path=self.root / "crytobot.toml",
            news_config_path=self.root / "crytobot-news.toml",
            console=out,
            clock=self.clock,
            stop=self.stop,
            wait=self.wait,
            news_fetch=self.fetch,
            news_stream=NewsStreamIO(
                self.connect,
                self.restrictions,
                self.env,
                None,
                first_wait_s=2.0,
                check_timeout_s=self.check_timeout_s,
            ),
        )
        return code, out.getvalue()

    def outputs(self) -> list[bytes]:
        found = [path.read_bytes() for path in self.root.iterdir() if path.is_file()]
        return found


def test_collects_stream_and_stops_cleanly(tmp_path: Path) -> None:
    """AC-3 uçtan uca, AC-10: duyuru yazılır; Ctrl+C bağlantıyı kapatır, çıkış 0."""
    world = World(tmp_path / "w")
    code, console = world.run("news")
    assert code == EXIT_OK, console
    assert "haber kaynak=akış kopukluk=0s" in console
    assert "haber kaynak=akış yeni=1 tekrar=0 geçersiz=0" in console
    assert "durdu: durdurma isteği tur_sayısı=2" in console
    assert len(world.sockets) == 1 and world.sockets[0].closed
    assert world.restriction_calls == 2  # before the lock, and before the connection


def test_missing_env_refused_no_request(tmp_path: Path) -> None:
    """AC-1: ortamda değişken yoksa hiçbir kaynağa istek gitmeden ret; kayıt oluşmaz."""
    world = World(tmp_path / "w", sources=stream_block() + rss_block(), env={})
    code, console = world.run("news")
    assert (code, console.strip()) == (
        EXIT_REFUSED,
        "news: reddedildi: ortam değişkeni yok: BINANCE_NEWS_API_KEY",
    )
    assert (world.restriction_calls, world.sockets, world.fetched) == (0, [], [])
    assert not (world.root / "news.db").exists()


def test_closed_stream_no_key_no_connection(tmp_path: Path) -> None:
    """AC-1: kapalı akış kaynağı anahtar istemez, bağlanılmaz."""
    world = World(tmp_path / "w", sources=stream_block(enabled=False) + rss_block(), env={})
    code, console = world.run("news")
    assert code == EXIT_OK, console
    assert world.fetched == ["coindesk", "coindesk"]
    assert (world.restriction_calls, world.sockets) == (0, [])


def test_no_stream_source_no_connection(tmp_path: Path) -> None:
    """PB-1: akış kaynağı olmayan ayarla bugünkü gibi; Binance'e bağlanılmaz, anahtar istenmez."""
    world = World(tmp_path / "w", sources=rss_block(), env={})
    code, console = world.run("news")
    assert code == EXIT_OK, console
    assert "haber kaynak=coindesk yeni=3 tekrar=0 geçersiz=0" in console
    assert (world.restriction_calls, world.sockets) == (0, [])


def test_excess_permission_exit_1(tmp_path: Path) -> None:
    """AC-2: başlangıçta fazla yetki: hiçbir kaynak sorgulanmadan çıkış 1; kayıt oluşmaz."""
    world = World(tmp_path / "w", sources=stream_block() + rss_block())
    world.permissions["enableWithdrawals"] = True
    code, console = world.run("news")
    assert (code, console.strip()) == (
        EXIT_REFUSED,
        "news: reddedildi: anahtar yetkisi fazla: enableWithdrawals",
    )
    assert (world.sockets, world.fetched) == ([], [])
    assert not (world.root / "news.db").exists()


def test_status_no_network_no_key(tmp_path: Path) -> None:
    """AC-8: durum ağa çıkmaz, anahtar okumaz; kayıttaki bağlantı durumunu gösterir."""
    world = World(tmp_path / "w")
    assert world.run("news")[0] == EXIT_OK
    calls = world.restriction_calls
    world.env = {}
    world.stop = StopRequest()
    code, console = world.run("news", "status")
    assert code == EXIT_OK, console
    (line,) = [row for row in console.splitlines() if row.startswith("kaynak=akış")]
    assert " kayıt=1 bağlantı=bağlı son_bağlantı=" in line and "kopukluk_toplam=0s" in line
    assert world.restriction_calls == calls and len(world.sockets) == 1


def test_stop_and_forced_stop(tmp_path: Path) -> None:
    """AC-10, review round 1 L-4 / round 2 M-1: ikinci Ctrl+C zorla durdurur (130) ve takılı bir
    bağlantıyı beklemez; bağlantı, akış iş parçacığı serbest kalınca yine kapanır."""
    hold = threading.Event()
    world = World(tmp_path / "w", sources=stream_block() + rss_block(), force=True, hold=hold)
    started = time.monotonic()
    code, _ = world.run("news")
    elapsed = time.monotonic() - started
    try:
        assert code == EXIT_FORCED
        # a join would wait 5 s on the stuck connection; the forced stop returns at once
        assert elapsed < 4.0, elapsed
        assert len(world.sockets) == 1 and not world.sockets[0].closed  # still stuck: not joined
    finally:
        hold.set()
    deadline = time.monotonic() + 3.0
    while not world.sockets[0].closed and time.monotonic() < deadline:
        time.sleep(0.02)
    assert world.sockets[0].closed  # the stream thread closes it once released


def test_startup_check_bounded_and_failure_unverified(tmp_path: Path) -> None:
    """Review round 1 L-3 / round 2 L-1: başlangıç yetki denetimi takılırsa ya da istisna atarsa
    doğrulanamadı sayılır — çıkış 1 değil; diğer kaynakların turu sürer."""
    block = threading.Event()
    world = World(tmp_path / "w", sources=stream_block() + rss_block(), check_timeout_s=0.2)
    world.restrictions_block = block
    started = time.monotonic()
    try:
        code, console = world.run("news")
    finally:
        block.set()
    assert code == EXIT_OK, console
    # the stuck check blocks for 10 s; bounded at 0.2 s (+ 2 s first wait) the round starts early
    assert world.first_fetch_at is not None and world.first_fetch_at - started < 6.0
    assert "haber kaynak=coindesk yeni=3" in console
    assert "news: reddedildi" not in console
    world = World(tmp_path / "w2", sources=stream_block() + rss_block())
    world.restrictions_error = RuntimeError("library failure")
    code, console = world.run("news")
    assert code == EXIT_OK, console
    assert "haber kaynak=akış hata=anahtar yetkisi doğrulanamadı" in console
    assert "haber kaynak=coindesk yeni=3" in console and world.sockets == []


def test_no_secret_in_any_output(tmp_path: Path) -> None:
    """AC-7: anahtar değerleri hiçbir satırda, kayıtta, dosyada ve durum çıktısında yok — bağlantı
    hatası metni değeri taşısa bile."""
    world = World(tmp_path / "w", connect_error=f"bağlanamadı {KEY} {SECRET}", rounds_before_stop=1)
    code, console = world.run("news")
    assert code == EXIT_OK
    assert "haber kaynak=akış hata=bağlanamadı <gizli> <gizli>" in console
    world.connect_error = None
    world.stop = StopRequest()
    status = world.run("news", "status")[1]
    world.env = {}
    refused = world.run("news")[1]
    for text in (console, status, refused):
        assert KEY not in text and SECRET not in text
    for blob in world.outputs():
        assert KEY.encode() not in blob and SECRET.encode() not in blob


@pytest.mark.parametrize("kind", ["binance-akış"])
def test_stream_kind_requires_wss_in_entry(tmp_path: Path, kind: str) -> None:
    world = World(tmp_path / "w", sources=stream_block().replace("wss://", "https://"))
    code, console = world.run("news")
    assert (code, console.strip()) == (
        EXIT_REFUSED,
        "news: reddedildi: ayar geçersiz: news.sources[1].url (wss değil)",
    )
