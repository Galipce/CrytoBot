"""Rapor metni (spec 0025 R-10, R-11, R-12; plan Risk 9). Saf ve belirlenimci.

Düz Türkçe metin, `\\n` satır sonu, sabit sıra: koşu bilgisi, varsayımlar, sonra örneklem içi,
örneklem dışı ve tüm koşu. Para 8 ondalık, yüzde ve oran 4 ondalık, `ROUND_HALF_EVEN`. Gerçek
saat, makine adı ve süre yazılmaz. Yalnız örneklem dışı parça "BR-10 kanıtı adayı" işaretini
taşır; rapor hiçbir parça için bir hüküm (eşik, sonuç) yazmaz.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from crytobot.backtest._metrics import PartMetrics, RunMetrics

CANDIDATE_MARK = "BR-10 kanıtı adayı"
UNDEFINED = "tanımsız"
_MONEY = Decimal("0.00000001")
_RATIO = Decimal("0.0001")
_CONTEXT = Context(prec=120, rounding=ROUND_HALF_EVEN)
ASSUMPTIONS: tuple[str, ...] = (
    "fiyat: tur anında açılan mumun açılışı",
    "spread: ayardaki sabit değer; dolumlara eklenmez, yalnız maliyet kapısında (BR-8) kullanılır",
    "çift kuralları: indirme anındaki hâliyle, dönem boyunca sabit",
    "stop ve hedef yalnız tur anlarında, tur fiyatıyla denetlenir; mum içi en yüksek ve en düşük"
    " değere bakılmaz",
    "B-51: risk, stop fiyatında, satış slippage'ı ve boşluklu düşüş olmadan hesaplanır;"
    " gerçekleşen zarar işlem başına risk sınırını aşabilir",
    "mum boşlukları doldurulmaz",
)


@dataclass(frozen=True)
class ReportFacts:
    """Koşunun bilgisi: dosyanın dönemi (bitiş hariç), aralıklar (Binance metni), ayrım anı,
    çiftler, indirme anı, ısınma mumu sayısı ve ayardaki spread."""

    start: datetime
    end: datetime
    candle_interval: str
    turn_interval: str
    split_at: datetime
    pairs: tuple[str, ...]
    downloaded_at: datetime
    candle_count: int
    spread: Decimal


def _moment(at: datetime | None) -> str:
    return "-" if at is None else at.astimezone(UTC).isoformat()


def _fixed(value: Decimal, places: Decimal) -> str:
    with localcontext(_CONTEXT):
        rounded = value.quantize(places)
    return format(abs(rounded) if rounded == 0 else rounded, "f")  # never "-0.0000"


def money(value: Decimal) -> str:
    return f"{_fixed(value, _MONEY)} USDT"


def percent(value: Decimal | None) -> str:
    if value is None:
        return UNDEFINED
    with localcontext(_CONTEXT):
        hundred = value * 100
    return f"%{_fixed(hundred, _RATIO)}"


def ratio(value: Decimal | None) -> str:
    return UNDEFINED if value is None else _fixed(value, _RATIO)


def _counts(items: Sequence[tuple[str, int]]) -> str:
    return ", ".join(f"{name} {count}" for name, count in items) or "yok"


def _halt(part: PartMetrics) -> str:
    if part.halt_started is not None:
        return f"başladı {_moment(part.halt_started)}"
    return "parça başında sürüyordu" if part.halted_at_start else "yok"


def _part(title: str, part: PartMetrics) -> list[str]:
    return [
        f"== {title} ==",
        f"turlar: {part.turns} (ilk {_moment(part.first_turn)}, son {_moment(part.last_turn)})",
        f"başlangıç kasası: {money(part.start_equity)}",
        f"bitiş kasası: {money(part.end_equity)}",
        f"net kâr/zarar: {money(part.net)} (getiri {percent(part.return_ratio)})",
        f"gerçekleşen kâr/zarar: {money(part.realized)}",
        f"gerçekleşmemiş kâr/zarar: {money(part.unrealized)}",
        f"işlem: {part.trades} (kazanan {part.winners}, zararlı {part.losers})",
        f"kazanma oranı: {percent(part.win_rate)}",
        f"kâr faktörü: {ratio(part.profit_factor)}",
        f"en büyük drawdown: {percent(part.max_drawdown)}",
        f"ortalama günlük getiri: {percent(part.average_daily_return)}",
        f"ödenen komisyon: {money(part.fees)}",
        f"ödenen slippage: {money(part.slippage)}",
        f"günlük zarar durdurmalı gün: {part.daily_loss_days}",
        f"drawdown durdurması: {_halt(part)}",
        f"fiyatı ya da verisi eksik tur (çift başına): {_counts(part.missing)}",
        f"öneri yok (nedene göre): {_counts(part.no_proposals)}",
        f"ret (nedene göre): {_counts(part.refusals)}",
        f"gönderilmeyen durum bildirimi (türe göre): {_counts(part.notices)}",
    ]


def report_text(facts: ReportFacts, metrics: RunMetrics) -> str:
    """R-10, R-11: raporun tamamı; son satır da `\\n` ile biter."""
    lines = [
        "CrytoBot backtest raporu",
        f"dönem: {_moment(facts.start)} .. {_moment(facts.end)} (bitiş hariç)",
        f"mum aralığı: {facts.candle_interval}",
        f"tur aralığı: {facts.turn_interval}",
        f"ayrım anı: {_moment(facts.split_at)}"
        " (örneklem içi bu andan önceki turlar, örneklem dışı bu an ve sonrası)",
        f"çiftler: {', '.join(facts.pairs)}",
        f"indirme anı: {_moment(facts.downloaded_at)}",
        f"ısınma mumu (candle_count): {facts.candle_count}",
        f"spread: {format(facts.spread, 'f')}",
        "",
        "varsayımlar:",
        *(f"- {assumption}" for assumption in ASSUMPTIONS),
        "",
        *_part("örneklem içi", metrics.in_sample),
        "",
        *_part(f"örneklem dışı — {CANDIDATE_MARK}", metrics.out_of_sample),
        "",
        *_part("tüm koşu", metrics.whole),
    ]
    return "\n".join(lines) + "\n"
