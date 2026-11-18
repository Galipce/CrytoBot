"""Geçmiş olay örnekleri ve ölçümleri (spec 0048 R-4, R-5, R-6, Q-3, Q-4, Q-6, G-2, G-7; plan Risk
5, 8). Saf: dosya, saat ve ağ kullanmaz.

- Örnek: duyuru x başlığındaki coin; coinsiz duyuru tek "coin yok" örneğidir. Referans an yayın
  anıdır; yayın anı yoksa ilk görme anı (işaretli), ikisi de yoksa referans an yoktur.
- Giriş mumu: açılışı referans andan kesin sonra olan ilk mum; açılışı referans andan 1 saatten
  daha sonraysa ölçülmez. Sinyal mumu giriş mumundan önceki mumdur: isabet 0045'in `outcomes`'ıyla
  o mumda hesaplanır (ATR orada, giriş = giriş mumunun açılışı), taban oran da aynı kuraldan çıkar.
- Taban oran: açılışı `[ref - 720 h, ref)` içindeki her mum sinyaldir; 24. pencere mumunun kapanışı
  ref'i aşan sayılmaz. O aralıkta 720'den az mum varsa (boşluk dahil) ya da ATR yoksa "mum
  yetmiyor".
- Seri her örneğin kendi aralığındaki (`sample_span`) mumlardan hesaplanır: aynı coinin başka
  örnekleri ATR'yi, isabeti ve taban oranı değiştirmez.
- Nedenlerin sabit sırası (`Reason`): ilk uyan neden yazılır.
- Dönem: model kesim anından önce ya da sonra; tam kesim anı "sonra"dır.
- Çakışma: aynı coinde (türden bağımsız) 24 mumluk penceresi başka bir ölçülen örnekle kesişen
  ölçülen örnek. Çakışan örnekler ayıklanmaz.

Oranlar `Fraction`'dır.
"""

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
from fractions import Fraction
from typing import Final

from crytobot.analysis import Candle
from crytobot.calibration._outcome import ATR_PERIOD, WINDOW, Costs, PairSeries, outcomes

HOUR: Final = timedelta(hours=1)
BASE_CANDLES: Final = 720
LATEST_ENTRY: Final = HOUR
# ATR warm-up before the first base signal, plus the hour the reference falls in
WARMUP_CANDLES: Final = ATR_PERIOD + 2
AFTER_CANDLES: Final = WINDOW + 2
MIN_MEASURED: Final = 30

POSITIVE: Final = "olumlu"
NEGATIVE: Final = "olumsuz"
NEUTRAL: Final = "nötr"
DIRECTIONS: Final = (POSITIVE, NEGATIVE, NEUTRAL)
BEFORE: Final = "kesimden önce"
AFTER: Final = "kesimden sonra"
TOTAL: Final = "toplam"
PERIODS: Final = (BEFORE, AFTER, TOTAL)


class Reason(Enum):
    """Ölçülemeyen örneğin nedeni; sıra denetim sırasıdır (plan Risk 8)."""

    NO_TIME = "yayın anı bilinmiyor"
    NO_COIN = "coin yok"
    NO_PAIR = "çift yok"
    NO_PRICES = "fiyat verisi yok"
    NO_ENTRY = "giriş mumu yok ya da geç"
    FEW_CANDLES = "mum yetmiyor"
    PAST_END = "pencere veri sonunu aşıyor"


class Move(Enum):
    UP = "yükseliş"
    DOWN = "düşüş"


@dataclass(frozen=True)
class EventAnnouncement:
    """Etiketlenmiş duyuru (spec 0048 Terimler). `pattern`: etiket denetiminin başlık kalıbı."""

    article_id: str
    origin: str
    catalog: str | None
    title: str
    published: datetime | None
    first_seen: datetime | None
    event_type: str
    direction: str
    coins: tuple[str, ...]
    pattern: str


@dataclass(frozen=True)
class EventSample:
    announcement: EventAnnouncement
    coin: str | None
    reference: datetime | None
    from_first_seen: bool


