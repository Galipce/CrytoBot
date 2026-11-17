"""Skorlayıcının ayarı: `crytobot-news.toml`'un `[score]` bölümü (spec 0051 R-8, AC-5, AC-8; plan
step 2).

Dosyanın tamamı geçerli olmalıdır: önce `[news]` `load_news_config` ile, sonra `[score]`. Yollar,
model adı ve bağlam dosyalarının parmak izleri zorunludur, varsayılansızdır; sayıların varsayılanı
ve aralığı vardır. Günlük çağrı sınırının kodda sabit üst sınırı `DAILY_CALL_HARD_CAP`'tir. Model
adı argv'ye girer: yalnız harf, rakam, nokta, tire ve alt çizgi. İlk sorun adıyla söylenir, ham
değer mesaja yazılmaz. Dosya açılmaz: yolların çözülmüş karşılaştırması ve parmak izlerinin
denetimi giriş noktasındadır.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from crytobot.news._config import NewsConfig, load_news_config

SECTION = "score"
DAILY_CALL_HARD_CAP = 1000
_PATH_LIMIT = 2048
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PATHS = ("store_path", "log_path", "calibration_report_path", "library_path")
_DIGESTS = ("calibration_report_sha256", "library_sha256")
# name: (default, minimum, maximum)
_NUMBERS: dict[str, tuple[int, int, int]] = {
    "interval_minutes": (5, 1, 1440),
    "max_calls_per_round": (20, 1, DAILY_CALL_HARD_CAP),
    "timeout_s": (120, 1, 3600),
    "quota_wait_minutes": (60, 1, 1440),
    "daily_call_limit": (200, 1, DAILY_CALL_HARD_CAP),
}


@dataclass(frozen=True)
class ScoreConfig:
    news: NewsConfig
    store_path: str
    log_path: str
    model: str
    calibration_report_path: str
    calibration_report_sha256: str
    library_path: str
    library_sha256: str
    interval_minutes: int
    max_calls_per_round: int
    timeout_s: int
    quota_wait_minutes: int
    daily_call_limit: int


@dataclass(frozen=True)
class ScoreConfigResult:
    config: ScoreConfig | None
    message: str


class _Problem(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _name(key: str) -> str:
    return f"{SECTION}.{key}"


def _text(table: Mapping[str, object], key: str) -> str:
    if key not in table:
        raise _Problem(f"ayar eksik: {_name(key)}")
    value = table[key]
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > _PATH_LIMIT
        or any(not char.isprintable() for char in value)
    ):
        raise _Problem(f"ayar geçersiz: {_name(key)}")
    return value


def _matching(table: Mapping[str, object], key: str, pattern: re.Pattern[str]) -> str:
    value = _text(table, key)
    if pattern.fullmatch(value) is None:
        raise _Problem(f"ayar geçersiz: {_name(key)}")
    return value


def _number(table: Mapping[str, object], key: str) -> int:
    default, minimum, maximum = _NUMBERS[key]
    value = table.get(key, default)
    # bool is an int: `true` is never a count
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise _Problem(f"ayar geçersiz: {_name(key)} ({minimum}…{maximum})")
    return value


def _load(document: Mapping[str, object], news: NewsConfig) -> ScoreConfig:
    table = document.get(SECTION)
    if table is None:
        raise _Problem(f"ayar eksik: {SECTION}")
    if not isinstance(table, Mapping):
        raise _Problem(f"ayar geçersiz: {SECTION}")
    known = (*_PATHS, *_DIGESTS, "model", *_NUMBERS)
    for key in table:
        if key not in known:
            raise _Problem(f"bilinmeyen ayar: {_name(key)}")
    store_path, log_path = _text(table, "store_path"), _text(table, "log_path")
    model = _matching(table, "model", _MODEL)
    report_path = _text(table, "calibration_report_path")
    report_sha = _matching(table, "calibration_report_sha256", _SHA256)
    library_path = _text(table, "library_path")
    library_sha = _matching(table, "library_sha256", _SHA256)
    numbers = {key: _number(table, key) for key in _NUMBERS}
    # other spellings of one file are caught resolved, in __main__ (plan step 7)
    if store_path in (news.store_path, news.log_path):
        raise _Problem(f"ayar geçersiz: {_name('store_path')}")
    if log_path in (news.store_path, news.log_path, store_path):
        raise _Problem(f"ayar geçersiz: {_name('log_path')}")
    return ScoreConfig(
        news,
        store_path,
        log_path,
        model,
        report_path,
        report_sha,
        library_path,
        library_sha,
        **numbers,
    )


def load_score_config(document: Mapping[str, object]) -> ScoreConfigResult:
    """Spec 0051 AC-8: dosyanın tamamı geçerli olmalı; ilk sorunun adıyla ret."""
    news = load_news_config(document)
    if news.config is None:
        return ScoreConfigResult(None, news.message)
    try:
        config = _load(document, news.config)
    except _Problem as problem:
        return ScoreConfigResult(None, problem.message)
    return ScoreConfigResult(config, "")
