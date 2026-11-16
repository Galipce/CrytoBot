"""Örnek kütüphanesinin raporu ve kütüphane dosyası metni (spec 0048 R-6…R-9; plan Risk 9, 11). Saf.

Rapor deterministiktir; değişen tek satır `GENERATED_PREFIX` ile başlar: üretim anı ve girdilerin
(kaynak kayıtlar, fiyat verisi) okunduğu anlar oradadır (plan Risk 9). Fiyat verisinin indirme anı
depodan gelir, değişmez. Tablo betimleyicidir: satırlarda karar sözcüğü yoktur. Başlıklar JSON
dizgisi olarak tırnaklı yazılır (denetim karakterleri kaçışlı; plan Risk 11).

Kütüphane dosyası JSON Lines'tır (UTF-8, `ensure_ascii=False`): 1. satır biçim, sürüm, kural seti
parmak izi, model kesim tarihi ve maliyetler; sonra örnek sırasıyla her örnek (R-7). Zaman satırı
yoktur, bütünüyle bayt bayt aynı üretilir. Başlık olduğu gibi yazılır; JSON çözülünce aynıdır.
"""

import json
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from typing import Final

from crytobot.calibration._events import (
    BASE_CANDLES,
    LATEST_ENTRY,
    MIN_MEASURED,
    NEUTRAL,
    PERIODS,
    EventAnnouncement,
    EventMeasured,
    Move,
    SampleResult,
    TableRow,
    reason_counts,
    table_rows,
)
from crytobot.calibration._outcome import ATR_PERIOD, STOP_ATR, TARGET_ATR, WINDOW
from crytobot.calibration._report import GENERATED_PREFIX
from crytobot.calibration._tuning import percent, points

LIBRARY_FORMAT: Final = "crytobot-event-library"
LIBRARY_VERSION: Final = 1
AUDIT_TITLES: Final = 20
AUDIT_PATTERNS: Final = 20
OTHER: Final = "diğer"
FEW: Final = "yetersiz örnek"


@dataclass(frozen=True)
class EventReportFacts:
    """Raporun ölçüm dışı girdileri. `forward_*`: ileriye dönük kayıt yoksa `None`."""

    generated_at: datetime
    sources_read_at: datetime
    prices_read_at: datetime
    archive_path: str
    archive_records: int
    forward_path: str
    forward_records: int | None
    price_path: str
    exchange_info_at: datetime | None
    downloaded_first: datetime | None
    downloaded_last: datetime | None
    download_seconds: float
    rules_fingerprint: str
    library_fingerprint: str


def _iso(moment: datetime | None) -> str:
    return "-" if moment is None else moment.astimezone(UTC).isoformat()


def _rate(value: Fraction | None) -> str:
    return "-" if value is None else percent(value)


def _difference(value: Fraction | None) -> str:
    return "-" if value is None else points(value)


def _row(row: TableRow) -> str:
    flag = f" [{FEW}]" if row.few else ""
    return (
        f"  {row.period}: duyuru={row.announcements} örnek={row.samples} "
        f"ölçülen={row.measured} çakışan={row.overlapping} isabet={_rate(row.hit)} "
        f"taban={_rate(row.base)} fark={_difference(row.difference)}{flag}"
    )


def _rows_section(title: str, rows: Sequence[TableRow]) -> list[str]:
    lines = ["", f"## {title}"]
    if not rows:
        return [*lines, "  (satır yok)"]
    for start in range(0, len(rows), len(PERIODS)):
        group = rows[start : start + len(PERIODS)]
        lines.append(f"{group[0].event_type} — {group[0].move.value}")
        lines.extend(_row(row) for row in group)
    return lines


def _header(measured: EventMeasured, facts: EventReportFacts) -> list[str]:
    costs = measured.costs
    forward = (
        f"ileriye dönük kayıt: {facts.forward_path} binance-duyuru kaydı={facts.forward_records}"
        if facts.forward_records is not None
        else f"ileriye dönük kayıt yok: {facts.forward_path} (yalnız arşivle)"
    )
    return [
        "# Geçmiş olay örnekleri — kalibrasyon tablosu (spec 0048)",
        f"{GENERATED_PREFIX}{_iso(facts.generated_at)} | okunma anları: kaynak kayıtlar "
        f"{_iso(facts.sources_read_at)}, fiyat verisi {_iso(facts.prices_read_at)}",
        f"arşiv: {facts.archive_path} kayıt={facts.archive_records}",
        forward,
        f"fiyat verisi: {facts.price_path} borsa bilgisi={_iso(facts.exchange_info_at)} "
        f"indirme: ilk={_iso(facts.downloaded_first)} son={_iso(facts.downloaded_last)} "
        f"toplam süre={facts.download_seconds:.1f} s",
        f"kural seti parmak izi: {facts.rules_fingerprint}",
        f"kütüphane dosyası parmak izi: {facts.library_fingerprint}",
        f"model kesim anı: {_iso(measured.cutoff)} (bu andan önceki olaylar modelin eğitim "
        'verisinde sonucuyla birlikte bulunabilir; tam kesim anı "sonra" dönemindedir)',
        f"maliyet: ücret={costs.fee} slippage={costs.slippage} spread={costs.spread} → "
        f"hedef mesafesinin alt sınırı giriş fiyatının {costs.factor() * 100:.4f}%'i",
        f"kural: giriş = açılışı referans andan kesin sonra olan ilk 1h mum (en geç "
        f"{int(LATEST_ENTRY.total_seconds() // 3600)} saat sonra); hedef max({TARGET_ATR}xATR, "
        f"maliyet), stop {STOP_ATR}xATR, ATR({ATR_PERIOD}) giriş mumundan önceki mumda; en çok "
        f"{WINDOW} mum; aynı mumda iki sınır ya da süre dolması isabet değildir",
        f"taban oran: referans andan önceki {BASE_CANDLES} mumun her kapanışı, aynı kural ve yön; "
        f'ölçülen örneği {MIN_MEASURED}\'dan az satır "{FEW}" işaretlidir',
        "not: tablo betimleyicidir; hiçbir aşama kapısının, stratejinin ya da filtrenin girdisi "
        "değildir (ADR 0003 ilke 3: değerlendirme ileriye dönük ölçümle yapılır)",
    ]


