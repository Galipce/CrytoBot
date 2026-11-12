"""Ayarlar, hata tipleri ve girdi denetimi (spec 0015 AC-8). Karar ve hesap `_proposal.py`'dedir.

Spec 0043 R-2: dört aday, her biri kendi donmuş ayar tipiyle — `StrategySettings` (S0, bugünkü
strateji aynen), `TrendFilterSettings` (S1), `BreakoutSettings` (S2), `TrendDipSettings` (S3). Her
tipin `name`'i adayın adıdır, `parameters()` alanlarını tanım sırasıyla verir. S3'ün 200 mumluk
trend ortalaması adayın tanımıdır, ayar değildir (`S3_TREND_PERIOD`, plan 0043 Risk 3).
`required_candles` en uzun göstergenin istediği mum sayısıdır (R-4, plan 0043 Risk 4).

Hata mesajları ham girdiyi basmaz (yalnız alan adı ve neden): `int`→`str` 4300 basamakta
`ValueError` fırlatır (`docs/conventions.md`, Known traps).
"""

from dataclasses import dataclass, fields
from decimal import Decimal
from enum import Enum
from typing import ClassVar

from crytobot.analysis import CandleProblem

# Tam hesabın boyutunu sınırlar: bu aralıktaki değerlerle en uç float'lar bile birkaç yüz basamak
# verir; sınırsız `k` ya da tick belleği bitirir (plan 0015, Risk 3).
MAX_EXPONENT = 40
MAX_DIGITS = 28
S3_TREND_PERIOD = 200  # spec 0043 R-2: S3's trend average belongs to the candidate, not a setting


class StrategyError(Exception):
    """`strategy` modülünün tüm hatalarının tabanı."""


class InputProblem(Enum):
    """Ayarın ya da girdinin reddedilme nedeni (AC-8)."""

    NOT_SETTINGS = "not_settings"
    NOT_INTEGER = "not_integer"
    NOT_A_NUMBER = "not_a_number"
    NON_FINITE = "non_finite"
    NOT_POSITIVE = "not_positive"
    FAST_NOT_BELOW_SLOW = "fast_not_below_slow"
    OUT_OF_RANGE = "out_of_range"
    OUT_OF_SCALE = "out_of_scale"
    INVALID_PAIR = "invalid_pair"
    NOT_A_FLAG = "not_a_flag"


class InvalidInputError(StrategyError):
    """Ayar ya da girdi geçersiz: `problem` nedeni, `name` alanın adı."""

    def __init__(self, problem: InputProblem, name: str) -> None:
        super().__init__(f"geçersiz girdi {name}: {problem.value}")
        self.problem = problem
        self.name = name


class InvalidCandlesError(StrategyError):
    """Mum serisi geçersiz: `problem` nedeni, `position` ilk geçersiz mumun konumu."""

    def __init__(self, problem: CandleProblem, position: int) -> None:
        super().__init__(f"geçersiz mum, konum {position}: {problem.value}")
        self.problem = problem
        self.position = position


class NonFiniteIndicatorError(StrategyError):
    """İndikatör sonlu olmayan bir değere ulaştı: `indicator` adı, `position` ilk ulaştığı konum."""

    def __init__(self, indicator: str, position: int) -> None:
        super().__init__(f"{indicator}: konum {position} sonlu olmayan sonuç verdi")
        self.indicator = indicator
        self.position = position


Parameters = tuple[tuple[str, int | Decimal], ...]


def _parameters(settings: object) -> Parameters:
    return tuple((item.name, getattr(settings, item.name)) for item in fields(settings))  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class StrategySettings:
    """S0, bugünkü strateji: EMA kesişimi ve RSI eşiğin altında. Varsayılan yoktur, her çağrıda
    açıkça verilir.

    Kurucu denetlemez: denetim `propose`'un girişindedir, atlanamaz. `rsi_threshold`, `k` ve `r`
    yalnız `Decimal` ya da tam sayıdır. Bu, dört tipin hepsi için geçerlidir.
    """

    name: ClassVar[str] = "S0"

    fast_period: int
    slow_period: int
    rsi_period: int
    rsi_threshold: Decimal | int
    atr_period: int
    k: Decimal | int
    r: Decimal | int

    def parameters(self) -> Parameters:
        """Alanlar tanım sırasıyla (ad, değer)."""
        return _parameters(self)


