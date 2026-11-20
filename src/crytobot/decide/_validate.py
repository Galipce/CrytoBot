"""Yanıtın doğrulanması (spec 0059 R-4, AC-4; plan Risk 4). Saf; yanıt güvenilmeyen girdidir.

Bütün yanıt: tek JSON nesnesi `{"decisions": [...]}` (tek bir ```json çiti soyulur); yinelenen
anahtar, bilinmeyen alan, `NaN`/`Infinity`, eksik ya da fazla coin, coinin iki kez geçmesi → şema
dışı (bütün tur `bekle`). Coin başına alanlar: `coin`, `action` (`al`/`bekle`), `entry_low`,
`entry_high`, `stop`, `target`, `valid_hours`, `confidence`, `reasons`. `al` için tutarlılık
kuralları (R-4): giriş alt ≤ üst; stop < giriş alt; hedef > giriş üst; bütün fiyatlar son 48 1h
mumun en düşüğünün %20 altı ile en yükseğinin %20 üstü arasında; geçerlilik 1-4 saat; güven 1-5; 1-3
gerekçe. Bozulan ilk kural o coini `tutarsız` yapar, adıyla; diğer coinler etkilenmez.
"""

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

from crytobot.decide._prompt import MAX_REASONS, MAX_VALID_HOURS

REPLY_LIMIT: Final = 64 * 1024
REASON_LIMIT: Final = 300
RANGE_MARGIN: Final = 0.20
_FIELDS: Final = frozenset(
    {
        "coin",
        "action",
        "entry_low",
        "entry_high",
        "stop",
        "target",
        "valid_hours",
        "confidence",
        "reasons",
    }
)
_LEVELS: Final = ("entry_low", "entry_high", "stop", "target")


class Status(StrEnum):
    BUY = "al"
    WAIT = "bekle"
    INCONSISTENT = "tutarsız"
    NO_DATA = "veri yok"
    SCHEMA = "şema dışı"


@dataclass(frozen=True)
class Decision:
    coin: str
    status: Status
    entry_low: float | None = None
    entry_high: float | None = None
    stop: float | None = None
    target: float | None = None
    valid_hours: int | None = None
    confidence: int | None = None
    reasons: tuple[str, ...] = ()
    reason: str | None = None  # why it was dropped (`tutarsız`, `şema dışı`, `veri yok`)
    action: str | None = None  # Claude's own action, kept when the decision is dropped (R-5)


@dataclass(frozen=True)
class Checked:
    """`schema_reason` doluysa yanıt bütünüyle atılmıştır."""

    decisions: tuple[Decision, ...]
    schema_reason: str | None = None


class _Schema(ValueError):
    pass


def _pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
    found: dict[str, object] = {}
    for key, value in pairs:
        if key in found:
            raise _Schema("yinelenen anahtar")
        found[key] = value
    return found


def _constant(_: str) -> object:
    raise _Schema("sayı değil")


def _unfence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        inner = stripped[3:-3]
        newline = inner.find("\n")
        return inner[newline + 1 :] if newline != -1 else inner
    return stripped


def _number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise _Schema("sayı değil")
    return float(value)


def _whole(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise _Schema("tamsayı değil")
    return value


def _reasons(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise _Schema("gerekçe listesi değil")
    return tuple(str(item) for item in value)


def _entry(raw: object) -> Decision:
    if not isinstance(raw, dict) or set(raw) != _FIELDS:
        raise _Schema("karar alanları")
    coin, action = raw["coin"], raw["action"]
    if not isinstance(coin, str) or action not in (Status.BUY.value, Status.WAIT.value):
        raise _Schema("coin ya da karar")
    low, high, stop, target = (_number(raw[key]) for key in _LEVELS)
    return Decision(
        coin,
        Status(action),
        low,
        high,
        stop,
        target,
        _whole(raw["valid_hours"]),
        _whole(raw["confidence"]),
        _reasons(raw["reasons"]),
        action=str(action),
    )


def _inconsistent(decision: Decision, low48: float, high48: float) -> str | None:
    """R-4'ün ilk bozulan kuralı; `bekle` için yalnız gerekçe sayısı ve uzunluğu."""
    if len(decision.reasons) > MAX_REASONS or any(
        not r.strip() or len(r) > REASON_LIMIT for r in decision.reasons
    ):
        return "gerekçe"
    if decision.status is Status.WAIT:
        return None
    levels = (decision.entry_low, decision.entry_high, decision.stop, decision.target)
    if any(level is None for level in levels):
        return "seviye eksik"
    entry_low, entry_high, stop, target = (float(level) for level in levels if level is not None)
    if not decision.reasons:
        return "gerekçe"
    if entry_low > entry_high:
        return "giriş bölgesi ters"
    if not stop < entry_low:
        return "stop girişin altında değil"
    if not target > entry_high:
        return "hedef girişin üstünde değil"
    floor, ceiling = low48 * (1 - RANGE_MARGIN), high48 * (1 + RANGE_MARGIN)
    if any(not floor <= level <= ceiling for level in (entry_low, entry_high, stop, target)):
        return "fiyat aralık dışı"
    if decision.valid_hours is None or not 1 <= decision.valid_hours <= MAX_VALID_HOURS:
        return "geçerlilik aralık dışı"
    if decision.confidence is None or not 1 <= decision.confidence <= 5:
        return "güven aralık dışı"
    return None


def schema_dropped(coins: Sequence[str], reason: str) -> Checked:
    return Checked(tuple(Decision(coin, Status.SCHEMA, reason=reason) for coin in coins), reason)


def check_reply(text: str | None, ranges: Mapping[str, tuple[float, float]]) -> Checked:
    """`ranges`: karar istenen coin → (48 mumun en düşüğü, en yükseği), istem sırasıyla."""
    coins = tuple(ranges)
    if text is None or len(text.encode("utf-8")) > REPLY_LIMIT:
        return schema_dropped(coins, "yanıt yok ya da çok büyük")
    try:
        document = json.loads(
            _unfence(text), object_pairs_hook=_pairs_hook, parse_constant=_constant
        )
        if not isinstance(document, dict) or set(document) != {"decisions"}:
            raise _Schema("kök nesne")
        entries = document["decisions"]
        if not isinstance(entries, list):
            raise _Schema("karar listesi")
        found = [_entry(raw) for raw in entries]
    except _Schema as error:
        return schema_dropped(coins, f"şema: {error}")
    except (ValueError, RecursionError):
        return schema_dropped(coins, "JSON değil")
    named = [decision.coin for decision in found]
    if sorted(named) != sorted(coins) or len(set(named)) != len(named):
        return schema_dropped(coins, "coin listesi uyuşmuyor")
    by_coin = {decision.coin: decision for decision in found}
    checked = []
    for coin in coins:
        decision = by_coin[coin]
        why = _inconsistent(decision, *ranges[coin])
        checked.append(
            decision if why is None else replace(decision, status=Status.INCONSISTENT, reason=why)
        )
    return Checked(tuple(checked))
