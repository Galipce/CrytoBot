"""Localhost HTTP sunucusu ve işleyici (spec 0031 R-1, R-3, R-7, R-8, AC-1, AC-2, AC-3, AC-8).

Yalnızca 127.0.0.1 adresine bağlanır.
Host başlığı localhost veya 127.0.0.1 olmayan istekleri HTTP 403 Forbidden ile,
GET dışındaki metotları HTTP 405 Method Not Allowed ile reddeder.
"""

import json
import socket
import urllib.parse
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from crytobot.dashboard._config import ALLOWED_HOSTS
from crytobot.dashboard._html import render_dashboard_html

StatusProvider = Callable[[], tuple[int, dict[str, Any]]]


class PortBusyError(Exception):
    """İstenen port başka bir süreç tarafından kullanıldığında fırlatılır (R-7, AC-8)."""


class DashboardHandler(BaseHTTPRequestHandler):
    """Pano HTTP istek işleyicisi: Host doğrulama ve salt-okunur GET uç noktaları."""

    server: "DashboardServer"  # type hint for self.server

    def log_message(self, format: str, *args: Any) -> None:
        """Konsola otomatik HTTP erişim satırları basılmaz."""
        pass

    def _validate_host(self) -> bool:
        """DNS rebinding koruması: Host başlığını denetler (R-3, ADR 0002)."""
        raw_host = self.headers.get("Host", "").strip()
        if not raw_host:
            self._send_forbidden("Host başlığı eksik")
            return False

        if raw_host.startswith("["):
            hostname = raw_host.partition("]")[0].lstrip("[")
        else:
            hostname = raw_host.partition(":")[0]

        hostname = hostname.lower()
        if hostname not in ALLOWED_HOSTS:
            self._send_forbidden("Yetkisiz Host başlığı")
            return False
        return True

    def _send_forbidden(self, reason: str) -> None:
        body = f"Erişim reddedildi: {reason}\n".encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_method_not_allowed(self) -> None:
        if not self._validate_host():
            return
        body = b"Metot kabul edilmiyor: yalnizca GET\n"
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        self._send_method_not_allowed()

    def do_PUT(self) -> None:
        self._send_method_not_allowed()

    def do_DELETE(self) -> None:
        self._send_method_not_allowed()

    def do_PATCH(self) -> None:
        self._send_method_not_allowed()

    def do_HEAD(self) -> None:
        self._send_method_not_allowed()

    def do_OPTIONS(self) -> None:
        self._send_method_not_allowed()

    def do_GET(self) -> None:
        if not self._validate_host():
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            html = render_dashboard_html()
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/status":
            code, data = self.server.status_provider()
            body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(body)
            return

        body = b"Bulunamadi\n"
        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DashboardServer(HTTPServer):
    """Yerel pano sunucusu: host ve port kontrolü ile açılır."""

    allow_reuse_address = False

    def __init__(
        self,
        server_address: tuple[str, int],
        status_provider: StatusProvider,
    ) -> None:
        self.status_provider = status_provider
        host, port = server_address
        try:
            super().__init__((host, port), DashboardHandler)
        except OSError as exc:
            raise PortBusyError(f"port meşgul: {port}") from exc


def create_server(
    host: str,
    port: int,
    status_provider: StatusProvider,
) -> DashboardServer:
    """Pano sunucusunu oluşturur. Port meşgulse PortBusyError fırlatır."""
    return DashboardServer((host, port), status_provider)
