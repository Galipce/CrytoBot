"""Risk limitleri: tanım, sabit üst sınırlar, config'ten yükleme, değiştirme kararı (spec 0002)."""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import cast

PER_TRADE_RISK = "per_trade_risk"
DAILY_LOSS_LIMIT = "daily_loss_limit"
MAX_DRAWDOWN = "max_drawdown"
MAX_OPEN_POSITIONS = "max_open_positions"
PROFIT_COST_MULTIPLE = "profit_cost_multiple"
RATIO_LIMITS = (PER_TRADE_RISK, DAILY_LOSS_LIMIT, MAX_DRAWDOWN)
CAPPED_LIMITS = (*RATIO_LIMITS, MAX_OPEN_POSITIONS)
LIMIT_NAMES = (*CAPPED_LIMITS, PROFIT_COST_MULTIPLE)

type LimitValue = Decimal | int

# the default context's exponent range: the exact difference of two values inside it stays bounded
SCALE = 999_999


def _in_scale(number: Decimal) -> bool:
    """Üssü varsayılan decimal aralığında (±999999) olan sayı (spec 0004 A-2)."""
    return -SCALE <= number.adjusted() <= SCALE


@dataclass(frozen=True)
class RiskLimits:
    """Oranlar kasaya göre (`Decimal("0.01")` = %1); pozisyon sayısı tam sayı; kat, beklenen kârın
    efektif maliyete oranının alt sınırı (spec 0005)."""

    per_trade_risk: Decimal
    daily_loss_limit: Decimal
    max_drawdown: Decimal
    max_open_positions: int
    profit_cost_multiple: Decimal = Decimal("2")


@dataclass(frozen=True)
class HardCaps:
    """Dört limitin sabit üst sınırları; kâr/maliyet katının üst değil alt sınırı var."""

    per_trade_risk: Decimal
    daily_loss_limit: Decimal
    max_drawdown: Decimal
    max_open_positions: int


# Hard caps: no config or change request can exceed them; only a new spec changes them (R-2).
HARD_CAPS = HardCaps(Decimal("0.02"), Decimal("0.05"), Decimal("0.25"), 8)
# Hard floor of the multiple: no config or change request can go below it (spec 0005 R-4).
HARD_FLOOR_MULTIPLE = Decimal("1")
DEFAULT_LIMITS = RiskLimits(Decimal("0.01"), Decimal("0.03"), Decimal("0.15"), 5, Decimal("2"))


@dataclass(frozen=True)
class LoadedLimits:
    limits: RiskLimits
    defaulted: frozenset[str]


class RiskError(Exception):
    """`risk` modülünün tüm hatalarının tabanı."""


