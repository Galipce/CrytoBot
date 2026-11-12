"""Teknik işlem önerisi (spec 0015): kesişim kararı, adı konmuş nedenler, fiyat kuralları.

Spec 0043 R-2: `propose` ayarın tipine göre adayın giriş koşulunu uygular — S0 bugünkü kesişim,
S1 kesişim ve trend ortalaması, S2 kırılma, S3 trend ortalaması ve aşırı satım. Öneri bütün
adaylarda aynı `_intent` ile kurulur (k*ATR stop, r*risk hedef, tick kuralları; AC-6).
Karşılaştırmalar en kısa ondalık gösterimle yapılır; eşitlik koşulu karşılamaz.

Sıra: girdi denetimi, adayın indikatörlerinin tümü (S0'da bugünkü sırayla), nedenler. Bu yüzden
hata "öneri yok"un önündedir: `POSITION_OPEN` geçersiz mumu ya da sonlu olmayan sonucu gizlemez
(plan 0015, Risk 2).

Hesap kendi bağlamında tam yapılır, sonuç yuvarlanmaz ve çağıranın decimal ayarı kararı
değiştirmez. Sonlu `BOUNDED` bağlamı burada yanlış olur: Wilder ATR düz seride `3e-323`'e kadar
söner ve bu gerçek bir değerdir. Boyutu `k`, `r` ve tick'in ölçek kapısı sınırlar (plan 0015,
Risk 3).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import (
    MAX_EMAX,
    MAX_PREC,
    MIN_EMIN,
    Context,
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    localcontext,
)
from enum import Enum

from crytobot.analysis import (
    Candle,
    InvalidCandleError,
    NonFiniteResultError,
    atr,
    ema,
    rsi,
    sma,
)
from crytobot.risk import TradeIntent
from crytobot.strategy._inputs import (
    S3_TREND_PERIOD,
    BreakoutSettings,
    CheckedNumbers,
    InvalidCandlesError,
    NonFiniteIndicatorError,
    Settings,
    StrategySettings,
    TrendDipSettings,
    TrendFilterSettings,
    check_inputs,
)

BUY = "buy"  # `risk`'in sabiti public değil; AC-9 uyumu sınar
_EXACT = Context(
    prec=MAX_PREC,
    Emax=MAX_EMAX,
    Emin=MIN_EMIN,
    traps=[Inexact, InvalidOperation, DivisionByZero, Overflow],
)
Series = tuple[float | None, ...]


class NoProposalReason(Enum):
    """ "Öneri yok" nedenleri; birden çok neden varsa bu sıradaki ilki döner."""

    POSITION_OPEN = "position_open"
    INSUFFICIENT_HISTORY = "insufficient_history"
    NO_CROSSOVER = "no_crossover"
    NO_BREAKOUT = "no_breakout"
    RSI_MISSING = "rsi_missing"
    RSI_TOO_HIGH = "rsi_too_high"
    NOT_ABOVE_TREND = "not_above_trend"
    ATR_MISSING = "atr_missing"
    INVALID_PRICES = "invalid_prices"


@dataclass(frozen=True, slots=True)
class NoProposal:
    """Hata olmayan olağan sonuç: bu mumda öneri yok."""

    reason: NoProposalReason


@dataclass(frozen=True, slots=True)
class _Indicators:
    """Adayın kullandığı seriler; kullanmadığı `None`'dır."""

    fast: Series | None
    slow: Series | None
    rsi: Series | None
    atr: Series
    trend: Series | None


def _trend_period(settings: Settings) -> int | None:
    if isinstance(settings, TrendFilterSettings):
        return settings.trend_period
    return S3_TREND_PERIOD if isinstance(settings, TrendDipSettings) else None


def _indicators(candles: Sequence[Candle], settings: Settings) -> _Indicators:
    """`analysis` hataları adı konmuş `strategy` hatasına çevrilir; mum denetimi burada yapılır.
    Sıra S0'da bugünküdür (hızlı, yavaş, RSI, ATR), trend ortalaması en sonda."""
    trend_period = _trend_period(settings)
    fast: Series | None = None
    slow: Series | None = None
    try:
        if isinstance(settings, StrategySettings | TrendFilterSettings):
            fast = ema(candles, period=settings.fast_period)
            slow = ema(candles, period=settings.slow_period)
        strength = (
            None
            if isinstance(settings, BreakoutSettings)
            else rsi(candles, period=settings.rsi_period)
        )
        volatility = atr(candles, period=settings.atr_period)
        trend = None if trend_period is None else sma(candles, period=trend_period)
    except InvalidCandleError as error:
        raise InvalidCandlesError(error.problem, error.position) from error
    except NonFiniteResultError as error:
        raise NonFiniteIndicatorError(error.indicator, error.position) from error
    return _Indicators(fast, slow, strength, volatility, trend)


def _shortest(value: float) -> Decimal:
    """En kısa ondalık gösterim (`0.1` → `0.1`). `int` kapanış, indikatörün gördüğü sayı olur."""
    return Decimal(repr(float(value)))


