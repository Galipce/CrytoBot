"""Gölge filtre kaydı, bot tarafı (spec 0052 R-1, R-2, R-6, R-7, R-8; plan step 4, Risk 4, 5, 7, 8,
A-1).

`[shadow]` bölümü bot ayar dosyasındadır: `record_path`, `score_path`, `news_path` — bölüm varsa üçü
zorunlu, bilinmeyen anahtar ret. Yol çakışmalarının çözülmüş karşılaştırması giriş noktasındadır.

`app` `news`'i ve `llm`'i import etmez (R-3k): filtre görünümü `ShadowParts.view` ile, `app`'in
kendi tipiyle (`PairFilter`) gelir; satırlar `ShadowParts.append` ile yazılır. Satır düz veridir
(A-1): JSON kodlaması ve dosya işi giriş noktasındadır. Satırlar `TurnResult`'tan kurulur, tur kodu
değişmez; görünüm, satır kurma ya da yazma hatası turu etkilemez (döngü tek satır yazar).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from crytobot.app._result import BuyHalt, PairNote, TurnResult
from crytobot.app._session import _INFORMATIONAL
from crytobot.risk import ApprovalReason
from crytobot.strategy import NoProposalReason

SECTION = "shadow"
KEYS = ("record_path", "score_path", "news_path")
ROW_VERSION = "1"
STEP = "gölge kayıt"  # the loop's error line: `döngü hatası: gölge kayıt <tip>`
_PATH_LIMIT = 2048

BUY_YES = "var"
BUY_NO = "yok"
NOT_EVALUATED = "değerlendirilmedi"
RISK_APPROVED = "onay"


@dataclass(frozen=True)
class ShadowConfig:
    record_path: str
    score_path: str
    news_path: str


@dataclass(frozen=True)
class ShadowConfigResult:
    """Bölüm yoksa `config` `None` ve `setting` `None`'dır (kayıt kapalı); sorun varsa `setting`
    ilk sorunlu ayarın adıdır."""

    config: ShadowConfig | None
    setting: str | None
    message: str


def load_shadow_config(document: object) -> ShadowConfigResult:
    """R-8: bölüm varsa üç yol zorunlu; ilk sorun adıyla, ham değer mesaja yazılmaz."""
    if not isinstance(document, Mapping):
        return ShadowConfigResult(None, SECTION, f"ayar geçersiz: {SECTION}")
    table = document.get(SECTION)
    if table is None:
        return ShadowConfigResult(None, None, "")
    if not isinstance(table, Mapping):
        return ShadowConfigResult(None, SECTION, f"ayar geçersiz: {SECTION}")
    for key in table:
        if key not in KEYS:
            name = f"{SECTION}.{key}"
            return ShadowConfigResult(None, name, f"bilinmeyen ayar: {name}")
    values: list[str] = []
    for key in KEYS:
        name = f"{SECTION}.{key}"
        if key not in table:
            return ShadowConfigResult(None, name, f"ayar eksik: {name}")
        value = table[key]
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > _PATH_LIMIT
            or any(not char.isprintable() for char in value)
        ):
            return ShadowConfigResult(None, name, f"ayar geçersiz: {name}")
        values.append(value)
    return ShadowConfigResult(ShadowConfig(*values), None, "")


@dataclass(frozen=True)
class PairFilter:
    """Bir çiftin tur anındaki filtre durumu, `app`'in diliyle. `events`: (haber kimliği, şiddet);
    `missing`: (bekleyen, şema dışı, bayat), `filtre yok`ta `None`."""

    state: str
    reason: str
    events: tuple[tuple[int, int], ...] = ()
    missing: tuple[int, int, int] | None = None
    held: str | None = None


# (tur anı, beyaz liste) -> çift başına filtre durumu
ShadowView = Callable[[datetime, tuple[str, ...]], Mapping[str, PairFilter]]


@dataclass(frozen=True)
class ShadowParts:
    """`view` kayıtları yalnız okur; `append` bir turun satırlarını tek yazımla ekler, yazamazsa
    fırlatır."""

    view: ShadowView
    append: Callable[[Sequence[Mapping[str, object]]], None]


@dataclass(frozen=True)
class Technical:
    buy: str
    reason: str | None
    risk: str | None
    order: str | None


def _halts_text(halts: Sequence[BuyHalt]) -> str:
    stopping = sorted(halt.value for halt in halts if halt not in _INFORMATIONAL)
    return ",".join(stopping) if stopping else "alım yolu çalışmadı"


def technical(result: TurnResult, pair: str) -> Technical:
    """Plan Risk 7: teknik al ve risk sonucu, `TurnResult`'tan."""
    if any(order.pair == pair for order in result.buys):
        return Technical(BUY_YES, None, RISK_APPROVED, None)
    outcome = next((each for each in result.pairs if each.pair == pair), None)
    if outcome is None:
        return Technical(NOT_EVALUATED, _halts_text(result.halts), None, None)
    reason = outcome.reason
    if isinstance(reason, NoProposalReason):
        return Technical(BUY_NO, reason.value, None, None)
    if isinstance(reason, ApprovalReason):
        return Technical(BUY_YES, None, f"ret: {reason.value}", None)
    if reason is PairNote.ALREADY_ORDERED:
        return Technical(BUY_YES, None, f"{NOT_EVALUATED}: {reason.value}", None)
    # a fill gate's note or an order refusal: risk approved, no order came of it
    return Technical(BUY_YES, None, RISK_APPROVED, reason.value)


def shadow_rows(
    result: TurnResult,
    at: datetime,
    whitelist: tuple[str, ...],
    view: Mapping[str, PairFilter],
) -> list[dict[str, object]]:
    """R-2: beyaz listedeki her çift için tam bir satır (plan Risk 5'in alanları)."""
    rows: list[dict[str, object]] = []
    for pair in whitelist:
        found = view[pair]
        made = technical(result, pair)
        rows.append(
            {
                "version": ROW_VERSION,
                "turn_at": at.astimezone(UTC).isoformat(),
                "pair": pair,
                "whitelist": list(whitelist),
                "state": found.state,
                "reason": found.reason,
                "events": [
                    {"news_id": news_id, "severity": severity} for news_id, severity in found.events
                ],
                "missing": None
                if found.missing is None
                else dict(zip(("pending", "schema", "stale"), found.missing, strict=True)),
                "held": found.held,
                "technical_buy": made.buy,
                "technical_reason": made.reason,
                "risk": made.risk,
                "order": made.order,
            }
        )
    return rows
