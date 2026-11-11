"""Spec 0039: Telegram güvenilirliği — sınıflama, kapanma, biçim, 429, geçici hata, süre sınırı.

Sahte transport ve enjekte saat kullanılır; süre sınırının gerçek kanıtı (CB-4) gerçek bir iş
parçacığıyla, 0.2 s bütçeyle ölçülür (plan Risk 1). Ağ pytest-socket ile kapalıdır.
"""

import json
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest

from crytobot.reporting import NotificationQueue, ReportingService, TelegramConfig
from crytobot.reporting._client import Outcome, classify

TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
CONFIG = TelegramConfig(enabled=True, bot_token=TOKEN, chat_id="99887766")
SLACK_S = 0.5  # gerçek saat ölçümlerinde iş parçacığı başlatma payı


def _body(code: int, description: str, retry_after: int | None = None) -> str:
    data: dict[str, Any] = {"ok": False, "error_code": code, "description": description}
    if retry_after is not None:
        data["parameters"] = {"retry_after": retry_after}
    return json.dumps(data)


OK = (200, '{"ok":true,"result":{}}')
PARSE_ERROR = (400, _body(400, "Bad Request: can't parse entities: unclosed tag"))
TOO_LONG = (400, _body(400, "Bad Request: message is too long"))
NETWORK = (0, "URLError: [Errno 11001] getaddrinfo failed")
UNAVAILABLE = (503, _body(503, "Service Unavailable"))

UNAUTHORIZED = (401, _body(401, "Unauthorized"))
CHAT_MISSING = (400, _body(400, "Bad Request: chat not found"))

PERMANENT = [
    pytest.param(UNAUTHORIZED, "yetkisiz token", id="401"),
    pytest.param(
        (403, _body(403, "Forbidden: bot was blocked by the user")), "bot engellendi", id="403"
    ),
    pytest.param(CHAT_MISSING, "chat bulunamadı", id="chat"),
    pytest.param((400, _body(400, "Bad Request: chat_id is empty")), "chat bulunamadı", id="empty"),
]


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Transport:
    """Sıradaki cevabı döner; cevaplar bitince sonuncusu tekrarlanır. Her isteği kaydeder."""

    def __init__(
        self, *answers: tuple[int, str], clock: FakeClock | None = None, cost: float = 0.0
    ):
        self.answers = list(answers)
        self.calls: list[dict[str, Any]] = []
        self.clock = clock
        self.cost = cost

    def __call__(self, url: str, payload: dict[str, Any]) -> tuple[int, str]:
        self.calls.append(payload)
        if self.clock is not None:
            self.clock.now += self.cost
        index = min(len(self.calls) - 1, len(self.answers) - 1)
        return self.answers[index]

    def texts(self) -> list[str]:
        return [call["text"] for call in self.calls]


class Hanging:
    """Serbest bırakılana kadar bekleyen transport (ad çözümleme takılması gibi)."""

    def __init__(self, hold_s: float | None = None) -> None:
        self.release = threading.Event()
        self.hold_s = hold_s
        self.calls = 0

    def __call__(self, url: str, payload: dict[str, Any]) -> tuple[int, str]:
        self.calls += 1
        self.release.wait(self.hold_s)
        return OK


@pytest.fixture
def hanging() -> Iterator[Hanging]:
    transport = Hanging()
    yield transport
    transport.release.set()


def _service(
    transport: Any, clock: FakeClock | None = None, budget: float = 5.0
) -> ReportingService:
    return ReportingService(
        CONFIG,
        queue=NotificationQueue(maxlen=10),
        transport=transport,
        monotonic=clock if clock is not None else time.monotonic,
        turn_budget_s=budget,
    )


def _queued(service: ReportingService) -> list[str]:
    return [message.text for message in list(service.queue._queue)]


# --- PB-6 ------------------------------------------------------------------------------------
def test_ok_single_html_request() -> None:
    transport = Transport(OK)
    service = _service(transport)
    service.begin_turn()
    assert service.dispatch("<b>m1</b>") is None
    assert service.dispatch("<b>m2</b>") is None
    service.end_turn()
    assert len(transport.calls) == 2
    assert all(call["parse_mode"] == "HTML" for call in transport.calls)
    assert len(service.queue) == 0


