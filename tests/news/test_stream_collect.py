"""Spec 0056 AC-3, AC-5, AC-6, AC-2 (toplama durur): akış kaynağı turda, sahte akış yüzüyle, gerçek
depoyla."""

import sqlite3
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

from crytobot.news import CollectionExit, NewsStore, read_snapshot, run_collection, run_round
from crytobot.news._binance_auth import PermissionCheck, Verdict
from crytobot.news._stream import StreamStatus
from tests.news.test_collect import START, Harness, make_config, source_table
from tests.news.test_stream_parse import message

STREAM = {**source_table("akış", "binance-akış"), "url": "wss://api.binance.com/sapi/wss"}
REGISTER = '{"type":"COMMAND","subType":"REGISTER","data":"SUCCESS","code":"00000000"}'


@dataclass
class FakeView:
    received: list[tuple[str, datetime]] = field(default_factory=list)
    connected: bool = True
    gap_total: timedelta = timedelta(0)
    fatal: PermissionCheck | None = None
    drains: int = 0

    def drain(self) -> list[tuple[str, datetime]]:
        self.drains += 1
        taken, self.received = self.received, []
        return taken

    def status(self) -> StreamStatus:
        return StreamStatus(
            self.connected,
            START if self.connected else None,
            None if self.connected else START,
            self.gap_total,
            self.fatal,
        )


def harness(tmp_path: Path, *sources: dict[str, object], **settings: object) -> Harness:
    return Harness(tmp_path, make_config(tmp_path, *(sources or (STREAM,)), **settings))


def run(h: Harness, view: FakeView) -> bool:
    store = NewsStore.open(h.config.store_path)
    try:
        return run_round(h.config, store, replace(h.parts(), streams={"akış": view}))
    finally:
        store.close()


def rows(h: Harness) -> list[tuple[str, str, str, str]]:
    with sqlite3.connect(h.config.store_path) as connection:
        return connection.execute(
            "SELECT source, key, title, first_seen_at FROM news ORDER BY id"
        ).fetchall()


def test_new_and_duplicate_counted(tmp_path: Path) -> None:
    """AC-3: duyuru bir kez yazılır; ilk görme anı alınma anı; tekrar sayılır; kontrol iletisi
    sayılmaz."""
    h = harness(tmp_path)
    seen = START + timedelta(minutes=3)
    view = FakeView([(REGISTER, START), (message(), seen), (message(), seen)])
    assert run(h, view)
    assert h.summary("akış") == "kaynak=akış yeni=1 tekrar=1 geçersiz=0"
    ((source, key, title, first_seen),) = rows(h)
    assert (source, title, first_seen) == ("akış", "Binance Will List ABC", seen.isoformat())
    assert key.startswith("id:akış:1795000000000:")
    view.received = [(message(), seen + timedelta(minutes=20))]
    assert run(h, view)
    assert h.summary("akış") == "kaynak=akış yeni=0 tekrar=1 geçersiz=0" and len(rows(h)) == 1


def test_quiet_round_is_not_error(tmp_path: Path) -> None:
    h = harness(tmp_path)
    assert run(h, FakeView(connected=True))
    assert h.summary("akış") == "kaynak=akış yeni=0 tekrar=0 geçersiz=0"


def test_invalid_counted_valid_written(tmp_path: Path) -> None:
    """AC-4: geçersiz ileti yazılmaz, sonraki geçerli yazılır."""
    h = harness(tmp_path)
    assert run(h, FakeView([("bozuk", START), (message(title=5), START), (message(), START)]))
    assert h.summary("akış") == "kaynak=akış yeni=1 tekrar=0 geçersiz=2" and len(rows(h)) == 1


def test_other_sources_not_delayed(tmp_path: Path) -> None:
    """AC-5: akış kaynağı sorgulanmaz ve beklenmez; kopukken de diğer kaynaklar aynı turda."""
    h = harness(tmp_path, STREAM, source_table("coindesk"))
    started = h.clock.now
    assert run(h, FakeView(connected=False))
    assert h.fetched == ["https://coindesk.example.org/feed"]
    assert h.summary("akış") == "kaynak=akış hata=kopuk"
    assert h.summary("coindesk").startswith("kaynak=coindesk yeni=")
    assert h.clock.now - started == timedelta(seconds=h.fetch_seconds)


def test_outage_alert_and_recovery(tmp_path: Path) -> None:
    """AC-6: kopukluk `source_alert_hours`'tan uzunsa tek giriş, ilk başarıda tek çıkış
    bildirimi."""
    h = harness(tmp_path, source_alert_hours=1)
    view = FakeView(connected=False)
    assert run(h, view)
    h.clock.advance(3601)
    assert run(h, view)
    h.clock.advance(600)
    assert run(h, view)
    assert len(h.notices) == 1 and "kesintisi" in h.notices[0]
    view.connected = True
    assert run(h, view)
    assert len(h.notices) == 2 and "yeniden çalışıyor" in h.notices[1]


def test_connection_state_written(tmp_path: Path) -> None:
    """AC-8'in kaynağı: bağlantı durumu kayda turla yazılır."""
    h = harness(tmp_path)
    assert run(h, FakeView(connected=False, gap_total=timedelta(seconds=75)))
    snapshot = read_snapshot(h.config.store_path)
    assert snapshot is not None
    stream = snapshot.sources["akış"].stream
    assert stream is not None and (stream.connected, stream.gap_total_s) == (False, 75)
    assert stream.gap_started_at == START and stream.last_connected_at is None


def test_excess_permission_stops_collection(tmp_path: Path) -> None:
    """AC-2: çalışırken fazla yetki görülürse toplama aynı retle durur."""
    h = harness(tmp_path)
    h.stop_after_waits = None
    view = FakeView(fatal=PermissionCheck(Verdict.EXCESS, ("enableWithdrawals",)))
    store = NewsStore.open(h.config.store_path)
    try:
        exit_ = run_collection(h.config, store, replace(h.parts(), streams={"akış": view}))
    finally:
        store.close()
    assert exit_ is CollectionExit.KEY_REFUSED
    assert h.lines[-1] == "reddedildi: anahtar yetkisi fazla: enableWithdrawals tur_sayısı=0"
    assert view.drains == 0
