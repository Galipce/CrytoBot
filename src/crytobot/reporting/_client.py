"""Telegram Bot API HTTPS POST istemcisi (spec 0029 R-2, R-3, R-7; spec 0039).

Sır güvenliği (docs/security.md): Bot token URL'de (`/bot<TOKEN>/sendMessage`) ve hata
mesajlarında asla açık olarak bulunmaz; her zaman `[REDACTED]` ile maskelenir.

Spec 0039: her cevap `classify` ile sınıflanır (kalıcı · biçim · reddedilen · hız sınırı ·
geçici). `attempt` tek istek atar ve transport'u daemon iş parçacığında çalıştırıp en fazla
`limit` saniye bekler: `urlopen(timeout=)` ad çözümlemeyi kapsamaz (docs/conventions.md).
"""

import json
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from crytobot.reporting._config import TelegramConfig

TransportFunc = Callable[[str, dict[str, Any]], tuple[int, str]]
_TOKEN_IN_URL_PATTERN = re.compile(r"/bot[^/]+/")
_LEGACY_LIMIT_S = 5.0  # send_message (tur penceresi dışında) için tek istek sınırı

# Telegram 400 açıklamalarında kalıcı hata (G-4) ve biçim hatası işaretleri
_CHAT_NOT_FOUND = ("chat not found", "chat_id is empty")
_PARSE_ERROR = "can't parse entities"


class Outcome(Enum):
    OK = "ok"
    PERMANENT = "permanent"  # 401 / 403 / 400 chat bulunamadı: Telegram kapanır (CB-1)
    FORMAT = "format"  # 400 can't parse entities: düz metinle tek deneme (CB-3)
    REJECTED = "rejected"  # diğer 4xx: atılır, yeniden denenmez (CB-3, plan Risk 3)
    RATE_LIMITED = "rate_limited"  # 429 (CB-6)
    TRANSIENT = "transient"  # ağ hatası, zaman aşımı, 5xx (CB-5, G-1)


@dataclass(frozen=True)
class Attempt:
    """Tek isteğin sonucu. `error` redakte hata adı; `reason` kalıcı hatanın gerekçesi."""

    outcome: Outcome
    error: str | None = None
    reason: str | None = None
    retry_after: float | None = None


_TIMED_OUT = Attempt(Outcome.TRANSIENT, "timeout")


def redact_secret(text: str, secret: str = "") -> str:
    """Metin içindeki Telegram bot token'ını ve URL yolundaki token'ı redakte eder."""
    if not text:
        return text
    result = _TOKEN_IN_URL_PATTERN.sub("/bot[REDACTED]/", text)
    if secret and secret.strip():
        result = result.replace(secret.strip(), "[REDACTED]")
    return result


def _parse_body(body: str) -> tuple[str, float | None]:
    """Gövdeden (açıklama küçük harfle, retry_after); JSON değilse ("", None)."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return "", None
    if not isinstance(data, dict):
        return "", None
    description = data.get("description")
    text = description.lower() if isinstance(description, str) else ""
    retry_after: float | None = None
    parameters = data.get("parameters")
    if isinstance(parameters, dict):
        value = parameters.get("retry_after")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            retry_after = float(value)
    return text, retry_after


def classify(status: int, body: str) -> Attempt:
    """HTTP durum kodu ve gövdeden sınıf (spec 0039 CB-1, CB-3, CB-5, CB-6; plan Risk 3)."""
    if 200 <= status < 300:
        return Attempt(Outcome.OK)
    if status == 0:
        return Attempt(Outcome.TRANSIENT, "network_error")
    description, retry_after = _parse_body(body)
    if status == 401:
        return Attempt(Outcome.PERMANENT, "http_401_unauthorized", "yetkisiz token")
    if status == 403:
        return Attempt(Outcome.PERMANENT, "http_403_forbidden", "bot engellendi")
    if status == 400:
        if any(marker in description for marker in _CHAT_NOT_FOUND):
            return Attempt(Outcome.PERMANENT, "http_400_bad_request", "chat bulunamadı")
        if _PARSE_ERROR in description:
            return Attempt(Outcome.FORMAT, "http_400_bad_request")
        return Attempt(Outcome.REJECTED, "http_400_bad_request")
    if status == 429:
        return Attempt(Outcome.RATE_LIMITED, "http_429", retry_after=retry_after)
    if 400 <= status < 500:
        return Attempt(Outcome.REJECTED, f"http_{status}")
    return Attempt(Outcome.TRANSIENT, f"http_{status}")  # 5xx; 1xx/3xx/≥600 de (Risk 3)


def _default_transport(url: str, payload: dict[str, Any]) -> tuple[int, str]:
    """urllib.request ile gerçek HTTPS POST çağrısı."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            status = int(response.status)
            body = response.read().decode("utf-8", errors="replace")
            return status, body
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        return int(err.code), body
    except urllib.error.URLError as err:
        return 0, f"URLError: {err.reason}"
    except TimeoutError:
        return 0, "TimeoutError: connection timed out"
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