# --- CB-1 ------------------------------------------------------------------------------------
@pytest.mark.parametrize(("answer", "reason"), PERMANENT)
def test_permanent_error_disables_at_any_call(answer: tuple[int, str], reason: str) -> None:
    # Tur 1: iki başarılı istek, üçüncüsü geçici hata (m3 ve m4 kuyrukta).
    transport = Transport(OK, OK, UNAVAILABLE, answer)
    service = _service(transport)
    service.begin_turn()
    assert service.dispatch("m1") is None
    assert service.dispatch("m2") is None
    assert service.dispatch("m3") == "http_503"
    assert service.dispatch("m4") == "http_503"
    service.end_turn()
    assert _queued(service) == ["m3", "m4"]
    assert service.take_disabled_reason() is None

    # Tur 2: kuyruk iletilirken 4. istekte kalıcı hata → kapanır, kuyruk boşalır.
    service.begin_turn()
    assert len(transport.calls) == 4
    assert not service.is_active
    assert len(service.queue) == 0
    assert service.dispatch("m5") is None  # aynı turda istek yok, satır yok (plan Risk 6)
    service.end_turn()
    assert len(transport.calls) == 4
    assert len(service.queue) == 0
    assert service.take_disabled_reason() == reason
    assert service.take_disabled_reason() is None  # bir kez (CB-2)

    # Tur 3: kendiliğinden açılmaz.
    service.begin_turn()
    assert service.dispatch("m6") is None
    service.end_turn()
    assert len(transport.calls) == 4
    assert len(service.queue) == 0


@pytest.mark.parametrize(("answer", "reason"), PERMANENT)
def test_permanent_error_classified(answer: tuple[int, str], reason: str) -> None:
    result = classify(*answer)
    assert result.outcome is Outcome.PERMANENT
    assert result.reason == reason


# --- CB-3 ------------------------------------------------------------------------------------
def test_format_error_plain_retry_then_drop() -> None:
    # Düz metin başarılı: iletilmiş sayılır, 2 istek.
    transport = Transport(PARSE_ERROR, OK)
    service = _service(transport)
    assert service.dispatch("<b>kırık") is None
    assert len(transport.calls) == 2
    assert transport.calls[0]["parse_mode"] == "HTML"
    assert "parse_mode" not in transport.calls[1]
    assert len(service.queue) == 0

    # Düz metin de 400: atılır, kuyruğa girmez, hata adı döner, Telegram kapanmaz.
    transport = Transport(PARSE_ERROR, PARSE_ERROR, OK)
    service = _service(transport)
    service.begin_turn()
    assert service.dispatch("<b>kırık") == "http_400_bad_request"
    assert len(transport.calls) == 2
    assert len(service.queue) == 0
    assert service.is_active
    assert service.dispatch("sonraki") is None  # aynı turda sonraki mesaj gider
    service.end_turn()
    assert len(transport.calls) == 3
    assert service.take_disabled_reason() is None


def test_format_error_plain_transient_keeps_plain_in_queue() -> None:
    # Plan Risk 5: düz metin denemesi geçici hataya düşerse mesaj düz metin olarak kuyrukta
    # kalır; sonraki turda tek istekle (HTML hatası tekrarlanmadan) iletilir.
    transport = Transport(PARSE_ERROR, NETWORK, OK)
    service = _service(transport)
    service.begin_turn()
    assert service.dispatch("<b>kırık") == "network_error"
    service.end_turn()
    assert len(transport.calls) == 2
    head = service.queue.peek()
    assert head is not None and head.parse_mode is None

    service.begin_turn()
    service.end_turn()
    assert len(transport.calls) == 3
    assert "parse_mode" not in transport.calls[2]
    assert len(service.queue) == 0


@pytest.mark.parametrize(
    "answer",
    [TOO_LONG, (404, _body(404, "Not Found")), (409, _body(409, "Conflict"))],
    ids=["400", "404", "409"],
)
def test_other_400_dropped_not_retried(answer: tuple[int, str]) -> None:
    transport = Transport(answer, OK)
    service = _service(transport)
    service.begin_turn()
    err = service.dispatch("m1")
    assert err == ("http_400_bad_request" if answer[0] == 400 else f"http_{answer[0]}")
    assert len(transport.calls) == 1  # yeniden denenmez
    assert len(service.queue) == 0  # kuyruğa girmez
    assert service.is_active  # kapanmaz
    assert service.dispatch("m2") is None
    service.end_turn()
    assert len(transport.calls) == 2
    assert service.take_disabled_reason() is None


