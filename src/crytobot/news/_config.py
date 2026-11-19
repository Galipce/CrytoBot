"""Haber ayarı: `crytobot-news.toml`'un `[news]` ve `[[news.sources]]` bölümleri (spec 0046 R-10,
AC-9; plan Risk 12, 13, A-2).

Yollar zorunludur, varsayılansızdır; diğerlerinin varsayılanı vardır. İlk sorun adıyla söylenir,
ham değer mesaja yazılmaz. Ağa çıkılmaz, dosya açılmaz: bot deposu ve kayıt yolu karşılaştırması
çözülmüş yollarla giriş noktasındadır.

Spec 0047 (plan Risk 1): `[news]`'in `archive_` önekli dört anahtarı arşiv komutunundur. Toplayıcı
onları tanır ama kullanmaz ve denetlemez; `load_archive_config` önce dosyanın tamamını
`load_news_config` ile, sonra arşiv anahtarlarını doğrular.

Spec 0051 (plan A-1): `[score]` bölümü skorlayıcınındır; aynı kalıpla tanınır ama burada
kullanılmaz ve denetlenmez (`_score_config.py`).

Spec 0055 (CB-1; plan Risk 1, 2): açık kaynak AI kullanım izni kaydı ister — `ai_permission_by`,
`ai_permission_on` (TOML tarihi), `ai_permission_basis`; kapalı kaynakta isteğe bağlıdır ama varsa
üçü birden ve geçerli olmalıdır. Kod izin kararı vermez, yalnız kaydın varlığını ve biçimini
denetler. Yükleyici saat bilmez: gelecek tarih `permission_in_future` ile giriş noktasında.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urlsplit

SECTION = "news"
SCORE_SECTION = "score"
KINDS = ("binance-duyuru", "rss")
MIN_INTERVAL_MINUTES = 5
_NAME_LIMIT = 64
_URL_LIMIT = 2048
_DEFAULTS = {"interval_minutes": 15, "max_response_kb": 2048, "source_alert_hours": 6}
_PATHS = ("store_path", "log_path")
_PERMISSION_KEYS = ("ai_permission_by", "ai_permission_on", "ai_permission_basis")
_SOURCE_KEYS = ("name", "type", "url", "enabled", *_PERMISSION_KEYS)
_BASIS_LIMIT = 1024
ARCHIVE_KEYS = ("archive_store_path", "archive_log_path", "archive_url", "archive_request_gap_s")
MIN_ARCHIVE_GAP_S = 1
_ARCHIVE_GAP_DEFAULT = 1


@dataclass(frozen=True)
class Permission:
    """Spec 0055: sahibin, kaynağın koşullarının AI ile işlemeye izin verdiğini yazdığı kayıt."""

    by: str
    on: date
    basis: str


@dataclass(frozen=True)
class NewsSource:
    name: str
    kind: str
    url: str
    enabled: bool
    permission: Permission | None = None

    @property
    def permitted(self) -> bool:
        """Spec 0055 Tanımlar: açık ve izin kaydı olan kaynak."""
        return self.enabled and self.permission is not None


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

    @property
    def permitted_names(self) -> frozenset[str]:
        """İzinli kaynakların adları; ayarda olmayan ad izinli değildir (spec 0055 Tanımlar)."""
        return frozenset(source.name for source in self.sources if source.permitted)


def permission_in_future(config: NewsConfig, today: date) -> str | None:
    """Spec 0055 CB-1, plan Risk 2: tarihi `today`'den (UTC) sonra olan ilk izin kaydının mesajı."""
    for index, source in enumerate(config.sources, start=1):
        if source.permission is not None and source.permission.on > today:
            return f"ayar geçersiz: {SECTION}.sources[{index}].ai_permission_on (gelecekte)"
    return None


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
    return NewsSource(name, str(kind), url, enabled, _permission(raw, prefix, enabled))


def _permission(raw: Mapping[str, object], prefix: str, enabled: bool) -> Permission | None:
    """Spec 0055 CB-1: açık kaynakta zorunlu; biri varsa üçü de; biçim kapalıda da denetlenir."""
    if not enabled and not any(key in raw for key in _PERMISSION_KEYS):
        return None
    for key in _PERMISSION_KEYS:
        if key not in raw:
            raise _missing(f"{prefix}.{key}")
    by = _text(raw["ai_permission_by"], f"{prefix}.ai_permission_by", _NAME_LIMIT)
    on = raw["ai_permission_on"]
    # tomllib gives a local date as `date`; a datetime is a `date` too and is refused
    if not isinstance(on, date) or isinstance(on, datetime):
        raise _invalid(f"{prefix}.ai_permission_on", "tarih değil")
    basis = _text(raw["ai_permission_basis"], f"{prefix}.ai_permission_basis", _BASIS_LIMIT)
    return Permission(by, on, basis)


def _load(document: Mapping[str, object]) -> NewsConfig:
    for section in document:
        if section not in (SECTION, SCORE_SECTION):
            raise _Problem(f"bilinmeyen ayar: {section}")
    table = document.get(SECTION)
    if table is None:
        raise _missing(SECTION)
    if not isinstance(table, Mapping):
        raise _invalid(SECTION)
    for key in table:
        if key not in (*_PATHS, *_DEFAULTS, *ARCHIVE_KEYS, "sources"):
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


@dataclass(frozen=True)
class ArchiveConfig:
    """Spec 0047 R-9: arşiv komutunun ayarı; `news` aynı dosyanın toplayıcı ayarıdır."""

    news: NewsConfig
    store_path: str
    log_path: str
    url: str
    request_gap_s: int

    @property
    def max_response_bytes(self) -> int:
        return self.news.max_response_bytes  # plan Risk 1: one page limit for both commands


@dataclass(frozen=True)
class ArchiveConfigResult:
    config: ArchiveConfig | None
    message: str


def _archive(document: Mapping[str, object], news: NewsConfig) -> ArchiveConfig:
    table = document[SECTION]
    assert isinstance(table, Mapping)  # load_news_config accepted it
    paths = []
    for key in ("archive_store_path", "archive_log_path"):
        if key not in table:
            raise _missing(f"{SECTION}.{key}")
        paths.append(_text(table[key], f"{SECTION}.{key}", _URL_LIMIT))
    if "archive_url" not in table:
        raise _missing(f"{SECTION}.archive_url")
    url = _https(table["archive_url"], f"{SECTION}.archive_url")
    gap = table.get("archive_request_gap_s", _ARCHIVE_GAP_DEFAULT)
    if not isinstance(gap, int) or isinstance(gap, bool) or gap < MIN_ARCHIVE_GAP_S:
        raise _invalid(f"{SECTION}.archive_request_gap_s")
    store_path, log_path = paths
    # other spellings of one file are caught resolved, in __main__ (plan Risk 2)
    if store_path in (news.store_path, news.log_path):
        raise _invalid(f"{SECTION}.archive_store_path")
    if log_path in (news.store_path, news.log_path, store_path):
        raise _invalid(f"{SECTION}.archive_log_path")
    return ArchiveConfig(news, store_path, log_path, url, gap)


def load_archive_config(document: Mapping[str, object]) -> ArchiveConfigResult:
    """Spec 0047 AC-10: dosyanın tamamı geçerli olmalı; ilk sorunun adıyla ret."""
    news = load_news_config(document)
    if news.config is None:
        return ArchiveConfigResult(None, news.message)
    try:
        config = _archive(document, news.config)
    except _Problem as problem:
        return ArchiveConfigResult(None, problem.message)
    return ArchiveConfigResult(config, "")
