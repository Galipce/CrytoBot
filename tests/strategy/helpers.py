"""Spec 0015 testlerinin ortak parçaları: elle hesaplanmış seriler ve ayar kurucusu.

Değerler `high = low = open = close` serilerde elle hesaplandı (plan 0015, Risk 7). Ayarlar kısa
seride kesişim kurmak içindir; "doğru" strateji değeri değildir (spec, Constraints).
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from crytobot.analysis import Candle
from crytobot.risk import TradeIntent
from crytobot.strategy import (
    BreakoutSettings,
    NoProposal,
    Settings,
    StrategySettings,
    TrendDipSettings,
    TrendFilterSettings,
    propose,
)
from tests.analysis.helpers import from_closes, from_hlc

PAIR = "BTC/USDT"
# EMA 1/2: önceki mumda 9.0 == 9.0, son mumda 10.0 > 9.67; RSI 2 = 60.0, ATR 2 = 1.0
CROSS_FROM_EQUAL = (10.0, 8.0, 9.0, 10.0)
# EMA 1/2: önceki mumda 8.5 < 8.67, son mumda 10.0 > 9.56; RSI 2 = 63.6, ATR 2 = 1.125
CROSS = (10.0, 8.0, 8.5, 10.0)


def make_settings(**overrides: Any) -> StrategySettings:
    values: dict[str, Any] = {
        "fast_period": 1,
        "slow_period": 2,
        "rsi_period": 2,
        "rsi_threshold": Decimal(70),
        "atr_period": 2,
        "k": Decimal(2),
        "r": Decimal(2),
    }
    return StrategySettings(**{**values, **overrides})


def run(
    closes: Sequence[float] | None = None,
    *,
    candles: Sequence[Candle] | None = None,
    tick: Any = 1,
    position_open: Any = False,
    pair: Any = PAIR,
    **settings: Any,
) -> TradeIntent | NoProposal:
    """Geçerli varsayılan senaryo: `CROSS_FROM_EQUAL`; test yalnız sınadığı alanı değiştirir."""
    series = (
        candles
        if candles is not None
        else from_closes(CROSS_FROM_EQUAL if closes is None else closes)
    )
    return propose(
        pair=pair,
        candles=series,
        position_open=position_open,
        tick=tick,
        settings=make_settings(**settings),
    )


# --- spec 0043: aday senaryoları (elle hesaplandı, `high = low = close` aksi yazılmadıkça) ---

# S1 (S0 ayarları + trend_period=4): S0 alım üretir (EMA 2: 10.0, 9.33 → 9.78; RSI 2 ≈ 42.9);
# 4 kapanışın ortalaması 9.75 < 10.0. İlk kapanış 13.0 ortalamayı tam 10.0, 14.0 ise 10.25 yapar.
TREND_BUY = (12.0, 8.0, 9.0, 10.0)
TREND_EQUAL = (13.0, 8.0, 9.0, 10.0)
TREND_BELOW = (14.0, 8.0, 9.0, 10.0)
# S2 (N=3, ATR 2): pencere = ilk üç mumun high'ı (11, 12, 11), en yükseği 12; ATR 2 = 3.125.
BREAKOUT_HIGHS = (11.0, 12.0, 11.0, 13.0)
BREAKOUT_LOWS = (9.0, 9.0, 9.0, 9.0)
BREAKOUT_CLOSES = (10.0, 10.0, 10.0, 12.5)
# S3 (RSI 2, ATR 2, ortalama 200): 196 düz mumdan sonra +20, -2, -2, -1. Son RSI 2 = 50.0,
# ATR 2 = 2.5, 200 kapanışın ortalaması 100.345. İlk kapanış 3031 ortalamayı tam 115.0 yapar.
DIP_TAIL = (120.0, 118.0, 116.0, 115.0)
DIP_BUY = (100.0,) * 196 + DIP_TAIL
DIP_EQUAL = (3031.0,) + (100.0,) * 195 + DIP_TAIL
DIP_BELOW = (3032.0,) + (100.0,) * 195 + DIP_TAIL
DIP_RSI = Decimal(50)


def make_trend_filter(**overrides: Any) -> TrendFilterSettings:
    values: dict[str, Any] = {
        "fast_period": 1,
        "slow_period": 2,
        "rsi_period": 2,
        "rsi_threshold": Decimal(70),
        "atr_period": 2,
        "k": Decimal(2),
        "r": Decimal(2),
        "trend_period": 4,
    }
    return TrendFilterSettings(**{**values, **overrides})


def make_breakout(**overrides: Any) -> BreakoutSettings:
    values: dict[str, Any] = {
        "breakout_period": 3,
        "atr_period": 2,
        "k": Decimal(2),
        "r": Decimal(2),
    }
    return BreakoutSettings(**{**values, **overrides})


def make_trend_dip(**overrides: Any) -> TrendDipSettings:
    values: dict[str, Any] = {
        "rsi_period": 2,
        "rsi_threshold": Decimal(51),
        "atr_period": 2,
        "k": Decimal(2),
        "r": Decimal(2),
    }
    return TrendDipSettings(**{**values, **overrides})


def propose_with(
    settings: Settings, candles: Sequence[Candle], *, tick: Any = 1
) -> TradeIntent | NoProposal:
    return propose(pair=PAIR, candles=candles, position_open=False, tick=tick, settings=settings)


def candidate_scenarios(scale: float = 1.0) -> list[tuple[Settings, list[Candle]]]:
    """Her aday için alım üreten bir senaryo (S0…S3 sırasıyla), fiyatlar `scale` ile."""

    def closes(values: Sequence[float]) -> list[Candle]:
        return from_closes(tuple(value * scale for value in values))

    breakout = from_hlc(
        tuple(value * scale for value in BREAKOUT_HIGHS),
        tuple(value * scale for value in BREAKOUT_LOWS),
        tuple(value * scale for value in BREAKOUT_CLOSES),
    )
    return [
        (make_settings(), closes(CROSS)),
        (make_trend_filter(), closes(TREND_BUY)),
        (make_breakout(), breakout),
        (make_trend_dip(), closes(DIP_BUY)),
    ]