class TelegramClient:
    """Telegram Bot API ile tek yönlü mesaj iletimi."""

    def __init__(
        self,
        config: TelegramConfig,
        transport: TransportFunc | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or _default_transport
        self._disabled: bool = False
        self._abandoned: threading.Thread | None = None

    @property
    def is_active(self) -> bool:
        """İstemci yapılandırılmış ve devre dışı kalmamış mı?"""
        return self._config.is_active and not self._disabled

    @property
    def busy(self) -> bool:
        """Süresi dolup terk edilen önceki istek hâlâ sürüyor mu? (plan Risk 4)"""
        thread = self._abandoned
        if thread is None:
            return False
        if thread.is_alive():
            return True
        self._abandoned = None
        return False

    def disable(self) -> None:
        """Kalıcı hata veya açık istek ile istemciyi devre dışı bırakır (spec 0039 CB-1)."""
        self._disabled = True

    def attempt(self, text: str, parse_mode: str | None, limit: float) -> Attempt:
        """Tek istek; en fazla `limit` saniye beklenir, süre dolarsa zaman aşımı (CB-4).

        Süresi dolan istek iş parçacığında terk edilir, sonucu yok sayılır (G-2).
        """
        if limit <= 0:
            return _TIMED_OUT
        url = f"https://api.telegram.org/bot{self._config.bot_token}/sendMessage"
        payload: dict[str, Any] = {"chat_id": self._config.chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode

        answers: list[tuple[int, str]] = []
        errors: list[Exception] = []

        def work() -> None:
            try:
                answers.append(self._transport(url, payload))
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=work, daemon=True, name="crytobot-telegram-call")
        thread.start()
        thread.join(min(limit, threading.TIMEOUT_MAX))
        if thread.is_alive():
            self._abandoned = thread
            return _TIMED_OUT
        if errors:
            name = redact_secret(type(errors[0]).__name__, self._config.bot_token)
            return Attempt(Outcome.TRANSIENT, name)
        status, body = answers[0]
        return classify(status, body)

    def send_message(
        self,
        text: str,
        parse_mode: str | None = "HTML",
    ) -> tuple[bool, str | None]:
        """Telegram'a tek bir mesaj gönderir (tur penceresi dışındaki çağıranlar için).

        Yalnız biçim hatasında (400 can't parse entities) düz metinle bir kez yeniden dener
        (spec 0039 CB-3). Kalıcı hatada istemci devre dışı kalır (CB-1).

        Dönüş: `(başarı: bool, hata_adı: str | None)`
        """
        if not self.is_active:
            return False, "reporting_disabled"
        result = self.attempt(text, parse_mode, _LEGACY_LIMIT_S)
        if result.outcome is Outcome.FORMAT and parse_mode is not None:
            result = self.attempt(text, None, _LEGACY_LIMIT_S)
            if result.outcome is Outcome.FORMAT:
                result = Attempt(Outcome.REJECTED, result.error)
        if result.outcome is Outcome.OK:
            return True, None
        if result.outcome is Outcome.PERMANENT:
            self.disable()
        return False, result.error
