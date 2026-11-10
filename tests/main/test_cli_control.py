"""Spec 0030 AC-1, AC-2, AC-4, AC-5, AC-6, AC-9: CLI uçtan uca kontrol komutları testleri."""

import io
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from crytobot.__main__ import (
    EXIT_OK,
    EXIT_REFUSED,
    StoreLock,
    run,
)
from crytobot.control import stop_flag_path
from crytobot.persistence import (
    load_audit_records,
    load_store,
    save_store,
)
from crytobot.risk import DEFAULT_LIMITS, engage_kill_switch, observe
from tests.main.test_entry import config_text

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def setup_config_and_store(root: Path, prepare: bool = True) -> tuple[Path, Path]:
    cfg_path = root / "crytobot.toml"
    cfg_path.write_text(config_text(root), encoding="utf-8")
    db_path = root / "bot.db"
    if prepare:
        code = run(["prepare"], config_path=cfg_path, console=io.StringIO(), clock=lambda: T0)
        assert code == EXIT_OK
    return cfg_path, db_path


def test_status_command_reports_all_metrics(tmp_path: Path) -> None:
    """AC-1 (R-1): Durum sorgulama tüm metrikleri doğru basar ve depoyu değiştirmez."""
    cfg_path, db_path = setup_config_and_store(tmp_path, prepare=True)
    before_bytes = db_path.read_bytes()

    console = io.StringIO()
    code = run(["status"], config_path=cfg_path, console=console, clock=lambda: T0)

    assert code == EXIT_OK
    out = console.getvalue()
    assert "Süreç Durumu: durdu" in out
    assert "Çalışma Modu: paper" in out
    assert "Serbest Bakiye: 10000 USDT" in out
    assert "Toplam Kasa: 10000 USDT" in out
    assert "Zirve Kasa: 10000 USDT" in out
    assert "Drawdown Oranı: %0.00" in out
    assert "Aktif Durdurmalar: yok" in out
    assert "Günün Kâr/Zararı (UTC):" in out
    assert "Açık Pozisyonlar (0)" in out
    assert "Son Tur / Gözlem:" in out
    # Depo salt-okunur incelenmiştir, değişmemiştir
    assert db_path.read_bytes() == before_bytes


def test_kill_switch_engages_and_is_idempotent(tmp_path: Path) -> None:
    """AC-2 (R-2, R-6): kill-switch devreye alma idempotenttir; audit kaydı bırakır."""
    cfg_path, db_path = setup_config_and_store(tmp_path, prepare=True)

    # 1. kill-switch komutu
    c1 = io.StringIO()
    code1 = run(["kill-switch"], config_path=cfg_path, console=c1, clock=lambda: T0)
    assert code1 == EXIT_OK
    assert "kill switch devreye alındı" in c1.getvalue()

    # 2. kill-switch on komutu (zaten devredeyken bilgi verir)
    c2 = io.StringIO()
    code2 = run(["kill-switch", "on"], config_path=cfg_path, console=c2, clock=lambda: T0)
    assert code2 == EXIT_OK
    assert "kill switch zaten devrede" in c2.getvalue()

    # Status çıktısında kill switch devrede görünür
    c_status = io.StringIO()
    run(["status"], config_path=cfg_path, console=c_status, clock=lambda: T0)
    assert "kill switch" in c_status.getvalue()

    # Audit log kayıtları
    audits = load_audit_records(db_path)
    assert len(audits) >= 2
    assert "kill-switch on" in audits[0]


