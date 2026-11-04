"""Mum tipi, hata tipleri ve girdi denetimi (spec 0014 AC-8, AC-9). Hesap `_indicators.py`'dedir.

Hata mesajları ham girdiyi basmaz (yalnız alan adı, konum, neden): `int`→`str` 4300 basamakta
`ValueError` fırlatır (`docs/conventions.md`, Known traps).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

_PRICE_FIELDS = ("open", "high", "low", "close")


class AnalysisError(Exception):
    """`analysis` modülünün tüm hatalarının tabanı."""


class CandleProblem(Enum):
    """Mumun reddedilme nedeni (AC-8)."""

    NOT_A_SERIES = "not_a_series"
    NOT_A_CANDLE = "not_a_candle"
    NON_NUMERIC = "non_numeric"
    NON_FINITE = "non_finite"
    NOT_POSITIVE = "not_positive"
    HIGH_BELOW_LOW = "high_below_low"
    OPEN_OUTSIDE_RANGE = "open_outside_range"
    CLOSE_OUTSIDE_RANGE = "close_outside_range"
    INVALID_TIME = "invalid_time"
    TIME_NOT_INCREASING = "time_not_increasing"


class ParameterProblem(Enum):
    """Parametrenin reddedilme nedeni (AC-9)."""

    NOT_INTEGER = "not_integer"
    NON_NUMERIC = "non_numeric"
    NON_FINITE = "non_finite"
    NOT_POSITIVE = "not_positive"
    FAST_NOT_BELOW_SLOW = "fast_not_below_slow"


class InvalidCandleError(AnalysisError):
    """Mum serisi geçersiz: `problem` nedeni, `position` ilk geçersiz mumun konumu.

    `NOT_A_SERIES`'te mum yoktur; `position` anlamsızdır, 0 taşır.
    """

    def __init__(self, problem: CandleProblem, position: int) -> None:
        super().__init__(f"geçersiz mum, konum {position}: {problem.value}")
        self.problem = problem
        self.position = position


class InvalidParameterError(AnalysisError):
    """Parametre geçersiz: `problem` nedeni, `name` parametrenin adı."""

    def __init__(self, problem: ParameterProblem, name: str) -> None:
        super().__init__(f"geçersiz parametre {name}: {problem.value}")
        self.problem = problem
        self.name = name


class NonFiniteResultError(AnalysisError):
    """Hesap sonlu olmayan bir değere ulaştı: `indicator` adı, `position` ilk ulaştığı konum."""

    def __init__(self, indicator: str, position: int) -> None:
        super().__init__(f"{indicator}: konum {position} sonlu olmayan sonuç verdi")
        self.indicator = indicator
        self.position = position


@dataclass(frozen=True, slots=True)
class Candle:
    """Kapanmış bir mum. Kurucu denetlemez: denetim her indikatörün girişindedir, atlanamaz.

    `open_time` `tzinfo`'lu olmalıdır (`docs/conventions.md`, Data rules). Mumun kapanmış olduğunu
    çağıran garanti eder: `analysis` saat kullanmaz.
    """

    open_time: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class Prices:
    """Denetlenmiş seri, `float` sütunlar halinde."""

    highs: tuple[float, ...]
    lows: tuple[float, ...]
    closes: tuple[float, ...]


def _field_problem(value: object) -> CandleProblem | None:
    """Tek fiyat alanının sorunu. Taşan `int` sonlu değildir: `float`'a sığmaz."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return CandleProblem.NON_NUMERIC
    try:
        finite = math.isfinite(value)
    except OverflowError:
        return CandleProblem.NON_FINITE
    if not finite:
        return CandleProblem.NON_FINITE
    return CandleProblem.NOT_POSITIVE if value <= 0 else None


def _candle_problem(candle: object) -> CandleProblem | None:
    if not isinstance(candle, Candle):
        return CandleProblem.NOT_A_CANDLE
    moment: object = candle.open_time
    if not isinstance(moment, datetime) or moment.utcoffset() is None:
        return CandleProblem.INVALID_TIME
    for name in _PRICE_FIELDS:
        problem = _field_problem(getattr(candle, name))
        if problem is not None:
            return problem
    if candle.high < candle.low:
        return CandleProblem.HIGH_BELOW_LOW
    if not candle.low <= candle.open <= candle.high:
        return CandleProblem.OPEN_OUTSIDE_RANGE
    if not candle.low <= candle.close <= candle.high:
        return CandleProblem.CLOSE_OUTSIDE_RANGE
    return None


def checked_prices(candles: Sequence[Candle]) -> Prices:
    """Tüm seriyi denetler; indikatörün kullanmadığı alanlar da dahil (AC-8).

    Dizi olmayan girdi, dokunulmadan reddedilir: generator iki geçişte sessizce boş sonuç verir ve
    tükenir; `dict` ile metin de mum serisi değildir.
    """
    if not isinstance(candles, Sequence) or isinstance(candles, str | bytes | bytearray):
        raise InvalidCandleError(CandleProblem.NOT_A_SERIES, 0)
    previous: datetime | None = None
    for position, candle in enumerate(candles):
        problem = _candle_problem(candle)
        if problem is not None:
            raise InvalidCandleError(problem, position)
        if previous is not None and candle.open_time <= previous:
            raise InvalidCandleError(CandleProblem.TIME_NOT_INCREASING, position)
        previous = candle.open_time
    return Prices(
        highs=tuple(float(candle.high) for candle in candles),
        lows=tuple(float(candle.low) for candle in candles),
        closes=tuple(float(candle.close) for candle in candles),
    )


def check_period(value: object, name: str) -> None:
    """Pozitif tam sayı; `bool` tam sayı sayılmaz. Dev periyot geçerlidir: sonuç tümüyle boştur."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidParameterError(ParameterProblem.NOT_INTEGER, name)
    if value <= 0:
        raise InvalidParameterError(ParameterProblem.NOT_POSITIVE, name)


def check_multiplier(value: object, name: str) -> float:
    """Pozitif ve sonlu sayı; `bool` sayı sayılmaz, `float`'a sığmayan `int` sonlu değildir."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidParameterError(ParameterProblem.NON_NUMERIC, name)
    try:
        number = float(value)
    except OverflowError:
        raise InvalidParameterError(ParameterProblem.NON_FINITE, name) from None
    if not math.isfinite(number):
        raise InvalidParameterError(ParameterProblem.NON_FINITE, name)
    if number <= 0:
        raise InvalidParameterError(ParameterProblem.NOT_POSITIVE, name)
    return number
