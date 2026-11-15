"""Ayarlama, çapraz sınama, hüküm ve iki aşamanın ölçümü (spec 0045 R-2…R-9; Risk 3, 9, 10).

Sabitler spec'tendir ve sonuca göre değişmez: çiftler, aralıklar, üç dönem, eşikler.

Kurallar (Risk 9):

- **Seçim (R-4):** ayarlama döneminde BTC'de en az 30 "al" sinyali veren ayarlar arasından isabet
  oranı en yüksek olan; eşitlikte ızgaradaki ilk ayar. Hiçbir ayar 30'a ulaşmazsa ayar yoktur.
- **Dayanıklılık (R-4):** seçilen ayarın komşularından taban oranı (kesin büyük) geçenler sayılır;
  `2·geçen < komşu sayısı` ise "dayanıksız" (tam yarısı dayanıksız değildir). 0 sinyalli komşu
  geçmez.
- **Çapraz sınama (R-5):** seçilen ayar dört çiftin her birinde kendi taban oranıyla; üçten azında
  geçerse "çapraz sınamada geçmedi". 0 sinyalli çift geçmez.
- **Hüküm (R-7):** ayar seçilmiş, dayanıksız ve "çapraz sınamada geçmedi" değil; görülmemiş dönemde
  beş çiftin birleşik sinyalleri ≥ 30; birleşik isabet - birleşik taban ≥ 5 puan; olağandışısız
  kümede isabet ≥ o kümenin taban oranı (olağandışısız sinyal yoksa koşul tutmaz). Tutmayan her
  koşul değeri ve eşiğiyle yazılır.

Ayarlama ve çapraz sınama bütün sinyallerle yapılır. "Sat" sinyalleri (R-9) yalnız varsayılan ve
seçilen ayarda ölçülür, seçimi ve hükmü etkilemez (Risk 10).

Ölçüm: indikatörler dosyanın ilk mumundan başlayarak, ölçülen son dönemin bitişinden önce açılan
mumlarla hesaplanır (göstergeler yalnız geçmişe bakar; ayarlama ve son ölçüm aynı değerleri
görür). İsabet dizisi çift x aralık başına bir kez hesaplanır.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from typing import Final

from crytobot.calibration._outcome import (
    EMPTY,
    Costs,
    Count,
    Direction,
    Outcomes,
    PairSeries,
    Period,
    Tally,
    counted_positions,
    outcomes,
    tally,
)
from crytobot.calibration._signals import (
    INDICATORS,
    IndicatorSpec,
    Setting,
    Signals,
    grid,
    neighbours,
    signals,
)
from crytobot.calibration._unusual import Flags, unusual_flags

BTC: Final = "BTC/USDT"
CROSS_PAIRS: Final = ("ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT")
PAIRS: Final = (BTC, *CROSS_PAIRS)
INTERVALS: Final = ("15m", "30m", "1h", "4h", "1d")
DATA_START: Final = datetime(2023, 1, 1, tzinfo=UTC)
TUNING: Final = Period(
    "ayarlama", datetime(2024, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC), (BTC,)
)
CROSS: Final = Period("çapraz sınama", TUNING.start, TUNING.end, CROSS_PAIRS)
UNSEEN: Final = Period(
    "görülmemiş", datetime(2025, 7, 1, tzinfo=UTC), datetime(2026, 11, 12, tzinfo=UTC), PAIRS
)
PERIODS: Final = (TUNING, CROSS, UNSEEN)  # the spec's periods; tests pass shorter ones
Periods = tuple[Period, Period, Period]  # tuning, cross test, unseen
MIN_SIGNALS: Final = 30
MARGIN: Final = Fraction(5, 100)
CROSS_NEEDED: Final = 3

Progress = Callable[[str], None]


# --- rules -------------------------------------------------------------------------------------
def beats(count: Count, base: Count) -> bool:
    """İsabet oranı taban oranı kesin geçer; sinyal yoksa geçmez."""
    rate, floor = count.rate, base.rate
    return rate is not None and floor is not None and rate > floor


@dataclass(frozen=True, slots=True)
class Selection:
    setting: Setting | None
    reason: str | None


def select(spec: IndicatorSpec, counts: Mapping[Setting, Count]) -> Selection:
    """R-4: en az 30 sinyalli ayarlar arasında en yüksek isabet; eşitlikte ızgaradaki ilk ayar."""
    best: Setting | None = None
    best_rate: Fraction | None = None
    for setting in grid(spec):
        count = counts[setting]
        rate = count.rate
        if count.signals < MIN_SIGNALS or rate is None:
            continue
        if best_rate is None or rate > best_rate:
            best, best_rate = setting, rate
    if best is None:
        most = max((counts[setting].signals for setting in grid(spec)), default=0)
        return Selection(
            None, f"ayar yok: hiçbir ayar {MIN_SIGNALS} sinyale ulaşmadı (en çok {most})"
        )
    return Selection(best, None)


@dataclass(frozen=True, slots=True)
class Robustness:
    passing: int
    total: int

    @property
    def fragile(self) -> bool:
        return 2 * self.passing < self.total


def robustness(
    spec: IndicatorSpec, setting: Setting, counts: Mapping[Setting, Count], base: Count
) -> Robustness:
    near = neighbours(spec, setting)
    return Robustness(sum(beats(counts[other], base) for other in near), len(near))


@dataclass(frozen=True, slots=True)
class CrossTest:
    passing: int
    total: int

    @property
    def failed(self) -> bool:
        return self.passing < CROSS_NEEDED


def cross_test(results: Sequence[tuple[Count, Count]]) -> CrossTest:
    """R-5: (sinyaller, taban) çift başına; üçten azında geçerse "geçmedi"."""
    return CrossTest(sum(beats(count, base) for count, base in results), len(results))


@dataclass(frozen=True, slots=True)
class Choice:
    """Bir indikatör x aralığın ayar seti satırı."""

    indicator: str
    interval: str
    setting: Setting | None
    reason: str | None
    fragile: bool
    cross_failed: bool
    neighbours: Robustness | None = None
    cross: CrossTest | None = None


@dataclass(frozen=True, slots=True)
class Verdict:
    usable: bool
    failures: tuple[str, ...]


def percent(rate: Fraction) -> str:
    return f"{float(rate * 100):.2f}%"


def points(value: Fraction) -> str:
    return f"{float(value * 100):+.2f}"


def verdict(choice: Choice, combined: Tally, base: Tally) -> Verdict:
    """R-7: koşulların hepsi tutarsa "kullanılabilir"; tutmayan her koşul değeriyle ve eşiğiyle."""
    if choice.setting is None:
        return Verdict(False, (f"geçmedi: ayar seçilmedi ({choice.reason})",))
    failures: list[str] = []
    if choice.fragile:
        near = choice.neighbours
        detail = f" (taban oranı geçen komşu {near.passing}/{near.total} < yarısı)" if near else ""
        failures.append(f"geçmedi: ayar dayanıksız{detail}")
    if choice.cross_failed:
        cross = choice.cross
        detail = f" ({cross.passing}/{cross.total} çift < {CROSS_NEEDED})" if cross else ""
        failures.append(f"geçmedi: çapraz sınamada geçmedi{detail}")
    if combined.all.signals < MIN_SIGNALS:
        failures.append(
            f"geçmedi: sinyal sayısı {MIN_SIGNALS}'dan az ({combined.all.signals} < {MIN_SIGNALS})"
        )
    rate, floor = combined.all.rate, base.all.rate
    if rate is None or floor is None:
        failures.append("geçmedi: isabet taban oranı 5 puan geçmiyor (sinyal yok)")
    elif rate - floor < MARGIN:
        failures.append(
            f"geçmedi: isabet taban oranı 5 puan geçmiyor ({points(rate - floor)} < +5)"
        )
    clean, clean_floor = combined.clean.rate, base.clean.rate
    if clean is None or clean_floor is None:
        failures.append(
            "geçmedi: olağandışısız isabet taban oranın altında (olağandışısız sinyal yok)"
        )
    elif clean < clean_floor:
        failures.append(
            "geçmedi: olağandışısız isabet taban oranın altında "
            f"({percent(clean)} < {percent(clean_floor)})"
        )
    return Verdict(not failures, tuple(failures))


# --- measurement -------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Measurement:
    """Bir ayarın bir çift x dönem x yöndeki sayımı ve sayılan sinyal konumları."""

    interval: str
    indicator: str
    setting: Setting
    period: str
    pair: str
    direction: Direction
    tally: Tally
    positions: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Base:
    """Taban oran: dönemin her mumu sinyal sayılarak."""

    interval: str
    period: str
    pair: str
    direction: Direction
    tally: Tally


@dataclass(frozen=True, slots=True)
class UnusualCount:
    interval: str
    period: str
    pair: str
    total: int
    by_rule: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class IntervalData:
    """Bir aralığın beş çifti (`PAIRS` sırasıyla)."""

    interval: str
    series: Mapping[str, PairSeries]


@dataclass(frozen=True)
class Measured:
    """Bir aşamanın bütün ölçümleri; kayıt dosyası için çift x aralık sonuçları ve işaretler."""

    periods: tuple[Period, ...]
    choices: tuple[Choice, ...]
    measurements: tuple[Measurement, ...]
    bases: tuple[Base, ...]
    unusual: tuple[UnusualCount, ...]
    outcomes: Mapping[tuple[str, str], Outcomes]
    flags: Mapping[tuple[str, str], Flags]
    verdicts: tuple[tuple[str, str, Verdict], ...] = ()


class _Interval:
    """Bir aralığın isabet dizileri, işaretleri, taban oranları ve sinyal önbelleği."""

    def __init__(self, data: IntervalData, costs: Costs, periods: Sequence[Period]) -> None:
        self.interval = data.interval
        self.series = data.series
        candles = {pair: data.series[pair].candles for pair in PAIRS}
        volumes = {pair: data.series[pair].volumes for pair in PAIRS}
        self.flags = unusual_flags(candles, volumes)
        self.results = {
            pair: outcomes(data.series[pair], costs, self.flags[pair]) for pair in PAIRS
        }
        last_end = max(period.end for period in periods)
        self.prefix = {
            pair: tuple(c for c in data.series[pair].candles if c.open_time < last_end)
            for pair in PAIRS
        }
        self.signals: dict[tuple[str, Setting, str], Signals] = {}
        self.bases: dict[tuple[str, str, Direction], Tally] = {}
        for period in periods:
            for pair in period.pairs:
                for direction in Direction:
                    self.bases[(period.name, pair, direction)] = tally(
                        self.results[pair], period, direction
                    )

    def measure(
        self,
        spec: IndicatorSpec,
        setting: Setting,
        period: Period,
        pair: str,
        directions: Sequence[Direction],
    ) -> list[Measurement]:
        key = (spec.name, setting, pair)
        found = self.signals.get(key)
        if found is None:  # one computation per setting and pair, whatever the period
            found = self.signals[key] = signals(spec, setting, self.prefix[pair])
        measured: list[Measurement] = []
        for direction in directions:
            positions = found.buy if direction is Direction.BUY else found.sell
            results = self.results[pair]
            counted = counted_positions(results, period, positions)
            measured.append(
                Measurement(
                    self.interval,
                    spec.name,
                    setting,
                    period.name,
                    pair,
                    direction,
                    tally(results, period, direction, counted),
                    counted,
                )
            )
        return measured

    def unusual(self, periods: Sequence[Period]) -> list[UnusualCount]:
        counts: list[UnusualCount] = []
        for period in periods:
            for pair in period.pairs:
                span = self.results[pair].span(period)
                letters = [self.flags[pair][index] for index in span if self.flags[pair][index]]
                by_rule = tuple((rule, sum(rule in item for item in letters)) for rule in "abcd")
                counts.append(UnusualCount(self.interval, period.name, pair, len(letters), by_rule))
        return counts

    def base_rows(self, periods: Sequence[Period]) -> list[Base]:
        return [
            Base(
                self.interval,
                period.name,
                pair,
                direction,
                self.bases[(period.name, pair, direction)],
            )
            for period in periods
            for pair in period.pairs
            for direction in Direction
        ]


def _measured_settings(spec: IndicatorSpec, choice: Choice) -> tuple[Setting, ...]:
    if choice.setting is None or choice.setting == spec.default:
        return (spec.default,)
    return (spec.default, choice.setting)


def _choose(
    spec: IndicatorSpec, block: _Interval, tuning: Period, measurements: list[Measurement]
) -> Choice:
    """R-4, R-5: BTC'de ızgara, seçim, dayanıklılık; diğer dört çiftte çapraz sınama."""
    grid_rows = [
        block.measure(spec, setting, tuning, BTC, (Direction.BUY,))[0] for setting in grid(spec)
    ]
    measurements.extend(grid_rows)
    counts = {row.setting: row.tally.all for row in grid_rows}
    base = block.bases[(tuning.name, BTC, Direction.BUY)].all
    chosen = select(spec, counts)
    if chosen.setting is None:
        return Choice(spec.name, block.interval, None, chosen.reason, False, False)
    near = robustness(spec, chosen.setting, counts, base)
    return Choice(
        spec.name, block.interval, chosen.setting, None, near.fragile, False, neighbours=near
    )


