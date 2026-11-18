"""İleriye dönük ölçüm raporu ve örnek dosyası metni (spec 0053 R-4…R-8; plan Risk 1, 5, 7). Saf.

Rapor deterministiktir; değişen tek satır `GENERATED_PREFIX` ile başlar (üretim anı). Sıra sabittir:
başlık (rapor anı, girdi yolları, maliyet, güncel üçlü, hüküm, sabit kurallar) → hüküm tablosu →
eski üçlüler (`hüküm dışı`) → yardımcı tablo (`hüküm dışı`) → gölge kayıt bölümü. Farklar iki
ondalıklı puandır; hüküm satırındaki değer bir ondalıklı ve aşağı yuvarlanmıştır, karar kesirle.

Örnek dosyası JSON Lines'tır (UTF-8, `ensure_ascii=False`): 1. satır biçim, sürüm, rapor anı,
maliyet, güncel üçlü ve hüküm; sonra örnek sırasıyla R-2'nin bütün alanları. Zaman satırı yoktur,
bütünüyle bayt bayt aynı üretilir.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from typing import Final

from crytobot.calibration._events import BASE_CANDLES, LATEST_ENTRY
from crytobot.calibration._forward import (
    MIN_DAYS,
    MIN_SAMPLES,
    MIN_SEVERITY,
    THRESHOLD,
    ForwardMeasured,
    ForwardReason,
    ForwardResult,
    ForwardTable,
    Rates,
    ShadowSection,
    Triple,
)
from crytobot.calibration._outcome import ATR_PERIOD, STOP_ATR, TARGET_ATR, WINDOW
from crytobot.calibration._report import GENERATED_PREFIX
from crytobot.calibration._tuning import percent, points

SAMPLES_FORMAT: Final = "crytobot-forward-samples"
SAMPLES_VERSION: Final = 1
NO_SHADOW: Final = "gölge kayıt yok"
UNUSUAL_NOTE: Final = (
    "olağandışı kuralı: a, c — b hacim yok, d beş çift yok,"
    " c pencerenin son 3 mumunda sonraki mumları göremez"
)


@dataclass(frozen=True)
class ForwardReportFacts:
    """Raporun ölçüm dışı girdileri. `score_skipped`: skor kaydında atlanan (okunamayan) satır;
    `shadow_path` `None`: bot ayarında `[shadow]` yok; `shadow_broken`: çözülemeyen gölge satırı."""

    generated_at: datetime
    score_path: str
    score_skipped: int
    news_path: str
    shadow_path: str | None
    shadow_broken: int
    price_path: str
    exchange_info_at: datetime | None
    downloaded_last: datetime | None


def _iso(moment: datetime | None) -> str:
    return "-" if moment is None else moment.astimezone(UTC).isoformat()


def _rate(value: Fraction | None) -> str:
    return "-" if value is None else percent(value)


def _difference(value: Fraction | None) -> str:
    return "-" if value is None else f"{points(value)} puan"


def _triple(triple: Triple | None) -> str:
    if triple is None:
        return "yok"
    model, prompt, context = triple
    return f"model={model} prompt={prompt} bağlam={context}"


def _counts(items: Sequence[tuple[str, int]]) -> str:
    return " ".join(f"{name}={count}" for name, count in items) or "-"


def _reasons(items: Sequence[tuple[ForwardReason, int]]) -> str:
    return " ".join(f"{reason.value}={count}" for reason, count in items)


def _rates(label: str, rates: Rates) -> list[str]:
    return [
        f"  {label}: örnek={rates.count}",
        f"    düşüş: isabet={_rate(rates.down_hit)} taban={_rate(rates.down_base)} "
        f"fark={_difference(rates.difference)}",
        f"    yükseliş (bilgi): isabet={_rate(rates.up_hit)} taban={_rate(rates.up_base)} "
        f"fark={_difference(rates.up_difference)}",
    ]


def _table(table: ForwardTable) -> list[str]:
    return [
        f"### {table.title}",
        f"  üçlü: {_triple(table.triple)}",
        f"  ilk skor anı={_iso(table.first_at)} son skor anı={_iso(table.last_at)}",
        f"  örnek={table.samples} sayılan={table.rates.count} örtüşen={table.overlapping} "
        f"beyaz liste dışı={table.outside}",
        *_rates("bütün sayılanlar", table.rates),
        *_rates("olağandışıya denk gelenler çıkarılmış (bilgi)", table.clean),
        f"  ölçülmeyen: {_reasons(table.unmeasured)}",
        f"  kaynak: {_counts(table.by_source)}",
        f"  olay türü: {_counts(table.by_type)}",
        f"  şiddet: {_counts(table.by_severity)}",
        f"  coin: {_counts(table.by_coin)}",
    ]


def _header(measured: ForwardMeasured, facts: ForwardReportFacts) -> list[str]:
    costs = measured.costs
    score = (
        f"skor kaydı: {facts.score_path} atlanan satır={facts.score_skipped}"
        if measured.score_record
        else f"skor kaydı yok: {facts.score_path}"
    )
    if facts.shadow_path is None:
        shadow = f"{NO_SHADOW}: bot ayarında [shadow] yok"
    elif measured.shadow is None:
        shadow = f"{NO_SHADOW}: {facts.shadow_path}"
    else:
        shadow = f"gölge kayıt: {facts.shadow_path} bozuk satır={facts.shadow_broken}"
    return [
        "# İleriye dönük ölçüm raporu — LLM olay skoru, gölge mod (spec 0053)",
        f"{GENERATED_PREFIX}{_iso(facts.generated_at)}",
        f"rapor anı: {_iso(measured.report_at)} "
        "(sonrasındaki skor, gölge satırı ve mum kullanılmaz)",
        score,
        f"haber kaydı: {facts.news_path}",
        shadow,
        f"fiyat verisi: {facts.price_path} borsa bilgisi={_iso(facts.exchange_info_at)} "
        f"son indirme={_iso(facts.downloaded_last)}",
        f"maliyet: ücret={costs.fee} slippage={costs.slippage} spread={costs.spread} → "
        f"hedef mesafesinin alt sınırı giriş fiyatının {costs.factor() * 100:.4f}%'i",
        f"güncel üçlü: {_triple(measured.current)} ilk sonuç={_iso(measured.current_first)}",
        f"hüküm: {measured.verdict.line}",
        f"örnek: olumsuz yön, şiddet ≥ {MIN_SEVERITY}; giriş = açılışı skor anından kesin sonra "
        f"olan ilk 1h mum (en geç {int(LATEST_ENTRY.total_seconds() // 3600)} saat sonra); "
        f"hedef max({TARGET_ATR}xATR, maliyet), stop {STOP_ATR}xATR, ATR({ATR_PERIOD}) giriş "
        f"mumundan önceki mumda; en çok {WINDOW} mum; aynı mumda iki sınır ya da süre dolması "
        "isabet değildir",
        f"taban oran: skor anından önceki {BASE_CANDLES} mumun her kapanışı, aynı kural ve yön; "
        "penceresi skor anını aşan mum sayılmaz",
        f"hüküm kuralı (ön kayıt): güncel üçlünün ilk sonucundan en az {MIN_DAYS} gün ve skor "
        f"anındaki beyaz listede en az {MIN_SAMPLES} ölçülmüş, örtüşmeyen örnek; düşüş isabeti "
        f"taban oranı en az {int(THRESHOLD * 100)} puan geçerse olumlu, geçmezse olumsuz",
        UNUSUAL_NOTE,
        "not: hüküm bilgi verir; emir, mod, beyaz liste ve ayar değişmez — kararı sahip verir",
    ]


def _shadow(section: ShadowSection | None) -> list[str]:
    lines = ["", "## Gölge kayıt (bilgi; hükme şart olarak girmez)"]
    if section is None:
        return [*lines, NO_SHADOW]
    lines += [
        f"satır={section.rows} tur={section.turns} ilk tur={_iso(section.first_at)} "
        f"son tur={_iso(section.last_at)}",
        "filtre durumu (çift başına):",
        *(f"  {pair}: {_counts(states)}" for pair, states in section.pairs),
        f'"filtre yok" nedenleri: {_counts(section.reasons)}',
        'teknik "al" (giriş: tur anından sonraki ilk 1h mum), yükseliş:',
    ]
    for buys in section.buys:
        lines.append(
            f"  {buys.state}: al={buys.buys} ölçülen={buys.measured} "
            f"isabet={_rate(buys.up_hit)} taban={_rate(buys.up_base)} "
            f"ölçülmeyen: {_reasons(buys.unmeasured)}"
        )
    return lines


def forward_report_text(measured: ForwardMeasured, facts: ForwardReportFacts) -> str:
    lines = [*_header(measured, facts), "", "## Hüküm tablosu"]
    lines += ["  (güncel üçlü yok)"] if measured.table is None else _table(measured.table)
    lines += ["", "## Hüküm dışı — eski üçlüler"]
    if not measured.old:
        lines.append("  (eski üçlü yok)")
    for table in measured.old:
        lines += _table(table)
    lines += ["", "## Hüküm dışı — yardımcı tablo (beyaz liste genişlemez)"]
    lines += ["  (güncel üçlü yok)"] if measured.side is None else _table(measured.side)
    lines += _shadow(measured.shadow)
    return "\n".join(lines) + "\n"


def _line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"


def _fraction(value: Fraction | None) -> str | None:
    return None if value is None else f"{value.numerator}/{value.denominator}"


def _triple_object(triple: Triple | None) -> dict[str, str] | None:
    if triple is None:
        return None
    return dict(zip(("model", "prompt_fingerprint", "context_fingerprint"), triple, strict=True))


def _sample(result: ForwardResult, overlapping: bool | None) -> dict[str, object]:
    sample = result.sample
    return {
        "news_id": sample.news_id,
        "source": sample.source,
        "event_type": sample.event_type,
        "severity": sample.severity,
        "coin": sample.coin,
        "scored_at": _iso(sample.scored_at),
        "triple": _triple_object(sample.triple),
        "whitelisted": sample.whitelisted,
        "entry_time": None if result.entry_time is None else _iso(result.entry_time),
        "entry_price": result.entry_price,
        "down_hit": result.down,
        "up_hit": result.up,
        "base_down": _fraction(result.base_down),
        "base_up": _fraction(result.base_up),
        "unusual": result.unusual,
        "overlapping": overlapping,
        "reason": None if result.reason is None else result.reason.value,
    }


def samples_text(measured: ForwardMeasured) -> str:
    costs = measured.costs
    header = _line(
        {
            "format": SAMPLES_FORMAT,
            "version": SAMPLES_VERSION,
            "report_at": _iso(measured.report_at),
            "costs": {
                "fee": str(costs.fee),
                "slippage": str(costs.slippage),
                "spread": str(costs.spread),
            },
            "current_triple": _triple_object(measured.current),
            "verdict": measured.verdict.line,
        }
    )
    rows = (
        _line(_sample(result, overlapping))
        for result, overlapping in zip(measured.results, measured.overlapping, strict=True)
    )
    return header + "".join(rows)
