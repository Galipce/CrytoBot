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
