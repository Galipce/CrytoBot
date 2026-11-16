"""Duyuru başlığının etiketi: olay türü, beklenen yön ve coinler (spec 0048 R-1, Q-1, Q-2; plan Risk
3, 4). Saf: ağ, dosya ve LLM kullanmaz.

Tür kuralları büyük/küçük harf duyarsızdır; başlık tablodaki sırayla ilk eşleşen türü alır, hiçbiri
eşleşmezse "diğer"dir. Spot listeleme ve listeden çıkarma yalnız başlıkta
`futures|perpetual|margin|options` geçmezse, vadeli / marjin yalnız `delist|remov` geçmezse sayılır
(A-3).

Coin adayları başlıkta ayrı duran belirteçlerdir (`[A-Za-z0-9Ⓢ]` dizileri): tamamı büyük harf ve
rakam, 2-10 karakter, en az bir harf. `XYZ/USDT`'de iki belirteç vardır (`USDT` dışlanır), `XYZUSDT`
`XYZ`'ye indirgenir, `(XYZ)` aynı kuraldan geçer. Dışlama listesi: ağlar, stabil coinler, tarih ve
sayı belirteçleri (rakam, sıra eki ya da saat eki: `1ST`, `10AM`; `AM`, `PM`) ve sabit kısaltmalar.
Coinler başlık sırasıyla, tekrarsız. Yanlış aday sessiz örnek üretmez: "çift yok" diye sayılır.

Kural setinin parmak izi (`RULES_FINGERPRINT`) türlerin, kalıpların ve listelerin kanonik JSON'unun
SHA-256'sıdır; bir kural değişirse değişir. Kurallar bu spec'le donar (R-1): değişiklik yeni spec.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Final

POSITIVE: Final = "olumlu"
NEGATIVE: Final = "olumsuz"
NEUTRAL: Final = "nötr"
OTHER: Final = "diğer"


@dataclass(frozen=True)
class EventRule:
    """Bir olay türü: ad, beklenen yön, eşleşmesi gereken kalıp ve eşleşmemesi gereken kalıp."""

    name: str
    direction: str
    pattern: str | None
    unless: str | None = None


RULES: Final = (
    EventRule("spot listeleme", POSITIVE, r"will list", r"futures|perpetual|margin|options"),
    EventRule("listeden çıkarma", NEGATIVE, r"delist", r"futures|perpetual|margin|options"),
    EventRule("işlem çifti kaldırma", NEGATIVE, r"remov\w* .*trading pairs"),
    EventRule("izleme etiketi", NEGATIVE, r"monitoring tag"),
    EventRule("launchpool / launchpad / HODLer", POSITIVE, r"launchpool|launchpad|hodler"),
    EventRule("vadeli / marjin listeleme", POSITIVE, r"futures|perpetual|margin", r"delist|remov"),
    EventRule("askıya alma ve bakım", NEUTRAL, r"suspen|maintenance"),
    EventRule("ağ yükseltmesi", NEUTRAL, r"upgrade|hard ?fork"),
    EventRule(OTHER, NEUTRAL, None),
)

TOKEN: Final = r"[A-Za-z0-9Ⓢ]+"
CANDIDATE: Final = r"(?=[A-Z0-9]*[A-Z])[A-Z0-9]{2,10}"
NUMBER_TOKEN: Final = r"[0-9]+(?:ST|ND|RD|TH|AM|PM)?|AM|PM"
PAIR_QUOTE: Final = "USDT"
NETWORKS: Final = ("BEP2", "BEP20", "ERC20", "TRC20", "SPL", "OMNI")
STABLES: Final = ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI", "USDP", "USDⓈ")
ABBREVIATIONS: Final = (
    "UTC",
    "API",
    "NFT",
    "FAQ",
    "KYC",
    "P2P",
    "VIP",
    "APR",
    "APY",
    "ETF",
    "AMA",
    "TBA",
)


@dataclass(frozen=True)
class Label:
    event_type: str
    direction: str
    coins: tuple[str, ...]


@dataclass(frozen=True)
class RuleSet:
    """Kural seti; testler değiştirilmiş bir kopyayla parmak izinin duyarlılığını sınar."""

    rules: tuple[EventRule, ...] = RULES
    token: str = TOKEN
    candidate: str = CANDIDATE
    number_token: str = NUMBER_TOKEN
    pair_quote: str = PAIR_QUOTE
    excluded: tuple[str, ...] = (*NETWORKS, *STABLES, *ABBREVIATIONS)


DEFAULT_RULES: Final = RuleSet()


def rules_fingerprint(rules: RuleSet = DEFAULT_RULES) -> str:
    canonical = {
        "rules": [[r.name, r.direction, r.pattern, r.unless] for r in rules.rules],
        "token": rules.token,
        "candidate": rules.candidate,
        "number_token": rules.number_token,
        "pair_quote": rules.pair_quote,
        "excluded": list(rules.excluded),
    }
    text = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


RULES_FINGERPRINT: Final = rules_fingerprint()


def event_type(title: str, rules: RuleSet = DEFAULT_RULES) -> EventRule:
    for rule in rules.rules:
        if rule.pattern is None:
            return rule
        if re.search(rule.pattern, title, re.IGNORECASE) and not (
            rule.unless is not None and re.search(rule.unless, title, re.IGNORECASE)
        ):
            return rule
    raise AssertionError("the last rule matches every title")  # pragma: no cover


def coins(title: str, rules: RuleSet = DEFAULT_RULES) -> tuple[str, ...]:
    found: list[str] = []
    excluded = set(rules.excluded)
    for token in re.findall(rules.token, title):
        name = token
        quote = rules.pair_quote
        if name.endswith(quote) and len(name) > len(quote):
            name = name[: -len(quote)]
        if not re.fullmatch(rules.candidate, name):
            continue
        if name in excluded or re.fullmatch(rules.number_token, name):
            continue
        if name not in found:
            found.append(name)
    return tuple(found)


def label(title: str, rules: RuleSet = DEFAULT_RULES) -> Label:
    rule = event_type(title, rules)
    return Label(rule.name, rule.direction, coins(title, rules))


def title_pattern(title: str, rules: RuleSet = DEFAULT_RULES) -> str:
    """Etiket denetiminin kalıbı (plan Risk 11): coin adayı belirteçler `X`, rakamlar `#`."""
    found = set(coins(title, rules))

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        quote = rules.pair_quote
        name = token[: -len(quote)] if token.endswith(quote) and len(token) > len(quote) else token
        return "X" if name in found else token

    return re.sub(r"[0-9]", "#", re.sub(rules.token, replace, title))


EVENT_TYPES: Final = tuple((rule.name, rule.direction) for rule in RULES)