def test_resume_clears_kill_switch_and_drawdown(tmp_path: Path) -> None:
    """AC-4 (R-3): resume hem kill switch'i hem drawdown durdurmasını kaldırır."""
    cfg_path, db_path = setup_config_and_store(tmp_path, prepare=True)

    # Bir gözlem yapalım ve kill switch'i açalım
    load_res = load_store(db_path, "paper")
    assert load_res.state is not None
    observed_state = observe(load_res.state.risk, T0, Decimal("10000"), DEFAULT_LIMITS).state
    ks_state = engage_kill_switch(observed_state).state
    save_store(db_path, load_res.state, load_res.state.ledger, load_res.state.execution, ks_state)

    console = io.StringIO()
    code = run(["resume"], config_path=cfg_path, console=console, clock=lambda: T0)
    assert code == EXIT_OK
    assert "durdurma kaldırıldı" in console.getvalue()

    # Status artık durdurma yok der
    c_status = io.StringIO()
    run(["status"], config_path=cfg_path, console=c_status, clock=lambda: T0)
    assert "Aktif Durdurmalar: yok" in c_status.getvalue()


def test_resume_refused_when_no_halt_active(tmp_path: Path) -> None:
    """AC-5 (R-3): Durdurma aktif değilken resume reddedilir ve audit kaydına ret yazılır."""
    cfg_path, db_path = setup_config_and_store(tmp_path, prepare=True)

    # Kasa gözlemi yapılmış ama durdurma yok
    load_res = load_store(db_path, "paper")
    assert load_res.state is not None
    observed_state = observe(load_res.state.risk, T0, Decimal("10000"), DEFAULT_LIMITS).state
    save_store(
        db_path, load_res.state, load_res.state.ledger, load_res.state.execution, observed_state
    )

    console = io.StringIO()
    code = run(["resume"], config_path=cfg_path, console=console, clock=lambda: T0)
    assert code == EXIT_REFUSED
    assert "durdurma yok" in console.getvalue()

    # Audit log ret kaydı taşır
    audits = load_audit_records(db_path)
    assert any('"action":"resume"' in a and '"result":"refused"' in a for a in audits)


def test_stop_command_sets_flag_and_cleans_up(tmp_path: Path) -> None:
    """AC-6 (R-4): Çalışmayan süreçte ret; çalışan süreçte .stop bayrağı konur."""
    cfg_path, db_path = setup_config_and_store(tmp_path, prepare=True)

    # 1. Bot çalışmıyorken stop reddedilir
    c1 = io.StringIO()
    code1 = run(["stop"], config_path=cfg_path, console=c1, clock=lambda: T0)
    assert code1 == EXIT_REFUSED
    assert "çalışan bot süreci yok" in c1.getvalue()
    flag = stop_flag_path(db_path)
    assert not flag.exists()

    # 2. Çalışan süreci simüle etmek için StoreLock alıyoruz
    lock = StoreLock(str(db_path))
    refused = lock.acquire()
    assert refused is None
    try:
        c2 = io.StringIO()
        code2 = run(["stop"], config_path=cfg_path, console=c2, clock=lambda: T0)
        assert code2 == EXIT_OK
        assert "durdurma isteği çalışan bot sürecine iletildi" in c2.getvalue()
        assert flag.exists()
    finally:
        lock.release()
        flag.unlink(missing_ok=True)


def test_control_commands_handle_missing_or_corrupt_store(tmp_path: Path) -> None:
    """AC-9 (R-8): Depo yokken veya bozukken komutlar çökmeden adıyla hata basar."""
    # 1. Depo dosyası henüz oluşturulmamışken
    cfg_path, db_path = setup_config_and_store(tmp_path, prepare=False)
    assert not db_path.exists()

    for cmd in (["status"], ["kill-switch"], ["resume"], ["stop"]):
        console = io.StringIO()
        code = run(cmd, config_path=cfg_path, console=console, clock=lambda: T0)
        assert code == EXIT_REFUSED
        assert "depo dosyası yok" in console.getvalue()
        # Yeni depo kendiliğinden oluşturulmaz
        assert not db_path.exists()

    # 2. Depo bozukken
    db_path.write_bytes(b"garbage-not-a-sqlite-db")
    for cmd in (["status"], ["kill-switch"], ["resume"]):
        console = io.StringIO()
        code = run(cmd, config_path=cfg_path, console=console, clock=lambda: T0)
        assert code == EXIT_REFUSED
        assert "depo okunamıyor" in console.getvalue()
        # Bozuk dosya ezilmez
        assert db_path.read_bytes() == b"garbage-not-a-sqlite-db"


