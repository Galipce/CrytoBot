"""Kapanış onayı: açık pozisyonun stop ya da hedefte kapanışı yeni işlem değildir (spec 0009)."""

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from crytobot.risk._approval import _number
from crytobot.risk._limits import DIGITS, SCALE, _brief, _in_scale, _show, _significant

CLOSE_REASONS = ("stop", "hedef")
# a position's client order id: "cb-" and the 1-32 character intent id (spec 0006 R-6)
_POSITION_ID = re.compile(r"cb-[A-Za-z0-9_-]{1,32}")


@dataclass(frozen=True)
class CloseRequest:
    """Ham kapanış talebi (R-1): spec 0008'in kapanış kararının alanları. Neden `"stop"` ya da
    `"hedef"`. Alanlar doğrulanmadan gelir."""

    position_id: object
    pair: object
    amount: object
    reason: object


class CloseRefusal(Enum):
    """Kapanış onayının tek ret nedeni (R-12): giriş kuralı kapanışı engellemez (R-2)."""

    INVALID_INPUT = "invalid_input"


@dataclass(frozen=True)
class CloseApproval:
    """Onayda `reason` `None`; talep değiştirilmeden taşınır (R-1)."""

    reason: CloseRefusal | None
    message: str
    request: object  # the request as given; a `CloseRequest` when approved

    @property
    def approved(self) -> bool:
        return self.reason is None


def _short(value: object) -> str:
    """Ret mesajı için ham girdi; uzun sayı basamak sayısıyla (R-13)."""
    if isinstance(value, Decimal) or (isinstance(value, int) and not isinstance(value, bool)):
        return _brief(Decimal(value))
    return _show(value)


def close_request_problems(request: CloseRequest) -> list[str]:
    """R-8, R-13: talebin biçimi; `execution` onaylı talebi de bununla yeniden denetler."""
    problems: list[str] = []
    position_id = request.position_id
    if not (isinstance(position_id, str) and _POSITION_ID.fullmatch(position_id)):
        problems.append(
            f"pozisyon kimliği {_short(position_id)} cb- ve 1-32 karakterlik harf, rakam, - ya da _"
            " olmalı"
        )
    if not isinstance(request.pair, str):
        problems.append(f"çift {_short(request.pair)} metin olmalı")
    amount = _number(request.amount)
    if amount is None or amount <= 0:
        problems.append(f"miktar {_short(request.amount)} sıfırdan büyük bir sayı olmalı")
    elif not _in_scale(amount):
        problems.append(f"miktar {_brief(amount)} ölçeği varsayılan üs aralığı (±{SCALE}) dışında")
    elif _significant(amount) > DIGITS:
        problems.append(f"miktar {_brief(amount)} {DIGITS} anlamlı basamaktan uzun")
    reason = request.reason
    if not (isinstance(reason, str) and reason in CLOSE_REASONS):
        problems.append(f"neden {_short(reason)} stop ya da hedef olmalı")
    return problems


def approve_close(request: object) -> CloseApproval:
    """R-1, R-2: kapanış talebini yalnızca biçimine bakarak onaylar; işlem riski, günlük zarar,
    drawdown, pozisyon limiti, kâr/maliyet katı, stop zorunluluğu, beyaz liste ve kill switch
    kapanışı engellemez — onay risk durumunu, kasayı ya da zamanı girdi olarak almaz."""
    if not isinstance(request, CloseRequest):
        return CloseApproval(
            CloseRefusal.INVALID_INPUT,
            f"geçersiz girdi: kapanış talebi {_short(request)} bir kapanış talebi olmalı",
            request,
        )
    problems = close_request_problems(request)
    if problems:
        return CloseApproval(
            CloseRefusal.INVALID_INPUT, "geçersiz girdi: " + "; ".join(problems), request
        )
    return CloseApproval(
        None,
        f"{request.pair}: {request.position_id} kapanışı onaylandı ({request.reason})",
        request,
    )
