"""İleriye dönük ölçüm ve hüküm (spec 0053 R-2…R-7, Q-1…Q-6, G-1…G-5; plan Risk 1…5, 9). Saf:
dosya, saat ve ağ kullanmaz.

- Örnek (R-2, plan Risk 5a, 5c): rapor anına kadarki her "skorlandı" sonucunun, yönü olumsuz ve
  şiddeti ≥ 2 olan olay skorları; bir haberde aynı coin için birden çok skor tek örnektir (şiddet en
  yüksek, tür onunki, eşitlikte alfabe). Skor anı sonucun anıdır. Sıra: skor anı, haber kimliği,
  coin.
- Look-ahead: rapor anından sonraki sonuç, gölge satırı ve mum girdiye hiç girmez. Bir örneğin
  mumları `forward_span`'dır: taban oranın 720 mumu ve ATR ısınması, giriş mumu ve 24 mum; örnek
  ancak 24. mumu rapor anına kadar kapandıysa ölçülür (`ölçüm bekliyor`, plan Risk 2).
- Skor anındaki beyaz liste (G-1): gölge kayıtta skor anından önceki ya da eşit son turun beyaz
  listesi; yoksa bot ayarındaki.
- Güncel üçlü (plan Risk 5b): rapor anına kadarki "skorlandı" sonuçlarından `(an, haber kimliği)`
  en büyük olanınki. Bir üçlünün ilk anı o üçlünün en eski "skorlandı" sonucudur.
- İsabet ve taban oran 0048'in çekirdeğidir (`measure_reference`): kopya kural yok.
- Olağandışı (plan Risk 1): penceresinde (giriş mumu…24. mum) 0045 R-8'in (a) ya da (c) kuralıyla
  işaretli mum. (b) hacim ister, (d) beş çift ister: uygulanmaz.
- Örtüşme (G-2, plan Risk 4): her tablonun kendi kümesinde, ölçülmüş örnekler sırayla gezilir;
  giriş mumu aynı coinde daha önce sayılmış örneğin `[giriş, giriş + 24 s)` aralığındaysa örtüşendir
  ve sayılmaz.
- Hüküm (R-3, plan Risk 3): güncel üçlünün, skor anındaki beyaz listede olan, ölçülmüş ve
  örtüşmeyen örnekleriyle; olağandışılar dahil. Eşik kesin: `fark ≥ 5/100`.
- İzinsiz kaynak (spec 0055 CB-4): `unpermitted`'teki haberlerin sonuçları hiçbir yere girmez
  (örnek, üçlü, ilk an, fiyat ihtiyacı); olumsuz (şiddet ≥ 2) coin örnekleri yalnız kaynak adına
  göre sayılır (`ForwardMeasured.unpermitted`).

Oranlar `Fraction`'dır.
"""

import math
from bisect import bisect_left
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from fractions import Fraction
from typing import Final

from crytobot.analysis import Candle
from crytobot.calibration._events import (
    BASE_CANDLES,
    HOUR,
    NEGATIVE,
    WARMUP_CANDLES,
    CoinPrices,
    Reason,
    Series,
    Span,
    Unmeasured,
    floor_hour,
    measure_reference,
    merge_spans,
    prepare_series,
)
from crytobot.calibration._outcome import WINDOW, Costs
from crytobot.calibration._unusual import unusual_flags

SCORED: Final = "skorlandı"
MIN_SEVERITY: Final = 2
MIN_DAYS: Final = 90
MIN_SAMPLES: Final = 30
THRESHOLD: Final = Fraction(5, 100)
DAY: Final = timedelta(days=1)
# the 24th window candle opens at the score's hour + 24 h and closes an hour later
PENDING_AFTER: Final = (WINDOW + 1) * HOUR
UNKNOWN_SOURCE: Final = "bilinmiyor"
UNUSUAL_RULES: Final = "ac"
SHADOW_STATES: Final = (
    "bastırılırdı",
    "bastırılmazdı",
    "bastırılmazdı — eksik bilgi",
    "filtre yok",
)
NO_FILTER: Final = "filtre yok"
VERDICT_TITLE: Final = "hüküm tablosu (güncel üçlü, skor anındaki beyaz liste)"
NO_VERDICT: Final = "hüküm yok"
POSITIVE_VERDICT: Final = "olumlu"
NEGATIVE_VERDICT: Final = "olumsuz"

