"""Spec 0029 (AC-1, R-1): Reporting konfigürasyon ve opt-in testleri."""

from pathlib import Path

from crytobot.reporting._config import load_reporting_config


def test_reporting_config_opt_in_and_disabled(tmp_path: Path) -> None:
    # 1. Varsayılan (boş ayar): devre dışı, hata yok
    cfg = load_reporting_config({})
    assert not cfg.enabled
    assert not cfg.is_active
    assert cfg.bot_token == ""
    assert cfg.chat_id == ""

    # 2. None girdi: devre dışı, hata yok
    cfg_none = load_reporting_config(None)
    assert not cfg_none.is_active

    # 3. enabled=False olarak verilmiş
    cfg_disabled = load_reporting_config(
        {"reporting": {"telegram": {"enabled": False, "chat_id": "12345"}}},
        env={"TELEGRAM_BOT_TOKEN": "my-secret-token"},
    )
    assert not cfg_disabled.enabled
    assert not cfg_disabled.is_active

    # 4. enabled=True ancak token eksik
    cfg_missing_token = load_reporting_config(
        {"reporting": {"telegram": {"enabled": True, "chat_id": "12345"}}},
        env={},
        env_path=tmp_path / "non_existent.env",
    )
    assert cfg_missing_token.enabled
    assert not cfg_missing_token.is_active

    # 5. enabled=True ancak chat_id eksik
    cfg_missing_chat = load_reporting_config(
        {"reporting": {"telegram": {"enabled": True, "chat_id": ""}}},
        env={"TELEGRAM_BOT_TOKEN": "my-secret-token"},
    )
    assert cfg_missing_chat.enabled
    assert not cfg_missing_chat.is_active

    # 6. enabled=True ve ortam değişkeninden token okundu: aktif
    cfg_env = load_reporting_config(
        {"reporting": {"telegram": {"enabled": True, "chat_id": "98765"}}},
        env={"TELEGRAM_BOT_TOKEN": "valid-token-from-env"},
    )
    assert cfg_env.enabled
    assert cfg_env.is_active
    assert cfg_env.bot_token == "valid-token-from-env"
    assert cfg_env.chat_id == "98765"

    # 7. enabled=True ve .env dosyasından token okundu: aktif
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# Comment\nTELEGRAM_BOT_TOKEN=token-from-file\nOTHER=foo\n", encoding="utf-8"
    )
    cfg_file = load_reporting_config(
        {"reporting": {"telegram": {"enabled": True, "chat_id": "111222"}}},
        env={},
        env_path=env_file,
    )
    assert cfg_file.enabled
    assert cfg_file.is_active
    assert cfg_file.bot_token == "token-from-file"
    assert cfg_file.chat_id == "111222"
