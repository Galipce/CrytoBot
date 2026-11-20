"""Karar turunun ayarı: `crytobot-decide.toml`'un `[decide]` bölümü (spec 0059 R-1, AC-1; ADR 0005).

Liste ADR 0005'in ön kayıtlı on coinidir (sıra serbest, küme aynı olmalı); farklıysa ret. Yollar ve
model zorunludur, varsayılansızdır; sayıların varsayılanı ve aralığı vardır. Model adı argv'ye
girer: yalnız harf, rakam, nokta, tire, alt çizgi. İlk sorun adıyla söylenir, ham değer mesaja
yazılmaz. Dosya açılmaz: yolların çözülmüş karşılaştırması giriş noktasındadır.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

SECTION: Final = "decide"
# ADR 0005 rule 1, as amended by ADR 0006 (TON is not traded) and ADR 0007 (20 coins)
PREREGISTERED_COINS: Final = (
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK", "TRX",
    "BCH", "LTC", "SUI", "XLM", "HBAR", "DOT", "SHIB", "UNI", "NEAR", "APT",
)  # fmt: skip
QUOTE: Final = "USDT"
DAILY_CALL_HARD_CAP: Final = 48  # twice the hourly turn: a failed call never doubles a day
_PATH_LIMIT: Final = 2048
_MODEL: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_PATHS: Final = ("store_path", "log_path", "score_path")
# name: (default, minimum, maximum)
_NUMBERS: Final[dict[str, tuple[int, int, int]]] = {
    "minute_after_close": (5, 0, 59),
    "daily_call_limit": (24, 1, DAILY_CALL_HARD_CAP),
    "timeout_s": (180, 1, 3600),
    "quota_wait_minutes": (60, 1, 1440),
}
_KEYS: Final = ("coins", "model", *_PATHS, *_NUMBERS)


@dataclass(frozen=True)
class DecideConfig:
    coins: tuple[str, ...]
    model: str
    store_path: str
    log_path: str
    score_path: str
    minute_after_close: int
    daily_call_limit: int
    timeout_s: int
    quota_wait_minutes: int

    @property
    def pairs(self) -> tuple[str, ...]:
        return tuple(f"{coin}/{QUOTE}" for coin in self.coins)


@dataclass(frozen=True)
class DecideConfigResult:
    config: DecideConfig | None
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


def _number(table: Mapping[str, object], key: str) -> int:
    default, low, high = _NUMBERS[key]
    value = table.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise _Problem(f"ayar geçersiz: {_name(key)} ({low}…{high})")
    return value


def _coins(table: Mapping[str, object]) -> tuple[str, ...]:
    if "coins" not in table:
        raise _Problem(f"ayar eksik: {_name('coins')}")
    value = table["coins"]
    if not isinstance(value, list) or not all(isinstance(coin, str) for coin in value):
        raise _Problem(f"ayar geçersiz: {_name('coins')}")
    coins = tuple(str(coin) for coin in value)
    if len(set(coins)) != len(coins) or set(coins) != set(PREREGISTERED_COINS):
        raise _Problem(f"ayar geçersiz: {_name('coins')} (ADR 0005/0007 ön kayıtlı listesi değil)")
    return coins


def _load(document: Mapping[str, object]) -> DecideConfig:
    for section in document:
        if section != SECTION:
            raise _Problem(f"bilinmeyen ayar: {section}")
    table = document.get(SECTION)
    if table is None:
        raise _Problem(f"ayar eksik: {SECTION}")
    if not isinstance(table, Mapping):
        raise _Problem(f"ayar geçersiz: {SECTION}")
    for key in table:
        if key not in _KEYS:
            raise _Problem(f"bilinmeyen ayar: {_name(key)}")
    coins = _coins(table)
    model = _text(table, "model")
    if not _MODEL.fullmatch(model):
        raise _Problem(f"ayar geçersiz: {_name('model')}")
    store, log, score = (_text(table, key) for key in _PATHS)
    if (
        len({store, log, score}) != 3
    ):  # other spellings of one file are caught resolved, in __main__
        raise _Problem(f"ayar geçersiz: {_name('log_path')}")
    return DecideConfig(
        coins,
        model,
        store,
        log,
        score,
        _number(table, "minute_after_close"),
        _number(table, "daily_call_limit"),
        _number(table, "timeout_s"),
        _number(table, "quota_wait_minutes"),
    )


def load_decide_config(document: Mapping[str, object]) -> DecideConfigResult:
    """Spec 0059 AC-1: geçerli ayar ya da ilk sorunun adını veren mesaj."""
    try:
        config = _load(document)
    except _Problem as problem:
        return DecideConfigResult(None, problem.message)
    return DecideConfigResult(config, "")
