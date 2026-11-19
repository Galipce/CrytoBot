"""Binance imzası ve anahtar yetkisinin hükmü (spec 0056 R-5, AC-2; plan Risk 7, 8, A-1). Saf: ağa,
saate ve ortama dokunmaz.

İmza: istek parametreleri (imza hariç) adlarına göre sıralanır, `ad=değer` `&` ile birleşir,
gizli anahtarla HMAC-SHA256, onaltılı. Yetki: `enableReading` `true` olmalı; izinli bayraklar
`enableReading` ve `enableFixReadOnly`; `enable`/`permits` önekli diğer her bayrak `true` ise yetki
fazladır (bilinmeyen yeni bayrak da — kapalı başa çıkar). `ipRestrict` yetki değildir.

Plan A-7 (VERIFY F-1): zaman damgası Binance'in anahtarsız sunucu saatidir (`TIME_PATH`); yerel
saat yalnız sunucu saati okunamazsa. Doğrulanamayan yetki sırsız bir neden taşıyabilir
(`http_<durum>[/<kod>]`, `timeout`, `bağlanamadı`, `yanıt geçersiz`): Binance'in hata metni hiç
alınmaz, yalnız sayısal kodu.
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
TIME_PATH: Final = "/api/v3/time"
INVALID_REPLY: Final = "yanıt geçersiz"
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
    reason: str | None = None  # plan A-7: why it is unverified, never a value

    @property
    def message(self) -> str:
        if self.verdict is Verdict.EXCESS:
            return f"anahtar yetkisi fazla: {', '.join(self.excess)}"
        if self.verdict is Verdict.UNVERIFIED:
            suffix = "" if self.reason is None else f" ({self.reason})"
            return f"anahtar yetkisi doğrulanamadı{suffix}"
        return "anahtar yetkisi: yalnız okuma"


UNVERIFIED: Final = PermissionCheck(Verdict.UNVERIFIED)


def judge_permissions(reply: bytes | str | None) -> PermissionCheck:
    """`reply`: yanıt gövdesi; alınamadıysa nedenin adı (`str`) ya da `None` → doğrulanamadı."""
    if reply is None:
        return UNVERIFIED
    if isinstance(reply, str):
        return PermissionCheck(Verdict.UNVERIFIED, reason=reply)
    invalid = PermissionCheck(Verdict.UNVERIFIED, reason=INVALID_REPLY)
    try:
        found = json.loads(reply)
    except (ValueError, UnicodeDecodeError):
        return invalid
    if not isinstance(found, dict) or found.get("enableReading") is not True:
        return invalid
    excess = []
    for name, value in found.items():
        if not isinstance(name, str) or not name.startswith(_PREFIXES):
            continue
        if not isinstance(value, bool):
            return invalid  # a flag that is not a boolean cannot be judged
        if value and name not in _ALLOWED:
            excess.append(name)
    if excess:
        return PermissionCheck(Verdict.EXCESS, tuple(sorted(excess)))
    return PermissionCheck(Verdict.READ_ONLY)


def error_reason(status: int, body: bytes) -> str:
    """HTTP hatasının sırsız adı: `http_<durum>`, Binance'in sayısal kodu varsa `/<kod>` (A-7)."""
    try:
        found = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return f"http_{status}"
    code = found.get("code") if isinstance(found, dict) else None
    if isinstance(code, int) and not isinstance(code, bool):
        return f"http_{status}/{code}"
    return f"http_{status}"


def server_time(body: bytes) -> int | None:
    """`/api/v3/time` yanıtı → milisaniye; okunamazsa `None` (yerel saat kullanılır, A-7)."""
    try:
        found = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    value = found.get("serverTime") if isinstance(found, dict) else None
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None