def _counts(measured: EventMeasured) -> list[str]:
    results = measured.results
    announcements = {r.sample.announcement.article_id for r in results}
    flagged = sum(r.sample.from_first_seen for r in results)
    lines = [
        "",
        "## Sayılar",
        f"duyuru={len(announcements)} örnek={len(results)} "
        f"ölçülen={sum(r.reason is None for r in results)} ilk görme anı kullanılan={flagged}",
        "ölçülemeyen (nedene göre):",
    ]
    lines.extend(f"  {reason.value}: {count}" for reason, count in reason_counts(measured))
    return lines


def _evenly(items: Sequence[EventAnnouncement], count: int) -> list[EventAnnouncement]:
    if len(items) <= count:
        return list(items)
    return [items[index * len(items) // count] for index in range(count)]


def _audit(measured: EventMeasured) -> list[str]:
    seen: dict[str, EventAnnouncement] = {}
    order: dict[str, int] = {}
    for position, result in enumerate(measured.results):
        item = result.sample.announcement
        if item.article_id not in seen:
            seen[item.article_id] = item
            order[item.article_id] = position
    announcements = sorted(seen.values(), key=lambda a: order[a.article_id])
    lines = ["", "## Etiket denetimi (R-8)"]
    for name, _ in measured.types:
        typed = [a for a in announcements if a.event_type == name]
        lines.append(f"{name}: duyuru={len(typed)}")
        lines.extend(
            f"  {json.dumps(item.title, ensure_ascii=False)}"
            for item in _evenly(typed, AUDIT_TITLES)
        )
    others = [a for a in announcements if a.event_type == OTHER]
    patterns = Counter(item.pattern for item in others)
    lines.append(f'"{OTHER}" türüne düşen duyuru: {len(others)}; en sık {AUDIT_PATTERNS} kalıp:')
    ranked = sorted(patterns.items(), key=lambda pair: (-pair[1], pair[0]))[:AUDIT_PATTERNS]
    lines.extend(f"  {count} x {json.dumps(text, ensure_ascii=False)}" for text, count in ranked)
    return lines


def event_report_text(measured: EventMeasured, facts: EventReportFacts) -> str:
    rows = table_rows(measured)
    neutral = {name for name, direction in measured.types if direction == NEUTRAL}
    main = [row for row in rows if row.main is True]
    other = [row for row in rows if row.main is False]
    both = [row for row in rows if row.event_type in neutral]
    lines = [
        *_header(measured, facts),
        *_counts(measured),
        *_rows_section("Ana sonuç (beklenen yönde)", main),
        *_rows_section("Öteki yön", other),
        *_rows_section("Nötr türler (iki yön, ana sonuç yok)", both),
        *_audit(measured),
    ]
    return "\n".join(lines) + "\n"


def _line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"


def _fraction(value: Fraction | None) -> str | None:
    return None if value is None else f"{value.numerator}/{value.denominator}"


def _sample(result: SampleResult) -> dict[str, object]:
    sample = result.sample
    item = sample.announcement
    return {
        "article_id": item.article_id,
        "origin": item.origin,
        "catalog": item.catalog,
        "title": item.title,
        "published": None if item.published is None else _iso(item.published),
        "first_seen": None if item.first_seen is None else _iso(item.first_seen),
        "reference_from_first_seen": sample.from_first_seen,
        "event_type": item.event_type,
        "direction": item.direction,
        "coin": sample.coin,
        "period": result.period,
        "entry_time": None if result.entry_time is None else _iso(result.entry_time),
        "entry_price": result.entry_price,
        "up_hit": result.hit(Move.UP),
        "down_hit": result.hit(Move.DOWN),
        "base_up": _fraction(result.base(Move.UP)),
        "base_down": _fraction(result.base(Move.DOWN)),
        "overlapping": result.overlapping,
        "reason": None if result.reason is None else result.reason.value,
    }


def _samples(measured: EventMeasured) -> Iterator[str]:
    for result in measured.results:
        yield _line(_sample(result))


def library_text(measured: EventMeasured, rules_fingerprint: str) -> str:
    costs = measured.costs
    header = _line(
        {
            "format": LIBRARY_FORMAT,
            "version": LIBRARY_VERSION,
            "rules_fingerprint": rules_fingerprint,
            "model_cutoff": _iso(measured.cutoff),
            "costs": {
                "fee": str(costs.fee),
                "slippage": str(costs.slippage),
                "spread": str(costs.spread),
            },
        }
    )
    return header + "".join(_samples(measured))
