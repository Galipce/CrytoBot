"""Binance imzası ve anahtar yetkisinin hükmü (spec 0056 R-5, AC-2; plan Risk 7, 8, A-1). Saf: ağa,
saate ve ortama dokunmaz.

İmza: istek parametreleri (imza hariç) adlarına göre sıralanır, `ad=değer` `&` ile birleşir,
gizli anahtarla HMAC-SHA256, onaltılı. Yetki: `enableReading` `true` olmalı; izinli bayraklar
`enableReading` ve `enableFixReadOnly`; `enable`/`permits` önekli diğer her bayrak `true` ise yetki
fazladır (bilinmeyen yeni bayrak da — kapalı başa çıkar). `ipRestrict` yetki değildir.
"""

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final
from urllib.parse import urlencode

STREAM_TOPIC: Final = "com_announcement_en"
RECV_WINDOW_MS: Final = 10_000
RESTRICTIONS_PATH: Final = "/sapi/v1/account/apiRestrictions"
_ALLOWED: Final = frozenset({"enableReading", "enableFixReadOnly"})
_PREFIXES: Final = ("enable", "permits")


def hmac_hex(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def signed_query(secret: str, params: Mapping[str, str | int]) -> str:
    """Sıralı parametreler ve sonda `signature`."""
    ordered = urlencode(sorted((name, str(value)) for name, value in params.items()), safe="|")
    return f"{ordered}&signature={hmac_hex(secret, ordered)}"


def stream_query(secret: str, now_ms: int, random: str) -> str:
    """Akış bağlantısının sorgusu (A-1)."""
    params: dict[str, str | int] = {
        "random": random,
        "topic": STREAM_TOPIC,
        "recvWindow": RECV_WINDOW_MS,
        "timestamp": now_ms,
    }
    return signed_query(secret, params)


def restrictions_query(secret: str, now_ms: int) -> str:
    return signed_query(secret, {"timestamp": now_ms, "recvWindow": RECV_WINDOW_MS})


class Verdict(Enum):
    READ_ONLY = "yalnız okuma"
    EXCESS = "fazla"
    UNVERIFIED = "doğrulanamadı"


@dataclass(frozen=True)
class PermissionCheck:
    verdict: Verdict
    excess: tuple[str, ...] = ()

    @property
    def message(self) -> str:
        if self.verdict is Verdict.EXCESS:
            return f"anahtar yetkisi fazla: {', '.join(self.excess)}"
        if self.verdict is Verdict.UNVERIFIED:
            return "anahtar yetkisi doğrulanamadı"
        return "anahtar yetkisi: yalnız okuma"


UNVERIFIED: Final = PermissionCheck(Verdict.UNVERIFIED)


def judge_permissions(body: bytes | None) -> PermissionCheck:
    """`body` `None`: yanıt alınamadı (ağ, zaman aşımı, HTTP hatası) → doğrulanamadı."""
    if body is None:
        return UNVERIFIED
    try:
        found = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return UNVERIFIED
    if not isinstance(found, dict) or found.get("enableReading") is not True:
        return UNVERIFIED
    excess = []
    for name, value in found.items():
        if not isinstance(name, str) or not name.startswith(_PREFIXES):
            continue
        if not isinstance(value, bool):
            return UNVERIFIED  # a flag that is not a boolean cannot be judged
        if value and name not in _ALLOWED:
            excess.append(name)
    if excess:
        return PermissionCheck(Verdict.EXCESS, tuple(sorted(excess)))
    return PermissionCheck(Verdict.READ_ONLY)
