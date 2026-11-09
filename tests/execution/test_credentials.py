"""Spec 0032 AC-1 ve AC-4: Kimlik bilgilerinin güvenli yüklenmesi ve redaksiyonu."""

from pathlib import Path

import pytest

from crytobot.execution._credentials import (
    CREDENTIALS_MISSING,
    REDACTED,
    CredentialsError,
    ExchangeCredentials,
    load_credentials,
    redact_secrets,
)


def test_load_credentials_from_env_and_file(tmp_path: Path) -> None:
    """AC-1: Canlı modda ve testnet modunda kimlikler ortamdan ve .env dosyasından okunur."""
    # 1. Ortam sözlüğünden canlı anahtarlar
    live_env = {
        "BINANCE_API_KEY": "live_key_123",
        "BINANCE_API_SECRET": "live_secret_456",
    }
    creds = load_credentials(testnet=False, env=live_env)
    assert creds.api_key == "live_key_123"
    assert creds.api_secret == "live_secret_456"
    assert not creds.testnet

    # 2. Testnet modunda canlı anahtarlar kullanılmaz, testnet anahtarları aranır
    with pytest.raises(CredentialsError) as exc_info:
        load_credentials(testnet=True, env=live_env)
    assert exc_info.value.code == CREDENTIALS_MISSING

    testnet_env = {
        "BINANCE_TESTNET_API_KEY": "testnet_key_abc",
        "BINANCE_TESTNET_API_SECRET": "testnet_secret_xyz",
    }
    creds_tn = load_credentials(testnet=True, env=testnet_env)
    assert creds_tn.api_key == "testnet_key_abc"
    assert creds_tn.api_secret == "testnet_secret_xyz"
    assert creds_tn.testnet

    # 3. .env dosyasından okuma (tek tırnak, çift tırnak, geçersiz satırlar ve yorumlar)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# Yorum satırı\n"
        "\n"
        "GEÇERSİZ_SATIR_EŞİTTİR_YOK\n"
        "BINANCE_API_KEY=file_key_789 # satır içi yorum\n"
        'export BINANCE_API_SECRET="file_secret_999"\n',
        encoding="utf-8",
    )
    creds_file = load_credentials(testnet=False, env={}, env_file=env_file)
    assert creds_file.api_key == "file_key_789"
    assert creds_file.api_secret == "file_secret_999"

    # 4. Eksik veya boş anahtarlar CREDENTIALS_MISSING ile reddedilir
    with pytest.raises(CredentialsError) as exc_missing:
        load_credentials(testnet=False, env={}, env_file=tmp_path / "non_existent.env")
    assert exc_missing.value.code == CREDENTIALS_MISSING

    with pytest.raises(CredentialsError) as exc_empty:
        load_credentials(testnet=False, env={"BINANCE_API_KEY": "  ", "BINANCE_API_SECRET": ""})
    assert exc_empty.value.code == CREDENTIALS_MISSING

    # Yalnızca secret eksikse
    with pytest.raises(CredentialsError):
        load_credentials(testnet=False, env={"BINANCE_API_KEY": "key1", "BINANCE_API_SECRET": ""})


def test_credentials_repr_and_str_redacted() -> None:
    """AC-4: API anahtarı ve secret hiçbir koşulda açık metin basılmaz."""
    secret_key = "super_secret_api_key_value_98765"
    secret_val = "ultra_confidential_secret_hash_43210"

    creds = ExchangeCredentials(api_key=secret_key, api_secret=secret_val, testnet=False)

    repr_str = repr(creds)
    str_str = str(creds)

    assert secret_key not in repr_str
    assert secret_val not in repr_str
    assert secret_key not in str_str
    assert secret_val not in str_str

    assert REDACTED in repr_str
    assert REDACTED in str_str

    # redact_secrets metin maskeleme
    raw_log = f"Order failed with key={secret_key} and sig={secret_val}"
    masked_log = redact_secrets(raw_log, creds)

    assert secret_key not in masked_log
    assert secret_val not in masked_log
    assert masked_log == f"Order failed with key={REDACTED} and sig={REDACTED}"

    # Sırları tekil olarak maskeleme
    creds_only_key = ExchangeCredentials(api_key="k_only", api_secret="", testnet=False)
    assert redact_secrets("k_only is key", creds_only_key) == f"{REDACTED} is key"

    creds_only_secret = ExchangeCredentials(api_key="", api_secret="s_only", testnet=False)
    assert redact_secrets("s_only is sec", creds_only_secret) == f"{REDACTED} is sec"

    # None creds ile çağrıldığında metni bozmaz
    assert redact_secrets("normal text", None) == "normal text"

    # Substring durumu: key secret'ın alt dizesi olsa bile uzunluk sırasına göre maskelenir (F-5)
    creds_sub = ExchangeCredentials(api_key="sub", api_secret="prefix_sub_suffix", testnet=False)
    masked_sub = redact_secrets("error: prefix_sub_suffix leaked", creds_sub)
    assert "prefix" not in masked_sub
    assert "suffix" not in masked_sub
    assert masked_sub == f"error: {REDACTED} leaked"
