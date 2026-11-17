"""Duyuru başlığının etiketi: olay türü, beklenen yön ve coinler (spec 0048 R-1, Q-1, Q-2; plan Risk
3, 4). Saf: ağ, dosya ve LLM kullanmaz.

Tür kuralları büyük/küçük harf duyarsızdır; başlık tablodaki sırayla ilk eşleşen türü alır, hiçbiri
eşleşmezse "diğer"dir. Bir tür, kalıbı eşleşir, dışlama kalıbı eşleşmez ve "coin gerekir" ise
başlıktan en az bir coin çıkarsa eşleşir. Spot listeleme ve listeden çıkarma yalnız başlıkta
`futures|perpetual|margin|options` geçmezse sayılır (A-3). Spec 0050 üç türü daralttı (B-93):
- spot listeleme: "Binance Will List …" ve "Binance Lists …"; yeni işlem çifti eklemek değildir
  (CB-3);
- listeden çıkarma: yalnız spot işlemden çıkarma; staking, kredi, teminat, dönüştürme, çekim, P2P,
  grid ve API ucu bildirimleri değildir (CB-2);
- vadeli / marjin listeleme: vadeli / perpetual / marjin terimi ve bir açılış fiili (list, launch,
  add, enable, available) birlikte, en az bir coin ile; kampanya, ödül, limit, ücret, teminat,
  sistem, program, copy trading, erteleme ve yeniden başlatma duyuruları değildir — başlığı
  "Binance Adds/Enables … Margin" ya da "… Added/Enabled … Margin" diye açılan marjin listelemesi
  ardından kampanya gelse de listelemedir (CB-1).

Coin çıkarma kademelidir (A-2); ilk karar veren kademe kazanır:
1. Parantez: `(XYZ)` içindeki semboller (tek harf yalnız tek başına parantezde: `(W)`). Parantezde
   ağ, kısaltma ya da tarih dışında bir sembol varsa kademe karar verir; tek başına parantezdeki
   stabil coin karar verir ama coin değildir ("First Digital USD (FDUSD)" → coin yok).
2. Çift: `A/B`'de yalnız `A`, `XYZUSDT`'de `XYZ`.
3. Serbest: başlıkta ayrı duran belirteçler (`[A-Za-z0-9Ⓢ]` dizileri), tamamı büyük harf ve rakam,
   2-10 karakter, en az bir harf.
Dışlama listesi (her kademede): ağlar, stabil coinler, tarih ve sayı belirteçleri (rakam, sıra eki
ya da saat eki: `1ST`, `10AM`; `AM`, `PM`) ve sabit kısaltmalar. Coinler başlık sırasıyla,
tekrarsız.

Kural setinin parmak izi (`RULES_FINGERPRINT`) türlerin, kalıpların ve listelerin kanonik JSON'unun
SHA-256'sıdır; bir kural değişirse değişir. Kurallar spec 0050'yle donar: değişiklik yeni spec.
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
    """Bir olay türü: ad, beklenen yön, eşleşmesi gereken kalıp, eşleşmemesi gereken kalıp ve
    başlıkta en az bir coin gerekip gerekmediği (spec 0050 CB-1)."""

    name: str
    direction: str
    pattern: str | None
    unless: str | None = None
    needs_coin: bool = False


SPOT_PATTERN: Final = r"will list|\bbinance lists\b"
DERIVATIVES: Final = r"futures|perpetual|margin|options"
DELIST_UNLESS: Final = (
    rf"{DERIVATIVES}|staking|loan|collateral|conver|withdraw|borrow|endpoint|p2p|grid"
)
FUTURES_PATTERN: Final = (
    r"^(?=.*(?:futures|perpetual|margin))"
    r"(?=.*\b(?:will (?:list|launch|add)|lists|launch(?:es|ed)?|adds?|added|enabl(?:e|es|ed)"
    r"|available)\b)"
)
# A margin listing that leads the title ("Binance Adds X on Isolated Margin, Launches … Promotion")
# stays a listing; the noise words exclude every other title (spec 0050 CB-1, plan step 3).
MARGIN_LEAD: Final = (
    r"binance (?:will )?(?:adds?|enables?)\b.*margin|[^,!]*\b(?:added|enabled)\b[^,!]*margin"
)
FUTURES_NOISE: Final = (
    r"postpone|resume|copy trading|collateral|bonus|reward|prize|voucher|airdrop|give ?away"
    r"|\b(?:to|&|and) win\b|\bwon\b|lucky draw|competition|tournament|challenge|promotion"
    r"|discount|waiver|referral|borrow|lending|limit|\bfees?\b|function|feature|\bsystem\b"
    r"|upgrade|program|\bclient\b"
)
FUTURES_UNLESS: Final = rf"delist|remov|^(?!{MARGIN_LEAD}).*(?:{FUTURES_NOISE})"


RULES: Final = (
    EventRule("spot listeleme", POSITIVE, SPOT_PATTERN, DERIVATIVES),
    EventRule("listeden çıkarma", NEGATIVE, r"delist", DELIST_UNLESS),
    EventRule("işlem çifti kaldırma", NEGATIVE, r"remov\w* .*trading pairs"),
    EventRule("izleme etiketi", NEGATIVE, r"monitoring tag"),
    EventRule("launchpool / launchpad / HODLer", POSITIVE, r"launchpool|launchpad|hodler"),
    EventRule("vadeli / marjin listeleme", POSITIVE, FUTURES_PATTERN, FUTURES_UNLESS, True),
    EventRule("askıya alma ve bakım", NEUTRAL, r"suspen|maintenance"),
    EventRule("ağ yükseltmesi", NEUTRAL, r"upgrade|hard ?fork"),
    EventRule(OTHER, NEUTRAL, None),
)

TOKEN: Final = r"[A-Za-z0-9Ⓢ]+"
CANDIDATE: Final = r"(?=[A-Z0-9]*[A-Z])[A-Z0-9]{2,10}"
PAREN_CANDIDATE: Final = r"(?=[A-Z0-9]*[A-Z])[A-Z0-9]{1,10}"
PAREN: Final = r"\(([^()]*)\)"
TIERS: Final = ("parantez", "çift", "serbest")
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
    paren: str = PAREN
    paren_candidate: str = PAREN_CANDIDATE
    stables: tuple[str, ...] = STABLES
    tiers: tuple[str, ...] = TIERS


DEFAULT_RULES: Final = RuleSet()


def rules_fingerprint(rules: RuleSet = DEFAULT_RULES) -> str:
    canonical = {
        "rules": [[r.name, r.direction, r.pattern, r.unless, r.needs_coin] for r in rules.rules],
        "token": rules.token,
        "candidate": rules.candidate,
        "number_token": rules.number_token,
        "pair_quote": rules.pair_quote,
        "excluded": list(rules.excluded),
        "paren": rules.paren,
        "paren_candidate": rules.paren_candidate,
        "stables": list(rules.stables),
        "tiers": list(rules.tiers),
    }
    text = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


RULES_FINGERPRINT: Final = rules_fingerprint()


def event_type(title: str, rules: RuleSet = DEFAULT_RULES) -> EventRule:
    for rule in rules.rules:
        if rule.pattern is None:
            return rule
        if (
            re.search(rule.pattern, title, re.IGNORECASE)
            and not (rule.unless is not None and re.search(rule.unless, title, re.IGNORECASE))
            and not (rule.needs_coin and not coins(title, rules))
        ):
            return rule
    raise AssertionError("the last rule matches every title")  # pragma: no cover


def _strip_quote(token: str, rules: RuleSet) -> str:
    quote = rules.pair_quote
    return token[: -len(quote)] if token.endswith(quote) and len(token) > len(quote) else token


def _is_coin(name: str, candidate: str, rules: RuleSet) -> bool:
    return (
        re.fullmatch(candidate, name) is not None
        and name not in rules.excluded
        and re.fullmatch(rules.number_token, name) is None
    )


def _add(found: list[str], name: str) -> None:
    if name not in found:
        found.append(name)


def _paren_tier(title: str, rules: RuleSet) -> tuple[bool, list[str]]:
    """(karar verdi mi, coinler): parantezde ağ, kısaltma ya da tarih dışında bir sembol varsa
    kademe karar verir; tek başına parantezdeki stabil coin (`(FDUSD)`) karar verir ama coin
    değildir; tek harf yalnız tek başına parantezde (`(W)`) coin olur (A-2)."""
    decided = False
    found: list[str] = []
    for inside in re.findall(rules.paren, title):
        alone = re.fullmatch(rules.token, inside.strip()) is not None
        candidate = rules.paren_candidate if alone else rules.candidate
        for token in re.findall(rules.token, inside):
            name = _strip_quote(token, rules)
            if alone and name in rules.stables:
                decided = True
            elif _is_coin(name, candidate, rules):
                decided = True
                _add(found, name)
    return decided, found


def _pair_tier(title: str, rules: RuleSet) -> list[str]:
    """`A/B`'de yalnız `A`, `XYZUSDT`'de `XYZ` (A-2)."""
    found: list[str] = []
    for match in re.finditer(rules.token, title):
        token = match.group(0)
        before = title[match.start() - 1] if match.start() > 0 else ""
        after = title[match.end()] if match.end() < len(title) else ""
        if before == "/":
            continue
        if after == "/":
            name = token
        elif token.endswith(rules.pair_quote) and len(token) > len(rules.pair_quote):
            name = _strip_quote(token, rules)
        else:
            continue
        if _is_coin(name, rules.candidate, rules):
            _add(found, name)
    return found


def _free_tier(title: str, rules: RuleSet) -> list[str]:
    found: list[str] = []
    for token in re.findall(rules.token, title):
        name = _strip_quote(token, rules)
        if _is_coin(name, rules.candidate, rules):
            _add(found, name)
    return found


def coins(title: str, rules: RuleSet = DEFAULT_RULES) -> tuple[str, ...]:
    """Kademeli coin çıkarma (A-2): parantez, çift, serbest belirteç; ilk karar veren kazanır."""
    decided, found = _paren_tier(title, rules)
    if decided:
        return tuple(found)
    pairs = _pair_tier(title, rules)
    if pairs:
        return tuple(pairs)
    return tuple(_free_tier(title, rules))


def label(title: str, rules: RuleSet = DEFAULT_RULES) -> Label:
    rule = event_type(title, rules)
    return Label(rule.name, rule.direction, coins(title, rules))


def title_pattern(title: str, rules: RuleSet = DEFAULT_RULES) -> str:
    """Etiket denetiminin kalıbı (plan Risk 11): coin adayı belirteçler `X`, rakamlar `#`."""
    found = set(coins(title, rules))

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        return "X" if _strip_quote(token, rules) in found else token

    return re.sub(r"[0-9]", "#", re.sub(rules.token, replace, title))


EVENT_TYPES: Final = tuple((rule.name, rule.direction) for rule in RULES)