# --- CB-4 ------------------------------------------------------------------------------------
def test_turn_budget_bounds_all_sends(hanging: Hanging) -> None:
    # Gerçek saat: ilk istek takılır; bütün tur bütçe + pay içinde biter, mesajlar sırayla
    # kuyrukta.
    service = _service(hanging, budget=0.2)
    started = time.monotonic()
    service.begin_turn()
    errors = [service.dispatch(f"m{n}") for n in range(1, 5)]
    service.end_turn()
    elapsed = time.monotonic() - started
    assert elapsed < 0.2 + SLACK_S
    assert hanging.calls == 1
    assert errors[0] == "timeout"
    assert _queued(service) == ["m1", "m2", "m3", "m4"]


def test_turn_budget_shared_by_slow_successes() -> None:
    # Gerçek saat: her istek 0.15 s sürüp başarılı; 0.2 s'lik bütçeyi ikinci istek tüketir.
    transport = Hanging(hold_s=0.15)
    service = _service(transport, budget=0.2)
    started = time.monotonic()
    service.begin_turn()
    for n in range(1, 5):
        service.dispatch(f"m{n}")
    service.end_turn()
    elapsed = time.monotonic() - started
    transport.release.set()
    assert elapsed < 0.2 + SLACK_S
    assert transport.calls == 2
    assert _queued(service) == ["m2", "m3", "m4"]


def test_dns_hang_bounded_by_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    # Varsayılan transport: urlopen(timeout=) ad çözümlemeyi kapsamaz; bekleme yine sınırlı.
    release = threading.Event()
    lookups: list[str] = []

    def hanging_lookup(host: Any, *args: Any, **kwargs: Any) -> Any:
        lookups.append(str(host))
        release.wait(10)
        raise socket.gaierror("lookup released")

    monkeypatch.setattr(socket, "getaddrinfo", hanging_lookup)
    service = ReportingService(CONFIG, turn_budget_s=0.2)
    try:
        started = time.monotonic()
        service.begin_turn()
        assert service.dispatch("m1") == "timeout"
        assert service.dispatch("m2") == "timeout"
        service.end_turn()
        assert time.monotonic() - started < 0.2 + SLACK_S
        assert lookups == ["api.telegram.org"]
        assert _queued(service) == ["m1", "m2"]

        # Plan Risk 4: terk edilen istek sürerken sonraki turda istek gitmez.
        started = time.monotonic()
        service.begin_turn()
        assert service.dispatch("m3") == "timeout"
        service.end_turn()
        assert time.monotonic() - started < SLACK_S
        assert lookups == ["api.telegram.org"]
        assert _queued(service) == ["m1", "m2", "m3"]
    finally:
        release.set()


def test_budget_expiry_queues_in_order() -> None:
    # Enjekte saat: her istek 2 s sürer. Turun başında kuyruk ve yeni mesajlar 5 s'yi paylaşır.
    clock = FakeClock()
    transport = Transport(NETWORK, OK, clock=clock, cost=2.0)
    service = _service(transport, clock=clock)
    assert service.dispatch("q1") == "network_error"  # önceki tur: kuyruğa
    transport.answers = [OK]

    service.begin_turn()  # q1 (2 s)
    errors = [service.dispatch(f"m{n}") for n in range(1, 5)]
    service.end_turn()
    # q1, m1 (4 s), m2 (kalan 1 s ile başlar, 6 s) gider; m3 ve m4 sırayla kuyrukta.
    assert transport.texts() == ["q1", "q1", "m1", "m2"]
    assert errors == [None, None, "telegram_turn_budget", "telegram_turn_budget"]
    assert _queued(service) == ["m3", "m4"]

    service.begin_turn()  # yeni tur, yeni bütçe
    service.end_turn()
    assert transport.texts()[-2:] == ["m3", "m4"]
    assert len(service.queue) == 0


# --- CB-5 ------------------------------------------------------------------------------------
@pytest.mark.parametrize("answer", [NETWORK, UNAVAILABLE, (502, "<html>Bad Gateway</html>")])
def test_first_transient_stops_turn(answer: tuple[int, str]) -> None:
    transport = Transport(answer)
    service = _service(transport)
    service.begin_turn()
    first = service.dispatch("m1")
    assert first is not None
    assert service.dispatch("m2") == first
    assert service.dispatch("m3") == first
    service.end_turn()
    assert len(transport.calls) == 1
    assert _queued(service) == ["m1", "m2", "m3"]
    assert service.is_active

    transport.answers = [OK]
    service.begin_turn()  # sonraki tur: kuyruk yeniden denenir
    service.end_turn()
    assert transport.texts() == ["m1", "m1", "m2", "m3"]
    assert len(service.queue) == 0


