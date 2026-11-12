"""Son değerlendirmenin ayar ızgarası (spec 0043 R-3; plan Adım 4, AC-7). Sabittir, ayardan okunmaz.

Ortak sabitler: RSI süresi 14, ATR süresi 14, r = 2; her aday için stop çarpanı k ∈ {1.5, 2, 3}.
Adaylar S0…S3 sırasıyla, her biri 9 kombinasyon; sıra seçimde eşitliğin çözümüdür (0042 R-2:
ızgara sırası, ilk gelen). Bir adayın içinde önce adayın kendi parametresi, sonra k döner.

- S0: (fast, slow) ∈ {(9, 21), (12, 26), (20, 50)}, RSI eşiği 70.
- S1: fast 12, slow 26, RSI eşiği 70, trend ortalaması L ∈ {100, 150, 200}.
- S2: kırılma penceresi N ∈ {20, 55, 100}.
- S3: trend ortalaması 200 (adayın tanımı), RSI aşırı satım eşiği ∈ {30, 35, 40}.
"""

from decimal import Decimal

from crytobot.strategy import (
    BreakoutSettings,
    Settings,
    StrategySettings,
    TrendDipSettings,
    TrendFilterSettings,
)

RSI_PERIOD = 14
ATR_PERIOD = 14
R = Decimal(2)
STOP_MULTIPLES: tuple[Decimal, ...] = (Decimal("1.5"), Decimal(2), Decimal(3))
S0_PERIODS: tuple[tuple[int, int], ...] = ((9, 21), (12, 26), (20, 50))
S1_TREND_PERIODS: tuple[int, ...] = (100, 150, 200)
S2_BREAKOUT_PERIODS: tuple[int, ...] = (20, 55, 100)
S3_OVERSOLD: tuple[Decimal, ...] = (Decimal(30), Decimal(35), Decimal(40))
_THRESHOLD = Decimal(70)

_S0 = tuple(
    StrategySettings(fast, slow, RSI_PERIOD, _THRESHOLD, ATR_PERIOD, k, R)
    for fast, slow in S0_PERIODS
    for k in STOP_MULTIPLES
)
_S1 = tuple(
    TrendFilterSettings(12, 26, RSI_PERIOD, _THRESHOLD, ATR_PERIOD, k, R, trend)
    for trend in S1_TREND_PERIODS
    for k in STOP_MULTIPLES
)
_S2 = tuple(
    BreakoutSettings(window, ATR_PERIOD, k, R)
    for window in S2_BREAKOUT_PERIODS
    for k in STOP_MULTIPLES
)
_S3 = tuple(
    TrendDipSettings(RSI_PERIOD, threshold, ATR_PERIOD, k, R)
    for threshold in S3_OVERSOLD
    for k in STOP_MULTIPLES
)

# R-3: one grid per candidate, S0…S3; never built from a setting
CANDIDATE_GRIDS: tuple[tuple[Settings, ...], ...] = (_S0, _S1, _S2, _S3)