def _stage_one_interval(
    block: _Interval,
    tuning: Period,
    cross: Period,
    measurements: list[Measurement],
    choices: list[Choice],
) -> None:
    for spec in INDICATORS:
        choice = _choose(spec, block, tuning, measurements)
        cross_rows: dict[Setting, list[Measurement]] = {}
        for setting in _measured_settings(spec, choice):
            sells = block.measure(spec, setting, tuning, BTC, (Direction.SELL,))
            measurements.extend(sells)
            rows: list[Measurement] = []
            for pair in cross.pairs:
                rows.extend(block.measure(spec, setting, cross, pair, tuple(Direction)))
            measurements.extend(rows)
            cross_rows[setting] = rows
        if choice.setting is not None:
            buys = [row for row in cross_rows[choice.setting] if row.direction is Direction.BUY]
            result = cross_test(
                [
                    (row.tally.all, block.bases[(cross.name, row.pair, Direction.BUY)].all)
                    for row in buys
                ]
            )
            choice = Choice(
                choice.indicator,
                choice.interval,
                choice.setting,
                None,
                choice.fragile,
                result.failed,
                neighbours=choice.neighbours,
                cross=result,
            )
        choices.append(choice)


def stage_one(
    data: Sequence[IntervalData],
    costs: Costs,
    progress: Progress = lambda _: None,
    *,
    periods_of: Periods = PERIODS,
) -> Measured:
    """1. aşama: varsayılan ölçüm, ayarlama (BTC) ve çapraz sınama; görülmemiş dönem ölçülmez."""
    tuning, cross, _ = periods_of
    periods = (tuning, cross)
    measurements: list[Measurement] = []
    choices: list[Choice] = []
    bases: list[Base] = []
    unusual: list[UnusualCount] = []
    results: dict[tuple[str, str], Outcomes] = {}
    flags: dict[tuple[str, str], Flags] = {}
    for item in data:
        progress(f"aralık {item.interval}")
        block = _Interval(item, costs, periods)
        _stage_one_interval(block, tuning, cross, measurements, choices)
        bases.extend(block.base_rows(periods))
        unusual.extend(block.unusual(periods))
        for pair in PAIRS:
            results[(item.interval, pair)] = block.results[pair]
            flags[(item.interval, pair)] = block.flags[pair]
    return Measured(
        periods, tuple(choices), tuple(measurements), tuple(bases), tuple(unusual), results, flags
    )


