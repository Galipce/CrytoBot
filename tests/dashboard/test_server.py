"""Spec 0031 AC-2, AC-3, AC-8 (R-3, R-4, R-7, R-8): Host denetimi, HTTP metot kısıtı, durum API'si testleri."""

import io
import json
import socket
from typing import Any
from unittest.mock import MagicMock

import pytest

from crytobot.dashboard import (
    DashboardConfig,
    DashboardHandler,
    PortBusyError,
    create_server,
    load_dashboard_config,
)


class DummySocket:
    def __init__(self, data: bytes) -> None:
        self.rfile = io.BytesIO(data)
        self.wfile = io.BytesIO()

    def makefile(self, mode: str = "r", *args: Any, **kwargs: Any) -> io.BytesIO:
        if "r" in mode:
            return self.rfile
        return self.wfile

    def sendall(self, data: bytes) -> None:
        self.wfile.write(data)


def simulate_request(
    raw_http: str,
    status_provider: Any = None,
) -> tuple[int, dict[str, str], bytes]:
    """Soket açmadan HTTP isteğini işler ve (status_code, headers, body) döner."""
    sock = DummySocket(raw_http.encode("utf-8"))
    server = MagicMock()
    server.status_provider = (
        status_provider if status_provider is not None else lambda: (200, {"status": "ok"})
    )

    DashboardHandler(sock, ("127.0.0.1", 12345), server)  # type: ignore[arg-type]

    response_bytes = sock.wfile.getvalue()
    header_part, _, body = response_bytes.partition(b"\r\n\r\n")
    if not header_part:
        header_part, _, body = response_bytes.partition(b"\n\n")

    lines = header_part.decode("utf-8", errors="replace").splitlines()
    status_line = lines[0] if lines else "HTTP/1.0 500 Error"
    status_code = int(status_line.split()[1])

    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()

    return status_code, headers, body


def test_host_and_method_validation() -> None:
    # AC-2: İzin verilen Host başlıkları
    for host in ["127.0.0.1", "127.0.0.1:8080", "localhost", "localhost:8080"]:
        req = f"GET / HTTP/1.1\r\nHost: {host}\r\n\r\n"
        code, headers, body = simulate_request(req)
        assert code == 200
        assert b"CrytoBot Pano" in body

    # AC-2: Reddedilen Host başlıkları (DNS rebinding koruması) -> HTTP 403
    for evil_host in [
        "attacker.com",
        "evil.org:8080",
        "192.168.1.5",
        "example.com",
        "attacker.localhost.com",
    ]:
        req = f"GET / HTTP/1.1\r\nHost: {evil_host}\r\n\r\n"
        code, headers, body = simulate_request(req)
        assert code == 403
        assert b"Eri\xc5\x9fim reddedildi" in body

    # AC-2: Host başlığı eksikse -> HTTP 403
    req = "GET / HTTP/1.1\r\n\r\n"
    code, _, _ = simulate_request(req)
    assert code == 403

    # AC-2, R-8: GET dışındaki metotlar -> HTTP 405 Method Not Allowed
    for method in ["POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]:
        req = f"{method} / HTTP/1.1\r\nHost: 127.0.0.1:8080\r\n\r\n"
        code, headers, body = simulate_request(req)
        assert code == 405
        assert headers.get("allow") == "GET"
        assert b"Metot kabul edilmiyor" in body


def test_api_status_endpoint_returns_json() -> None:
    test_data = {
        "is_running": True,
        "mode": "paper",
        "equity": 10500.5,
        "positions": [],
    }

    def mock_provider() -> tuple[int, dict[str, Any]]:
        return 200, test_data

    req = "GET /api/status HTTP/1.1\r\nHost: 127.0.0.1:8080\r\n\r\n"
    code, headers, body = simulate_request(req, status_provider=mock_provider)

    assert code == 200
    assert "application/json" in headers.get("content-type", "")
    assert headers.get("cache-control") is not None

    parsed_json = json.loads(body.decode("utf-8"))
    assert parsed_json["is_running"] is True
    assert parsed_json["equity"] == 10500.5


def test_api_status_endpoint_returns_error_status_when_store_fails() -> None:
    def error_provider() -> tuple[int, dict[str, Any]]:
        return 503, {"error": "depo bulunamadı"}

    req = "GET /api/status HTTP/1.1\r\nHost: 127.0.0.1:8080\r\n\r\n"
    code, headers, body = simulate_request(req, status_provider=error_provider)

    assert code == 503
    parsed_json = json.loads(body.decode("utf-8"))
    assert parsed_json["error"] == "depo bulunamadı"


def test_unknown_path_returns_404() -> None:
    req = "GET /bilinmeyen HTTP/1.1\r\nHost: 127.0.0.1:8080\r\n\r\n"
    code, _, body = simulate_request(req)
    assert code == 404
    assert b"Bulunamadi" in body


def test_dashboard_config_validation() -> None:
    # Boş config -> varsayılanlar
    res = load_dashboard_config(None)
    assert res.config == DashboardConfig("127.0.0.1", 8080)
    assert res.setting is None

    # Bölüm yoksa
    res = load_dashboard_config({})
    assert res.config == DashboardConfig("127.0.0.1", 8080)

    # Geçerli özel port
    res = load_dashboard_config({"dashboard": {"port": 9090, "host": "127.0.0.1"}})
    assert res.config == DashboardConfig("127.0.0.1", 9090)

    # Geçersiz host
    res = load_dashboard_config({"dashboard": {"host": "0.0.0.0"}})
    assert res.config is None
    assert res.setting == "dashboard.host"

    # Geçersiz port
    for bad_port in [0, 65536, "8080", True, None]:
        res = load_dashboard_config({"dashboard": {"port": bad_port}})
        assert res.config is None
        assert res.setting == "dashboard.port"

    # Bilinmeyen anahtar
    res = load_dashboard_config({"dashboard": {"extra": "foo"}})
    assert res.config is None
    assert res.setting == "dashboard.extra"

    # Geçersiz bölüm tipi
    res = load_dashboard_config({"dashboard": "not_a_map"})
    assert res.config is None
    assert res.setting == "dashboard"


@pytest.mark.enable_socket
def test_create_server_refuses_when_port_busy() -> None:
    # Bir soket açıp portu tutuyoruz
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        _, port = sock.getsockname()

        with pytest.raises(PortBusyError) as exc_info:
            create_server("127.0.0.1", port, lambda: (200, {}))
        assert f"port meşgul: {port}" in str(exc_info.value)
    finally:
        sock.close()