@dataclass(frozen=True, slots=True)
class TrendFilterSettings:
    """S1: S0'ın giriş koşulu, ek olarak son kapanış son `trend_period` kapanışın basit
    ortalamasının üzerinde."""

    name: ClassVar[str] = "S1"

    fast_period: int
    slow_period: int
    rsi_period: int
    rsi_threshold: Decimal | int
    atr_period: int
    k: Decimal | int
    r: Decimal | int
    trend_period: int

    def parameters(self) -> Parameters:
        """Alanlar tanım sırasıyla (ad, değer)."""
        return _parameters(self)


@dataclass(frozen=True, slots=True)
class BreakoutSettings:
    """S2: son kapanış, ondan önceki `breakout_period` mumun en yüksek fiyatını (`high`) aşıyor."""

    name: ClassVar[str] = "S2"

    breakout_period: int
    atr_period: int
    k: Decimal | int
    r: Decimal | int

    def parameters(self) -> Parameters:
        """Alanlar tanım sırasıyla (ad, değer)."""
        return _parameters(self)


@dataclass(frozen=True, slots=True)
class TrendDipSettings:
    """S3: son kapanış 200 kapanışın basit ortalamasının üzerinde, RSI aşırı satım eşiğinin
    (`rsi_threshold`) altında."""

    name: ClassVar[str] = "S3"

    rsi_period: int
    rsi_threshold: Decimal | int
    atr_period: int
    k: Decimal | int
    r: Decimal | int

    def parameters(self) -> Parameters:
        """Alanlar tanım sırasıyla (ad, değer)."""
        return _parameters(self)


Settings = StrategySettings | TrendFilterSettings | BreakoutSettings | TrendDipSettings
# spec 0043 R-2: the fixed candidate set, in order (a tuple: no mutable module state)
CANDIDATES: tuple[type[Settings], ...] = (
    StrategySettings,
    TrendFilterSettings,
    BreakoutSettings,
    TrendDipSettings,
)


def candidate(name: object) -> type[Settings] | None:
    """Adı verilen adayın ayar tipi; bilinmeyen ad `None`."""
    return next((kind for kind in CANDIDATES if kind.name == name), None)


def candidate_parameters(name: object) -> tuple[str, ...] | None:
    """Adı verilen adayın parametre adları, tanım sırasıyla; bilinmeyen ad `None`."""
    kind = candidate(name)
    return None if kind is None else tuple(item.name for item in fields(kind))


@dataclass(frozen=True, slots=True)
class CheckedNumbers:
    """Denetlenmiş eşik (S2'de yok), oran ve tick, `Decimal` olarak."""

    rsi_threshold: Decimal | None
    k: Decimal
    r: Decimal
    tick: Decimal


def _check_period(value: object, name: str) -> None:
    """Pozitif tam sayı; `bool` tam sayı sayılmaz. Dev periyot geçerlidir: geçmiş yetmez."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidInputError(InputProblem.NOT_INTEGER, name)
    if value <= 0:
        raise InvalidInputError(InputProblem.NOT_POSITIVE, name)


def _finite_number(value: object, name: str) -> Decimal:
    """Sonlu `Decimal` ya da tam sayı; `float` ve `bool` reddedilir.

    Sonluluk karşılaştırmadan önce sınanır: `NaN` ile karşılaştırma `InvalidOperation` fırlatır.
    """
    if isinstance(value, bool) or not isinstance(value, Decimal | int):
        raise InvalidInputError(InputProblem.NOT_A_NUMBER, name)
    number = Decimal(value)
    if not number.is_finite():
        raise InvalidInputError(InputProblem.NON_FINITE, name)
    return number


def _scaled_number(value: object, name: str) -> Decimal:
    """Pozitif, sonlu ve ölçek içinde sayı (plan 0015, Risk 3). Değer `str`'e çevrilmez."""
    number = _finite_number(value, name)
    if number <= 0:
        raise InvalidInputError(InputProblem.NOT_POSITIVE, name)
    digits = len(bytes(number.as_tuple().digits).rstrip(b"\0"))
    if abs(number.adjusted()) > MAX_EXPONENT or digits > MAX_DIGITS:
        raise InvalidInputError(InputProblem.OUT_OF_SCALE, name)
    return number


