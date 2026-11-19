"""Spec 0056 AC-7, AC-2 (review round 1 M-1, M-2, L-2): gerçek bağlantı katmanı, kütüphane
sahtesiyle (ağ yok). Kütüphanenin hata metni anahtarı taşısa bile satıra giden ad sabittir;
yönlendirme izlenmez; `urlopen`'ın sarmadığı `HTTPException` yakalanır."""

import http.client
import io
import ssl
import urllib.error
import urllib.request
from typing import Any

import pytest
import websocket

from crytobot.news import _stream_ws
from crytobot.news._secrets import StreamKeys
from crytobot.news._stream import CONTROL_FRAME, ConnectionLost
from crytobot.news._stream_ws import (
    WsConnection,
    fetch_restrictions,
    fetch_server_time,
    open_stream,
)

KEY = "FAKEKEY-abcdefghijklmnop0123"
SECRET = "FAKESECRET-qrstuvwxyz456789"
KEYS = StreamKeys(KEY, SECRET)
URL = "wss://api.binance.com/sapi/wss"
LEAK = f"failure carrying {KEY} and {SECRET}"


def clean(text: str) -> None:
    assert KEY not in text and SECRET not in text


@pytest.mark.parametrize(
    ("error", "name"),
    [
        (websocket.WebSocketBadStatusException(LEAK + " %s %s", 401, "Unauthorized"), "http_401"),
        (websocket.WebSocketTimeoutException(LEAK), "timeout"),
        (TimeoutError(LEAK), "timeout"),
        (OSError(LEAK), "bağlanamadı"),
        (ssl.SSLError(LEAK), "bağlanamadı"),
        (websocket.WebSocketException(LEAK), "bağlanamadı"),
        (ValueError(LEAK), "bağlanamadı"),
    ],
)
def test_connect_errors_named_without_values(
    monkeypatch: pytest.MonkeyPatch, error: Exception, name: str
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(websocket, "create_connection", refuse)
    with pytest.raises(ConnectionLost) as raised:
        open_stream(URL, KEYS, 1)
    assert raised.value.name == name
    clean(raised.value.name)
    clean(str(raised.value))
    assert raised.value.__suppress_context__


def test_connect_signed_header_no_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def accept(address: str, **options: Any) -> object:
        seen.update(options, address=address)
        return object()

    monkeypatch.setattr(websocket, "create_connection", accept)
    open_stream(URL, KEYS, 1795000000000)
    assert seen["header"] == [f"X-MBX-APIKEY: {KEY}"]
    assert seen["redirect_limit"] == 0
    assert seen["address"].startswith(f"{URL}?random=")
    assert "timestamp=1795000000000" in seen["address"] and "&signature=" in seen["address"]
    clean(seen["address"])  # the secret signs; it never travels


class FakeSocket:
    def __init__(self, frames: list[object]) -> None:
        self.frames = frames
        self.timeouts: list[float] = []
        self.pinged = 0
        self.closed = False

    def settimeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)

    def recv_data(self, control_frame: bool = False) -> tuple[int, object]:
        assert control_frame
        frame = self.frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        assert isinstance(frame, tuple)
        return frame

    def ping(self, payload: str = "") -> None:
        self.pinged += 1
        first = self.frames[0] if self.frames else None
        if isinstance(first, OSError):
            self.frames.pop(0)
            raise first

    def close(self) -> None:
        self.closed = True
        raise OSError(LEAK)


def test_frames_mapped() -> None:
    abnf = websocket.ABNF
    fake = FakeSocket(
        [
            (abnf.OPCODE_TEXT, b'{"a":1}'),
            (abnf.OPCODE_TEXT, "metin"),
            (abnf.OPCODE_PONG, b""),
            (abnf.OPCODE_BINARY, b"\x00"),
            websocket.WebSocketTimeoutException(LEAK),
            (abnf.OPCODE_CLOSE, b""),
        ]
    )
    connection = WsConnection(fake)  # type: ignore[arg-type]
    assert connection.recv(1.0) == '{"a":1}'
    assert connection.recv(1.0) == "metin"
    assert connection.recv(1.0) == CONTROL_FRAME
    assert connection.recv(1.0) == CONTROL_FRAME
    assert connection.recv(1.0) is None
    with pytest.raises(ConnectionLost) as raised:
        connection.recv(1.0)
    assert raised.value.name == "kapandı" and fake.timeouts == [1.0] * 6
    connection.close()  # a failing close is swallowed
    assert fake.closed


