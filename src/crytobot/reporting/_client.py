"""Telegram Bot API HTTPS POST istemcisi (spec 0029 R-2, R-3, R-7, AC-2, AC-7).

Sır güvenliği (docs/security.md): Bot token URL'de (`/bot<TOKEN>/sendMessage`) ve hata
mesajlarında asla açık olarak bulunmaz; her zaman `[REDACTED]` ile maskelenir.
Ağ hatası veya 401 Unauthorized durumunda bot döngüsünü engellemeden güvenli hata döner.
"""

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from crytobot.reporting._config import TelegramConfig

TransportFunc = Callable[[str, dict[str, Any]], tuple[int, str]]
_TOKEN_IN_URL_PATTERN = re.compile(r"/bot[^/]+/")


def redact_secret(text: str, secret: str = "") -> str:
    """Metin içindeki Telegram bot token'ını ve URL yolundaki token'ı redakte eder."""
    if not text:
        return text
    result = _TOKEN_IN_URL_PATTERN.sub("/bot[REDACTED]/", text)
    if secret and secret.strip():
        result = result.replace(secret.strip(), "[REDACTED]")
    return result


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

    @property
    def is_active(self) -> bool:
        """İstemci yapılandırılmış ve devre dışı kalmamış mı?"""
        return self._config.is_active and not self._disabled

    def disable(self) -> None:
        """Kimlik hatası veya açık istek ile istemciyi devre dışı bırakır (R-7, G-5)."""
        self._disabled = True

    def send_message(
        self,
        text: str,
        parse_mode: str | None = "HTML",
    ) -> tuple[bool, str | None]:
        """Telegram'a tek bir mesaj gönderir.

        HTTP 400 (Bad Request - HTML ayrıştırma hatası) durumunda mesajı düz metin
        (parse_mode=None) olarak tekrar iletmeyi dener (R-3, G-2).
        HTTP 401 (Unauthorized) durumunda istemci otomatik devre dışı kalır (G-5).

        Dönüş: `(başarı: bool, hata_adı: str | None)`
        """
        if not self.is_active:
            return False, "reporting_disabled"

        url = f"https://api.telegram.org/bot{self._config.bot_token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": self._config.chat_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            status, _body = self._transport(url, payload)
        except Exception as exc:
            safe_err = redact_secret(f"{type(exc).__name__}", self._config.bot_token)
            return False, safe_err

        # Başarılı (HTTP 200)
        if 200 <= status < 300:
            return True, None

        # HTTP 400: Telegram ayrıştırma hatası olabilir; HTML yerine düz metin ile tekrar dene (G-2)
        if status == 400 and parse_mode is not None:
            plain_payload = {
                "chat_id": self._config.chat_id,
                "text": text,
            }
            try:
                retry_status, _ = self._transport(url, plain_payload)
                if 200 <= retry_status < 300:
                    return True, None
            except Exception:
                pass
            return False, "http_400_bad_request"

        # HTTP 401: Geçersiz token -> Telegram'ı devre dışı bırak (G-5)
        if status == 401:
            self.disable()
            return False, "http_401_unauthorized"

        # Ağ veya sunucu hatası (0, 429, 500, vb.)
        if status == 0:
            return False, "network_error"
        return False, f"http_{status}"
