"""Spec 0015 testlerinin ortak parçaları: elle hesaplanmış seriler ve ayar kurucusu.

Değerler `high = low = open = close` serilerde elle hesaplandı (plan 0015, Risk 7). Ayarlar kısa
seride kesişim kurmak içindir; "doğru" strateji değeri değildir (spec, Constraints).
"""

from decimal import Decimal
from typing import Any

from crytobot.strategy import StrategySettings

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