Triple = tuple[str, str, str]  # model, prompt fingerprint, context fingerprint


class ForwardReason(Enum):
    """Ölçülmeme nedeni; sıra denetim sırasıdır (plan Risk 2)."""

    NO_PAIR = "çift yok"
    PENDING = "ölçüm bekliyor"
    NO_PRICES = "fiyat verisi yok"
    NO_ENTRY = "giriş mumu yok ya da geç"
    FEW_CANDLES = "mum yetmiyor"


# 0048's reasons; a window cut by a data gap has too few candles as well
_FROM_EVENTS: Final = {
    Reason.NO_PAIR: ForwardReason.NO_PAIR,
    Reason.NO_PRICES: ForwardReason.NO_PRICES,
    Reason.NO_ENTRY: ForwardReason.NO_ENTRY,
    Reason.FEW_CANDLES: ForwardReason.FEW_CANDLES,
    Reason.PAST_END: ForwardReason.FEW_CANDLES,
}


@dataclass(frozen=True)
class ScoredNews:
    """Skor kaydındaki bir haberin tek sonucu: tür, an ve (skorlandıysa) üçlü."""

    news_id: int
    kind: str
    at: datetime
    triple: Triple | None


@dataclass(frozen=True)
class ForwardEvent:
    news_id: int
    coin: str
    event_type: str
    direction: str
    severity: int


@dataclass(frozen=True)
class ShadowTurn:
    """Gölge kaydın bir satırı (spec 0052): tur anı, çift, o turun beyaz listesi, filtre durumu ve
    nedeni, teknik "al" var mı."""

    turn_at: datetime
    pair: str
    whitelist: tuple[str, ...]
    state: str
    reason: str
    technical_buy: bool


