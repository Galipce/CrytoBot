"""Ayarlar, hata tipleri ve girdi denetimi (spec 0015 AC-8). Karar ve hesap `_proposal.py`'dedir.

Hata mesajları ham girdiyi basmaz (yalnız alan adı ve neden): `int`→`str` 4300 basamakta
`ValueError` fırlatır (`docs/conventions.md`, Known traps).
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from crytobot.analysis import CandleProblem

# Tam hesabın boyutunu sınırlar: bu aralıktaki değerlerle en uç float'lar bile birkaç yüz basamak
# verir; sınırsız `k` ya da tick belleği bitirir (plan 0015, Risk 3).
MAX_EXPONENT = 40
MAX_DIGITS = 28


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


@dataclass(frozen=True, slots=True)
class StrategySettings:
    """Strateji ayarları; varsayılan yoktur, her çağrıda açıkça verilir.

    Kurucu denetlemez: denetim `propose`'un girişindedir, atlanamaz. `rsi_threshold`, `k` ve `r`
    yalnız `Decimal` ya da tam sayıdır.
    """

    fast_period: int
    slow_period: int
    rsi_period: int
    rsi_threshold: Decimal | int
    atr_period: int
    k: Decimal | int
    r: Decimal | int


@dataclass(frozen=True, slots=True)
class CheckedNumbers:
    """Denetlenmiş eşik, oran ve tick, `Decimal` olarak."""

    rsi_threshold: Decimal
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


def check_inputs(
    *, pair: object, position_open: object, tick: object, settings: object
) -> tuple[StrategySettings, CheckedNumbers]:
    """Sıra: ayarlar, tick, çift, açık pozisyon bilgisi. Mum serisi bunlardan sonra denetlenir."""
    if not isinstance(settings, StrategySettings):
        raise InvalidInputError(InputProblem.NOT_SETTINGS, "settings")
    _check_period(settings.fast_period, "fast_period")
    _check_period(settings.slow_period, "slow_period")
    if settings.fast_period >= settings.slow_period:
        raise InvalidInputError(InputProblem.FAST_NOT_BELOW_SLOW, "fast_period")
    _check_period(settings.rsi_period, "rsi_period")
    threshold = _finite_number(settings.rsi_threshold, "rsi_threshold")
    if not 0 < threshold <= 100:
        raise InvalidInputError(InputProblem.OUT_OF_RANGE, "rsi_threshold")
    _check_period(settings.atr_period, "atr_period")
    numbers = CheckedNumbers(
        rsi_threshold=threshold,
        k=_scaled_number(settings.k, "k"),
        r=_scaled_number(settings.r, "r"),
        tick=_scaled_number(tick, "tick"),
    )
    if not isinstance(pair, str) or pair == "":
        raise InvalidInputError(InputProblem.INVALID_PAIR, "pair")
    if not isinstance(position_open, bool):
        raise InvalidInputError(InputProblem.NOT_A_FLAG, "position_open")
    return settings, numbers
