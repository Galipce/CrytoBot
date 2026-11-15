"""Haber ayarı: `crytobot-news.toml`'un `[news]` ve `[[news.sources]]` bölümleri (spec 0046 R-10,
AC-9; plan Risk 12, 13, A-2).

Yollar zorunludur, varsayılansızdır; diğerlerinin varsayılanı vardır. İlk sorun adıyla söylenir,
ham değer mesaja yazılmaz. Ağa çıkılmaz, dosya açılmaz: bot deposu ve kayıt yolu karşılaştırması
çözülmüş yollarla giriş noktasındadır.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

SECTION = "news"
KINDS = ("binance-duyuru", "rss")
MIN_INTERVAL_MINUTES = 5
_NAME_LIMIT = 64
_URL_LIMIT = 2048
_DEFAULTS = {"interval_minutes": 15, "max_response_kb": 2048, "source_alert_hours": 6}
_PATHS = ("store_path", "log_path")
_SOURCE_KEYS = ("name", "type", "url", "enabled")


@dataclass(frozen=True)
class NewsSource:
    name: str
    kind: str
    url: str
    enabled: bool


@dataclass(frozen=True)
class NewsConfig:
    store_path: str
    log_path: str
    interval_minutes: int
    max_response_kb: int
    source_alert_hours: int
    sources: tuple[NewsSource, ...]

    @property
    def max_response_bytes(self) -> int:
        return self.max_response_kb * 1024  # plan Risk 6: KB = 1024 bayt


@dataclass(frozen=True)
class NewsConfigResult:
    config: NewsConfig | None
    message: str


class _Problem(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _missing(name: str) -> _Problem:
    return _Problem(f"ayar eksik: {name}")


def _invalid(name: str, why: str = "") -> _Problem:
    return _Problem(f"ayar geçersiz: {name}{f' ({why})' if why else ''}")


def _positive_int(table: Mapping[str, object], key: str, minimum: int) -> int:
    value = table.get(key, _DEFAULTS[key])
    # bool is an int: `true` is never a count
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise _invalid(f"{SECTION}.{key}")
    return value


def _text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise _invalid(name)
    if any(not char.isprintable() for char in value):
        raise _invalid(name)
    return value


def _https(value: object, name: str) -> str:
    url = _text(value, name, _URL_LIMIT)
    try:
        parts = urlsplit(url)
    except ValueError:
        raise _invalid(name, "https değil") from None
    if parts.scheme != "https" or not parts.hostname:
        raise _invalid(name, "https değil")
    return url


def _source(raw: object, index: int) -> NewsSource:
    prefix = f"{SECTION}.sources[{index}]"
    if not isinstance(raw, Mapping):
        raise _invalid(prefix)
    for key in raw:
        if key not in _SOURCE_KEYS:
            raise _Problem(f"bilinmeyen ayar: {prefix}.{key}")
    for key in ("name", "type", "url"):
        if key not in raw:
            raise _missing(f"{prefix}.{key}")
    name = _text(raw["name"], f"{prefix}.name", _NAME_LIMIT)
    kind = raw["type"]
    if kind not in KINDS:
        raise _invalid(f"{prefix}.type", "bilinmeyen tür")
    url = _https(raw["url"], f"{prefix}.url")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise _invalid(f"{prefix}.enabled")
    return NewsSource(name, str(kind), url, enabled)


def _load(document: Mapping[str, object]) -> NewsConfig:
    for section in document:
        if section != SECTION:
            raise _Problem(f"bilinmeyen ayar: {section}")
    table = document.get(SECTION)
    if table is None:
        raise _missing(SECTION)
    if not isinstance(table, Mapping):
        raise _invalid(SECTION)
    for key in table:
        if key not in (*_PATHS, *_DEFAULTS, "sources"):
            raise _Problem(f"bilinmeyen ayar: {SECTION}.{key}")
    paths = []
    for key in _PATHS:
        if key not in table:
            raise _missing(f"{SECTION}.{key}")
        paths.append(_text(table[key], f"{SECTION}.{key}", _URL_LIMIT))
    interval = _positive_int(table, "interval_minutes", MIN_INTERVAL_MINUTES)
    max_kb = _positive_int(table, "max_response_kb", 1)
    alert_hours = _positive_int(table, "source_alert_hours", 1)
    raw_sources = table.get("sources")
    if raw_sources is None or (isinstance(raw_sources, list) and not raw_sources):
        raise _missing(f"{SECTION}.sources")
    if not isinstance(raw_sources, list):
        raise _invalid(f"{SECTION}.sources")
    sources = tuple(_source(raw, index) for index, raw in enumerate(raw_sources, start=1))
    seen: set[str] = set()
    for index, source in enumerate(sources, start=1):
        if source.name in seen:
            raise _invalid(f"{SECTION}.sources[{index}].name", "aynı ad iki kez")
        seen.add(source.name)
    store_path, log_path = paths
    if store_path == log_path:  # other spellings of one file are caught resolved, in __main__
        raise _invalid(f"{SECTION}.log_path")
    return NewsConfig(store_path, log_path, interval, max_kb, alert_hours, sources)


def load_news_config(document: Mapping[str, object]) -> NewsConfigResult:
    """Spec 0046 AC-9: geçerli ayar ya da ilk sorunun adını veren mesaj."""
    try:
        config = _load(document)
    except _Problem as problem:
        return NewsConfigResult(None, problem.message)
    return NewsConfigResult(config, "")