def _combined(rows: Sequence[Tally]) -> Tally:
    total = EMPTY
    for row in rows:
        total = total + row
    return total


def final_stage(
    data: Sequence[IntervalData],
    costs: Costs,
    choices: Sequence[Choice],
    progress: Progress = lambda _: None,
    *,
    periods_of: Periods = PERIODS,
) -> Measured:
    """2. aşama: ayar setiyle üç dönem; yeniden ayarlanmaz. Hüküm görülmemiş dönemden (R-7)."""
    periods = periods_of
    unseen = periods[2]
    by_key = {(choice.indicator, choice.interval): choice for choice in choices}
    measurements: list[Measurement] = []
    bases: list[Base] = []
    unusual: list[UnusualCount] = []
    verdicts: list[tuple[str, str, Verdict]] = []
    results: dict[tuple[str, str], Outcomes] = {}
    flags: dict[tuple[str, str], Flags] = {}
    ordered: list[Choice] = []
    for item in data:
        progress(f"aralık {item.interval}")
        block = _Interval(item, costs, periods)
        for spec in INDICATORS:
            choice = by_key[(spec.name, item.interval)]
            ordered.append(choice)
            for setting in _measured_settings(spec, choice):
                for period in periods:
                    for pair in period.pairs:
                        measurements.extend(
                            block.measure(spec, setting, period, pair, tuple(Direction))
                        )
            combined = EMPTY
            if choice.setting is not None:
                combined = _combined(
                    [
                        row.tally
                        for row in measurements
                        if row.interval == item.interval
                        and row.indicator == spec.name
                        and row.setting == choice.setting
                        and row.period == unseen.name
                        and row.direction is Direction.BUY
                    ]
                )
            base = _combined(
                [block.bases[(unseen.name, pair, Direction.BUY)] for pair in unseen.pairs]
            )
            verdicts.append((spec.name, item.interval, verdict(choice, combined, base)))
        bases.extend(block.base_rows(periods))
        unusual.extend(block.unusual(periods))
        for pair in PAIRS:
            results[(item.interval, pair)] = block.results[pair]
            flags[(item.interval, pair)] = block.flags[pair]
    return Measured(
        periods,
        tuple(ordered),
        tuple(measurements),
        tuple(bases),
        tuple(unusual),
        results,
        flags,
        tuple(verdicts),
    )