@dataclass(frozen=True)
class Span:
    """`[start, end)`, saat başına hizalı."""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class CoinPrices:
    """Bir coinin fiyat verisi: USDT spot çifti var mı ve 1h mumları (açılış sırasıyla)."""

    has_pair: bool
    candles: tuple[Candle, ...]


@dataclass(frozen=True)
class SampleResult:
    sample: EventSample
    reason: Reason | None
    period: str | None
    entry_time: datetime | None = None
    entry_price: float | None = None
    up: bool | None = None
    down: bool | None = None
    base_up: Fraction | None = None
    base_down: Fraction | None = None
    window_end: datetime | None = None
    overlapping: bool = False

    def hit(self, move: Move) -> bool | None:
        return self.up if move is Move.UP else self.down

    def base(self, move: Move) -> Fraction | None:
        return self.base_up if move is Move.UP else self.base_down


@dataclass(frozen=True)
class EventMeasured:
    results: tuple[SampleResult, ...]
    types: tuple[tuple[str, str], ...]
    costs: Costs
    cutoff: datetime


@dataclass(frozen=True)
class TableRow:
    """Tablonun bir satırı (R-6). `main`: ana sonuç mu; nötr türde `None`."""

    event_type: str
    move: Move
    period: str
    main: bool | None
    announcements: int
    samples: int
    measured: int
    overlapping: int
    hit: Fraction | None
    base: Fraction | None

    @property
    def difference(self) -> Fraction | None:
        if self.hit is None or self.base is None:
            return None
        return self.hit - self.base

    @property
    def few(self) -> bool:
        return self.measured < MIN_MEASURED


def floor_hour(moment: datetime) -> datetime:
    moment = moment.astimezone(UTC)
    return moment.replace(minute=0, second=0, microsecond=0)


def event_samples(announcements: Iterable[EventAnnouncement]) -> tuple[EventSample, ...]:
    """Duyuru başına coin örnekleri; sıra referans an (yoksa sonda), kimlik, başlıktaki coin."""
    samples: list[EventSample] = []
    for item in announcements:
        reference = item.published if item.published is not None else item.first_seen
        flagged = item.published is None and item.first_seen is not None
        for coin in item.coins or (None,):
            samples.append(EventSample(item, coin, reference, flagged))
    far = datetime.max.replace(tzinfo=UTC)
    order = {id(sample): index for index, sample in enumerate(samples)}
    return tuple(
        sorted(
            samples,
            key=lambda s: (
                s.reference is None,
                far if s.reference is None else s.reference,
                s.announcement.article_id,
                order[id(s)],
            ),
        )
    )


def sample_span(reference: datetime) -> Span:
    """Bir örneğin fiyat aralığı: taban oran ve ATR ısınması, giriş mumu ve 24 mum (R-3)."""
    base = floor_hour(reference)
    return Span(
        base - (BASE_CANDLES + WARMUP_CANDLES) * HOUR,
        base + AFTER_CANDLES * HOUR,
    )


def merge_spans(spans: Iterable[Span]) -> tuple[Span, ...]:
    merged: list[Span] = []
    for span in sorted(spans, key=lambda s: (s.start, s.end)):
        if merged and span.start <= merged[-1].end:
            last = merged[-1]
            merged[-1] = Span(last.start, max(last.end, span.end))
        else:
            merged.append(span)
    return tuple(merged)


def price_needs(samples: Iterable[EventSample]) -> dict[str, tuple[Span, ...]]:
    """Coin başına birleşik aralıklar (üst üste binenler bir kez); coin sırasıyla."""
    spans: dict[str, list[Span]] = {}
    for sample in samples:
        if sample.coin is None or sample.reference is None:
            continue
        spans.setdefault(sample.coin, []).append(sample_span(sample.reference))
    return {coin: merge_spans(spans[coin]) for coin in sorted(spans)}


