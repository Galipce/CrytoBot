"""LLM yanıtının doğrulaması (spec 0051 R-3, AC-3; plan step 5, Risk 5). Saf: dosya, ağ ve LLM yok.

Yanıt güvenilmeyen girdidir. İki katman:
- Bütün ret ("şema dışı", yeniden denenmez): metin 16 KB'ı ya da süreç çıktı sınırını aşıyor, JSON
  değil (kod çiti, yinelenen anahtar, NaN dahil), kök tam `{"events": [...]}` değil, listede 20'den
  çok öğe var ya da bir öğe tam altı anahtarlı nesne değil.
- Tekil ret (yalnız o olay skoru, nedeni sayılır): yinelenen coin (ikinci ve sonrakiler), alıntı boş
  ya da LLM'e verilen başlıkta veya metinde birebir geçmiyor, ad alıntıda birebir geçmiyor, coinin
  USDT spot çifti yok, tür, yön ya da şiddet tanımlı değerlerden biri değil.
"Birebir" harf duyarlıdır; tek gevşetme, satır sonu dahil art arda boşlukların iki tarafta da tek
boşluk sayılmasıdır (G-2).
"""

import json
import re
from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass
from typing import Final

from crytobot.news._labels import EVENT_TYPES
from crytobot.news._score_prompt import DIRECTIONS, MAX_EVENTS, SEVERITIES
from crytobot.news._score_store import EventScore

REPLY_LIMIT_BYTES: Final = 16 * 1024
KEYS: Final = frozenset({"coin", "name", "event_type", "direction", "severity", "quote"})
_TYPES: Final = frozenset(name for name, _ in EVENT_TYPES)
_SPACE: Final = re.compile(r"\s+")

TOO_LARGE: Final = "boyut sınırı"
NOT_JSON: Final = "çözümlenemiyor"
BAD_ROOT: Final = "kök biçimi"
TOO_MANY: Final = "olay sayısı sınırı"
BAD_ITEM: Final = "öğe biçimi"

DUPLICATE: Final = "yinelenen coin"
EMPTY_QUOTE: Final = "alıntı boş"
NOT_VERBATIM: Final = "alıntı birebir değil"
NAME_NOT_QUOTED: Final = "ad alıntıda yok"
NO_PAIR: Final = "USDT çifti yok"
BAD_TYPE: Final = "tür tanımsız"
BAD_DIRECTION: Final = "yön tanımsız"
BAD_SEVERITY: Final = "şiddet tanımsız"


@dataclass(frozen=True)
class Checked:
    """`schema_reason` doluysa yanıt bütünüyle reddedildi; `scores` boştur."""

    scores: tuple[EventScore, ...]
    rejections: tuple[tuple[str, int], ...]
    schema_reason: str | None
    size: int


def _squeeze(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


class _Duplicate(ValueError):
    pass


def _pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise _Duplicate
    return dict(pairs)


def _constant(_: str) -> object:
    raise ValueError("NaN or Infinity")


def _whole(text: str) -> list[dict[str, object]] | str:
    try:
        root = json.loads(text, object_pairs_hook=_pairs_hook, parse_constant=_constant)
    except (ValueError, RecursionError):
        return NOT_JSON
    if not isinstance(root, dict) or set(root) != {"events"}:
        return BAD_ROOT
    events = root["events"]
    if not isinstance(events, list):
        return BAD_ROOT
    if len(events) > MAX_EVENTS:
        return TOO_MANY
    if not all(isinstance(item, dict) and set(item) == KEYS for item in events):
        return BAD_ITEM
    return events


def _single(
    item: dict[str, object], title: str, body: str, pairs: Collection[str]
) -> EventScore | str:
    coin, name, quote = item["coin"], item["name"], item["quote"]
    kind, direction, severity = item["event_type"], item["direction"], item["severity"]
    if not isinstance(quote, str) or not _squeeze(quote):
        return EMPTY_QUOTE
    squeezed = _squeeze(quote)
    if squeezed not in _squeeze(title) and squeezed not in _squeeze(body):
        return NOT_VERBATIM
    if not isinstance(name, str) or not _squeeze(name) or _squeeze(name) not in squeezed:
        return NAME_NOT_QUOTED
    if not isinstance(coin, str) or coin not in pairs:
        return NO_PAIR
    if not isinstance(kind, str) or kind not in _TYPES:
        return BAD_TYPE
    if not isinstance(direction, str) or direction not in DIRECTIONS:
        return BAD_DIRECTION
    if not isinstance(severity, int) or isinstance(severity, bool) or severity not in SEVERITIES:
        return BAD_SEVERITY
    return EventScore(coin, name, kind, direction, severity, quote)


def check_reply(
    text: str | None, overflow: bool, title: str, body: str, pairs: Collection[str]
) -> Checked:
    """`text`: zarfın `result` metni; `overflow`: süreç çıktı sınırını aştı. `title`, `body`:
    LLM'e verilen haber metni. `pairs`: borsa bilgisinde USDT spot çifti olan coinler."""
    size = 0 if text is None else len(text.encode("utf-8"))
    if overflow or text is None or size > REPLY_LIMIT_BYTES:
        return Checked((), (), TOO_LARGE, size)
    events = _whole(text)
    if isinstance(events, str):
        return Checked((), (), events, size)
    scores: list[EventScore] = []
    reasons: Counter[str] = Counter()
    seen: set[str] = set()
    for item in events:
        coin = json.dumps(item["coin"], sort_keys=True)  # any JSON value, compared as written
        if coin in seen:
            reasons[DUPLICATE] += 1
            continue
        seen.add(coin)
        checked = _single(item, title, body, pairs)
        if isinstance(checked, str):
            reasons[checked] += 1
        else:
            scores.append(checked)
    return Checked(tuple(scores), tuple(sorted(reasons.items())), None, size)
