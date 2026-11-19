"""Akışın gerçek etkileri (spec 0056; plan Risk 1, 8, 10): `websocket-client` bağlantısı ve imzalı
yetki isteği. Yalnız giriş noktası kurar; testler sahtelerini kullanır.

Hata adları sabittir (`http_<kod>`, `timeout`, `bağlanamadı`, `bağlantı koptu`, `kapandı`): adres,
imza ve anahtar hiçbir hata adına girmez.
"""

import secrets
import ssl
import urllib.error
import urllib.request
from contextlib import suppress
from typing import Final
from urllib.parse import urlsplit

import websocket

from crytobot.news._binance_auth import RESTRICTIONS_PATH, restrictions_query, stream_query
from crytobot.news._fetch import USER_AGENT
from crytobot.news._secrets import StreamKeys
from crytobot.news._stream import ConnectionLost

CONNECT_TIMEOUT_S: Final = 30.0
RESTRICTIONS_LIMIT: Final = 64 * 1024
_HEADER: Final = "X-MBX-APIKEY"


class WsConnection:
    """`websocket-client` bağlantısının `Connection` yüzü."""

    def __init__(self, socket_: websocket.WebSocket) -> None:
        self._ws = socket_

    def recv(self, timeout: float) -> str | None:
        self._ws.settimeout(timeout)
        try:
            opcode, data = self._ws.recv_data(control_frame=True)
        except websocket.WebSocketTimeoutException:
            return None
        except (websocket.WebSocketException, OSError):
            raise ConnectionLost("bağlantı koptu") from None
        if opcode == websocket.ABNF.OPCODE_CLOSE:
            raise ConnectionLost("kapandı")
        if opcode != websocket.ABNF.OPCODE_TEXT:
            return None  # ping is answered by the library; pong and binary are not announcements
        return bytes(data).decode("utf-8", "replace") if not isinstance(data, str) else data

    def ping(self) -> None:
        try:
            self._ws.ping("")
        except (websocket.WebSocketException, OSError):
            raise ConnectionLost("bağlantı koptu") from None

    def close(self) -> None:
        with suppress(websocket.WebSocketException, OSError):
            self._ws.close()


def open_stream(url: str, keys: StreamKeys, now_ms: int) -> WsConnection:
    """İmzalı adresle bağlanır; anahtar başlıkta."""
    address = f"{url}?{stream_query(keys.secret, now_ms, secrets.token_hex(16))}"
    try:
        socket_ = websocket.create_connection(
            address, header=[f"{_HEADER}: {keys.key}"], timeout=CONNECT_TIMEOUT_S
        )
    except websocket.WebSocketBadStatusException as error:
        raise ConnectionLost(f"http_{int(error.status_code)}") from None
    except (TimeoutError, websocket.WebSocketTimeoutException):
        raise ConnectionLost("timeout") from None
    except (websocket.WebSocketException, OSError, ssl.SSLError, ValueError):
        raise ConnectionLost("bağlanamadı") from None
    return WsConnection(socket_)


def fetch_restrictions(url: str, keys: StreamKeys, now_ms: int) -> bytes | None:
    """Anahtarın yetki yanıtı; alınamazsa `None` (yetki doğrulanamadı). Akış adresinin sunucusu."""
    host = urlsplit(url).hostname
    if not host:
        return None
    address = f"https://{host}{RESTRICTIONS_PATH}?{restrictions_query(keys.secret, now_ms)}"
    request = urllib.request.Request(address, headers={_HEADER: keys.key, "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=CONNECT_TIMEOUT_S) as response:
            body = response.read(RESTRICTIONS_LIMIT + 1)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return None if len(body) > RESTRICTIONS_LIMIT else body
