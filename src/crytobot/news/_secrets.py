"""Akış kaynağının anahtarları (spec 0056 R-4, AC-1, AC-7; plan Risk 10).

Değerler yalnız ortamdan ya da `.env` dosyasından okunur; ortam önceliklidir. `news`
`execution`'ı import edemez (R-3a): okuyucu burada, küçük ve ayrı. Değerleri taşıyan tip
`repr`/`str`'de maskelidir; hata mesajı yalnız değişkenin adını söyler, değeri asla.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

MASK = "<gizli>"


class SecretsError(Exception):
    """`message` yalnız değişken adını taşır."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class StreamKeys:
    """Anahtar ve gizli anahtar; yazdırılınca maskeli."""

    key: str = field(repr=False)
    secret: str = field(repr=False)

    def __repr__(self) -> str:
        return f"StreamKeys({MASK})"

    __str__ = __repr__

    @property
    def values(self) -> tuple[str, str]:
        """Taramalar ve maskeleme için (AC-7)."""
        return self.key, self.secret


def _env_file(path: Path) -> dict[str, str]:
    """`AD=değer` satırları; `#` yorum, tırnaklar soyulur. Okunamayan dosya boş sayılır."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    found: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        found[name.strip()] = value
    return found


def load_stream_keys(
    key_env: str,
    secret_env: str,
    env: Mapping[str, str] | None = None,
    env_file: Path | None = None,
) -> StreamKeys:
    """AC-1: eksik ya da boş değişken `ortam değişkeni yok: <ad>`; değer mesaja girmez."""
    environment: Mapping[str, str] = os.environ if env is None else env
    from_file = {} if env_file is None else _env_file(env_file)
    values = []
    for name in (key_env, secret_env):
        value = (environment.get(name) or from_file.get(name) or "").strip()
        if not value:
            raise SecretsError(f"ortam değişkeni yok: {name}")
        values.append(value)
    return StreamKeys(values[0], values[1])


def redact(text: str, keys: StreamKeys | None) -> str:
    """Son savunma hattı: metinde geçen değerleri maskeler (dış kütüphanenin hata metinleri)."""
    if keys is None:
        return text
    for value in keys.values:
        text = text.replace(value, MASK)
    return text
