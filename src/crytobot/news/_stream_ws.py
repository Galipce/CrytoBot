"""Akışın gerçek etkileri (spec 0056; plan Risk 1, 8, 10): `websocket-client` bağlantısı ve imzalı
yetki isteği. Yalnız giriş noktası kurar; birim testleri kütüphaneyi sahtesiyle değiştirir.

Hata adları sabittir (`http_<kod>`, `timeout`, `bağlanamadı`, `bağlantı koptu`, `kapandı`): adres,
imza ve anahtar hiçbir hata adına girmez; kütüphanenin hata metni atılır. Yönlendirme izlenmez
(anahtar başlığı başka adrese taşınmaz; review round 1 L-2). `urlopen` `http.client.HTTPException`'ı
`URLError`'a sarmaz ve o `OSError` değildir: ayrıca yakalanır (review round 1 M-1).

Plan A-7: sunucu saati anahtarsız, aynı yönlendirmesiz açıcıyla okunur; yetki isteği alınamazsa
nedenin sırsız adı döner (`http_<durum>[/<Binance kodu>]`, `timeout`, `bağlanamadı`,
`yanıt geçersiz`).
"""

import http.client
import secrets
import ssl
import urllib.error
import urllib.request
from contextlib import suppress
from typing import Final
from urllib.parse import urlsplit

import websocket

from crytobot.news._binance_auth import (
    INVALID_REPLY,
    RESTRICTIONS_PATH,
    TIME_PATH,
    error_reason,
    restrictions_query,
    server_time,
    stream_query,
)
from crytobot.news._fetch import USER_AGENT
from crytobot.news._secrets import StreamKeys
from crytobot.news._stream import CONTROL_FRAME, ConnectionLost

CONNECT_TIMEOUT_S: Final = 30.0
TIME_TIMEOUT_S: Final = 10.0
RESTRICTIONS_LIMIT: Final = 64 * 1024
_ERROR_BODY_LIMIT: Final = 4096
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
        except (websocket.WebSocketException, OSError, ValueError):
            raise ConnectionLost("bağlantı koptu") from None
        if opcode == websocket.ABNF.OPCODE_CLOSE:
            raise ConnectionLost("kapandı")
        if opcode != websocket.ABNF.OPCODE_TEXT:
            return CONTROL_FRAME  # ping (answered by the library), pong, binary: liveness only
        if isinstance(data, str):
            return data
        return bytes(data).decode("utf-8", "replace")

    def ping(self) -> None:
        try:
            self._ws.ping("")
        except (websocket.WebSocketException, OSError):
            raise ConnectionLost("bağlantı koptu") from None

    def close(self) -> None:
        with suppress(websocket.WebSocketException, OSError):
            self._ws.close()


def open_stream(url: str, keys: StreamKeys, now_ms: int) -> WsConnection:
    """İmzalı adresle bağlanır; anahtar başlıkta; yönlendirme izlenmez."""
    address = f"{url}?{stream_query(keys.secret, now_ms, secrets.token_hex(16))}"
    try:
        socket_ = websocket.create_connection(
            address,
            header=[f"{_HEADER}: {keys.key}"],
            timeout=CONNECT_TIMEOUT_S,
            redirect_limit=0,
        )
    except websocket.WebSocketBadStatusException as error:
        raise ConnectionLost(f"http_{int(error.status_code)}") from None
    except (TimeoutError, websocket.WebSocketTimeoutException):
        raise ConnectionLost("timeout") from None
    except (websocket.WebSocketException, OSError, ssl.SSLError, ValueError):
        raise ConnectionLost("bağlanamadı") from None
    return WsConnection(socket_)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None  # a 3xx stays an HTTPError: the key header never travels to another address


_OPENER: Final = urllib.request.build_opener(_NoRedirect)


def fetch_server_time(url: str) -> int | None:
    """Binance'in sunucu saati (ms), anahtarsız; okunamazsa `None` (yerel saat kullanılır)."""
    host = urlsplit(url).hostname
    if not host:
        return None
    request = urllib.request.Request(
        f"https://{host}{TIME_PATH}", headers={"User-Agent": USER_AGENT}
    )
    try:
        with _OPENER.open(request, timeout=TIME_TIMEOUT_S) as response:
            body: bytes = response.read(_ERROR_BODY_LIMIT + 1)
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return None
    return None if len(body) > _ERROR_BODY_LIMIT else server_time(body)


def fetch_restrictions(url: str, keys: StreamKeys, now_ms: int) -> bytes | str:
    """Anahtarın yetki yanıtı; alınamazsa nedenin sırsız adı (yetki doğrulanamadı). Akış adresinin
    sunucusu."""
    host = urlsplit(url).hostname
    if not host:
        return "bağlanamadı"
    address = f"https://{host}{RESTRICTIONS_PATH}?{restrictions_query(keys.secret, now_ms)}"
    request = urllib.request.Request(address, headers={_HEADER: keys.key, "User-Agent": USER_AGENT})
    try:
        with _OPENER.open(request, timeout=CONNECT_TIMEOUT_S) as response:
            body: bytes = response.read(RESTRICTIONS_LIMIT + 1)
    except urllib.error.HTTPError as error:
        try:
            detail = error.read(_ERROR_BODY_LIMIT)
        except (OSError, http.client.HTTPException, ValueError):
            detail = b""
        return error_reason(int(error.code), detail)
    except TimeoutError:
        return "timeout"
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return "bağlanamadı"
    return INVALID_REPLY if len(body) > RESTRICTIONS_LIMIT else body
