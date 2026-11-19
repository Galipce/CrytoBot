"""Spec 0056 AC-2, AC-5, AC-10 (review round 1 M-1, M-3, L-1, L-5): akış yöneticisi sahte bağlantı,
sahte saat ve sahte yetkiyle."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from crytobot.news._binance_auth import UNVERIFIED, PermissionCheck, Verdict
from crytobot.news._stream import (
    CONTROL_FRAME,
    FIRST_DELAY_S,
    LIVENESS_S,
    MAX_DELAY_S,
    PING_EVERY_S,
    REGISTER_WITHIN_S,
    RENEW_AFTER_S,
    Connection,
    ConnectionLost,
    StreamParts,
    StreamRunner,
)

T0 = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
READ_ONLY = PermissionCheck(Verdict.READ_ONLY)
EXCESS = PermissionCheck(Verdict.EXCESS, ("enableWithdrawals",))
REG = '{"type":"COMMAND","subType":"REGISTER","data":"SUCCESS","code":"00000000"}'
REG_BAD = '{"type":"COMMAND","subType":"REGISTER","data":"FAIL","code":"10001"}'

# a scripted connection: each step is a message, None (quiet second), "LOST", or "BOOM"
Script = list[str | None]


@dataclass
class FakeConnection:
    world: "World"
    script: Script
    pings: int = 0
    closed: bool = False
    pong_due: bool = False

    def recv(self, timeout: float) -> str | None:
        self.world.now += timeout
        if self.world.stop_at is not None and self.world.now >= self.world.stop_at:
            self.world.stop_requested = True
        if self.pong_due:
            self.pong_due = False
            return CONTROL_FRAME
        if not self.script:
            return None
        step = self.script.pop(0)
        if step == "LOST":
            raise ConnectionLost("bağlantı koptu")
        if step == "BOOM":
            raise RuntimeError("library failure")
        return step

    def ping(self) -> None:
        self.pings += 1
        self.pong_due = self.world.pongs

    def close(self) -> None:
        self.closed = True


@dataclass
class World:
    """Saat saniye cinsinden; `attempts` her bağlanma girişiminin sonucu: betik, hata adı ya da
    `Exception` örneği."""

    attempts: list[Script | str | Exception] = field(default_factory=list)
    checks: list[PermissionCheck | Exception] = field(default_factory=list)
    now: float = 0.0
    waits: list[float] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    connections: list[FakeConnection] = field(default_factory=list)
    stop_requested: bool = False
    stop_at: float | None = None
    max_waits: int = 50
    pongs: bool = True

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
        if isinstance(attempt, Exception):
            raise attempt
        if isinstance(attempt, str):
            raise ConnectionLost(attempt)
        connection = FakeConnection(self, attempt)
        self.connections.append(connection)
        return connection

    def check(self) -> PermissionCheck:
        found = self.checks.pop(0) if self.checks else READ_ONLY
        if isinstance(found, Exception):
            raise found
        return found

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


def quiet(seconds: int) -> Script:
    return [None] * seconds


def test_messages_queued_with_receive_time() -> None:
    world = World(attempts=[[REG, "a", None, "b", "LOST"]])
    runner = world.runner()
    runner.run()
    taken = runner.drain()
    assert [text for text, _ in taken] == ["a", "b"]  # the registration is not queued
    assert taken[0][1] == T0 + timedelta(seconds=2)
    assert runner.drain() == []


def test_backoff_doubles_caps_resets() -> None:
    """AC-5: 5, 10, 20 … 900'de sabit; kısa ömürlü bağlantı beklemeyi sıfırlamaz (M-3); kayıtlı ve
    en az 60 sn ayakta kalan bağlantıdan sonra yine 5."""
    world = World(
        attempts=[
            *(["bağlanamadı"] * 9),
            [REG, "LOST"],  # registered but short-lived: the back-off keeps growing
            [REG, *quiet(70), "LOST"],  # stable: the back-off starts over
            "bağlanamadı",
        ]
    )
    world.runner().run()
    assert world.waits[:9] == [5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 320.0, 640.0, 900.0]
    assert world.waits[9:12] == [900.0, 5.0, 10.0]
    assert world.waits[0] == FIRST_DELAY_S and max(world.waits) == MAX_DELAY_S


def test_reconnect_after_drop_doubles() -> None:
    """M-3: kopma da ardışık hatadır: 5, 10, 20 (eski davranış 5, 5, 10'du)."""
    world = World(attempts=[[REG, "LOST"], [REG, "LOST"], [REG, "LOST"]])
    world.runner().run()
    assert world.waits == [5.0, 10.0, 20.0]


def test_gap_line_written() -> None:
    """AC-5: her kopukluk kayıtla biter, süresiyle satır; toplam durumda."""
    world = World(attempts=["bağlanamadı", [REG, None, "LOST"], [REG, "LOST"]])
    runner = world.runner()
    runner.run()
    gaps = [line for line in world.lines if "kopukluk=" in line]
    # start → 5 s wait → REG at 6 s; lost at 8 s → 10 s wait → REG at 19 s
    assert gaps == ["kaynak=akış kopukluk=6s", "kaynak=akış kopukluk=11s"]
    status = runner.status()
    assert status.gap_total == timedelta(seconds=17)
    assert status.connected is False and status.gap_started_at is not None
    assert status.last_connected_at == T0 + timedelta(seconds=19)


def test_register_rejected_or_missing_is_not_connected() -> None:
    """L-1: bağlı sayılmak için kayıt kodu `00000000`; başka kod ya da 30 sn sessizlik
    kopukluktur."""
    world = World(attempts=[[REG_BAD], quiet(40)])
    runner = world.runner()
    runner.run()
    assert "kaynak=akış hata=kayıt reddedildi" in world.lines
    assert "kaynak=akış hata=kayıt yok" in world.lines
    assert not any("kopukluk=" in line for line in world.lines)
    status = runner.status()
    assert status.connected is False and status.last_connected_at is None
    assert world.connections[1].closed and REGISTER_WITHIN_S == 30


def test_liveness_lost_without_frames() -> None:
    """L-5: canlılık iletisine yanıt da dahil hiç çerçeve gelmezse bağlantı kopmuş sayılır."""
    world = World(attempts=[[REG, *quiet(200)]], pongs=False)
    runner = world.runner()
    runner.run()
    assert "kaynak=akış hata=canlılık yok" in world.lines
    assert world.connections[0].closed and runner.status().connected is False
    assert LIVENESS_S < 2.5 * PING_EVERY_S + 1


def test_unverified_waits_others_continue() -> None:
    """AC-2: doğrulanamayan yetki bağlantısız beklemedir; doğrulanınca bağlanılır."""
    world = World(checks=[UNVERIFIED, UNVERIFIED, READ_ONLY], attempts=[[REG, "x", "LOST"]])
    runner = world.runner()
    runner.run()
    assert world.lines[:2] == ["kaynak=akış hata=anahtar yetkisi doğrulanamadı"] * 2
    assert world.waits[:2] == [5.0, 10.0]
    assert len(world.connections) == 1 and runner.status().fatal is None
    assert [text for text, _ in runner.drain()] == ["x"]


def test_unexpected_errors_are_retried() -> None:
    """M-1: beklenmeyen istisna iş parçacığını öldürmez; doğrulanamadı / bağlanamadı / koptu."""
    world = World(
        checks=[RuntimeError("check"), READ_ONLY, READ_ONLY, READ_ONLY],
        attempts=[RuntimeError("connect"), [REG, "BOOM"], [REG, "y", "LOST"]],
    )
    runner = world.runner()
    runner.run()
    assert world.lines[:2] == [
        "kaynak=akış hata=anahtar yetkisi doğrulanamadı",
        "kaynak=akış hata=bağlanamadı",
    ]
    assert "kaynak=akış hata=bağlantı koptu" in world.lines
    assert [text for text, _ in runner.drain()] == ["y"]


def test_excess_on_reconnect_stops() -> None:
    """AC-2: yeniden bağlanmada fazla yetki görülürse koşu biter, bağlanılmaz; durum ölümcül."""
    world = World(checks=[READ_ONLY, EXCESS], attempts=[[REG, "LOST"], [REG]])
    runner = world.runner()
    runner.run()
    assert len(world.connections) == 1
    assert runner.status().fatal == EXCESS


def test_excess_at_start_never_connects() -> None:
    world = World(checks=[EXCESS], attempts=[[REG]])
    runner = world.runner()
    runner.run()
    assert world.connections == [] and runner.status().fatal == EXCESS


def test_ping_and_daily_renewal() -> None:
    """Canlılık iletisi 30 sn'den sık; bağlantı 24 saat dolmadan yenilenir."""
    world = World(attempts=[[REG, *quiet(int(RENEW_AFTER_S + 5))], [REG, "LOST"]])
    world.runner().run()
    first = world.connections[0]
    assert first.closed
    # at least one liveness message every 30 s over the whole connection
    assert first.pings >= RENEW_AFTER_S / 30 and PING_EVERY_S < 30
    assert "kaynak=akış bağlantı yenileniyor (24 saat)" in world.lines
    assert len(world.connections) == 2
    assert world.waits[0] == FIRST_DELAY_S  # a day-long connection was stable


def test_stop_closes_connection() -> None:
    """AC-10: durdurma isteği bağlantıyı kapatır, yeniden bağlanılmaz."""
    world = World(attempts=[[REG, *quiet(100)], [REG]], stop_at=3.0)
    world.runner().run()
    assert len(world.connections) == 1 and world.connections[0].closed
