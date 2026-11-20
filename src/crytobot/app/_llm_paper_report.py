"""LLM paper ölçümünün raporu ve hükmü (spec 0060 R-6, R-7, C-6...C-8, AC-6, AC-8, AC-9). Saf.

Karar kaydı `app`'in tipleriyle gelir (giriş noktası çevirir, R-3k). Dönem: çağrılı turların model
ve istem parmak izi; ölçüm başlangıcından sonra değişirse ölçüm o turdan yeniden başlar ve 90 gün o
andan sayılır (C-6); hüküm son dönemindir. Ölçüme girenler: dönem içindeki geçerli `al`lar. Karar
istenen coinler: `al`, `tutarsız`, `şema dışı` ve Claude'un kendi `bekle`si (`action='bekle'`);
kararsız turların `bekle`si ve `veri yok` sayılmaz (C-8). Hüküm yalnız dönem bitince verilir.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from crytobot.app._llm_paper import PaperDecision, PaperTrade, Replay, Status
from crytobot.app._llm_paper_config import (
    FEE,
    LIMITS,
    MAX_BAD_DECISIONS,
    MAX_DRAWDOWN,
    MEASUREMENT_END,
    MEASUREMENT_SPAN,
    MEASUREMENT_START,
    MIN_CLOSED_TRADES,
    MIN_PROFIT_FACTOR,
    OPENING_BALANCE,
    RANDOM_PERCENTILE,
    RANDOM_REPEATS,
    RANDOM_SEED,
    SLIPPAGE,
    SPREAD,
)
from crytobot.app._llm_paper_random import RandomResult, closed_net

RUNNING = "ölçüm sürüyor"
DATA_MISSING = "veri eksik: önce llm-paper download"
POSITIVE = "olumlu"
NEGATIVE = "olumsuz"
INSUFFICIENT = "yetersiz örnek"
LOW_QUALITY = "karar kalitesi düşük"
ASKED_STATUSES = ("al", "tutarsız", "şema dışı")


@dataclass(frozen=True)
class RecordTurn:
    at: datetime
    model: str
    prompt_fingerprint: str
    outcome: str
    called: bool


@dataclass(frozen=True)
class RecordDecision:
    at: datetime
    coin: str
    status: str
    action: str | None
    entry_low: Decimal | None
    entry_high: Decimal | None
    stop: Decimal | None
    target: Decimal | None
    valid_hours: int | None


@dataclass(frozen=True)
class Period:
    model: str
    prompt_fingerprint: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class S0Summary:
    """ADR 0004 S0 koşusunun pencereye düşen işlemleri (bilgi, G-9)."""

    closed: int
    open: int
    net: Decimal
    profit_factor: Decimal | None


@dataclass(frozen=True)
class Metrics:
    closed: int
    wins: int
    net: Decimal
    profit_factor: Decimal | None
    max_drawdown: Decimal
    average_hours: Decimal | None


@dataclass(frozen=True)
class Verdict:
    name: str
    failed: tuple[str, ...] = ()
    quality_low: bool = False

    @property
    def line(self) -> str:
        detail = f" ({', '.join(self.failed)})" if self.failed else ""
        return f"{self.name}{detail}"


@dataclass(frozen=True)
class Counts:
    turns: int = 0
    called: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)
    asked: int = 0
    buys: int = 0
    waits: int = 0
    inconsistent: int = 0
    schema: int = 0

    def share(self, count: int) -> Decimal | None:
        return None if not self.asked else Decimal(count) / Decimal(self.asked)

    @property
    def bad_share(self) -> Decimal | None:
        if not self.asked:
            return None
        return Decimal(self.inconsistent + self.schema) / Decimal(self.asked)


def periods(turns: Sequence[RecordTurn]) -> tuple[Period, ...]:
    """Ölçüm başlangıcından sonraki çağrılı turların parmak izi dönemleri (C-6)."""
    found: list[Period] = []
    for turn in sorted(turns, key=lambda t: t.at):
        if not turn.called or turn.at < MEASUREMENT_START:
            continue
        key = (turn.model, turn.prompt_fingerprint)
        if found and (found[-1].model, found[-1].prompt_fingerprint) == key:
            continue
        if not found and turn.at >= MEASUREMENT_END:
            break
        if found and turn.at >= found[-1].end:
            break
        start = MEASUREMENT_START if not found else turn.at
        if found:
            last = found[-1]
            found[-1] = Period(last.model, last.prompt_fingerprint, last.start, turn.at)
        found.append(Period(turn.model, turn.prompt_fingerprint, start, start + MEASUREMENT_SPAN))
    return tuple(found)


def active_period(turns: Sequence[RecordTurn]) -> Period:
    found = periods(turns)
    if found:
        return found[-1]
    return Period("-", "-", MEASUREMENT_START, MEASUREMENT_END)


def counts(
    turns: Sequence[RecordTurn], decisions: Sequence[RecordDecision], period: Period
) -> Counts:
    inside = [t for t in turns if period.start <= t.at < period.end]
    outcomes: dict[str, int] = {}
    for turn in inside:
        outcomes[turn.outcome] = outcomes.get(turn.outcome, 0) + 1
    rows = [d for d in decisions if period.start <= d.at < period.end]
    waits = sum(d.status == "bekle" and d.action == "bekle" for d in rows)
    asked = sum(d.status in ASKED_STATUSES for d in rows) + waits
    return Counts(
        len(inside),
        sum(t.called for t in inside),
        outcomes,
        asked,
        sum(d.status == "al" for d in rows),
        waits,
        sum(d.status == "tutarsız" for d in rows),
        sum(d.status == "şema dışı" for d in rows),
    )


def buy_decisions(decisions: Sequence[RecordDecision], period: Period) -> list[PaperDecision]:
    """Dönem içindeki geçerli `al`lar, tur ve coin sırasıyla."""
    found = []
    for d in sorted(decisions, key=lambda r: (r.at, r.coin)):
        if d.status != "al" or not period.start <= d.at < period.end:
            continue
        if None in (d.entry_low, d.entry_high, d.stop, d.target, d.valid_hours):
            continue
        assert d.entry_low is not None and d.entry_high is not None
        assert d.stop is not None and d.target is not None and d.valid_hours is not None
        found.append(
            PaperDecision(d.at, d.coin, d.entry_low, d.entry_high, d.stop, d.target, d.valid_hours)
        )
    return found


def _drawdown(curve: Sequence[tuple[datetime, Decimal]]) -> Decimal:
    peak, worst = Decimal(0), Decimal(0)
    for _, equity in curve:
        peak = max(peak, equity)
        if peak > 0:
            worst = max(worst, (peak - equity) / peak)
    return worst


def metrics(result: Replay) -> Metrics:
    closed = [t for t in result.trades if t.status is Status.CLOSED and t.net is not None]
    gains = sum((t.net for t in closed if t.net is not None and t.net > 0), Decimal(0))
    losses = sum((-t.net for t in closed if t.net is not None and t.net < 0), Decimal(0))
    hours = [
        Decimal(int((t.exit_at - t.filled_at).total_seconds() // 3600))
        for t in closed
        if t.exit_at is not None and t.filled_at is not None
    ]
    return Metrics(
        len(closed),
        sum(t.net is not None and t.net > 0 for t in closed),
        closed_net(result.trades),
        None if losses == 0 else gains / losses,
        _drawdown(result.curve),
        None if not hours else sum(hours, Decimal(0)) / len(hours),
    )


def verdict(
    period: Period,
    at: datetime,
    found: Metrics,
    chance: RandomResult,
    tally: Counts,
    horizon: datetime,
) -> Verdict:
    """C-7, R-7: dönem bitmeden `ölçüm sürüyor`; dönem bittiği halde oynatma dönem sonuna
    ulaşmadıysa (indirilmemiş saatler) yine `ölçüm sürüyor` ve nedeni (M-1); sonra yetersiz
    örnek, olumsuz ya da olumlu."""
    quality_low = tally.bad_share is not None and tally.bad_share > MAX_BAD_DECISIONS
    if at < period.end:
        return Verdict(RUNNING, (), quality_low)
    if horizon < period.end:
        return Verdict(RUNNING, (DATA_MISSING,), quality_low)
    if found.closed < MIN_CLOSED_TRADES:
        return Verdict(
            INSUFFICIENT, (f"kapanmış işlem {found.closed} < {MIN_CLOSED_TRADES}",), quality_low
        )
    failed: list[str] = []
    if found.net <= 0:
        failed.append("net kâr ≤ 0")
    if found.profit_factor is not None and found.profit_factor < MIN_PROFIT_FACTOR:
        failed.append(f"kâr faktörü < {MIN_PROFIT_FACTOR}")
    if found.max_drawdown > MAX_DRAWDOWN:
        failed.append(f"drawdown > %{MAX_DRAWDOWN * 100:.0f}")
    ceiling = chance.percentile(RANDOM_PERCENTILE)
    if ceiling is None or found.net <= ceiling:
        failed.append(f"rastgelenin {RANDOM_PERCENTILE}. yüzdeliğini geçmiyor")
    if quality_low:
        failed.append(LOW_QUALITY)
    return Verdict(NEGATIVE if failed else POSITIVE, tuple(failed), quality_low)


def _money(value: Decimal | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _ratio(value: Decimal | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _share(value: Decimal | None) -> str:
    return "-" if value is None else f"%{value * 100:.1f}"


def _stamp(moment: datetime | None) -> str:
    return "-" if moment is None else moment.strftime("%Y-%m-%dT%H:%MZ")


@dataclass(frozen=True)
class ReportFacts:
    at: datetime
    written_at: datetime
    record_path: str
    record_skipped: int
    price_path: str
    rules_at: str | None
    s0: S0Summary | None
    random_missing: int
    horizon: datetime | None = None
    limited_by: str | None = None  # the coin whose download holds the horizon back (I-a)
    empty_spans: int = 0  # spans stored without candles (L-c)


def report_text(
    all_periods: Sequence[Period],
    period: Period,
    tally: Counts,
    result: Replay,
    found: Metrics,
    chance: RandomResult,
    judged: Verdict,
    facts: ReportFacts,
) -> str:
    trades = result.trades
    statuses: dict[str, int] = {}
    rejections: dict[str, int] = {}
    exits: dict[str, int] = {}
    coins: dict[str, list[Decimal]] = {}
    for t in trades:
        statuses[t.status.value] = statuses.get(t.status.value, 0) + 1
        if t.rejection:
            rejections[t.rejection] = rejections.get(t.rejection, 0) + 1
        if t.exit_kind is not None:
            exits[t.exit_kind.value] = exits.get(t.exit_kind.value, 0) + 1
        if t.status is Status.CLOSED and t.net is not None:
            coins.setdefault(t.decision.coin, []).append(t.net)

    def pairs(items: dict[str, int]) -> str:
        return " ".join(f"{k.replace(' ', '_')}={v}" for k, v in sorted(items.items())) or "-"

    win_share = None if not found.closed else Decimal(found.wins) / found.closed
    llm_rank = chance.rank_of(found.net)
    lines = [
        "# CrytoBot LLM paper ölçümü (spec 0060, ADR 0005/0006)",
        f"rapor anı: {_stamp(facts.at)} yazıldı: {_stamp(facts.written_at)}",
        f"karar kaydı: {facts.record_path} okunamayan_satır={facts.record_skipped}",
        f"fiyat verisi: {facts.price_path} borsa_kuralları: {facts.rules_at or '-'}",
        f"ön kayıt: başlangıç {_stamp(MEASUREMENT_START)} süre 90 gün; kasa {OPENING_BALANCE}"
        f" USDT; komisyon {FEE} kayma {SLIPPAGE} spread {SPREAD} (varsayım); risk: işlem"
        f" {LIMITS.per_trade_risk} günlük {LIMITS.daily_loss_limit} drawdown"
        f" {LIMITS.max_drawdown} pozisyon {LIMITS.max_open_positions} kat"
        f" {LIMITS.profit_cost_multiple}",
        "varsayım: dolum mumu kararın verildiği dakikadan önceki ilk dakikaları da kapsar (tur anı"
        " 1h sınırıdır); dolum mumunda hedef yalnız dolum açılışta olduysa sayılır (A-8)",
        f"oynatma ufku: {_stamp(facts.horizon)}"
        + ("" if facts.limited_by is None else f" (sınırlayan: {facts.limited_by})"),
        *(
            [
                f"uyarı: mumsuz indirilmiş aralık={facts.empty_spans} (borsa kesintisi ya da"
                " kapanmamış mum; geçici olanları bir sonraki indirme yeniden ister)"
            ]
            if facts.empty_spans
            else []
        ),
        "",
        "## Dönemler",
        *(
            f"- {_stamp(p.start)} → {_stamp(p.end)} model={p.model}"
            f" istem={p.prompt_fingerprint[:12]}"
            for p in all_periods
        ),
        f"etkin dönem: {_stamp(period.start)} → {_stamp(period.end)}",
        "",
        "## Kararlar",
        f"tur={tally.turns} çağrı={tally.called} sonuçlar: {pairs(tally.outcomes)}",
        f"karar_istenen={tally.asked} al={tally.buys} claude_bekle={tally.waits}"
        f" tutarsız={tally.inconsistent} şema_dışı={tally.schema}"
        f" şema_dışı+tutarsız={_share(tally.bad_share)} (sınır %{MAX_BAD_DECISIONS * 100:.0f})",
        f"oranlar: al={_share(tally.share(tally.buys))}"
        f" claude_bekle={_share(tally.share(tally.waits))}"
        f" tutarsız={_share(tally.share(tally.inconsistent))}"
        f" şema_dışı={_share(tally.share(tally.schema))}",
        "",
        "## İşlemler",
        f"durum: {pairs(statuses)}",
        f"risk reddi: {pairs(rejections)}",
        f"kapanış: {pairs(exits)}",
        f"kapanmış={found.closed} kazanan={found.wins} kazanma_oranı={_share(win_share)}",
        f"net kâr (maliyetlerden sonra): {_money(found.net)} USDT"
        f" kâr_faktörü={_ratio(found.profit_factor)} en_büyük_drawdown={_share(found.max_drawdown)}"
        f" ortalama_süre={_ratio(found.average_hours)} saat",
        f"son kasa (açıklar son fiyatla): {_money(result.final_equity)} USDT"
        f" drawdown_durdurması={_stamp(result.halted_at)}"
        f" durdurmadaki_kasa={_money(result.halted_equity)}",
        "coin başına (kapanmış, net):",
        *(
            f"- {coin}: {len(nets)} {_money(sum(nets, Decimal(0)))}"
            for coin, nets in sorted(coins.items())
        ),
        "",
        "## Eşlenik rastgele",
        f"tohum={RANDOM_SEED} tekrar={len(chance.nets)}/{RANDOM_REPEATS}"
        f" kurulamayan_ikiz={facts.random_missing}",
        f"yüzdelik 5={_money(chance.percentile(5))} 50={_money(chance.percentile(50))}"
        f" 95={_money(chance.percentile(95))} USDT; LLM yüzdeliği={_ratio(llm_rank)}",
        "",
        "## S0 (ADR 0004, bilgi; hükme girmez)",
        "S0 yok"
        if facts.s0 is None
        else f"kapanmış={facts.s0.closed} açık={facts.s0.open} net={_money(facts.s0.net)} USDT"
        f" kâr_faktörü={_ratio(facts.s0.profit_factor)}",
        "",
        "## Hüküm",
        f"hüküm: {judged.line}",
        *([f"uyarı: {LOW_QUALITY}"] if judged.quality_low else []),
        "Hüküm bilgi verir: emir, mod, liste ve ayar değişmez; live ayrı ADR ister.",
    ]
    return "\n".join(lines) + "\n"


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def trade_rows(trades: Sequence[PaperTrade]) -> tuple[dict[str, str | int | None], ...]:
    """İşlem dosyasının satırları: her kararın sonucu bir satır (giriş noktası JSON Lines yazar)."""
    rows: list[dict[str, str | int | None]] = []
    for t in trades:
        d = t.decision
        rows.append(
            {
                "turn": d.turn.isoformat(),
                "coin": d.coin,
                "entry_low": str(d.entry_low),
                "entry_high": str(d.entry_high),
                "stop": str(d.stop),
                "target": str(d.target),
                "valid_hours": d.valid_hours,
                "status": t.status.value,
                "rejection": t.rejection,
                "filled_at": None if t.filled_at is None else t.filled_at.isoformat(),
                "fill_price": _decimal(t.fill_price),
                "amount": _decimal(t.amount),
                "exit_at": None if t.exit_at is None else t.exit_at.isoformat(),
                "exit_price": _decimal(t.exit_price),
                "exit_kind": None if t.exit_kind is None else t.exit_kind.value,
                "net": _decimal(t.net),
            }
        )
    return tuple(rows)