def live_setup(root: Path) -> tuple[Path, Path]:
    """Spec 0035: canlı ayar (`bot.mode = "live"`) ve borsaya çıkmadan açılmış canlı depo."""
    from crytobot.app import PrepareOutcome, prepare_live_store
    from tests.app.test_live_start import FakeLiveClient, write_test_config

    cfg_path = write_test_config(root, mode="live")
    db_path = root / "bot.db"
    prepared = prepare_live_store(
        db_path.as_posix(), T0, live_client=FakeLiveClient(free_balance=Decimal("1000.00"))
    )
    assert prepared.outcome is PrepareOutcome.PREPARED, prepared.message
    return cfg_path, db_path


def test_stop_ends_running_live_bot(tmp_path: Path) -> None:
    """Spec 0035 AC-3 (R-4): çalışan canlı bota `stop` iletilir; botun beklemesi bayrağı görüp
    durdurma ister (spec 0030 R-4 yolu)."""
    from crytobot.__main__ import make_wait
    from crytobot.app import StopRequest

    cfg_path, db_path = live_setup(tmp_path)
    lock = StoreLock(str(db_path))
    assert lock.acquire() is None
    flag = stop_flag_path(db_path)
    try:
        console = io.StringIO()
        assert run(["stop"], config_path=cfg_path, console=console, clock=lambda: T0) == EXIT_OK
        assert "durdurma isteği çalışan bot sürecine iletildi" in console.getvalue()
        assert flag.exists()
        stop = StopRequest()
        make_wait(stop, sleep=lambda _s: None, stop_flag_path=flag)(30.0)
        assert stop.requested and stop.source == "cli-stop"
    finally:
        lock.release()
        flag.unlink(missing_ok=True)


def test_kill_switch_and_resume_while_live_bot_runs(tmp_path: Path) -> None:
    """Spec 0035 plan Risk 1, AC-12: çalışan botta kill switch isteği bayrağa yazılır (depo
    değişmez); resume `önce stop` ile reddedilir."""
    from crytobot.control import kill_flag_path

    cfg_path, db_path = live_setup(tmp_path)
    before = load_store(db_path, "live")
    assert before.state is not None
    lock = StoreLock(str(db_path))
    assert lock.acquire() is None
    kill_flag = kill_flag_path(db_path)
    try:
        c1 = io.StringIO()
        assert run(["kill-switch"], config_path=cfg_path, console=c1, clock=lambda: T0) == EXIT_OK
        assert "çalışan bota iletildi" in c1.getvalue()
        assert kill_flag.exists()
        c2 = io.StringIO()
        assert run(["resume"], config_path=cfg_path, console=c2, clock=lambda: T0) == EXIT_REFUSED
        assert "çalışan bot var: önce stop" in c2.getvalue()
        after = load_store(db_path, "live")
        assert after.state is not None and after.state.revision == before.state.revision
    finally:
        lock.release()
        kill_flag.unlink(missing_ok=True)


