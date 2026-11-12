"""Rapor metni (spec 0025 R-10, R-11, R-12; plan Risk 9). Saf ve belirlenimci.

Düz Türkçe metin, `\\n` satır sonu, sabit sıra: koşu bilgisi, varsayımlar, sonra örneklem içi,
örneklem dışı ve tüm koşu. Para 8 ondalık, yüzde ve oran 4 ondalık, `ROUND_HALF_EVEN`. Makine
adı ve süre yazılmaz; gerçek saat yalnız başlıktaki üretim anıdır (spec 0040 CB-2, 0025 R-12'yi
bu kadarıyla geçersiz kılar): aynı veri, ayar ve üretim anı bayt bayt aynı raporu verir. Başlık
rapor koşullarını da (spec 0040 CB-3) `CONDITIONS` sırasıyla, botun etkin değeriyle yazar.
Spec 0042 R-1 (0025 R-9/R-10'un varsayılan rapor kısmını geçersiz kılar): iki biçim.
- Varsayılan (`report_text`): başlık, varsayımlar ve yalnız örneklem içi parça; örneklem dışından ve
  saklı dönemden tek rakam yoktur, aday işareti yoktur, hüküm yazılmaz.
- Son değerlendirme (`final_report_text`): ilk satır `FINAL_TITLE`; sınanan kombinasyon sayısı
  (R-5), paper adayı ya da "aday yok" (R-4), her aday için seçilen ayar, dönem özetleri ve hüküm
  (R-3); paper adayı varsa başlık onun bilgilerini taşır ve onun örneklem içi, örneklem dışı
  ("BR-10 kanıtı adayı" işaretiyle, yalnız orada), saklı dönem ve tüm koşu parçaları yazılır. Aday
  yoksa başlık yalnız ortak bilgileri (spread, üretim anı, rapor koşulları) taşır.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from crytobot.backtest._metrics import PartMetrics, RunMetrics

CANDIDATE_MARK = "BR-10 kanıtı adayı"
TITLE = "CrytoBot backtest raporu"
FINAL_TITLE = "CrytoBot backtest raporu — son değerlendirme"
COMBINATIONS_LABEL = "sınanan kombinasyon"
PAPER_LABEL = "paper adayı"
NO_CANDIDATE = "aday yok"
UNDEFINED = "tanımsız"
GENERATED_LABEL = "üretim anı"
# spec 0040 CB-3: the report conditions, in header order; names are the setting keys (plan Risk 5)
CONDITIONS: tuple[str, ...] = (
    "fee",
    "slippage",
    "per_trade_risk",
    "daily_loss_limit",
    "max_drawdown",
    "max_open_positions",
    "profit_cost_multiple",
    "opening_balance",
)
_MONEY = Decimal("0.00000001")
_RATIO = Decimal("0.0001")
_CONTEXT = Context(prec=120, rounding=ROUND_HALF_EVEN)
ASSUMPTIONS: tuple[str, ...] = (
    "fiyat: tur anında açılan mumun açılışı",
    "spread: ayardaki sabit değer; dolumlara eklenmez, yalnız maliyet kapısında (BR-8) kullanılır",
    "çift kuralları: indirme anındaki hâliyle, dönem boyunca sabit",
    "stop ve hedef yalnız tur anlarında, tur fiyatıyla denetlenir; mum içi en yüksek ve en düşük"
    " değere bakılmaz",
    "risk, stop fiyatında satış slippage'ı ve komisyonuyla hesaplanır; stopun altına"
    " boşluklu düşüş hesaba katılmaz, gerçekleşen zarar işlem başına risk sınırını aşabilir",
    "mum boşlukları doldurulmaz",
)


@dataclass(frozen=True)
class ReportFacts:
    """Koşunun bilgisi: dosyanın dönemi (bitiş hariç), aralıklar (Binance metni), ayrım anı,
    çiftler, indirme anı, ısınma mumu sayısı ve ayardaki spread; spec 0040: üretim anı ve rapor
    koşulları (etkin değerler, `CONDITIONS` adlarıyla); spec 0042: strateji adı ve saklı dönem
    başı (yalnız son değerlendirmede yazılır)."""

    start: datetime
    end: datetime
    candle_interval: str
    turn_interval: str
    split_at: datetime
    pairs: tuple[str, ...]
    downloaded_at: datetime
    candle_count: int
    spread: Decimal
    strategy: Mapping[str, int | Decimal | str] | None = None
    generated_at: datetime = field(kw_only=True)
    strategy_name: str | None = field(default=None, kw_only=True)  # spec 0042 R-7
    holdout_at: datetime | None = field(default=None, kw_only=True)  # spec 0042 R-1
    fee: Decimal = field(kw_only=True)
    slippage: Decimal = field(kw_only=True)
    per_trade_risk: Decimal = field(kw_only=True)
    daily_loss_limit: Decimal = field(kw_only=True)
    max_drawdown: Decimal = field(kw_only=True)
    max_open_positions: int = field(kw_only=True)
    profit_cost_multiple: Decimal = field(kw_only=True)
    opening_balance: Decimal = field(kw_only=True)

    def conditions(self) -> tuple[tuple[str, Decimal | int], ...]:
        """`CONDITIONS` sırasıyla (ad, değer)."""
        return tuple((name, getattr(self, name)) for name in CONDITIONS)


def _plain(value: Decimal | int) -> str:
    return format(value, "f") if isinstance(value, Decimal) else str(value)


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


# spec 0043 plan Risk 8: the report's short names; every other parameter keeps its own name
_SHORT = {"fast_period": "fast", "slow_period": "slow", "rsi_period": "rsi", "atr_period": "atr"}


def _strategy_text(strategy: Mapping[str, int | Decimal | str]) -> str:
    """Parametre eşlemi sırasıyla `ad=değer`; S0'ın satırı bugünküyle bayt bayt aynıdır
    (`fast=12 slow=26 rsi=14 rsi_threshold=70 atr=14 k=2 r=2`), yeni adaylar yalnız kendi
    parametrelerini yazar (spec 0043, plan Risk 8)."""
    return " ".join(f"{_SHORT.get(name, name)}={value}" for name, value in strategy.items())


def _common(facts: ReportFacts) -> list[str]:
    """Üretim anı ve rapor koşulları (spec 0040 CB-2, CB-3): başlığın sonu, her biçimde aynı."""
    return [
        f"{GENERATED_LABEL}: {_moment(facts.generated_at)}",
        *(f"{name}: {_plain(value)}" for name, value in facts.conditions()),
    ]


def _header(facts: ReportFacts, *, final: bool) -> list[str]:
    # spec 0042 AC-1: the default report names no later period
    split = ", örneklem dışı bu an ile saklı dönem başı arası" if final else ""
    header = [
        f"dönem: {_moment(facts.start)} .. {_moment(facts.end)} (bitiş hariç)",
        f"mum aralığı: {facts.candle_interval}",
        f"tur aralığı: {facts.turn_interval}",
        f"ayrım anı: {_moment(facts.split_at)} (örneklem içi bu andan önceki turlar{split})",
    ]
    if final and facts.holdout_at is not None:
        header.append(f"saklı dönem başı: {_moment(facts.holdout_at)} (bu an ve sonrası)")
    header.extend(
        [
            f"çiftler: {', '.join(facts.pairs)}",
            f"indirme anı: {_moment(facts.downloaded_at)}",
            f"ısınma mumu (candle_count): {facts.candle_count}",
            f"spread: {format(facts.spread, 'f')}",
        ]
    )
    if facts.strategy is not None:
        name = f"{facts.strategy_name} " if final and facts.strategy_name else ""
        header.append(f"strateji: {name}{_strategy_text(facts.strategy)}")
    return [*header, *_common(facts)]


def _assumptions() -> list[str]:
    return ["varsayımlar:", *(f"- {assumption}" for assumption in ASSUMPTIONS)]


def report_text(facts: ReportFacts, metrics: RunMetrics) -> str:
    """R-10, R-11; spec 0042 R-1: varsayılan rapor, yalnız örneklem içi. Son satır da `\\n` ile
    biter."""
    lines = [
        TITLE,
        *_header(facts, final=False),
        "",
        *_assumptions(),
        "",
        *_part("örneklem içi", metrics.in_sample),
    ]
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class CandidateResult:
    """Bir adayın (strateji ve aralık) sonucu: seçilen ayar (`None`: örneklem içinde 30 işlemli
    kombinasyon yok), hesaplanan dönemlerin metrikleri ve hüküm (R-3)."""

    name: str
    interval: str
    setting: Mapping[str, int | Decimal | str] | None
    in_sample: PartMetrics | None
    out_of_sample: PartMetrics | None
    holdout: PartMetrics | None
    verdict: str

    @property
    def label(self) -> str:
        return f"{self.name} {self.interval}"


def _summary(title: str, part: PartMetrics | None) -> list[str]:
    if part is None:
        return []
    return [
        f"{title}: işlem {part.trades}, kâr faktörü {ratio(part.profit_factor)},"
        f" net kâr/zarar {money(part.net)}, en büyük drawdown {percent(part.max_drawdown)}"
    ]


def _candidate(result: CandidateResult) -> list[str]:
    setting = "yok" if result.setting is None else _strategy_text(result.setting)
    return [
        f"== aday: {result.label} ==",
        f"seçilen ayar: {setting}",
        *_summary("örneklem içi", result.in_sample),
        *_summary("örneklem dışı", result.out_of_sample),
        *_summary("saklı dönem", result.holdout),
        f"sonuç: {result.verdict}",
    ]


def final_report_text(
    facts: ReportFacts,
    combinations: int,
    candidates: Sequence[CandidateResult],
    paper: int | None,
    metrics: RunMetrics | None,
) -> str:
    """Spec 0042 R-1, R-3…R-5: son değerlendirme raporu. `paper` paper adayının sırasıdır; varsa
    `facts` ve `metrics` onun koşusudur (`metrics.holdout` dolu), yoksa `facts` yalnız ortak başlık
    için kullanılır."""
    if paper is None:
        header = [f"spread: {format(facts.spread, 'f')}", *_common(facts)]
        named = NO_CANDIDATE
    else:
        header = _header(facts, final=True)
        named = candidates[paper].label
    lines = [
        FINAL_TITLE,
        *header,
        f"{COMBINATIONS_LABEL}: {combinations}",
        f"{PAPER_LABEL}: {named}",
        "",
        *_assumptions(),
    ]
    for result in candidates:
        lines.extend(["", *_candidate(result)])
    if paper is not None:
        assert metrics is not None and metrics.holdout is not None
        lines.extend(
            [
                "",
                *_part("örneklem içi", metrics.in_sample),
                "",
                *_part(f"örneklem dışı — {CANDIDATE_MARK}", metrics.out_of_sample),
                "",
                *_part("saklı dönem", metrics.holdout),
                "",
                *_part("tüm koşu", metrics.whole),
            ]
        )
    return "\n".join(lines) + "\n"