def _threshold(value: object) -> Decimal:
    threshold = _finite_number(value, "rsi_threshold")
    if not 0 < threshold <= 100:
        raise InvalidInputError(InputProblem.OUT_OF_RANGE, "rsi_threshold")
    return threshold


def _check_settings(settings: object) -> tuple[Settings, Decimal | None, Decimal, Decimal]:
    """Alan sırasıyla denetim; S0'ın sırası bugünküyle aynıdır. Döner: ayar, eşik (S2'de
    `None`), `k`, `r`."""
    if not isinstance(settings, CANDIDATES):
        raise InvalidInputError(InputProblem.NOT_SETTINGS, "settings")
    threshold: Decimal | None = None
    if isinstance(settings, StrategySettings | TrendFilterSettings):
        _check_period(settings.fast_period, "fast_period")
        _check_period(settings.slow_period, "slow_period")
        if settings.fast_period >= settings.slow_period:
            raise InvalidInputError(InputProblem.FAST_NOT_BELOW_SLOW, "fast_period")
    if isinstance(settings, BreakoutSettings):
        _check_period(settings.breakout_period, "breakout_period")
    else:
        _check_period(settings.rsi_period, "rsi_period")
        threshold = _threshold(settings.rsi_threshold)
    _check_period(settings.atr_period, "atr_period")
    k = _scaled_number(settings.k, "k")
    r = _scaled_number(settings.r, "r")
    if isinstance(settings, TrendFilterSettings):
        _check_period(settings.trend_period, "trend_period")
    return settings, threshold, k, r


def required_candles(settings: object) -> int:
    """R-4 (plan 0043 Risk 4): adayın bir öneri için istediği en az mum sayısı, en uzun
    göstergeyle: kesişim iki EMA değeri (`slow+1`), RSI `rsi_period+1`, ATR `atr_period`, trend
    ortalaması L (S3'te 200), kırılma penceresi N ve son mum (`N+1`). Geçersiz ayar `propose`'daki
    adla reddedilir."""
    checked = _check_settings(settings)[0]
    needs = [checked.atr_period]
    if isinstance(checked, StrategySettings | TrendFilterSettings):
        needs.append(checked.slow_period + 1)
    if isinstance(checked, BreakoutSettings):
        needs.append(checked.breakout_period + 1)
    else:
        needs.append(checked.rsi_period + 1)
    if isinstance(checked, TrendFilterSettings):
        needs.append(checked.trend_period)
    if isinstance(checked, TrendDipSettings):
        needs.append(S3_TREND_PERIOD)
    return max(needs)


def check_inputs(
    *, pair: object, position_open: object, tick: object, settings: object
) -> tuple[Settings, CheckedNumbers]:
    """Sıra: ayarlar, tick, çift, açık pozisyon bilgisi. Mum serisi bunlardan sonra denetlenir."""
    checked, threshold, k, r = _check_settings(settings)
    numbers = CheckedNumbers(rsi_threshold=threshold, k=k, r=r, tick=_scaled_number(tick, "tick"))
    if not isinstance(pair, str) or pair == "":
        raise InvalidInputError(InputProblem.INVALID_PAIR, "pair")
    if not isinstance(position_open, bool):
        raise InvalidInputError(InputProblem.NOT_A_FLAG, "position_open")
    return checked, numbers
