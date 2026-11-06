"""Backtest turunun girdileri (spec 0025 R-5, R-6; plan Risk 6, 8).

Tur anı t için her çiftin `PairMarket`'ı, ileriye bakmadan:

- **Mumlar:** açılışı + aralığı ≤ t olanların son `candle_count` kadarı (kapanmış mumlar). Kapanışı
  t'den sonra olan hiçbir mum verilmez. Boşluk doldurulmaz.
- **Fiyat:** açılışı t olan mumun `open` metni, zamanı t. O mum yoksa fiyat eksiktir.
- **Kurallar ve fiyat adımı** dosyanın başlığından, **spread** ayardan, sabit.

Mumlar `analysis`'e `float` olarak gider; değer `float`'ta birebir geri dönmüyorsa o çiftin serisi
eksik veridir (`_market._candle`, paper'daki gibi). Eksik tur: tura verilen veride fiyat sorunu
ya da son kapanmış mumun yaşı sorunu (turun kendi kuralları; `propose` ikinci kez çağrılmaz).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from crytobot.analysis import Candle
from crytobot.app._inputs import PairMarket, TurnSettings, candle_age_issue, price_issue
from crytobot.app._market import _candle
from crytobot.market_data import HistoryData, HistoryPair, MarketCandle
from crytobot.risk import PairRules


@dataclass(frozen=True)
class _Pair:
    """Bir çiftin hazırlanmış mumları: açılış sırasıyla, `analysis` biçimi ve birebir olmayanların
    önek sayımı (pencerede birebir olmayan var mı, tek çıkarmayla)."""

    name: str
    opens: tuple[datetime, ...]
    candles: tuple[MarketCandle, ...]
    series: tuple[Candle | None, ...]
    inexact_before: tuple[int, ...]
    by_open: dict[datetime, int]
    rules: PairRules
    tick: Decimal


def _prepared(pair: HistoryPair) -> _Pair:
    series = tuple(_candle(candle) for candle in pair.candles)
    inexact_before = [0]
    for translated in series:
        inexact_before.append(inexact_before[-1] + (translated is None))
    opens = tuple(candle.open_time for candle in pair.candles)
    rules = PairRules(pair.rules.amount_step, pair.rules.min_amount, pair.rules.min_notional)
    return _Pair(
        pair.pair,
        opens,
        pair.candles,
        series,
        tuple(inexact_before),
        {open_time: index for index, open_time in enumerate(opens)},
        rules,
        pair.tick,
    )


class TurnInputs:
    """Veri dosyasından tur anı başına piyasa girdisi; dosya bir kez hazırlanır.

    Turlar zamanda ileri gider: çift başına kapanmış mum sayısı bir imleçle ilerler (`app`'in
    izinli importlarında `bisect` yoktur). Geri giden an imleci baştan sayar.
    """

    def __init__(
        self, data: HistoryData, settings: TurnSettings, candle_count: int, spread: Decimal
    ) -> None:
        self._settings = settings
        self._count = candle_count
        self._spread = spread
        self._pairs = tuple(_prepared(pair) for pair in data.pairs)
        self._closed = [0] * len(self._pairs)
        self._last: datetime | None = None

    def _closed_count(self, index: int, pair: _Pair, at: datetime) -> int:
        """Açılışı + aralığı ≤ `at` olan mum sayısı."""
        closed = self._closed[index]
        latest_open = at - self._settings.candle_interval
        while closed < len(pair.opens) and pair.opens[closed] <= latest_open:
            closed += 1
        self._closed[index] = closed
        return closed

    def _series(self, index: int, pair: _Pair, at: datetime) -> tuple[Candle, ...] | None:
        closed = self._closed_count(index, pair, at)
        first = max(0, closed - self._count)
        if pair.inexact_before[closed] - pair.inexact_before[first]:
            return None  # a rounded series decides nothing (spec 0017 R-10)
        return tuple(candle for candle in pair.series[first:closed] if candle is not None)

    def market(self, at: datetime) -> dict[str, PairMarket]:
        """R-5: tura verilen piyasa; anahtar sırası dosyanın çift sırasıdır."""
        if self._last is not None and at < self._last:
            self._closed = [0] * len(self._pairs)
        self._last = at
        market: dict[str, PairMarket] = {}
        for number, pair in enumerate(self._pairs):
            index = pair.by_open.get(at)
            price = None if index is None else pair.candles[index].open
            market[pair.name] = PairMarket(
                self._series(number, pair, at),
                price,
                None if price is None else at,
                pair.rules,
                pair.tick,
                self._spread,
            )
        return market

    def missing(self, market: dict[str, PairMarket], at: datetime) -> tuple[str, ...]:
        """R-6, R-10: fiyatı ya da verisi eksik ya da bayat çiftler, dosya sırasıyla."""
        found: list[str] = []
        for name, data in market.items():
            candles: Sequence[Candle] | None = data.candles
            if (
                price_issue(data, self._settings, at) is not None
                or candles is None
                or candle_age_issue(candles, self._settings, at) is not None
            ):
                found.append(name)
        return tuple(found)
