"""Spec 0029 (AC-2, AC-7, R-2, R-7): TelegramClient sır redaksiyonu ve istemci testleri."""

from typing import Any

from crytobot.reporting._client import TelegramClient, redact_secret
from crytobot.reporting._config import TelegramConfig

SECRET_TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
CHAT_ID = "99887766"


def _make_config(enabled: bool = True) -> TelegramConfig:
    return TelegramConfig(enabled=enabled, bot_token=SECRET_TOKEN, chat_id=CHAT_ID)


def test_secret_redaction_in_errors_and_logs() -> None:
    # 1. URL içindeki bot token'ı redakte edilir
    url = f"https://api.telegram.org/bot{SECRET_TOKEN}/sendMessage"
    redacted = redact_secret(url, SECRET_TOKEN)
    assert SECRET_TOKEN not in redacted
    assert redacted == "https://api.telegram.org/bot[REDACTED]/sendMessage"

    # 2. Hata metninde geçen token redakte edilir
    error_msg = f"Failed to connect to api.telegram.org with token {SECRET_TOKEN} inside"
    safe_msg = redact_secret(error_msg, SECRET_TOKEN)
    assert SECRET_TOKEN not in safe_msg
    assert "[REDACTED]" in safe_msg

    # 3. İstemci hata durumunda token'ı dışarı sızdırmaz
    def failing_transport(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        raise RuntimeError(f"Connection failed to {url}")

    client = TelegramClient(_make_config(), transport=failing_transport)
    success, err = client.send_message("Test message")
    assert not success
    assert err is not None
    assert SECRET_TOKEN not in err


def test_client_http_401_disables_itself() -> None:
    # HTTP 401 Unauthorized durumunda istemci kalıcı olarak devre dışı kalmalıdır (R-7, G-5)
    call_count = 0

    def auth_fail_transport(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        nonlocal call_count
        call_count += 1
        return 401, '{"ok":false,"error_code":401,"description":"Unauthorized"}'

    client = TelegramClient(_make_config(), transport=auth_fail_transport)
    assert client.is_active

    success, err = client.send_message("Hello")
    assert not success
    assert err == "http_401_unauthorized"
    assert not client.is_active
    assert call_count == 1

    # Devre dışı kaldıktan sonra yeni çağrılar ağa çıkmaz
    success2, err2 = client.send_message("Second message")
    assert not success2
    assert err2 == "reporting_disabled"
    assert call_count == 1


def test_client_http_400_plain_text_fallback() -> None:
    # HTTP 400 Bad Request (örn. parse error) durumunda HTML yerine düz metinle
    # tekrar denenir (R-3, G-2)
    calls: list[dict[str, Any]] = []

    def parse_error_then_ok_transport(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        calls.append(payload)
        if "parse_mode" in payload:
            return (
                400,
                '{"ok":false,"error_code":400,"description":"Bad Request: can\'t parse entities"}',
            )
        return 200, '{"ok":true,"result":{}}'

    client = TelegramClient(_make_config(), transport=parse_error_then_ok_transport)
    success, err = client.send_message("Broken <b>text", parse_mode="HTML")

    assert success
    assert err is None
    assert len(calls) == 2
    # İlk çağrı HTML parse_mode ile yapıldı
    assert calls[0].get("parse_mode") == "HTML"
    # İkinci çağrı parse_mode olmadan düz metin olarak yapıldı
    assert "parse_mode" not in calls[1]
