"""Borsa API anahtar/secret veri yapısı ve redaksiyonu (spec 0032 R-1, R-4, R-8)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

REDACTED = "***REDACTED***"
CREDENTIALS_MISSING = "CREDENTIALS_MISSING"


class ExecutionError(Exception):
    """Execution modülü temel hata sınıfı."""


class CredentialsError(ExecutionError):
    """Borsa kimlik bilgileri eksik veya geçersiz olduğunda fırlatılır."""

    def __init__(self, message: str = CREDENTIALS_MISSING, code: str = CREDENTIALS_MISSING) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, repr=False)
class ExchangeCredentials:
    """Binance API anahtarları. __repr__ ve __str__ açık sır basmaz (R-4)."""

    api_key: str
    api_secret: str
    testnet: bool = False

    def __repr__(self) -> str:
        return (
            f"ExchangeCredentials(api_key={REDACTED}, api_secret={REDACTED}, "
            f"testnet={self.testnet!r})"
        )

    def __str__(self) -> str:
        return (
            f"ExchangeCredentials(api_key={REDACTED}, api_secret={REDACTED}, "
            f"testnet={self.testnet!r})"
        )


def _parse_env_file(path: Path) -> dict[str, str]:
    """Basit .env dosya ayrıştırıcısı. Yalnızca KEY=VAL satırlarını okur."""
    if not path.is_file():
        return {}
    res: dict[str, str] = {}
    content = path.read_text(encoding="utf-8")
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        res[k] = v
    return res


def load_credentials(
    testnet: bool = False,
    env: Mapping[str, str] | None = None,
    env_file: Path | str | None = None,
) -> ExchangeCredentials:
    """Canlı veya testnet borsa kimlik bilgilerini yükler (R-1, R-8).

    Config dosyasında anahtar aranmaz. Eksik veya boşsa CREDENTIALS_MISSING fırlatılır.
    """
    key_var = "BINANCE_TESTNET_API_KEY" if testnet else "BINANCE_API_KEY"
    secret_var = "BINANCE_TESTNET_API_SECRET" if testnet else "BINANCE_API_SECRET"

    file_env: dict[str, str] = {}
    if env_file is not None:
        file_env = _parse_env_file(Path(env_file))
    elif env is None and Path(".env").is_file():
        file_env = _parse_env_file(Path(".env"))

    env_map: Mapping[str, str] = os.environ if env is None else env

    api_key = env_map.get(key_var) or file_env.get(key_var) or ""
    api_secret = env_map.get(secret_var) or file_env.get(secret_var) or ""

    api_key = api_key.strip()
    api_secret = api_secret.strip()

    if not api_key or not api_secret:
        raise CredentialsError(
            f"Borsa kimlik bilgileri eksik ({key_var}, {secret_var}): {CREDENTIALS_MISSING}",
            code=CREDENTIALS_MISSING,
        )

    return ExchangeCredentials(api_key=api_key, api_secret=api_secret, testnet=testnet)


def redact_secrets(text: str, credentials: ExchangeCredentials | None = None) -> str:
    """Metin veya log içerisindeki API anahtarlarını maskeler (R-4)."""
    if credentials is None:
        return text
    out = text
    if credentials.api_key:
        out = out.replace(credentials.api_key, REDACTED)
    if credentials.api_secret:
        out = out.replace(credentials.api_secret, REDACTED)
    return out
