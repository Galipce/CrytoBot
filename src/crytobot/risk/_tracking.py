"""Günlük zarar ve drawdown takibi: gün başı ve zirve kasa, drawdown durdurması (spec 0004)."""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum

from crytobot.risk._approval import _number, _reached
from crytobot.risk._limits import SCALE, Channel, RiskLimits, _in_scale, _limit_problems, _show


@dataclass(frozen=True)
class RiskState:
    """Son gözleme göre risk durumu; hiç gözlem yoksa alanlar `None` (`EMPTY_STATE`)."""

    day: date | None
    day_start_equity: Decimal | None
    peak_equity: Decimal | None
    last_time: datetime | None
    last_equity: Decimal | None
    halted: bool
    kill_switch: bool = False


EMPTY_STATE = RiskState(None, None, None, None, None, False, False)


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


def risk_state_problems(state: object) -> list[str]:
    """Spec 0011 R-6: `observe` ve `resume`'un üretemeyeceği durumun sorunları; ham değer yok."""
    if not isinstance(state, RiskState):
        return ["risk durumu değil"]
    fields = (
        state.day,
        state.day_start_equity,
        state.peak_equity,
        state.last_time,
        state.last_equity,
    )
    if type(state.halted) is not bool:
        return ["durdurma işareti doğru ya da yanlış olmalı"]
    if type(state.kill_switch) is not bool:
        return ["kill switch işareti doğru ya da yanlış olmalı"]
    if all(field is None for field in fields):
        return ["gözlem yokken durdurma olmaz"] if state.halted else []
    if any(field is None for field in fields):
        return ["alanlar kısmen boş"]
    equities = (state.day_start_equity, state.peak_equity, state.last_equity)
    for equity in equities:
        if not (isinstance(equity, Decimal) and equity.is_finite() and equity > 0):
            return ["gün başı, zirve ya da son kasa sıfırdan büyük bir sayı değil"]
        if not _in_scale(equity):
            return [f"kasa ölçeği varsayılan üs aralığı (±{SCALE}) dışında"]
    at, day = state.last_time, state.day
    if not (isinstance(at, datetime) and at.utcoffset() is not None):
        return ["son gözlem zamanı zaman dilimi taşımalı"]
    if not isinstance(day, date) or isinstance(day, datetime):
        return ["gün tarih olmalı"]
    try:
        if at.astimezone(UTC).date() != day:
            return ["gün son gözlem zamanının UTC günü değil"]
    except OverflowError:  # an extreme date cannot be converted (B-9)
        return ["son gözlem zamanı UTC'ye çevrilemiyor"]
    assert state.peak_equity is not None and state.last_equity is not None  # checked above
    if state.peak_equity < state.last_equity:
        return ["zirve son kasanın altında"]
    return []


def observe(state: RiskState, at: object, equity: object, limits: RiskLimits) -> StateUpdate:
    """BR-5, BR-6: gözlemle gün başı ve zirve kasayı günceller; drawdown limitinde durdurur."""

    def reject(detail: str) -> StateUpdate:
        return StateUpdate(state, TrackingReason.INVALID_OBSERVATION, f"geçersiz gözlem: {detail}")

    if not isinstance(at, datetime) or at.utcoffset() is None:
        return reject(f"zaman {_show(at)} zaman dilimi taşımalı")
    if state.last_time is not None and at < state.last_time:
        return reject(f"zaman {at.isoformat()} son gözlemden ({state.last_time.isoformat()}) eski")
    number = _number(equity)
    if number is None or number <= 0:
        return reject(f"kasa {_show(equity)} sıfırdan büyük bir sayı olmalı")
    if not _in_scale(number):  # spec 0004 A-2: past it, the exact drawdown check grows unbounded
        return reject(f"kasa {number} ölçeği varsayılan üs aralığı (±{SCALE}) dışında")
    problems = _limit_problems(limits)
    if problems:
        return reject("limitler geçersiz: " + "; ".join(problems))
    day = at.astimezone(UTC).date()
    new_day = day != state.day or state.day_start_equity is None
    day_start = number if new_day else state.day_start_equity
    peak = number if state.peak_equity is None else max(state.peak_equity, number)
    halted = state.halted or _reached(peak, number, limits.max_drawdown)
    updated = RiskState(day, day_start, peak, at, number, halted, state.kill_switch)
    note = " (drawdown durdurması)" if halted and not state.halted else ""
    return StateUpdate(updated, None, f"kasa {number} gözlendi{note}")


def resume(state: RiskState, channel: str) -> StateUpdate:
    """BR-6: drawdown durdurmasını ve kill switch'i yalnızca CLI kaldırır; zirve kasa son gözlenen kasa olur."""

    def reject(reason: TrackingReason, message: str) -> StateUpdate:
        return StateUpdate(state, reason, message)

    if state.last_equity is None and not (state.kill_switch or state.halted):
        return reject(TrackingReason.EMPTY_STATE, "risk durumu boş: önce kasa gözlenmeli")
    try:
        source = Channel(channel)
    except ValueError:
        return reject(TrackingReason.UNKNOWN_CHANNEL, f"{_show(channel)}: bilinmeyen kanal")
    if source is Channel.TELEGRAM:
        return reject(
            TrackingReason.TELEGRAM_RESUME, "durdurma Telegram'dan kaldırılamaz; yalnızca CLI"
        )
    if not state.halted and not state.kill_switch:
        return reject(TrackingReason.NOT_HALTED, "durdurma yok; durum değişmedi")
    # the peak restarts at the last equity, or the next observation would halt again at once
    peak = state.last_equity if state.last_equity is not None else state.peak_equity
    resumed = replace(state, halted=False, kill_switch=False, peak_equity=peak)
    return StateUpdate(resumed, None, f"durdurma kaldırıldı; zirve kasa {peak}")


def engage_kill_switch(state: RiskState) -> StateUpdate:
    """Acil durdurma anahtarını devreye alır."""
    if state.kill_switch:
        return StateUpdate(state, None, "kill switch zaten devrede; durum değişmedi")
    updated = replace(state, kill_switch=True)
    return StateUpdate(updated, None, "kill switch devreye alındı")