@dataclass(frozen=True)
class Series:
    """Bir örneğin kendi aralığındaki seri (review round 1 F-3): ATR ve sonuçlar yalnız o
    aralığın mumlarından; başka örneklerin aralıkları sonucu değiştirmez."""

    opens: tuple[datetime, ...]
    buy: tuple[bool | None, ...]
    sell: tuple[bool | None, ...]
    entry: tuple[float | None, ...]
    last_open: tuple[datetime | None, ...]


# Wilder ATR's first value sits at `period - 1` (analysis.atr); before it there is no ATR
FIRST_ATR: Final = ATR_PERIOD - 1


def prepare_series(candles: Sequence[Candle], costs: Costs) -> Series:
    if not candles:
        return Series((), (), (), (), ())
    series = PairSeries("", HOUR, tuple(candles), ())
    results = outcomes(series, costs, [""] * len(candles))
    return Series(results.opens, results.buy, results.sell, results.entry, results.last_open)


def _base(coin: Series, low: int, high: int, reference: datetime) -> tuple[Fraction, Fraction]:
    signals = ups = downs = 0
    for index in range(low, high):
        last = coin.last_open[index]
        up = coin.buy[index]
        if last is None or up is None or last + HOUR > reference:
            continue
        signals += 1
        ups += up
        downs += bool(coin.sell[index])
    if signals == 0:  # pragma: no cover - 720 candles before the reference always count some
        raise Unmeasured(Reason.FEW_CANDLES)
    return Fraction(ups, signals), Fraction(downs, signals)


class Unmeasured(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason.value)
        self.reason = reason


@dataclass(frozen=True)
class Measurement:
    """Bir referans anın ölçümü (spec 0053 plan step 2: 0048 ile ileriye dönük ölçümün ortak
    çekirdeği). `signal`: sinyal mumunun serideki konumu; giriş mumu `signal + 1`'dir."""

    entry_time: datetime
    entry_price: float | None
    up: bool
    down: bool
    base_up: Fraction
    base_down: Fraction
    window_end: datetime
    signal: int


def measure_reference(reference: datetime, coin: Series | None, has_pair: bool) -> Measurement:
    """Giriş mumu, isabet ve taban oran; ölçülemiyorsa `Unmeasured` (nedenin sırası `Reason`)."""
    if not has_pair or coin is None:
        raise Unmeasured(Reason.NO_PAIR)
    opens = coin.opens
    if not opens:
        raise Unmeasured(Reason.NO_PRICES)
    entry = bisect_right(opens, reference)
    if entry >= len(opens) or opens[entry] - reference > LATEST_ENTRY:
        raise Unmeasured(Reason.NO_ENTRY)
    signal = entry - 1
    low = bisect_left(opens, reference - BASE_CANDLES * HOUR)
    high = bisect_left(opens, reference)
    if signal < FIRST_ATR or high - low < BASE_CANDLES or low < FIRST_ATR:
        raise Unmeasured(Reason.FEW_CANDLES)
    up, down, last = coin.buy[signal], coin.sell[signal], coin.last_open[signal]
    if up is None or last is None:
        raise Unmeasured(Reason.PAST_END)
    base_up, base_down = _base(coin, low, high, reference)
    return Measurement(
        opens[entry],
        coin.entry[signal],
        up,
        bool(down),
        base_up,
        base_down,
        last + HOUR,
        signal,
    )


def _measure(sample: EventSample, coin: Series | None, has_pair: bool) -> SampleResult:
    reference = sample.reference
    assert reference is not None and sample.coin is not None  # checked by the caller
    found = measure_reference(reference, coin, has_pair)
    return SampleResult(
        sample,
        None,
        None,
        found.entry_time,
        found.entry_price,
        found.up,
        found.down,
        found.base_up,
        found.base_down,
        found.window_end,
    )


def _period(reference: datetime | None, cutoff: datetime) -> str | None:
    if reference is None:
        return None
    return AFTER if reference >= cutoff else BEFORE


