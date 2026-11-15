"""Kalibrasyon raporu metni (spec 0045 R-3…R-9, AC-9; plan Risk 12). Saf.

Rapor deterministiktir: sıra indikatör (R-1 sırası), aralık, dönem, çift, yöndür; oranlar yüzde, iki
ondalık. Değişen tek satır üretim anı satırıdır. 1. aşamada ayar setinin parmak izi o satırdadır,
çünkü ayar seti dosyası üretim anını taşır (Risk 3: onay anı onunla karşılaştırılır); son raporda
onaylanmış parmak izi kendi satırındadır.

Bölümler: başlık (dönemler, maliyet, sızıntı notu, veri dosyaları), veri boşlukları, olağandışı mum
sayıları, taban oranlar, "al" sinyalleri (indikatör x aralık: varsayılan ve ayarlı ayar, dönem ve
çift başına sayımlar, birleşik sonuçlar, son raporda hüküm), 1. aşamada ayarlama ızgarası, "sat"
sinyalleri (R-9), son raporda hüküm özeti.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from crytobot.calibration._outcome import EMPTY, Costs, Count, Direction, Tally
from crytobot.calibration._signals import INDICATORS, IndicatorSpec, Setting, setting_label
from crytobot.calibration._tuning import (
    INTERVALS,
    MIN_SIGNALS,
    Choice,
    Measured,
    Measurement,
    Verdict,
    percent,
)

GENERATED_PREFIX = "üretim anı: "
LEAK_NOTE = (
    "not: görülmemiş dönem 0044'te yalnız S0…S3'ün hükümleriyle görüldü (küçük sızıntı); "
    "2025-01-01 → 2025-07-01 bilerek kullanılmaz (0044'ün dönem bölünmesi)"
)


@dataclass(frozen=True, slots=True)
class DataFacts:
    interval: str
    path: str
    sha256: str
    downloaded_at: datetime


@dataclass(frozen=True, slots=True)
class GapRow:
    interval: str
    period: str
    pair: str
    first: datetime
    last: datetime
    count: int


@dataclass(frozen=True, slots=True)
class ReportFacts:
    """Raporun ölçüm dışı girdileri. `final`: son ölçüm mü. 1. aşamada `settings_sha256` yazılan
    ayar setinin, son ölçümde onaylanan ayar setinin parmak izidir."""

    final: bool
    generated_at: datetime
    costs: Costs
    data: tuple[DataFacts, ...]
    gaps: tuple[GapRow, ...]
    settings_sha256: str
    approved_by: str | None = None
    approved_at: datetime | None = None


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _rate(count: Count) -> str:
    rate = count.rate
    return "-" if rate is None else percent(rate)


def _tally(tally: Tally) -> str:
    return (
        f"sinyal={tally.all.signals} isabet={_rate(tally.all)} | olağandışısız "
        f"sinyal={tally.clean.signals} isabet={_rate(tally.clean)} | boşluklu={tally.gapped}"
    )


def _versus(tally: Tally, base: Tally) -> str:
    return (
        f"sinyal={tally.all.signals} isabet={_rate(tally.all)} taban={_rate(base.all)} | "
        f"olağandışısız sinyal={tally.clean.signals} isabet={_rate(tally.clean)} "
        f"taban={_rate(base.clean)} | boşluklu={tally.gapped}"
    )


def _sum(rows: Iterable[Tally]) -> Tally:
    total = EMPTY
    for row in rows:
        total = total + row
    return total


class _Index:
    def __init__(self, measured: Measured) -> None:
        self.measured = measured
        self.rows: dict[tuple[str, str, Setting, str, str, Direction], Measurement] = {
            (m.interval, m.indicator, m.setting, m.period, m.pair, m.direction): m
            for m in measured.measurements
        }
        self.bases = {(b.interval, b.period, b.pair, b.direction): b.tally for b in measured.bases}
        self.choices = {(c.indicator, c.interval): c for c in measured.choices}
        self.verdicts: Mapping[tuple[str, str], Verdict] = {
            (name, interval): item for name, interval, item in measured.verdicts
        }

    def tally(
        self, interval: str, name: str, setting: Setting, period: str, pair: str, d: Direction
    ) -> Tally | None:
        row = self.rows.get((interval, name, setting, period, pair, d))
        return None if row is None else row.tally

    def base(self, interval: str, period: str, pair: str, d: Direction) -> Tally:
        return self.bases[(interval, period, pair, d)]


def _header(facts: ReportFacts, measured: Measured) -> list[str]:
    title = "son ölçüm (üç dönem, hüküm)" if facts.final else "1. aşama (ayarlama ve çapraz sınama)"
    lines = [f"CrytoBot kalibrasyon raporu — {title}"]
    generated = f"{GENERATED_PREFIX}{_iso(facts.generated_at)}"
    if not facts.final:
        generated += f" (ayar seti parmak izi: {facts.settings_sha256})"
    lines.append(generated)
    if facts.final:
        lines.append(f"ayar seti parmak izi: {facts.settings_sha256}")
        lines.append(
            f"ayar seti onayı: {facts.approved_by or '-'}, "
            f"{_iso(facts.approved_at) if facts.approved_at else '-'}"
        )
    costs = facts.costs
    lines.append(
        f"maliyet: ücret={format(costs.fee, 'f')} slippage={format(costs.slippage, 'f')} "
        f"spread={format(costs.spread, 'f')}"
    )
    lines.append(
        "isabet: 24 mum içinde hedef = giriş + max(2xATR, maliyet mesafesi), "
        "stop = giriş - 1xATR (sat: ters yön); ATR(14) sinyal mumunda; giriş sonraki mumun açılışı"
    )
    for period in measured.periods:
        lines.append(
            f"dönem {period.name}: {_iso(period.start)} → {_iso(period.end)} "
            f"(bitiş hariç), çiftler {', '.join(period.pairs)}"
        )
    lines.append(LEAK_NOTE)
    lines.append(
        f"seçim: en az {MIN_SIGNALS} sinyalli ayarlar arasında en yüksek isabet "
        "(eşitlikte ızgaradaki ilk)"
    )
    lines.append("")
    lines.append("## veri dosyaları")
    for item in facts.data:
        lines.append(
            f"{item.interval}: {item.path} sha256={item.sha256} indirme={_iso(item.downloaded_at)}"
        )
    return lines


def _gaps(facts: ReportFacts) -> list[str]:
    lines = ["", "## veri boşlukları (doldurulmaz)"]
    if not facts.gaps:
        lines.append("yok")
    for gap in facts.gaps:
        lines.append(
            f"{gap.interval} {gap.pair} {gap.period}: {_iso(gap.first)} → {_iso(gap.last)} "
            f"({gap.count} mum)"
        )
    return lines


def _unusual(measured: Measured) -> list[str]:
    lines = ["", "## olağandışı mumlar (ölçümden çıkarılmaz)"]
    for row in measured.unusual:
        rules = " ".join(f"{rule}={count}" for rule, count in row.by_rule)
        lines.append(f"{row.interval} {row.pair} {row.period}: {row.total} ({rules})")
    return lines


def _bases(index: _Index) -> list[str]:
    lines = ["", "## taban oran (her mum sinyal sayılarak)"]
    for base in index.measured.bases:
        lines.append(
            f"{base.interval} {base.pair} {base.period} {base.direction.value}: "
            f"mum={base.tally.all.signals} isabet={_rate(base.tally.all)} | olağandışısız "
            f"mum={base.tally.clean.signals} isabet={_rate(base.tally.clean)}"
        )
    return lines


def _choice_line(spec: IndicatorSpec, choice: Choice) -> str:
    if choice.setting is None:
        return f"ayarlı: yok ({choice.reason})"
    near, cross = choice.neighbours, choice.cross
    marks = [
        "dayanıksız" if choice.fragile else "dayanıklı",
        f"komşu {near.passing}/{near.total} taban oranı geçiyor" if near else "",
        "çapraz sınamada geçmedi" if choice.cross_failed else "çapraz sınamada geçti",
        f"{cross.passing}/{cross.total} çift" if cross else "",
    ]
    same = " (varsayılanla aynı)" if choice.setting == spec.default else ""
    return f"ayarlı: {setting_label(spec, choice.setting)}{same} — " + ", ".join(
        mark for mark in marks if mark
    )


def _settings(spec: IndicatorSpec, choice: Choice) -> list[tuple[str, Setting]]:
    found = [("varsayılan", spec.default)]
    if choice.setting is not None:
        found.append(("ayarlı", choice.setting))
    return found


def _block(index: _Index, spec: IndicatorSpec, interval: str, direction: Direction) -> list[str]:
    choice = index.choices[(spec.name, interval)]
    lines = ["", f"### {spec.name} {interval} ({direction.value})"]
    lines.append(f"varsayılan: {setting_label(spec, spec.default)}")
    lines.append(_choice_line(spec, choice))
    for role, setting in _settings(spec, choice):
        for period in index.measured.periods:
            rows: list[tuple[str, Tally, Tally]] = []
            for pair in period.pairs:
                tally = index.tally(interval, spec.name, setting, period.name, pair, direction)
                if tally is not None:
                    rows.append((pair, tally, index.base(interval, period.name, pair, direction)))
            if not rows:
                continue
            if len(rows) > 1:
                total, base = _sum(r[1] for r in rows), _sum(r[2] for r in rows)
                lines.append(f"{role} {period.name} birleşik: {_versus(total, base)}")
            for pair, tally, base in rows:
                lines.append(f"{role} {period.name} {pair}: {_versus(tally, base)}")
    if direction is Direction.BUY and index.measured.verdicts:
        item = index.verdicts[(spec.name, interval)]
        lines.append("hüküm: kullanılabilir" if item.usable else "hüküm: kullanılamaz")
        lines.extend(item.failures)
    return lines


def _grid(index: _Index) -> list[str]:
    lines = ["", "## ayarlama ızgarası (BTC/USDT, ayarlama dönemi, al)"]
    for spec in INDICATORS:
        for interval in INTERVALS:
            rows = [
                m
                for m in index.measured.measurements
                if m.indicator == spec.name
                and m.interval == interval
                and m.period == "ayarlama"
                and m.direction is Direction.BUY
            ]
            if not rows:
                continue
            lines.append(f"### {spec.name} {interval}")
            for row in rows:
                lines.append(f"{setting_label(spec, row.setting)}: {_tally(row.tally)}")
    return lines


def _summary(index: _Index) -> list[str]:
    lines = ["", "## hüküm özeti (görülmemiş dönem, beş çift birleşik)"]
    for spec in INDICATORS:
        for interval in INTERVALS:
            item = index.verdicts.get((spec.name, interval))
            if item is None:
                continue
            word = "kullanılabilir" if item.usable else "kullanılamaz"
            first = f" — {item.failures[0]}" if item.failures else ""
            more = f" (+{len(item.failures) - 1} koşul)" if len(item.failures) > 1 else ""
            lines.append(f"{spec.name} {interval}: {word}{first}{more}")
    return lines


def _intervals(measured: Measured) -> list[str]:
    seen = {choice.interval for choice in measured.choices}
    return [interval for interval in INTERVALS if interval in seen]


def report_text(measured: Measured, facts: ReportFacts) -> str:
    index = _Index(measured)
    lines = _header(facts, measured)
    lines += _gaps(facts)
    lines += _unusual(measured)
    lines += _bases(index)
    intervals = _intervals(measured)
    lines += ["", "## al sinyalleri"]
    for spec in INDICATORS:
        for interval in intervals:
            lines += _block(index, spec, interval, Direction.BUY)
    if not facts.final:
        lines += _grid(index)
    lines += ["", "## çıkış sinyalleri (sat; seçimi ve hükmü etkilemez)"]
    for spec in INDICATORS:
        for interval in intervals:
            lines += _block(index, spec, interval, Direction.SELL)
    if facts.final:
        lines += _summary(index)
    return "\n".join(lines) + "\n"
