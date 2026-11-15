"""İsabet kuralı, taban oran ve sayım (spec 0045 Q-1…Q-3, R-3, R-8, R-9; plan Risk 4, 5, 6, 9). Saf.

Sinyal mumu `t`; giriş fiyatı dosyada `t`'den sonraki ilk mumun açılışıdır. Pencere `t`'den sonraki
24 mevcut mumdur (giriş mumu 1.); veri boşluğundaki eksik mumlar atlanır. `t` ile 24. mum arasında
beklenen açılış eksikse sinyal "boşluklu"dur (sayılır, raporda sayısı yazılır).

- Hedef mesafesi `max(2·ATR, d_maliyet)`; `d_maliyet = giriş·(2(ücret+slippage)+spread)/(1-ücret-
  slippage)`: BR-8 maliyeti `(giriş+hedef)·(ücret+slippage) + giriş·spread`'i karşılayan en küçük
  mesafe (Risk 4). ATR(14) sinyal mumundadır.
- "Al": fiyat `giriş + mesafe`'ye (yüksek ≥) `giriş - ATR`'ye (düşük ≤) inmeden önce ulaşırsa
  isabet. Aynı mumda iki sınıra değerse ya da 24 mum dolarsa isabet yoktur. "Sat" (R-9, Risk 6)
  aynı kuralın tersidir: `giriş - mesafe`'ye `giriş + ATR`'ye çıkmadan önce iniş.
- İsabet her `t` için bir kez hesaplanır (`Outcomes`); taban oran dönemin her mumudur, sinyaller
  onun alt kümesidir: ikisi aynı kuraldan çıkar (Risk 5).
- Dönemde sayılan: açılışı `[başlangıç, bitiş)` içinde ve 24. mumunun açılışı bitişten önce olan
  `t` (penceresi dönem bitişini aşan sayılmaz, K-3). ATR'si olmayan ya da dosyada 24 mumu
  kalmamış `t`'nin sonucu yoktur, sayılmaz.
- Olağandışıya denk gelen: `t` dahil sonraki 24 mumda olağandışı mum var.

Oranlar `Fraction`'dır (Risk 9): "tam 5 puan" kesin karşılaştırılır.
"""

from bisect import bisect_left
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from typing import Final

from crytobot.analysis import Candle, atr

WINDOW: Final = 24
ATR_PERIOD: Final = 14
TARGET_ATR: Final = 2
STOP_ATR: Final = 1


class Direction(Enum):
    BUY = "al"
    SELL = "sat"


@dataclass(frozen=True, slots=True)
class Costs:
    """Ölçüm ayarının maliyetleri (oran): ücret, slippage, spread."""

    fee: Decimal
    slippage: Decimal
    spread: Decimal

    def factor(self) -> float:
        """`d_maliyet / giriş`."""
        side = self.fee + self.slippage
        return float((2 * side + self.spread) / (1 - side))


@dataclass(frozen=True, slots=True)
class PairSeries:
    """Bir çiftin bir aralıktaki mevcut mumları (açılış sırasıyla) ve hacimleri."""

    pair: str
    interval: timedelta
    candles: tuple[Candle, ...]
    volumes: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class Period:
    """Bir ölçüm dönemi: ad, `[start, end)` ve çiftleri."""

    name: str
    start: datetime
    end: datetime
    pairs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Outcomes:
    """Bir çiftin her mumu için sonuç: `buy`/`sell` isabet (`None`: sonuç yok), giriş fiyatı,
    24. mumun açılışı, boşluklu mu, penceresinde olağandışı mum var mı."""

    series: PairSeries
    buy: tuple[bool | None, ...]
    sell: tuple[bool | None, ...]
    entry: tuple[float | None, ...]
    last_open: tuple[datetime | None, ...]
    gapped: tuple[bool, ...]
    unusual: tuple[bool, ...]
    opens: tuple[datetime, ...]

    def hits(self, direction: Direction) -> tuple[bool | None, ...]:
        return self.buy if direction is Direction.BUY else self.sell

    def span(self, period: Period) -> range:
        """Açılışı dönemin içinde olan mumların konumları."""
        return range(bisect_left(self.opens, period.start), bisect_left(self.opens, period.end))

    def counted(self, index: int, period: Period) -> bool:
        last = self.last_open[index]
        moment = self.opens[index]
        return (
            self.buy[index] is not None
            and last is not None
            and period.start <= moment < period.end
            and last < period.end
        )