def test_first_transient_timeout_stops_turn(hanging: Hanging) -> None:
    service = _service(hanging, budget=0.1)
    service.begin_turn()
    assert service.dispatch("m1") == "timeout"
    assert service.dispatch("m2") == "timeout"
    service.end_turn()
    assert hanging.calls == 1
    assert _queued(service) == ["m1", "m2"]

    hanging.release.set()
    deadline = time.monotonic() + 2
    while service._client.busy and time.monotonic() < deadline:
        time.sleep(0.01)
    service.begin_turn()
    service.end_turn()
    assert hanging.calls == 3
    assert len(service.queue) == 0


def test_transport_exception_is_transient() -> None:
    def raising(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        raise TimeoutError(f"timed out reaching {url}")

    service = _service(raising)
    service.begin_turn()
    assert service.dispatch("m1") == "TimeoutError"
    assert service.dispatch("m2") == "TimeoutError"
    service.end_turn()
    assert _queued(service) == ["m1", "m2"]
    assert service.is_active


# --- CB-6 ------------------------------------------------------------------------------------
def test_rate_limit_blocks_across_turns() -> None:
    clock = FakeClock()
    transport = Transport((429, _body(429, "Too Many Requests: retry after 3600", 3600)), OK)
    service = _service(transport, clock=clock)
    service.begin_turn()
    assert service.dispatch("m1") == "http_429"
    assert service.dispatch("m2") == "http_429"
    service.end_turn()
    assert len(transport.calls) == 1
    assert _queued(service) == ["m1", "m2"]

    clock.now += 3599  # üst sınır yok: süre verildiği kadar
    service.begin_turn()
    assert service.dispatch("m3") == "http_429"
    service.end_turn()
    assert len(transport.calls) == 1
    assert service.is_active

    clock.now += 1
    service.begin_turn()  # süre doldu: kuyruk sırayla
    service.end_turn()
    assert transport.texts() == ["m1", "m1", "m2", "m3"]
    assert len(service.queue) == 0
    assert service.is_active
    assert service.take_disabled_reason() is None


def test_rate_limit_without_retry_after_acts_transient() -> None:
    transport = Transport((429, _body(429, "Too Many Requests")), OK)
    service = _service(transport, clock=FakeClock())
    service.begin_turn()
    assert service.dispatch("m1") == "http_429"
    assert service.dispatch("m2") == "http_429"
    service.end_turn()
    assert len(transport.calls) == 1

    service.begin_turn()  # yalnız o turun geri kalanı için
    service.end_turn()
    assert transport.texts() == ["m1", "m1", "m2"]
    assert service.is_active


# --- PB-1 ------------------------------------------------------------------------------------
def test_no_secret_on_error_paths(hanging: Hanging) -> None:
    def leaky(answer: tuple[int, str]) -> Any:
        def transport(url: str, payload: dict[str, Any]) -> tuple[int, str]:
            status, body = answer
            data = json.loads(body)
            data["description"] += f" {url} {TOKEN}"  # sunucu cevabında token geçse bile
            return status, json.dumps(data)

        return transport

    def raising(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        raise RuntimeError(f"connect failed {url} token={TOKEN}")

    seen: list[str] = []
    cases: list[Any] = [
        leaky(UNAUTHORIZED),
        leaky(CHAT_MISSING),
        leaky(PARSE_ERROR),
        leaky((429, _body(429, "Too Many Requests", 30))),
        leaky(UNAVAILABLE),
        raising,
    ]
    for transport in cases:
        service = _service(transport, clock=FakeClock())
        seen.extend(str(service.dispatch("m1")) for _ in range(2))
        seen.append(str(service.take_disabled_reason()))
        seen.extend(service.drain_queue())
    timed = _service(hanging, budget=0.05)
    seen.append(str(timed.dispatch("m1")))
    assert all(TOKEN not in text and "ABC-DEF" not in text for text in seen)
    assert "chat bulunamadı" in seen and "yetkisiz token" in seen


# --- PB-2 ------------------------------------------------------------------------------------
def test_queue_cap_and_order_preserved() -> None:
    transport = Transport(NETWORK)
    service = _service(transport)
    for n in range(1, 13):
        service.dispatch(f"m{n}")  # her çağrı kendi turu (plan Risk 2)
    assert _queued(service) == [f"m{n}" for n in range(3, 13)]
    assert service.queue.dropped_count == 2

    transport.answers = [OK]
    before = len(transport.calls)
    assert service.dispatch("yeni") is None
    assert transport.texts()[before:] == [f"m{n}" for n in range(3, 13)] + ["yeni"]
    assert len(service.queue) == 0
