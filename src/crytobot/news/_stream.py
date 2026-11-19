"""Akış yöneticisi (spec 0056 R-2, R-5, R-6, AC-2, AC-5, AC-10; plan Risk 5, 6, 7, A-1).

Kendi iş parçacığında koşar; gerçek etkiler (saat, bekleme, bağlantı, yetki okuma, durdurma)
`StreamParts` ile gelir. Her bağlantıdan önce yetki denetlenir: fazla yetki ölümcüldür (koşu biter,
toplayıcı durur); doğrulanamayan yetki bağlantısız beklemedir. Bağlantı kurulamaz ya da koparsa
bekleme 5 sn'den başlar, her ardışık hatada iki katına çıkar, en çok 15 dk; başarılı bağlantıda 5
sn'ye döner. Bağlantı 24 saat dolmadan yenilenir; canlılık iletisi 30 sn'den sık gider (sağlayıcı
saniyede en çok 5 ileti kabul eder). Kopukluk (ilk bağlantıdan önce ve koptuktan sonra bağlanana
kadar) bitince `kaynak=<ad> kopukluk=<n>s` satırı. Alınan metin iletileri alınma anıyla kuyruğa
girer; kayda yalnız tur yazar (`drain`).
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol

from crytobot.news._binance_auth import PermissionCheck, Verdict

FIRST_DELAY_S: Final = 5.0
MAX_DELAY_S: Final = 900.0
PING_EVERY_S: Final = 25.0
RENEW_AFTER_S: Final = 23 * 3600 + 50 * 60  # the provider closes a connection at 24 h
RECV_TIMEOUT_S: Final = 1.0


class ConnectionLost(Exception):
    """`name`: satıra yazılan hata adı (değer ya da adres taşımaz)."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


class Connection(Protocol):
    def recv(self, timeout: float) -> str | None:
        """Bir metin iletisi; süre dolarsa `None`; bağlantı koptuysa `ConnectionLost`."""
        ...

    def ping(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class StreamParts:
    """`wait` en çok verilen süre bekler, durdurma istendiyse `True` döner."""

    clock: Callable[[], datetime]
    monotonic: Callable[[], float]
    wait: Callable[[float], bool]
    stopped: Callable[[], bool]
    connect: Callable[[], Connection]
    check_permissions: Callable[[], PermissionCheck]
    say: Callable[[str], None]


@dataclass(frozen=True)
class StreamStatus:
    connected: bool
    last_connected_at: datetime | None
    gap_started_at: datetime | None
    gap_total: timedelta
    fatal: PermissionCheck | None = None


def seconds(span: timedelta) -> str:
    return f"{int(span.total_seconds())}s"


class StreamRunner:
    """Bir akış kaynağının bağlantısı. `run` iş parçacığında; `drain` ve `status` turdan."""

    def __init__(
        self,
        name: str,
        parts: StreamParts,
        last_connected_at: datetime | None = None,
        gap_total: timedelta = timedelta(0),
    ) -> None:
        self.name = name
        self.parts = parts
        self._lock = threading.Lock()
        self._queue: list[tuple[str, datetime]] = []
        self._connected = False
        self._last_connected_at = last_connected_at
        self._gap_started_at: datetime | None = parts.clock()
        self._gap_total = gap_total
        self._fatal: PermissionCheck | None = None
        self._delay = FIRST_DELAY_S

    def drain(self) -> list[tuple[str, datetime]]:
        with self._lock:
            taken, self._queue = self._queue, []
        return taken

    def status(self) -> StreamStatus:
        with self._lock:
            return StreamStatus(
                self._connected,
                self._last_connected_at,
                self._gap_started_at,
                self._gap_total,
                self._fatal,
            )

    def _say(self, text: str) -> None:
        self.parts.say(f"kaynak={self.name} {text}")

    def _back_off(self) -> bool:
        """Bekler, sonraki beklemeyi iki katına çıkarır; durdurma istendiyse `True`."""
        stop = self.parts.wait(self._delay)
        self._delay = min(self._delay * 2, MAX_DELAY_S)
        return stop

    def _opened(self) -> None:
        now = self.parts.clock()
        with self._lock:
            started = self._gap_started_at
            gap = timedelta(0) if started is None else max(now - started, timedelta(0))
            self._gap_total += gap
            self._gap_started_at = None
            self._connected = True
            self._last_connected_at = now
        self._delay = FIRST_DELAY_S
        self._say(f"kopukluk={seconds(gap)}")

    def _closed(self) -> None:
        with self._lock:
            self._connected = False
            self._gap_started_at = self.parts.clock()

    def run(self) -> None:
        """Durdurulana ya da fazla yetki görülene kadar."""
        while not self.parts.stopped():
            check = self.parts.check_permissions()
            if check.verdict is Verdict.EXCESS:
                with self._lock:
                    self._fatal = check
                return
            if check.verdict is not Verdict.READ_ONLY:
                self._say(f"hata={check.message}")
                if self._back_off():
                    return
                continue
            try:
                connection = self.parts.connect()
            except ConnectionLost as lost:
                self._say(f"hata={lost.name}")
                if self._back_off():
                    return
                continue
            self._opened()
            stopped = self._read(connection)
            self._closed()
            if stopped or self.parts.wait(self._delay):
                return

    def _read(self, connection: Connection) -> bool:
        """Bağlantı açıkken; durdurma istendiyse `True`. Her durumda bağlantı kapanır."""
        opened = last_ping = self.parts.monotonic()
        try:
            while True:
                if self.parts.stopped():
                    return True
                now = self.parts.monotonic()
                if now - opened >= RENEW_AFTER_S:
                    self._say("bağlantı yenileniyor (24 saat)")
                    return False
                if now - last_ping >= PING_EVERY_S:
                    connection.ping()
                    last_ping = now
                text = connection.recv(RECV_TIMEOUT_S)
                if text is not None:
                    with self._lock:
                        self._queue.append((text, self.parts.clock()))
        except ConnectionLost as lost:
            self._say(f"hata={lost.name}")
            return False
        finally:
            connection.close()