@pytest.mark.parametrize(
    "error", [websocket.WebSocketConnectionClosedException(LEAK), OSError(LEAK), ValueError(LEAK)]
)
def test_recv_and_ping_failures_are_lost(error: Exception) -> None:
    connection = WsConnection(FakeSocket([error]))  # type: ignore[arg-type]
    with pytest.raises(ConnectionLost) as raised:
        connection.recv(1.0)
    assert raised.value.name == "bağlantı koptu"
    clean(str(raised.value))
    connection = WsConnection(FakeSocket([OSError(LEAK)]))  # type: ignore[arg-type]
    with pytest.raises(ConnectionLost) as raised:
        connection.ping()
    assert raised.value.name == "bağlantı koptu"


class FakeResponse(io.BytesIO):
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def test_restrictions_request_signed(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[urllib.request.Request] = []

    def answer(request: urllib.request.Request, timeout: float) -> FakeResponse:
        seen.append(request)
        return FakeResponse(b'{"enableReading":true}')

    monkeypatch.setattr(_stream_ws._OPENER, "open", answer)
    assert fetch_restrictions(URL, KEYS, 7) == b'{"enableReading":true}'
    (request,) = seen
    assert request.full_url.startswith("https://api.binance.com/sapi/v1/account/apiRestrictions?")
    assert request.get_header("X-mbx-apikey") == KEY
    clean(request.full_url)


def http_error(status: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(URL, status, LEAK, {}, io.BytesIO(body))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("error", "name"),
    [
        (http_error(400, b'{"code":-1021,"msg":"' + LEAK.encode() + b'"}'), "http_400/-1021"),
        (http_error(401, LEAK.encode()), "http_401"),
        (http_error(302, b""), "http_302"),
        (urllib.error.URLError(LEAK), "bağlanamadı"),
        (http.client.BadStatusLine(LEAK), "bağlanamadı"),
        (http.client.IncompleteRead(b"x"), "bağlanamadı"),
        (http.client.LineTooLong(LEAK), "bağlanamadı"),
        (TimeoutError(LEAK), "timeout"),
        (OSError(LEAK), "bağlanamadı"),
    ],
)
def test_restrictions_failures_unverified(
    monkeypatch: pytest.MonkeyPatch, error: Exception, name: str
) -> None:
    """M-1: `HTTPException` (`URLError`'a sarılmaz, `OSError` değil) da doğrulanamadı olur. Plan
    A-7: nedenin sırsız adı döner; Binance'in ya da kütüphanenin metni girmez."""

    def fail(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(_stream_ws._OPENER, "open", fail)
    reason = fetch_restrictions(URL, KEYS, 7)
    assert reason == name
    assert isinstance(reason, str)
    clean(reason)


def test_server_time_keyless(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan A-7: sunucu saati anahtarsız istekle; hata ya da bozuk yanıt `None`."""
    seen: list[urllib.request.Request] = []
    answers = iter([b'{"serverTime":1795000000999}', b"<html>", b"x" * 5000])

    def answer(request: urllib.request.Request, timeout: float) -> FakeResponse:
        seen.append(request)
        return FakeResponse(next(answers))

    monkeypatch.setattr(_stream_ws._OPENER, "open", answer)
    assert fetch_server_time(URL) == 1795000000999
    assert fetch_server_time(URL) is None
    assert fetch_server_time(URL) is None  # oversized
    assert seen[0].full_url == "https://api.binance.com/api/v3/time"
    assert seen[0].get_header("X-mbx-apikey") is None
    assert fetch_server_time("wss:///x") is None

    def fail(*_args: object, **_kwargs: object) -> None:
        raise http.client.BadStatusLine(LEAK)

    monkeypatch.setattr(_stream_ws._OPENER, "open", fail)
    assert fetch_server_time(URL) is None


def test_restrictions_oversized_or_hostless(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review round 2 I-3: sunucusuz adres ve sınırı aşan yanıt doğrulanamadı olur; tam sınır
    geçer."""
    assert fetch_restrictions("wss:///sapi/wss", KEYS, 7) == "bağlanamadı"
    limit = _stream_ws.RESTRICTIONS_LIMIT
    sizes = iter([limit + 1, limit])

    def answer(request: urllib.request.Request, timeout: float) -> FakeResponse:
        return FakeResponse(b"x" * next(sizes))

    monkeypatch.setattr(_stream_ws._OPENER, "open", answer)
    assert fetch_restrictions(URL, KEYS, 7) == "yanıt geçersiz"
    assert fetch_restrictions(URL, KEYS, 7) == b"x" * limit


def test_redirects_not_followed() -> None:
    """L-2: yönlendirme işleyicisi yeni istek kurmaz; 3xx `HTTPError` kalır."""
    handlers: list[Any] = getattr(_stream_ws._OPENER, "handlers")  # noqa: B009 - untyped attribute
    handler: Any = next(h for h in handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
    request = urllib.request.Request("https://api.binance.com/x", headers={"X-MBX-APIKEY": KEY})
    assert handler.redirect_request(request, None, 302, "Found", {}, "http://evil/") is None