def test_control_commands_need_no_credentials(tmp_path: Path, monkeypatch: object) -> None:
    """Spec 0035 AC-8 (R-5): API anahtarı yokken dört komut ve pano canlı depoda çalışır; borsa
    istemcisi hiç kurulmaz."""
    import pytest

    import crytobot.execution._live_client as live_client
    from crytobot.__main__ import _load_toml
    from crytobot.app import get_dashboard_status, load_config

    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    cfg_path, db_path = live_setup(tmp_path)
    for name in ("BINANCE_API_KEY", "BINANCE_API_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # yerel .env okunmaz

    def no_exchange(*_a: object, **_k: object) -> None:
        raise AssertionError("borsa istemcisi kurulmamalı")

    monkeypatch.setattr(live_client.BinanceLiveClient, "__init__", no_exchange)

    for cmd in (["status"], ["kill-switch"], ["resume"]):
        console = io.StringIO()
        assert run(cmd, config_path=cfg_path, console=console, clock=lambda: T0) == EXIT_OK, (
            cmd,
            console.getvalue(),
        )
    lock = StoreLock(str(db_path))
    assert lock.acquire() is None
    try:
        assert (
            run(["stop"], config_path=cfg_path, console=io.StringIO(), clock=lambda: T0) == EXIT_OK
        )
    finally:
        lock.release()
        stop_flag_path(db_path).unlink(missing_ok=True)

    document = _load_toml(cfg_path)
    loaded = load_config(document, T0)
    assert loaded.config is not None, loaded.message
    code, data = get_dashboard_status(loaded.config, clock=lambda: T0)
    assert code == 200 and data["mode"] == "live"


def test_kill_flag_reaches_running_loop_end_to_end(tmp_path: Path) -> None:
    """Spec 0035 AC-1, AC-11 (R-4), review round 1 M-1: `kill-switch` bot çalışırken bayrağa
    yazılır; `start` döngüsü onu turunda kendi kaydıyla işler, bayrak silinir, denetim kaydı
    `engaged`. Bağlantı (`__main__` → `LoopParts` → tur) gerçek CLI yolundan sınanır."""
    from crytobot.control import kill_flag_path
    from tests.main.test_entry import Bot

    bot = Bot(tmp_path / "bot")
    assert bot.run("prepare")[0] == EXIT_OK
    lock = StoreLock(str(bot.store))
    assert lock.acquire() is None  # a running bot holds the lock
    try:
        console = io.StringIO()
        code = run(["kill-switch"], config_path=bot.config_path, console=console, clock=bot.clock)
        assert code == EXIT_OK and "çalışan bota iletildi" in console.getvalue()
    finally:
        lock.release()
    assert kill_flag_path(bot.store).exists()

    code, _ = bot.run("start")

    assert code == EXIT_OK
    loaded = load_store(bot.store, "paper")
    assert loaded.state is not None and loaded.state.risk.kill_switch
    assert not kill_flag_path(bot.store).exists()
    rows = load_audit_records(bot.store)
    assert any('"result":"requested"' in r for r in rows)
    assert any('"result":"engaged"' in r and "çalışan bot isteği" in r for r in rows)


def test_stop_flag_ends_loop_after_turn_and_is_cleared(tmp_path: Path) -> None:
    """Spec 0035 AC-3 (R-4), review round 1 M-2: tur sürerken gelen `stop` bayrağını botun
    beklemesi görür; bot turunu tamamlayıp temiz çıkar, bayrak çıkışta silinir."""
    from crytobot.app import StopRequest
    from crytobot.market_data import MarketRead, ReadSettings
    from tests.main.test_entry import Bot

    bot = Bot(tmp_path / "bot", stop_on_read=None)
    assert bot.run("prepare")[0] == EXIT_OK
    flag = stop_flag_path(bot.store)
    turns: list[int] = []

    def read_then_stop(pairs: tuple[str, ...], settings: ReadSettings) -> MarketRead:
        turns.append(1)
        if len(turns) == 1:  # the `stop` command arrives while the first turn runs
            assert run(["stop"], config_path=bot.config_path, console=io.StringIO()) == EXIT_OK
            assert flag.exists()
        return bot.read(pairs, settings)

    console = io.StringIO()
    code = run(
        ["start", "--trial"],
        config_path=bot.config_path,
        console=console,
        clock=bot.clock,
        stop=StopRequest(),
        read=read_then_stop,
        wait=None,  # the real wait: it is what watches the flag
    )

    assert code == EXIT_OK
    assert turns == [1]  # one turn completed, no second read
    assert "durdurma isteği" in console.getvalue()
    assert not flag.exists()