class RiskConfigError(RiskError):
    """Config'teki risk limitleri geçersiz; tüm sorunlar `problems` içinde."""

    def __init__(self, problems: tuple[str, ...]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class RejectReason(Enum):
    UNKNOWN_CHANNEL = "unknown_channel"
    UNKNOWN_LIMIT = "unknown_limit"
    INVALID_VALUE = "invalid_value"
    ABOVE_CAP = "above_cap"
    TELEGRAM_INCREASE = "telegram_increase"
    BELOW_FLOOR = "below_floor"
    TELEGRAM_DECREASE = "telegram_decrease"


@dataclass(frozen=True)
class _Problem:
    reason: RejectReason
    message: str


def _validate(name: str, value: object) -> LimitValue | _Problem:
    """Tek bir limit değerini doğrular; `name` bilinen bir limit adıdır."""
    number: LimitValue
    if isinstance(value, bool):
        return _Problem(RejectReason.INVALID_VALUE, f"{name}: {value!r} sayı değil")
    if name == MAX_OPEN_POSITIONS:
        if not isinstance(value, int):
            return _Problem(RejectReason.INVALID_VALUE, f"{name}: {value!r} tam sayı değil")
        if value < 1:
            return _Problem(RejectReason.INVALID_VALUE, f"{name}: {value} en az 1 olmalı")
        number = value
    else:
        if isinstance(value, int):
            number = Decimal(value)
        elif isinstance(value, Decimal):
            number = value
        else:
            return _Problem(RejectReason.INVALID_VALUE, f"{name}: {value!r} sayı değil")
        # NaN/infinity first: NaN fails every comparison and would slip past the cap check
        if not number.is_finite():
            return _Problem(RejectReason.INVALID_VALUE, f"{name}: {value} sonlu bir sayı değil")
        if name == PROFIT_COST_MULTIPLE:
            if not _in_scale(number):
                return _Problem(
                    RejectReason.INVALID_VALUE,
                    f"{name}: {value} ölçeği varsayılan üs aralığı (±{SCALE}) dışında",
                )
            if number < HARD_FLOOR_MULTIPLE:
                return _Problem(
                    RejectReason.BELOW_FLOOR,
                    f"{name}: {value} alt sınırın ({HARD_FLOOR_MULTIPLE}) altında",
                )
            return number
        if number <= 0:
            return _Problem(RejectReason.INVALID_VALUE, f"{name}: {value} sıfırdan büyük olmalı")
    cap = _caps()[name]
    if number > cap:
        return _Problem(RejectReason.ABOVE_CAP, f"{name}: {value} üst sınırı {cap} aşıyor")
    return number


def _values(limits: RiskLimits) -> dict[str, LimitValue]:
    return {name: getattr(limits, name) for name in LIMIT_NAMES}


def _caps() -> dict[str, LimitValue]:
    return {name: getattr(HARD_CAPS, name) for name in CAPPED_LIMITS}


def _build(values: Mapping[str, LimitValue]) -> RiskLimits:
    return RiskLimits(
        per_trade_risk=cast(Decimal, values[PER_TRADE_RISK]),
        daily_loss_limit=cast(Decimal, values[DAILY_LOSS_LIMIT]),
        max_drawdown=cast(Decimal, values[MAX_DRAWDOWN]),
        max_open_positions=cast(int, values[MAX_OPEN_POSITIONS]),
        profit_cost_multiple=cast(Decimal, values[PROFIT_COST_MULTIPLE]),
    )


def load_limits(toml_text: str) -> LoadedLimits:
    """Config metninin `[risk]` tablosundan limitleri yükler; eksik limitler varsayılanı alır.

    Ondalıklar tam okunur (`parse_float=Decimal`). Herhangi bir sorun → `RiskConfigError`,
    tüm sorunlarla birlikte.
    """
    try:
        document = tomllib.loads(toml_text, parse_float=Decimal)
    except tomllib.TOMLDecodeError as error:
        raise RiskConfigError((f"config TOML olarak okunamadı: {error}",)) from error
    section = document.get("risk", {})
    if not isinstance(section, dict):
        raise RiskConfigError(("risk: bir tablo olmalı",))
    problems = [
        f"{key!r} = {value}: bilinmeyen limit adı"
        for key, value in section.items()
        if key not in LIMIT_NAMES
    ]
    values = _values(DEFAULT_LIMITS)
    for name in LIMIT_NAMES:
        if name in section:
            checked = _validate(name, section[name])
            if isinstance(checked, _Problem):
                problems.append(checked.message)
            else:
                values[name] = checked
    if problems:
        raise RiskConfigError(tuple(problems))
    return LoadedLimits(_build(values), frozenset(LIMIT_NAMES) - section.keys())


class Channel(Enum):
    CLI = "cli"
    TELEGRAM = "telegram"


@dataclass(frozen=True)
class LimitChange:
    """Ham değiştirme isteği: limit adı, yeni değer (`Decimal` veya `int`) ve kanal adı."""

    limit: str
    value: object
    channel: str


@dataclass(frozen=True)
class ChangeDecision:
    """Karar sonrası geçerli limitler; ret durumunda limitler değişmemiştir."""

    limits: RiskLimits
    reason: RejectReason | None
    message: str

    @property
    def accepted(self) -> bool:
        return self.reason is None


def decide_change(current: RiskLimits, change: LimitChange) -> ChangeDecision:
    """BR-13: sıkılaştırma her kanaldan; gevşetme yalnızca CLI'den, en fazla sabit sınıra kadar.

    Dört limitte sıkılaştırmak düşürmek, kâr/maliyet katında yükseltmektir (spec 0005 R-5).
    """

    def reject(reason: RejectReason, message: str) -> ChangeDecision:
        return ChangeDecision(current, reason, message)

    try:
        channel = Channel(change.channel)
    except ValueError:
        return reject(RejectReason.UNKNOWN_CHANNEL, f"{change.channel!r}: bilinmeyen kanal")
    if change.limit not in LIMIT_NAMES:
        return reject(RejectReason.UNKNOWN_LIMIT, f"{change.limit!r}: bilinmeyen limit adı")
    checked = _validate(change.limit, change.value)
    if isinstance(checked, _Problem):
        return reject(checked.reason, checked.message)
    values = _values(current)
    if (
        channel is Channel.TELEGRAM
        and change.limit == PROFIT_COST_MULTIPLE
        and checked < values[change.limit]
    ):
        return reject(
            RejectReason.TELEGRAM_DECREASE,
            f"{change.limit}: Telegram'dan düşürme yapılamaz ({values[change.limit]} → {checked});"
            " yalnızca CLI",
        )
    if (
        channel is Channel.TELEGRAM
        and change.limit != PROFIT_COST_MULTIPLE
        and checked > values[change.limit]
    ):
        return reject(
            RejectReason.TELEGRAM_INCREASE,
            f"{change.limit}: Telegram'dan artırma yapılamaz ({values[change.limit]} → {checked});"
            " yalnızca CLI",
        )
    values[change.limit] = checked
    return ChangeDecision(_build(values), None, f"{change.limit}: {checked} kabul edildi")


def _limit_problems(limits: RiskLimits) -> list[str]:
    """Limitleri nereden kurulmuş olursa olsun alan alan doğrular (spec 0003 R-7, B-3)."""
    problems = []
    for name, value in _values(limits).items():
        checked = _validate(name, value)
        if isinstance(checked, _Problem):
            problems.append(checked.message)
    return problems
