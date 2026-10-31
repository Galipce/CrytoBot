"""Günlük zarar ve drawdown takibi: gün başı ve zirve kasa, drawdown durdurması (spec 0004)."""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum

from crytobot.risk._approval import _number, _reached
from crytobot.risk._limits import Channel, RiskLimits, _limit_problems


@dataclass(frozen=True)
class RiskState:
    """Son gözleme göre risk durumu; hiç gözlem yoksa alanlar `None` (`EMPTY_STATE`)."""

    day: date | None
    day_start_equity: Decimal | None
    peak_equity: Decimal | None
    last_time: datetime | None
    last_equity: Decimal | None
    halted: bool


EMPTY_STATE = RiskState(None, None, None, None, None, False)


class TrackingReason(Enum):
    INVALID_OBSERVATION = "invalid_observation"
    EMPTY_STATE = "empty_state"
    UNKNOWN_CHANNEL = "unknown_channel"
    TELEGRAM_RESUME = "telegram_resume"
    NOT_HALTED = "not_halted"


@dataclass(frozen=True)
class StateUpdate:
    """Güncelleme sonrası durum; ret durumunda durum değişmemiştir."""

    state: RiskState
    reason: TrackingReason | None
    message: str

    @property
    def accepted(self) -> bool:
        return self.reason is None


def observe(state: RiskState, at: object, equity: object, limits: RiskLimits) -> StateUpdate:
    """BR-5, BR-6: gözlemle gün başı ve zirve kasayı günceller; drawdown limitinde durdurur."""

    def reject(detail: str) -> StateUpdate:
        return StateUpdate(state, TrackingReason.INVALID_OBSERVATION, f"geçersiz gözlem: {detail}")

    if not isinstance(at, datetime) or at.utcoffset() is None:
        return reject(f"zaman {at!r} zaman dilimi taşımalı")
    if state.last_time is not None and at < state.last_time:
        return reject(f"zaman {at.isoformat()} son gözlemden ({state.last_time.isoformat()}) eski")
    number = _number(equity)
    if number is None or number <= 0:
        return reject(f"kasa {equity!r} sıfırdan büyük bir sayı olmalı")
    problems = _limit_problems(limits)
    if problems:
        return reject("limitler geçersiz: " + "; ".join(problems))
    day = at.astimezone(UTC).date()
    new_day = day != state.day or state.day_start_equity is None
    day_start = number if new_day else state.day_start_equity
    peak = number if state.peak_equity is None else max(state.peak_equity, number)
    halted = state.halted or _reached(peak, number, limits.max_drawdown)
    updated = RiskState(day, day_start, peak, at, number, halted)
    note = " (drawdown durdurması)" if halted and not state.halted else ""
    return StateUpdate(updated, None, f"kasa {number} gözlendi{note}")


def resume(state: RiskState, channel: str) -> StateUpdate:
    """BR-6: drawdown durdurmasını yalnızca CLI kaldırır; zirve kasa son gözlenen kasa olur."""

    def reject(reason: TrackingReason, message: str) -> StateUpdate:
        return StateUpdate(state, reason, message)

    if state.last_equity is None:
        return reject(TrackingReason.EMPTY_STATE, "risk durumu boş: önce kasa gözlenmeli")
    try:
        source = Channel(channel)
    except ValueError:
        return reject(TrackingReason.UNKNOWN_CHANNEL, f"{channel!r}: bilinmeyen kanal")
    if source is Channel.TELEGRAM:
        return reject(
            TrackingReason.TELEGRAM_RESUME, "durdurma Telegram'dan kaldırılamaz; yalnızca CLI"
        )
    if not state.halted:
        return reject(TrackingReason.NOT_HALTED, "durdurma yok; durum değişmedi")
    # the peak restarts at the last equity, or the next observation would halt again at once
    resumed = replace(state, halted=False, peak_equity=state.last_equity)
    return StateUpdate(resumed, None, f"durdurma kaldırıldı; zirve kasa {state.last_equity}")
