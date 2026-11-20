"""Spec 0059 test yardımcıları: sentetik mumlar, coin verisi ve yanıt kurucuları."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crytobot.analysis import Candle
from crytobot.decide import PREREGISTERED_COINS, CoinData, EventNote

BOUNDARY = datetime(2026, 11, 20, 10, tzinfo=UTC)
HOUR = timedelta(hours=1)
H4 = timedelta(hours=4)


def series(end: datetime, count: int, span: timedelta, base: float) -> tuple[Candle, ...]:
    """`end`'de kapanan `count` mum; hafif dalgalı, yükselen fiyat."""
    candles = []
    for index in range(count):
        open_time = end - span * (count - index)
        middle = base * (1 + 0.0005 * index + 0.01 * ((index % 7) - 3) / 3)
        candles.append(
            Candle(open_time, middle * 0.999, middle * 1.004, middle * 0.995, middle * 1.001)
        )
    return tuple(candles)


def coin_data(
    coin: str,
    base: float = 100.0,
    boundary: datetime = BOUNDARY,
    h1: int = 250,
    h4: int = 40,
    events: tuple[EventNote, ...] = (),
    tick: Decimal | None = Decimal("0.01"),
) -> CoinData:
    return CoinData(
        coin, series(boundary, h1, HOUR, base), series(boundary, h4, H4, base), tick, events
    )


def all_data(boundary: datetime = BOUNDARY) -> dict[str, CoinData | None]:
    return {
        coin: coin_data(coin, 10.0 * (i + 1), boundary)
        for i, coin in enumerate(PREREGISTERED_COINS)
    }


def wait_entry(coin: str) -> dict[str, object]:
    return {
        "coin": coin,
        "action": "bekle",
        "entry_low": None,
        "entry_high": None,
        "stop": None,
        "target": None,
        "valid_hours": None,
        "confidence": None,
        "reasons": ["trend belirsiz: ema20 ema50 altında"],
    }


def buy_entry(coin: str, low: float, high: float, **changes: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "coin": coin,
        "action": "al",
        "entry_low": low,
        "entry_high": high,
        "stop": low * 0.97,
        "target": high * 1.05,
        "valid_hours": 4,
        "confidence": 3,
        "reasons": ["rsi14 50 üstü", "fiyat ema50 üstünde"],
    }
    entry.update(changes)
    return entry


def reply(*entries: dict[str, object]) -> str:
    return json.dumps({"decisions": list(entries)})
