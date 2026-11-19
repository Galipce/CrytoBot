"""Spec 0056 AC-2, AC-5, AC-10: akış yöneticisi sahte bağlantı, sahte saat ve sahte yetkiyle."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from crytobot.news._binance_auth import UNVERIFIED, PermissionCheck, Verdict
from crytobot.news._stream import (
    FIRST_DELAY_S,
    MAX_DELAY_S,
    PING_EVERY_S,
    RENEW_AFTER_S,
    Connection,
    ConnectionLost,
    StreamParts,
    StreamRunner,
)

T0 = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
READ_ONLY = PermissionCheck(Verdict.READ_ONLY)
EXCESS = PermissionCheck(Verdict.EXCESS, ("enableWithdrawals",))

# a scripted connection: each step is a message, None (quiet second), or "LOST"
Script = list[str | None]


@dataclass
class FakeConnection:
    world: "World"
    script: Script
    pings: int = 0
    closed: bool = False

    def recv(self, timeout: float) -> str | None:
        self.world.now += timeout
        if self.world.stop_at is not None and self.world.now >= self.world.stop_at:
            self.world.stop_requested = True
        if not self.script:
            return None
        step = self.script.pop(0)
        if step == "LOST":
            raise ConnectionLost("bağlantı koptu")
        return step

    def ping(self) -> None:
        self.pings += 1

    def close(self) -> None:
        self.closed = True


@dataclass
class World:
    """Saat saniye cinsinden; `attempts` her bağlanma girişiminin sonucu: betik ya da hata adı."""

    attempts: list[Script | str] = field(default_factory=list)
    checks: list[PermissionCheck] = field(default_factory=list)
    now: float = 0.0
    waits: list[float] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    connections: list[FakeConnection] = field(default_factory=list)
    stop_requested: bool = False
    stop_at: float | None = None
    max_waits: int = 50

    def clock(self) -> datetime:
        return T0 + timedelta(seconds=self.now)

    def wait(self, seconds: float) -> bool:
        self.waits.append(seconds)
        self.now += seconds
        if len(self.waits) >= self.max_waits or (not self.attempts and not self.checks):
            self.stop_requested = True
        return self.stop_requested

    def connect(self) -> Connection:
        attempt = self.attempts.pop(0) if self.attempts else "bağlanamadı"
        if isinstance(attempt, str):
            raise ConnectionLost(attempt)
        connection = FakeConnection(self, attempt)
        self.connections.append(connection)
        return connection

    def check(self) -> PermissionCheck:
        return self.checks.pop(0) if self.checks else READ_ONLY

    def runner(self, check: Callable[[], PermissionCheck] | None = None) -> StreamRunner:
        parts = StreamParts(
            self.clock,
            lambda: self.now,
            self.wait,
            lambda: self.stop_requested,
            self.connect,
            check or self.check,
            self.lines.append,
        )
        return StreamRunner("akış", parts)


def test_messages_queued_with_receive_time() -> None:
    world = World(attempts=[["a", None, "b", "LOST"]])
    runner = world.runner()
    runner.run()
    taken = runner.drain()
    assert [text for text, _ in taken] == ["a", "b"]
    assert taken[0][1] == T0 + timedelta(seconds=1)
    assert runner.drain() == []


def test_backoff_doubles_caps_resets() -> None:
    """AC-5: 5, 10, 20 … 900'de sabit; başarılı bağlantıdan sonra yine 5."""
    failures = ["bağlanamadı"] * 10
    world = World(attempts=[*failures, ["LOST"], "bağlanamadı", "bağlanamadı"])
    world.runner().run()
    expected = [5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 320.0, 640.0, 900.0, 900.0]
    assert world.waits[: len(expected)] == expected
    assert world.waits[len(expected) :][:3] == [5.0, 5.0, 10.0]
    assert world.waits[0] == FIRST_DELAY_S and max(world.waits) == MAX_DELAY_S
    assert world.lines.count("kaynak=akış hata=bağlanamadı") == 12


def test_gap_line_written() -> None:
    """AC-5: her kopukluk bitince süresiyle satır; toplam durumda."""
    world = World(attempts=["bağlanamadı", [None, "LOST"], ["LOST"]])
    runner = world.runner()
    runner.run()
    gaps = [line for line in world.lines if "kopukluk=" in line]
    # start → 5 s wait → connected; 2 s connected, lost → 5 s wait → connected
    assert gaps == ["kaynak=akış kopukluk=5s", "kaynak=akış kopukluk=5s"]
    status = runner.status()
    assert status.gap_total == timedelta(seconds=10)
    assert status.connected is False and status.gap_started_at is not None
    assert status.last_connected_at == T0 + timedelta(seconds=12)


def test_unverified_waits_others_continue() -> None:
    """AC-2: doğrulanamayan yetki bağlantısız beklemedir; doğrulanınca bağlanılır."""
    world = World(checks=[UNVERIFIED, UNVERIFIED, READ_ONLY], attempts=[["x", "LOST"]])
    runner = world.runner()
    runner.run()
    assert world.lines[:2] == ["kaynak=akış hata=anahtar yetkisi doğrulanamadı"] * 2
    assert world.waits[:2] == [5.0, 10.0]
    assert len(world.connections) == 1 and runner.status().fatal is None
    assert [text for text, _ in runner.drain()] == ["x"]


def test_excess_on_reconnect_stops() -> None:
    """AC-2: yeniden bağlanmada fazla yetki görülürse koşu biter, bağlanılmaz; durum ölümcül."""
    world = World(checks=[READ_ONLY, EXCESS], attempts=[["LOST"], ["never"]])
    runner = world.runner()
    runner.run()
    assert len(world.connections) == 1
    assert runner.status().fatal == EXCESS


def test_excess_at_start_never_connects() -> None:
    world = World(checks=[EXCESS], attempts=[["never"]])
    runner = world.runner()
    runner.run()
    assert world.connections == [] and runner.status().fatal == EXCESS


def test_ping_and_daily_renewal() -> None:
    """Canlılık iletisi 30 sn'den sık; bağlantı 24 saat dolmadan yenilenir."""
    quiet: Script = [None] * int(RENEW_AFTER_S + 5)
    world = World(attempts=[quiet, ["LOST"]])
    world.runner().run()
    first = world.connections[0]
    assert first.closed
    # at least one liveness message every 30 s over the whole connection
    assert first.pings >= RENEW_AFTER_S / 30 and PING_EVERY_S < 30
    assert "kaynak=akış bağlantı yenileniyor (24 saat)" in world.lines
    assert len(world.connections) == 2


def test_stop_closes_connection() -> None:
    """AC-10: durdurma isteği bağlantıyı kapatır, yeniden bağlanılmaz."""
    world = World(attempts=[[None] * 100, ["never"]], stop_at=3.0)
    world.runner().run()
    assert len(world.connections) == 1 and world.connections[0].closed
