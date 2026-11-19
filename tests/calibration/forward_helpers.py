"""Spec 0053 ileriye dönük ölçüm testlerinin ortak parçaları (plan A-1): düz 1h mum serisi, skor
sonuçları, olay skorları, gölge satırları.

Seri `T0`'dan başlar; mum `i` `at(i)`'de açılır, hepsi `FLAT` (ATR(14) tam 2). Skor anı
`scored_hour(h)` = `at(h) + 30 dk`: giriş mumu `h + 1`, pencere `h + 1 … h + 24`, rapor anı en erken
`at(h + 25)`. Düşüş hedefi giriş fiyatı 100'ün 4 altı (96), stop 102.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crytobot.analysis import Candle
from crytobot.calibration import (
    SCORED,
    CoinPrices,
    Costs,
    ForwardEvent,
    ForwardInputs,
    ScoredNews,
    ShadowTurn,
)

T0 = datetime(2025, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)
NO_COSTS = Costs(Decimal(0), Decimal(0), Decimal(0))
TRIPLE = ("claude-sonnet", "p" * 8, "c" * 8)
OTHER_TRIPLE = ("claude-opus", "q" * 8, "d" * 8)
WHITELIST = ("BTC/USDT", "ETH/USDT")
FIRST_HOUR = 800  # 720 base candles and the ATR warm-up fit before it
SPACING = 745  # one sample's base window never holds an earlier sample's hit candle

Prices = tuple[float, float, float, float]  # open, high, low, close
FLAT: Prices = (100.0, 101.0, 99.0, 100.0)
DOWN_HIT: Prices = (100.0, 101.0, 95.0, 100.0)
UP_HIT: Prices = (100.0, 105.0, 99.0, 100.0)
STOP_UP: Prices = (100.0, 103.0, 99.0, 100.0)
BOTH: Prices = (100.0, 103.0, 95.0, 100.0)
UNUSUAL_DOWN: Prices = (100.0, 101.0, 80.0, 100.0)  # rule (a): range 21 > 4 x ATR


def at(index: int) -> datetime:
    return T0 + index * HOUR


def scored_hour(hour: int) -> datetime:
    return at(hour) + timedelta(minutes=30)


def series(
    count: int, changes: Mapping[int, Prices] | None = None, missing: Sequence[int] = ()
) -> tuple[Candle, ...]:
    changes = changes or {}
    return tuple(
        Candle(at(index), *changes.get(index, FLAT))
        for index in range(count)
        if index not in missing
    )


def priced(
    count: int, changes: Mapping[int, Prices] | None = None, missing: Sequence[int] = ()
) -> CoinPrices:
    return CoinPrices(True, series(count, changes, missing))


def result(news_id: int, moment: datetime, triple: tuple[str, str, str] = TRIPLE) -> ScoredNews:
    return ScoredNews(news_id, SCORED, moment, triple)


def event(
    news_id: int,
    coin: str = "BTC",
    severity: int = 2,
    direction: str = "olumsuz",
    kind: str = "hack",
) -> ForwardEvent:
    return ForwardEvent(news_id, coin, kind, direction, severity)


def turn(
    moment: datetime,
    pair: str = "BTC/USDT",
    whitelist: tuple[str, ...] = WHITELIST,
    state: str = "bastırılmazdı",
    reason: str = "olumsuz olay yok",
    buy: bool = False,
) -> ShadowTurn:
    return ShadowTurn(moment, pair, whitelist, state, reason, buy)


def inputs(
    results: Sequence[ScoredNews] | None,
    events: Sequence[ForwardEvent] = (),
    shadow: Sequence[ShadowTurn] | None = None,
    whitelist: tuple[str, ...] = WHITELIST,
    sources: Mapping[int, str] | None = None,
    unpermitted: Mapping[int, str] | None = None,
) -> ForwardInputs:
    return ForwardInputs(
        None if results is None else tuple(results),
        tuple(events),
        dict(sources or {}),
        None if shadow is None else tuple(shadow),
        whitelist,
        dict(unpermitted or {}),
    )


def spaced(count: int, changes: Prices = DOWN_HIT, offset: int = 5) -> tuple[list[int], CoinPrices]:
    """`count` örnek saati `SPACING` arayla; her pencerenin `offset`. mumu `changes`."""
    hours = [FIRST_HOUR + SPACING * k for k in range(count)]
    marks = {hour + offset: changes for hour in hours}
    return hours, priced(hours[-1] + 30, marks)


def spaced_inputs(
    hours: Sequence[int],
    coin: str = "BTC",
    first_id: int = 1,
    triple: tuple[str, str, str] = TRIPLE,
) -> tuple[list[ScoredNews], list[ForwardEvent]]:
    results = [result(first_id + k, scored_hour(h), triple) for k, h in enumerate(hours)]
    events = [event(first_id + k, coin) for k in range(len(hours))]
    return results, events