def _round_down(value: Decimal, tick: Decimal) -> Decimal:
    """Pozitif değeri tick'in katına indirir. `quantize` yetmez: tick 10'un kuvveti olmayabilir."""
    return (value // tick) * tick


def _round_up(value: Decimal, tick: Decimal) -> Decimal:
    down = _round_down(value, tick)
    return down if down == value else down + tick


def _intent(
    pair: str, close: float, atr_value: float, numbers: CheckedNumbers
) -> TradeIntent | None:
    """Spec'in fiyat kuralları; `0 < stop < giriş < hedef` sağlanmazsa `None`.

    Hedef yuvarlanmamış fiyatlardan hesaplanır, üç fiyat ayrı ayrı yuvarlanır. `//` sıfıra doğru
    kestiği için sıfırın altındaki ham stop yuvarlamaya girmez.
    """
    tick = numbers.tick
    with localcontext(_EXACT):
        raw_entry = _shortest(close)
        raw_stop = raw_entry - numbers.k * _shortest(atr_value)
        if raw_stop <= 0:
            return None
        raw_target = raw_entry + numbers.r * (raw_entry - raw_stop)
        entry = _round_up(raw_entry, tick)
        stop = _round_down(raw_stop, tick)
        target = _round_down(raw_target, tick)
    if not 0 < stop < entry < target:
        return None
    return TradeIntent(pair=pair, side=BUY, entry=entry, stop=stop, target=target)


def _crossed_up(fast: Series, slow: Series) -> bool | None:
    """Son mumda yukarı kesişim var mı; gereken dört değerden biri yoksa `None`."""
    if len(fast) < 2:
        return None
    previous_fast, previous_slow, last_fast, last_slow = fast[-2], slow[-2], fast[-1], slow[-1]
    if previous_fast is None or previous_slow is None or last_fast is None or last_slow is None:
        return None
    return previous_fast <= previous_slow and last_fast > last_slow


def _above(close: float, value: float) -> bool:
    """Kesin üstünde; eşitlik aşmaz (R-2)."""
    return _shortest(close) > _shortest(value)


def _breakout_reason(candles: Sequence[Candle], window: int) -> NoProposalReason | None:
    """S2: pencere son kapanmış mumdan önceki `window` mumdur, son mumu içermez (AC-4)."""
    if len(candles) < window + 1:
        return NoProposalReason.INSUFFICIENT_HISTORY
    highest = max(float(candle.high) for candle in candles[-window - 1 : -1])
    return None if _above(candles[-1].close, highest) else NoProposalReason.NO_BREAKOUT


def _rsi_reason(strength: Series, threshold: Decimal | None) -> NoProposalReason | None:
    value = strength[-1] if strength else None
    if value is None:
        return NoProposalReason.RSI_MISSING
    assert threshold is not None  # every RSI candidate has a checked threshold
    return NoProposalReason.RSI_TOO_HIGH if _shortest(value) >= threshold else None


def _entry_reason(
    candles: Sequence[Candle], settings: Settings, series: _Indicators, numbers: CheckedNumbers
) -> NoProposalReason | None:
    """Adayın giriş koşulu; tutmayan ilk neden `NoProposalReason` sırasıyla."""
    if isinstance(settings, BreakoutSettings):
        return _breakout_reason(candles, settings.breakout_period)
    trend = series.trend
    average = trend[-1] if trend else None
    if trend is not None and average is None:
        return NoProposalReason.INSUFFICIENT_HISTORY
    if series.fast is not None and series.slow is not None:
        crossed = _crossed_up(series.fast, series.slow)
        if crossed is None:
            return NoProposalReason.INSUFFICIENT_HISTORY
        if not crossed:
            return NoProposalReason.NO_CROSSOVER
    assert series.rsi is not None  # every candidate but S2 reads RSI
    reason = _rsi_reason(series.rsi, numbers.rsi_threshold)
    if reason is None and average is not None and not _above(candles[-1].close, average):
        return NoProposalReason.NOT_ABOVE_TREND
    return reason


def propose(
    *,
    pair: str,
    candles: Sequence[Candle],
    position_open: bool,
    tick: Decimal | int,
    settings: Settings,
) -> TradeIntent | NoProposal:
    """Son mum için tek sonuç: alım önerisi ya da adı konmuş "öneri yok" nedeni.

    `settings`'in tipi adayı seçer (spec 0043 R-2). Seri yalnız kapanmış mumlardan oluşmalıdır;
    bunu ve bayat veriyi denetlemek çağıranın işidir. Saat, ağ, depo ve global durum kullanmaz;
    kâr hedefi ve kâr-zarar girdi değildir (BR-1).
    """
    checked_settings, numbers = check_inputs(
        pair=pair, position_open=position_open, tick=tick, settings=settings
    )
    series = _indicators(candles, checked_settings)
    if position_open:
        return NoProposal(NoProposalReason.POSITION_OPEN)
    reason = _entry_reason(candles, checked_settings, series, numbers)
    if reason is not None:
        return NoProposal(reason)
    atr_value = series.atr[-1]
    if atr_value is None:
        return NoProposal(NoProposalReason.ATR_MISSING)
    intent = _intent(pair, candles[-1].close, atr_value, numbers)
    return NoProposal(NoProposalReason.INVALID_PRICES) if intent is None else intent