@dataclass(frozen=True)
class ForwardInputs:
    """`results` `None`: skor kaydı yok. `shadow` `None`: gölge kayıt yok. `sources`: haber
    kimliği → kaynak türü. `whitelist`: bot ayarındaki beyaz liste. `unpermitted`: kaynağı izinli
    olmayan haberin kimliği → kaynak adı (spec 0055 CB-4)."""

    results: tuple[ScoredNews, ...] | None
    events: tuple[ForwardEvent, ...]
    sources: Mapping[int, str]
    shadow: tuple[ShadowTurn, ...] | None
    whitelist: tuple[str, ...]
    unpermitted: Mapping[int, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ForwardSample:
    news_id: int
    source: str
    event_type: str
    severity: int
    coin: str
    scored_at: datetime
    triple: Triple
    whitelisted: bool


@dataclass(frozen=True)
class ForwardResult:
    sample: ForwardSample
    reason: ForwardReason | None
    entry_time: datetime | None = None
    entry_price: float | None = None
    up: bool | None = None
    down: bool | None = None
    base_up: Fraction | None = None
    base_down: Fraction | None = None
    unusual: bool | None = None


@dataclass(frozen=True)
class Rates:
    """Bir kümenin düşüş ve yükseliş isabeti ve taban oranı (örnek oranlarının ortalaması)."""

    count: int
    down_hit: Fraction | None
    down_base: Fraction | None
    up_hit: Fraction | None
    up_base: Fraction | None

    @property
    def difference(self) -> Fraction | None:
        if self.down_hit is None or self.down_base is None:
            return None
        return self.down_hit - self.down_base

    @property
    def up_difference(self) -> Fraction | None:
        if self.up_hit is None or self.up_base is None:
            return None
        return self.up_hit - self.up_base


Counts = tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class ForwardTable:
    """R-4: bir kümenin tablosu. `judged`: hükme giren tablo mu (değilse `hüküm dışı`)."""

    title: str
    judged: bool
    triple: Triple | None
    first_at: datetime | None
    last_at: datetime | None
    samples: int
    rates: Rates
    clean: Rates
    overlapping: int
    unmeasured: tuple[tuple[ForwardReason, int], ...]
    outside: int
    by_source: Counts
    by_type: Counts
    by_severity: Counts
    by_coin: Counts


@dataclass(frozen=True)
class ForwardVerdict:
    kind: str
    line: str


@dataclass(frozen=True)
class ShadowBuys:
    """Bir filtre durumundaki teknik "al"lar: sayı, yükseliş isabeti ve taban oranı."""

    state: str
    buys: int
    measured: int
    up_hit: Fraction | None
    up_base: Fraction | None
    unmeasured: tuple[tuple[ForwardReason, int], ...]


@dataclass(frozen=True)
class ShadowSection:
    rows: int
    turns: int
    first_at: datetime | None
    last_at: datetime | None
    pairs: tuple[tuple[str, Counts], ...]
    reasons: Counts
    buys: tuple[ShadowBuys, ...]


@dataclass(frozen=True)
class ForwardMeasured:
    """Bütün ölçüm. `overlapping`: örnek başına birincil tablodaki örtüşme (beyaz listedeyse
    üçlüsünün tablosu, değilse güncel üçlünün yardımcı tablosu); hiçbir tabloda değilse `None`.
    `unpermitted`: izinsiz kaynaktan gelen, sayılmayan coin örnekleri, kaynak adına göre."""

    report_at: datetime
    costs: Costs
    score_record: bool
    current: Triple | None
    current_first: datetime | None
    results: tuple[ForwardResult, ...]
    overlapping: tuple[bool | None, ...]
    verdict: ForwardVerdict
    table: ForwardTable | None
    old: tuple[ForwardTable, ...]
    side: ForwardTable | None
    shadow: ShadowSection | None
    unpermitted: Counts = ()


def base_of(pair: str) -> str:
    """`BTC/USDT` → `BTC` (0052 G-6)."""
    return pair.split("/", 1)[0]


def forward_span(reference: datetime) -> Span:
    """Bir örneğin mumları: taban oran ve ATR ısınması, giriş mumu ve 24 mum (24. mumun kapanışı
    `taban + 25 s`)."""
    base = floor_hour(reference)
    return Span(base - (BASE_CANDLES + WARMUP_CANDLES) * HOUR, base + PENDING_AFTER)


def is_pending(reference: datetime, report_at: datetime) -> bool:
    return floor_hour(reference) + PENDING_AFTER > report_at


def _all_scored(inputs: ForwardInputs, report_at: datetime) -> list[ScoredNews]:
    return [
        item
        for item in inputs.results or ()
        if item.kind == SCORED and item.triple is not None and item.at <= report_at
    ]


def _scored(inputs: ForwardInputs, report_at: datetime) -> list[ScoredNews]:
    """İzinli kaynakların "skorlandı" sonuçları; bütün ölçüm bunlardan türer (CB-4)."""
    return [
        item for item in _all_scored(inputs, report_at) if item.news_id not in inputs.unpermitted
    ]


def _chosen(
    events: Iterable[ForwardEvent], news_ids: Iterable[int]
) -> dict[tuple[int, str], ForwardEvent]:
    """Olumsuz (şiddet ≥ 2) olay skorları, (haber, coin) başına tek: şiddet en yüksek, eşitlikte
    tür alfabesi."""
    wanted = set(news_ids)
    chosen: dict[tuple[int, str], ForwardEvent] = {}
    for event in events:
        if event.news_id not in wanted:
            continue
        if event.direction != NEGATIVE or event.severity < MIN_SEVERITY:
            continue
        key = (event.news_id, event.coin)
        held = chosen.get(key)
        if held is None or (-event.severity, event.event_type) < (-held.severity, held.event_type):
            chosen[key] = event
    return chosen


def unpermitted_counts(inputs: ForwardInputs, report_at: datetime) -> Counts:
    """CB-4: izinsiz kaynaktan gelen olumsuz coin örnekleri, kaynak adına göre."""
    news_ids = {
        item.news_id
        for item in _all_scored(inputs, report_at)
        if item.news_id in inputs.unpermitted
    }
    chosen = _chosen(inputs.events, news_ids)
    return _counts(inputs.unpermitted[news_id] for news_id, _ in chosen)


def current_triple(inputs: ForwardInputs, report_at: datetime) -> Triple | None:
    scored = _scored(inputs, report_at)
    if not scored:
        return None
    return max(scored, key=lambda item: (item.at, item.news_id)).triple


def triple_spans(
    inputs: ForwardInputs, report_at: datetime
) -> dict[Triple, tuple[datetime, datetime]]:
    """Üçlü → (ilk, son) "skorlandı" anı."""
    spans: dict[Triple, tuple[datetime, datetime]] = {}
    for item in _scored(inputs, report_at):
        assert item.triple is not None  # kept by `_scored`
        first, last = spans.get(item.triple, (item.at, item.at))
        spans[item.triple] = (min(first, item.at), max(last, item.at))
    return spans


def _turns(inputs: ForwardInputs, report_at: datetime) -> list[ShadowTurn]:
    return sorted(
        (row for row in inputs.shadow or () if row.turn_at <= report_at),
        key=lambda row: row.turn_at,
    )


def whitelist_at(turns: Sequence[ShadowTurn], at: datetime, fallback: tuple[str, ...]) -> set[str]:
    """G-1: skor anından önceki ya da eşit son turun beyaz listesi (coinler); tur yoksa ayardaki.
    `turns` tur anı sırasıyladır."""
    chosen: tuple[str, ...] = fallback
    for row in turns:
        if row.turn_at > at:
            break
        chosen = row.whitelist
    return {base_of(pair) for pair in chosen}


def forward_samples(inputs: ForwardInputs, report_at: datetime) -> tuple[ForwardSample, ...]:
    """R-2, AC-1: rapor anına kadarki olumsuz (şiddet ≥ 2) olay skorları, coin başına tek örnek."""
    scored = {item.news_id: item for item in _scored(inputs, report_at)}
    chosen = _chosen(inputs.events, scored)
    turns = _turns(inputs, report_at)
    samples = []
    for (news_id, coin), event in chosen.items():
        result = scored[news_id]
        assert result.triple is not None  # kept by `_scored`
        samples.append(
            ForwardSample(
                news_id,
                inputs.sources.get(news_id, UNKNOWN_SOURCE),
                event.event_type,
                event.severity,
                coin,
                result.at,
                result.triple,
                coin in whitelist_at(turns, result.at, inputs.whitelist),
            )
        )
    return tuple(sorted(samples, key=lambda s: (s.scored_at, s.news_id, s.coin)))


def shadow_buys(inputs: ForwardInputs, report_at: datetime) -> tuple[ShadowTurn, ...]:
    """R-7: rapor anına kadarki teknik "al" satırları."""
    return tuple(row for row in _turns(inputs, report_at) if row.technical_buy)


def price_coins(inputs: ForwardInputs, report_at: datetime) -> tuple[str, ...]:
    """Fiyat bilgisi gereken coinler: bütün örneklerin ve teknik "al"ların; coin sırasıyla."""
    coins = {s.coin for s in forward_samples(inputs, report_at)}
    coins.update(base_of(row.pair) for row in shadow_buys(inputs, report_at))
    return tuple(sorted(coins))


def _references(inputs: ForwardInputs, report_at: datetime) -> list[tuple[str, datetime]]:
    found = [(s.coin, s.scored_at) for s in forward_samples(inputs, report_at)]
    found += [(base_of(row.pair), row.turn_at) for row in shadow_buys(inputs, report_at)]
    return found


def download_needs(inputs: ForwardInputs, report_at: datetime) -> dict[str, tuple[Span, ...]]:
    """İndirme (plan Risk 9): bütün örneklerin ve teknik "al"ların aralıkları, coin başına
    birleşik; coin sırasıyla. Henüz kapanmamış mumları indirme adımı kendisi almaz."""
    spans: dict[str, list[Span]] = {}
    for coin, reference in _references(inputs, report_at):
        spans.setdefault(coin, []).append(forward_span(reference))
    return {coin: merge_spans(spans[coin]) for coin in sorted(spans)}


def report_needs(
    inputs: ForwardInputs, report_at: datetime, pairs: Iterable[str]
) -> dict[str, tuple[Span, ...]]:
    """Rapor (plan Risk 2): ölçülecek (çifti olan, beklemeyen) örneklerin ve teknik "al"ların
    aralıkları; biri indirilmemişse rapor reddeder."""
    listed = set(pairs)
    spans: dict[str, list[Span]] = {}
    for coin, reference in _references(inputs, report_at):
        if coin in listed and not is_pending(reference, report_at):
            spans.setdefault(coin, []).append(forward_span(reference))
    return {coin: merge_spans(spans[coin]) for coin in sorted(spans)}


@dataclass(frozen=True)
class _Measured:
    reason: ForwardReason | None
    entry_time: datetime | None = None
    entry_price: float | None = None
    up: bool | None = None
    down: bool | None = None
    base_up: Fraction | None = None
    base_down: Fraction | None = None
    unusual: bool | None = None


class _Prices:
    """Her referansın serisi kendi aralığından (`forward_span`), aynı coin ve aralık bir kez."""

    def __init__(self, prices: Mapping[str, CoinPrices], costs: Costs) -> None:
        self._prices = prices
        self._costs = costs
        self._opens = {
            coin: tuple(candle.open_time for candle in item.candles)
            for coin, item in prices.items()
            if item.has_pair
        }
        self._cache: dict[tuple[str, datetime], tuple[Series, tuple[str, ...]]] = {}

    def _series(self, coin: str, span: Span) -> tuple[Series, tuple[str, ...]]:
        key = (coin, span.start)
        if key not in self._cache:
            times = self._opens[coin]
            low, high = bisect_left(times, span.start), bisect_left(times, span.end)
            candles: Sequence[Candle] = self._prices[coin].candles[low:high]
            flags = unusual_flags({coin: candles}, {coin: [0.0] * len(candles)})[coin]
            self._cache[key] = (prepare_series(candles, self._costs), flags)
        return self._cache[key]

    def measure(self, coin: str, reference: datetime, report_at: datetime) -> _Measured:
        known = self._prices.get(coin)
        if known is None or not known.has_pair:
            return _Measured(ForwardReason.NO_PAIR)
        if is_pending(reference, report_at):
            return _Measured(ForwardReason.PENDING)
        series, flags = self._series(coin, forward_span(reference))
        try:
            found = measure_reference(reference, series, True)
        except Unmeasured as unmeasured:
            return _Measured(_FROM_EVENTS[unmeasured.reason])
        window = flags[found.signal + 1 : found.signal + 1 + WINDOW]
        unusual = any(set(letters) & set(UNUSUAL_RULES) for letters in window)
        return _Measured(
            None,
            found.entry_time,
            found.entry_price,
            found.up,
            found.down,
            found.base_up,
            found.base_down,
            unusual,
        )


def _overlapping(results: Sequence[ForwardResult]) -> set[int]:
    """Plan Risk 4: konumlar sırayla (skor anı, haber kimliği, coin); ilk sayılır."""
    order = sorted(
        range(len(results)),
        key=lambda i: (
            results[i].sample.scored_at,
            results[i].sample.news_id,
            results[i].sample.coin,
        ),
    )
    counted: dict[str, datetime] = {}
    marked: set[int] = set()
    for index in order:
        result = results[index]
        entry = result.entry_time
        if result.reason is not None or entry is None:
            continue
        coin = result.sample.coin
        earlier = counted.get(coin)
        if earlier is not None and entry < earlier + WINDOW * HOUR:
            marked.add(index)
            continue
        counted[coin] = entry
    return marked


def _mean(values: Sequence[Fraction]) -> Fraction | None:
    return None if not values else sum(values, Fraction(0)) / len(values)


def rates(results: Sequence[ForwardResult]) -> Rates:
    done = [r for r in results if r.reason is None]
    return Rates(
        len(done),
        _mean([Fraction(int(bool(r.down))) for r in done]),
        _mean([b for r in done if (b := r.base_down) is not None]),
        _mean([Fraction(int(bool(r.up))) for r in done]),
        _mean([b for r in done if (b := r.base_up) is not None]),
    )


def _counts(values: Iterable[str]) -> Counts:
    return tuple(sorted(Counter(values).items()))


def _reasons(results: Iterable[ForwardResult]) -> tuple[tuple[ForwardReason, int], ...]:
    found = Counter(r.reason for r in results if r.reason is not None)
    return tuple((reason, found.get(reason, 0)) for reason in ForwardReason)


def _table(
    title: str,
    judged: bool,
    triple: Triple | None,
    span: tuple[datetime, datetime] | None,
    chosen: Sequence[ForwardResult],
    outside: int,
) -> tuple[ForwardTable, set[int]]:
    marked = _overlapping(chosen)
    counted = [r for i, r in enumerate(chosen) if r.reason is None and i not in marked]
    table = ForwardTable(
        title,
        judged,
        triple,
        None if span is None else span[0],
        None if span is None else span[1],
        len(chosen),
        rates(counted),
        rates([r for r in counted if not r.unusual]),
        len(marked),
        _reasons(chosen),
        outside,
        _counts(r.sample.source for r in counted),
        _counts(r.sample.event_type for r in counted),
        _counts(str(r.sample.severity) for r in counted),
        _counts(r.sample.coin for r in counted),
    )
    return table, marked


def _points(value: Fraction) -> str:
    """Bir ondalıkla, aşağı yuvarlanmış (karar kesirle verilir; plan Risk 5f)."""
    tenths = math.floor(value * 1000)
    return f"{tenths / 10:+.1f}"


def decide(
    current_first: datetime | None, report_at: datetime, count: int, difference: Fraction | None
) -> ForwardVerdict:
    """R-3 sırası; `hüküm yok` kalan gün ve kalan örnek sayısını yazar (plan Risk 5e)."""
    if current_first is None:
        return ForwardVerdict(
            NO_VERDICT, f"{NO_VERDICT}: skor yok — kalan {MIN_DAYS} gün, {MIN_SAMPLES} örnek"
        )
    elapsed = report_at - current_first
    days = elapsed // DAY
    remaining = f"kalan {max(0, MIN_DAYS - days)} gün, {max(0, MIN_SAMPLES - count)} örnek"
    if elapsed < MIN_DAYS * DAY:
        return ForwardVerdict(
            NO_VERDICT, f"{NO_VERDICT}: süre yetersiz ({days}/{MIN_DAYS} gün) — {remaining}"
        )
    if count < MIN_SAMPLES or difference is None:
        return ForwardVerdict(
            NO_VERDICT, f"{NO_VERDICT}: olay yetersiz ({count}/{MIN_SAMPLES}) — {remaining}"
        )
    if difference >= THRESHOLD:
        return ForwardVerdict(
            POSITIVE_VERDICT,
            f"{POSITIVE_VERDICT}: isabet taban oranı en az 5 puan geçiyor "
            f"({_points(difference)} ≥ +5)",
        )
    return ForwardVerdict(
        NEGATIVE_VERDICT,
        f"{NEGATIVE_VERDICT}: isabet taban oranı 5 puan geçmiyor ({_points(difference)} < +5)",
    )


def _shadow(inputs: ForwardInputs, report_at: datetime, prices: _Prices) -> ShadowSection | None:
    if inputs.shadow is None:
        return None
    rows = _turns(inputs, report_at)
    moments = sorted({row.turn_at for row in rows})
    pairs: dict[str, Counter[str]] = {}
    for row in rows:
        pairs.setdefault(row.pair, Counter())[row.state] += 1
    states = [*SHADOW_STATES, *sorted({row.state for row in rows} - set(SHADOW_STATES))]
    buys: list[ShadowBuys] = []
    for state in states:
        chosen = [row for row in rows if row.technical_buy and row.state == state]
        found = [prices.measure(base_of(row.pair), row.turn_at, report_at) for row in chosen]
        done = [item for item in found if item.reason is None]
        missing = Counter(item.reason for item in found if item.reason is not None)
        buys.append(
            ShadowBuys(
                state,
                len(chosen),
                len(done),
                _mean([Fraction(int(bool(item.up))) for item in done]),
                _mean([b for item in done if (b := item.base_up) is not None]),
                tuple((reason, missing.get(reason, 0)) for reason in ForwardReason),
            )
        )
    return ShadowSection(
        len(rows),
        len(moments),
        moments[0] if moments else None,
        moments[-1] if moments else None,
        tuple(
            (pair, tuple((state, pairs[pair].get(state, 0)) for state in states))
            for pair in sorted(pairs)
        ),
        _counts(row.reason for row in rows if row.state == NO_FILTER),
        tuple(buys),
    )


def measure_forward(
    inputs: ForwardInputs,
    report_at: datetime,
    prices: Mapping[str, CoinPrices],
    costs: Costs,
) -> ForwardMeasured:
    """Bütün ölçüm, tablolar ve hüküm; `prices` en az `price_coins`'in coinlerini taşır."""
    priced = _Prices(prices, costs)
    results: list[ForwardResult] = []
    for sample in forward_samples(inputs, report_at):
        found = priced.measure(sample.coin, sample.scored_at, report_at)
        results.append(
            ForwardResult(
                sample,
                found.reason,
                found.entry_time,
                found.entry_price,
                found.up,
                found.down,
                found.base_up,
                found.base_down,
                found.unusual,
            )
        )
    current = current_triple(inputs, report_at)
    spans = triple_spans(inputs, report_at)
    overlapping: list[bool | None] = [None] * len(results)

    def triple_table(triple: Triple, title: str, judged: bool) -> ForwardTable:
        positions = [i for i, r in enumerate(results) if r.sample.triple == triple]
        inside = [i for i in positions if results[i].sample.whitelisted]
        table, marked = _table(
            title,
            judged,
            triple,
            spans.get(triple),
            [results[i] for i in inside],
            len(positions) - len(inside),
        )
        for at, index in enumerate(inside):
            overlapping[index] = at in marked
        return table

    table: ForwardTable | None = None
    side: ForwardTable | None = None
    if current is not None:
        table = triple_table(current, VERDICT_TITLE, True)
    old = tuple(
        triple_table(triple, "hüküm dışı (eski üçlü)", False)
        for triple in sorted((t for t in spans if t != current), key=lambda t: (spans[t][0], t))
    )
    if current is not None:
        positions = [
            i
            for i, r in enumerate(results)
            if r.sample.triple == current and r.reason is not ForwardReason.NO_PAIR
        ]
        side, marked = _table(
            "hüküm dışı (yardımcı tablo: güncel üçlü, USDT spot çifti olan bütün coinler)",
            False,
            current,
            spans.get(current),
            [results[i] for i in positions],
            sum(not results[i].sample.whitelisted for i in positions),
        )
        for at, index in enumerate(positions):
            if not results[index].sample.whitelisted:
                overlapping[index] = at in marked
    first = None if current is None else spans[current][0]
    verdict = decide(
        first,
        report_at,
        0 if table is None else table.rates.count,
        None if table is None else table.rates.difference,
    )
    return ForwardMeasured(
        report_at,
        costs,
        inputs.results is not None,
        current,
        first,
        tuple(results),
        tuple(overlapping),
        verdict,
        table,
        old,
        side,
        _shadow(inputs, report_at, priced),
        unpermitted_counts(inputs, report_at),
    )