@dataclass(frozen=True, slots=True)
class Count:
    signals: int
    hits: int

    @property
    def rate(self) -> Fraction | None:
        return None if self.signals == 0 else Fraction(self.hits, self.signals)

    def __add__(self, other: "Count") -> "Count":
        return Count(self.signals + other.signals, self.hits + other.hits)


ZERO: Final = Count(0, 0)


@dataclass(frozen=True, slots=True)
class Tally:
    """Bütün sinyallerle (`all`), olağandışıya denk gelenler çıkarılmış (`clean`) ve boşluklu
    sinyal sayısı."""

    all: Count
    clean: Count
    gapped: int

    def __add__(self, other: "Tally") -> "Tally":
        return Tally(self.all + other.all, self.clean + other.clean, self.gapped + other.gapped)


EMPTY: Final = Tally(ZERO, ZERO, 0)


def _hit(candles: Sequence[Candle], start: int, target: float, stop: float, *, buy: bool) -> bool:
    for candle in candles[start : start + WINDOW]:
        if buy:
            if candle.low <= stop:  # the stop alone, or both bounds in one candle
                return False
            if candle.high >= target:
                return True
        else:
            if candle.high >= stop:
                return False
            if candle.low <= target:
                return True
    return False


def outcomes(series: PairSeries, costs: Costs, flags: Sequence[str]) -> Outcomes:
    """Her mum için "al" ve "sat" sonucu; `flags` mum başına olağandışı kural harfleri."""
    candles = series.candles
    count = len(candles)
    averages = atr(candles, period=ATR_PERIOD)
    factor = costs.factor()
    marked = [0]
    for letters in flags:
        marked.append(marked[-1] + (1 if letters else 0))
    expected = WINDOW * series.interval
    buy: list[bool | None] = []
    sell: list[bool | None] = []
    entry: list[float | None] = []
    last_open: list[datetime | None] = []
    gapped: list[bool] = []
    unusual: list[bool] = []
    for index in range(count):
        average = averages[index]
        last = index + WINDOW
        unusual.append(marked[min(last, count - 1) + 1] - marked[index] > 0)
        if average is None or last >= count:
            buy.append(None)
            sell.append(None)
            entry.append(None)
            last_open.append(None)
            gapped.append(False)
            continue
        price = candles[index + 1].open
        distance = max(TARGET_ATR * average, price * factor)
        stop = STOP_ATR * average
        buy.append(_hit(candles, index + 1, price + distance, price - stop, buy=True))
        sell.append(_hit(candles, index + 1, price - distance, price + stop, buy=False))
        entry.append(price)
        last_open.append(candles[last].open_time)
        gapped.append(candles[last].open_time - candles[index].open_time != expected)
    return Outcomes(
        series,
        tuple(buy),
        tuple(sell),
        tuple(entry),
        tuple(last_open),
        tuple(gapped),
        tuple(unusual),
        tuple(candle.open_time for candle in candles),
    )


def tally(
    results: Outcomes,
    period: Period,
    direction: Direction,
    positions: Iterable[int] | None = None,
) -> Tally:
    """Dönemde sayılan sinyaller; `positions` `None` ise dönemin her mumu (taban oran)."""
    hits = results.hits(direction)
    chosen = results.span(period) if positions is None else positions
    signals = found = clean_signals = clean_found = gaps = 0
    for index in chosen:
        if not results.counted(index, period):
            continue
        hit = bool(hits[index])
        signals += 1
        found += hit
        gaps += results.gapped[index]
        if not results.unusual[index]:
            clean_signals += 1
            clean_found += hit
    return Tally(Count(signals, found), Count(clean_signals, clean_found), gaps)


def counted_positions(
    results: Outcomes, period: Period, positions: Iterable[int]
) -> tuple[int, ...]:
    """Verilen sinyal konumlarından dönemde sayılanlar (kayıt dosyası için)."""
    return tuple(index for index in positions if results.counted(index, period))
