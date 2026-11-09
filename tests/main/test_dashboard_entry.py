"""Spec 0031 AC-1, AC-8 (R-1, R-7): CLI `dashboard` komutu, port çakışması ve durdurma testleri."""

import io
import socket
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crytobot.__main__ import EXIT_OK, EXIT_REFUSED, StopRequest, run
from tests.main.test_entry import config_text

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def setup_config_and_store(
    root: Path, prepare: bool = True, custom_dashboard: str = ""
) -> tuple[Path, Path]:
    cfg_path = root / "crytobot.toml"
    text = config_text(root)
    if custom_dashboard:
        text += f"\n{custom_dashboard}\n"
    cfg_path.write_text(text, encoding="utf-8")
    db_path = root / "bot.db"
    if prepare:
        code = run(["prepare"], config_path=cfg_path, console=io.StringIO(), clock=lambda: T0)
        assert code == EXIT_OK
    return cfg_path, db_path


@pytest.mark.enable_socket
def test_dashboard_starts_and_stops_cleanly(tmp_path: Path) -> None:
    """AC-1 (R-1): dashboard komutu sunucuyu başlatır, adresi konsola yazar, temizce durur."""
    # Portu dinamik boş bir porta ayarlayarak test edelim
    probe_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe_sock.bind(("127.0.0.1", 0))
    _, free_port = probe_sock.getsockname()
    probe_sock.close()

    cfg_path, _ = setup_config_and_store(
        tmp_path, prepare=True, custom_dashboard=f"[dashboard]\nport = {free_port}\n"
    )

    console = io.StringIO()
    stop = StopRequest()

    def stop_after_delay() -> None:
        time.sleep(0.3)
        stop.request("test_done")

    stopper = threading.Thread(target=stop_after_delay)
    stopper.start()

    code = run(
        ["dashboard"],
        config_path=cfg_path,
        console=console,
        clock=lambda: T0,
        stop=stop,
    )
    stopper.join()

    assert code == EXIT_OK
    out = console.getvalue()
    assert f"http://127.0.0.1:{free_port}" in out


@pytest.mark.enable_socket
def test_dashboard_refuses_when_port_busy(tmp_path: Path) -> None:
    """AC-8 (R-7): Port meşgulken ret mesajı basar ve EXIT_REFUSED döner."""
    busy_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    busy_sock.bind(("127.0.0.1", 0))
    _, busy_port = busy_sock.getsockname()

    try:
        cfg_path, _ = setup_config_and_store(
            tmp_path, prepare=True, custom_dashboard=f"[dashboard]\nport = {busy_port}\n"
        )
        console = io.StringIO()
        code = run(
            ["dashboard"],
            config_path=cfg_path,
            console=console,
            clock=lambda: T0,
        )

        assert code == EXIT_REFUSED
        out = console.getvalue()
        assert f"port meşgul: {busy_port}" in out
    finally:
        busy_sock.close()


def test_dashboard_refuses_invalid_dashboard_config(tmp_path: Path) -> None:
    """Geçersiz dashboard ayarlarında (ör. bilinmeyen ayar) EXIT_REFUSED döner."""
    cfg_path, _ = setup_config_and_store(
        tmp_path, prepare=True, custom_dashboard="[dashboard]\nunknown = true\n"
    )
    console = io.StringIO()
    code = run(
        ["dashboard"],
        config_path=cfg_path,
        console=console,
        clock=lambda: T0,
    )

    assert code == EXIT_REFUSED
    out = console.getvalue()
    assert "bilinmeyen ayar: dashboard.unknown" in out