def _overlaps(results: list[SampleResult]) -> list[SampleResult]:
    windows: dict[str, list[tuple[datetime, datetime, int]]] = {}
    for index, result in enumerate(results):
        start, end, coin = result.entry_time, result.window_end, result.sample.coin
        if result.reason is None and start is not None and end is not None and coin is not None:
            windows.setdefault(coin, []).append((start, end, index))
    marked: set[int] = set()
    for items in windows.values():
        items.sort()
        for position, (_, end, index) in enumerate(items):
            for later_start, _, later in items[position + 1 :]:
                if later_start >= end:
                    break
                marked.update((index, later))
    return [
        replace(result, overlapping=True) if index in marked else result
        for index, result in enumerate(results)
    ]


def measure_events(
    samples: Sequence[EventSample],
    prices: Mapping[str, CoinPrices],
    costs: Costs,
    cutoff: datetime,
    types: Sequence[tuple[str, str]],
) -> EventMeasured:
    """Her örneğin sonucu, örnek sırasıyla. Seri her örneğin kendi aralığında (`sample_span`)
    hesaplanır; aynı coin ve aynı aralık bir kez (review round 1 F-3)."""
    opens = {
        coin: tuple(candle.open_time for candle in item.candles)
        for coin, item in prices.items()
        if item.has_pair
    }
    prepared: dict[tuple[str, datetime], Series] = {}

    def own(coin: str, reference: datetime) -> Series | None:
        if coin not in opens:
            return None
        span = sample_span(reference)
        key = (coin, span.start)
        if key not in prepared:
            times = opens[coin]
            low, high = bisect_left(times, span.start), bisect_left(times, span.end)
            prepared[key] = prepare_series(prices[coin].candles[low:high], costs)
        return prepared[key]

    results: list[SampleResult] = []
    for sample in samples:
        period = _period(sample.reference, cutoff)
        if sample.reference is None:
            results.append(SampleResult(sample, Reason.NO_TIME, period))
            continue
        if sample.coin is None:
            results.append(SampleResult(sample, Reason.NO_COIN, period))
            continue
        known = prices.get(sample.coin)
        try:
            result = _measure(
                sample, own(sample.coin, sample.reference), known is not None and known.has_pair
            )
        except Unmeasured as unmeasured:
            results.append(SampleResult(sample, unmeasured.reason, period))
            continue
        results.append(replace(result, period=period))
    return EventMeasured(tuple(_overlaps(results)), tuple(types), costs, cutoff)


def _mean(values: Sequence[Fraction]) -> Fraction | None:
    return None if not values else sum(values, Fraction(0)) / len(values)


def _main(direction: str, move: Move) -> bool | None:
    if direction == POSITIVE:
        return move is Move.UP
    if direction == NEGATIVE:
        return move is Move.DOWN
    return None


def table_rows(measured: EventMeasured) -> tuple[TableRow, ...]:
    """Tür (tablo sırası) x yön x dönem; toplam dönem ikisinin birleşimidir."""
    rows: list[TableRow] = []
    for name, direction in measured.types:
        typed = [r for r in measured.results if r.sample.announcement.event_type == name]
        for move in (Move.UP, Move.DOWN):
            for period in PERIODS:
                chosen = [
                    r
                    for r in typed
                    if r.period is not None and (period == TOTAL or r.period == period)
                ]
                done = [r for r in chosen if r.reason is None]
                hits = [Fraction(int(bool(r.hit(move)))) for r in done]
                bases = [b for r in done if (b := r.base(move)) is not None]
                rows.append(
                    TableRow(
                        name,
                        move,
                        period,
                        _main(direction, move),
                        len({r.sample.announcement.article_id for r in chosen}),
                        len(chosen),
                        len(done),
                        sum(r.overlapping for r in done),
                        _mean(hits),
                        _mean(bases),
                    )
                )
    return tuple(rows)


def reason_counts(measured: EventMeasured) -> tuple[tuple[Reason, int], ...]:
    """Her neden (sabit sırayla) ve ölçülemeyen örnek sayısı; sıfırlar da yazılır."""
    return tuple((reason, sum(r.reason is reason for r in measured.results)) for reason in Reason)
