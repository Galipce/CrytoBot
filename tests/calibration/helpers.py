"""Spec 0045 kalibrasyon testlerinin ortak parçaları: düz mum serisi, dönem, maliyet."""

import math
import random
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crytobot.analysis import Candle
from crytobot.calibration import Costs, IntervalData, PairSeries, Period

T0 = datetime(2024, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)
BTC = "BTC/USDT"
NO_COSTS = Costs(Decimal(0), Decimal(0), Decimal(0))

Prices = tuple[float, float, float, float]  # open, high, low, close
FLAT: Prices = (100.0, 101.0, 99.0, 100.0)  # true range 2: ATR(14) is exactly 2


def at(index: int) -> datetime:
    return T0 + index * HOUR


def flat_series(
    count: int,
    changes: Mapping[int, Prices] | None = None,
    *,
    pair: str = BTC,
    missing: tuple[int, ...] = (),
    volumes: Mapping[int, float] | None = None,
) -> PairSeries:
    """`count` saatlik mum, hepsi `FLAT`; `changes` konum → fiyatlar; `missing` dosyada olmayan."""
    changes = changes or {}
    volumes = volumes or {}
    candles = []
    found_volumes = []
    for index in range(count):
        if index in missing:
            continue
        open_, high, low, close = changes.get(index, FLAT)
        candles.append(Candle(at(index), open_, high, low, close))
        found_volumes.append(volumes.get(index, 1.0))
    return PairSeries(pair, HOUR, tuple(candles), tuple(found_volumes))


def period(start: int, end: int, pairs: tuple[str, ...] = (BTC,)) -> Period:
    return Period("p", at(start), at(end), pairs)


def oscillating(seed: int, count: int = 420, pair: str = BTC) -> PairSeries:
    """Salınımlı seri (7-9 mumluk dalga + gürültü): her indikatör sık kesişir."""
    rng = random.Random(seed)
    price, candles = 100.0, []
    for index in range(count):
        wave = 100 * (1 + 0.04 * math.sin(2 * math.pi * index / (7 + seed % 3)))
        close = wave * (1 + rng.gauss(0, 0.01))
        high = max(price, close) * (1 + abs(rng.gauss(0, 0.004)))
        low = min(price, close) * (1 - abs(rng.gauss(0, 0.004)))
        candles.append(Candle(at(index), price, high, low, close))
        price = close
    spikes = {150, 350}  # rule (b): one unusual candle in the tuning, one in the unseen period
    volumes = tuple(100.0 if index in spikes else 1.0 + index % 5 for index in range(count))
    return PairSeries(pair, HOUR, tuple(candles), volumes)


PAIRS = (BTC, "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT")
TUNE = Period("ayarlama", at(60), at(300), (BTC,))
CROSS = Period("çapraz sınama", at(60), at(300), PAIRS[1:])
UNSEEN = Period("görülmemiş", at(320), at(420), PAIRS)
SHORT_PERIODS = (TUNE, CROSS, UNSEEN)


def small_data(interval: str = "1h") -> list[IntervalData]:
    return [
        IntervalData(
            interval, {pair: oscillating(seed, pair=pair) for seed, pair in enumerate(PAIRS)}
        )
    ]
