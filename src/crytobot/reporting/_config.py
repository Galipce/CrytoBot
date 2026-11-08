"""Reporting ve Telegram konfigürasyon yükleyicisi (spec 0029 R-1, AC-1).

Telegram bildirimleri isteğe bağlıdır (opt-in). `crytobot.toml` dosyasında `[reporting.telegram]`
bölümünde `enabled = true` olduğunda aktiftir. Bot token ortam değişkeninden (`TELEGRAM_BOT_TOKEN`)
veya `.env` dosyasından okunur; chat ID ise config dosyasından alınır.
Ayarlar eksik veya `enabled = false` ise bot hata vermeden başlar, bildirimler devre dışı kalır.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ENV_TOKEN_KEY = "TELEGRAM_BOT_TOKEN"


@dataclass(frozen=True)
class TelegramConfig:
    """Telegram bildirim ayarları."""

    enabled: bool
    bot_token: str
    chat_id: str

    @property
    def is_active(self) -> bool:
        """Bildirim gönderimi için ayarlar tam ve devrede mi?"""
        return self.enabled and bool(self.bot_token.strip()) and bool(self.chat_id.strip())


def _read_env_file(path: Path) -> dict[str, str]:
    """Basit .env ayrıştırıcısı: boş satırları ve yorumları atlar, tırnakları temizler."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip("\"'")
        values[key] = val
    return values


def load_reporting_config(
    raw_config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    env_path: Path | str | None = None,
) -> TelegramConfig:
    """[reporting.telegram] ayarlarını yükler.

    Eksik ayar durumunda hata fırlatmaz, `is_active=False` olan yapılandırma döner (R-1, AC-1).
    """
    if raw_config is None:
        raw_config = {}

    reporting_section = raw_config.get("reporting")
    if not isinstance(reporting_section, Mapping):
        reporting_section = {}

    telegram_section = reporting_section.get("telegram")
    if not isinstance(telegram_section, Mapping):
        # Allow flat structure if raw_config is the telegram section itself
        telegram_section = (
            raw_config if ("enabled" in raw_config or "chat_id" in raw_config) else {}
        )

    enabled_val = telegram_section.get("enabled", False)
    enabled = enabled_val is True

    chat_id_val = telegram_section.get("chat_id", "")
    chat_id = str(chat_id_val).strip() if chat_id_val is not None else ""

    # Bot token: önce verilen env eşlemine, sonra os.environ'a, sonra .env dosyasına bakılır
    bot_token = ""
    if env is not None and ENV_TOKEN_KEY in env:
        bot_token = env[ENV_TOKEN_KEY].strip()
    elif ENV_TOKEN_KEY in os.environ:
        bot_token = os.environ[ENV_TOKEN_KEY].strip()
    else:
        path = Path(env_path) if env_path is not None else Path(".env")
        env_vars = _read_env_file(path)
        bot_token = env_vars.get(ENV_TOKEN_KEY, "").strip()

    return TelegramConfig(
        enabled=enabled,
        bot_token=bot_token,
        chat_id=chat_id,
    )
