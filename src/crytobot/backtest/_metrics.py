"""Tur kayıtlarından parça metrikleri (spec 0025 R-9, R-10; plan Risk 7, 8). Saf hesap.

Kasa, turun kasa gözlemiyle aynı tanımdır: her turdan sonra, açık pozisyonlar her çiftin son
bilinen tur fiyatıyla (`TurnRecord.marks`). Örneklem dışı parça, son örneklem içi turun kasası ve
açık pozisyonlarıyla başlar; saklı dönem (spec 0042 R-1) aynı yolla son örneklem dışı turun kasası
ve açık pozisyonlarıyla; tüm koşu açılış kasasıyla.

- Gerçekleşen: parçada kapanan işlemlerin `Closure.realized` toplamı (komisyonlar dahil, slippage
  dolum fiyatında).
- Gerçekleşmemiş: açık pozisyonların değeri eksi maliyeti (miktar * maliyet fiyatı + alım
  komisyonu), parça sonu ile parça başı farkı.
  Net = gerçekleşen + gerçekleşmemiş = bitiş - başlangıç.
- Drawdown: parçanın başlangıç ve tur kasaları üzerinde en büyük (zirve - kasa) / zirve.
- Ortalama günlük getiri: parçanın simüle UTC günlerinin son tur kasasından; ilk gün parçanın
  başlangıç kasasına göre.

Hesap 60 basamaklı bağlamda yapılır; bölümler orada yuvarlanır, biçimleme rapordadır.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from crytobot.portfolio import Closure, Position

_CONTEXT = Context(prec=60, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True)
class TurnRecord:
    """Bir turun sonrası. `missing`: fiyatı ya da verisi eksik çiftler; `no_proposals` ve
    `refusals`: neden adları; `notices`: bu turda başlayan durum bildirimlerinin türleri."""

    at: datetime
    equity: Decimal
    positions: tuple[Position, ...]
    marks: Mapping[str, Decimal]
    closures: tuple[Closure, ...]
    fees: Decimal
    slippage: Decimal
    daily_loss: bool
    halted: bool
    missing: tuple[str, ...]
    no_proposals: tuple[str, ...]
    refusals: tuple[str, ...]
    notices: tuple[str, ...]


@dataclass(frozen=True)
class PartMetrics:
    """Bir parçanın metrikleri. `None`: tanımsız (işlem yok, zararlı işlem yok, gün yok).

    `halt_started`: drawdown durdurmasının bu parçada başladığı tur anı; `halted_at_start`:
    durdurma parça başında sürüyordu. Sayımlar (ad, sayı) çiftleridir; eksik turlar verilen çift
    sırasıyla, nedenler ve bildirimler ada göre sıralı."""

    first_turn: datetime | None
    last_turn: datetime | None
    turns: int
    start_equity: Decimal
    end_equity: Decimal
    net: Decimal
    return_ratio: Decimal
    realized: Decimal
    unrealized: Decimal
    trades: int
    winners: int
    losers: int
    win_rate: Decimal | None
    profit_factor: Decimal | None
    max_drawdown: Decimal
    average_daily_return: Decimal | None
    fees: Decimal
    slippage: Decimal
    daily_loss_days: int
    halt_started: datetime | None
    halted_at_start: bool
    missing: tuple[tuple[str, int], ...]
    no_proposals: tuple[tuple[str, int], ...]
    refusals: tuple[tuple[str, int], ...]
    notices: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class RunMetrics:
    """`holdout`: yalnız saklı dönem başı verildiyse (spec 0042); o zaman örneklem dışı saklı
    dönemin başında biter."""

    in_sample: PartMetrics
    out_of_sample: PartMetrics
    whole: PartMetrics
    holdout: PartMetrics | None = None


def unrealized(positions: Sequence[Position], marks: Mapping[str, Decimal]) -> Decimal:
    """Açık pozisyonların değeri eksi maliyeti; fiyat son bilinen tur fiyatıdır."""
    with localcontext(_CONTEXT):
        total = Decimal(0)
        for position in positions:
            value = position.amount * marks[position.pair]
            total += value - (position.amount * position.cost_price + position.fee)
        return total


def _drawdown(start: Decimal, equities: Sequence[Decimal]) -> Decimal:
    peak, worst = start, Decimal(0)
    for equity in equities:
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak)
    return worst


def _daily_returns(start: Decimal, records: Sequence[TurnRecord]) -> list[Decimal]:
    last_by_day: dict[date, Decimal] = {}
    for record in records:
        last_by_day[record.at.date()] = record.equity  # records come in time order
    returns: list[Decimal] = []
    previous = start
    for equity in last_by_day.values():
        returns.append((equity - previous) / previous)
        previous = equity
    return returns


def _counts(names: Sequence[str]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(Counter(names).items()))


def _halt(halted_at_start: bool, records: Sequence[TurnRecord]) -> datetime | None:
    before = halted_at_start
    for record in records:
        if record.halted and not before:
            return record.at
        before = record.halted
    return None


def part_metrics(
    start_equity: Decimal,
    start_unrealized: Decimal,
    halted_at_start: bool,
    records: Sequence[TurnRecord],
    pairs: Sequence[str],
) -> PartMetrics:
    """Bir parçanın metrikleri; `records` parçanın turlarıdır, zaman sırasıyla."""
    with localcontext(_CONTEXT):
        last = records[-1] if records else None
        end_equity = start_equity if last is None else last.equity
        end_unrealized = (
            start_unrealized if last is None else unrealized(last.positions, last.marks)
        )
        results = [closure.realized for record in records for closure in record.closures]
        gains = [value for value in results if value > 0]
        losses = [value for value in results if value < 0]
        daily = _daily_returns(start_equity, records)
        missing = Counter(pair for record in records for pair in record.missing)
        return PartMetrics(
            first_turn=records[0].at if records else None,
            last_turn=None if last is None else last.at,
            turns=len(records),
            start_equity=start_equity,
            end_equity=end_equity,
            net=end_equity - start_equity,
            return_ratio=(end_equity - start_equity) / start_equity,
            realized=sum(results, Decimal(0)),
            unrealized=end_unrealized - start_unrealized,
            trades=len(results),
            winners=len(gains),
            losers=len(losses),
            win_rate=Decimal(len(gains)) / len(results) if results else None,
            profit_factor=sum(gains, Decimal(0)) / -sum(losses, Decimal(0)) if losses else None,
            max_drawdown=_drawdown(start_equity, [record.equity for record in records]),
            average_daily_return=sum(daily, Decimal(0)) / len(daily) if daily else None,
            fees=sum((record.fees for record in records), Decimal(0)),
            slippage=sum((record.slippage for record in records), Decimal(0)),
            daily_loss_days=len({record.at.date() for record in records if record.daily_loss}),
            halt_started=_halt(halted_at_start, records),
            halted_at_start=halted_at_start,
            missing=tuple((pair, missing[pair]) for pair in pairs),
            no_proposals=_counts([name for record in records for name in record.no_proposals]),
            refusals=_counts([name for record in records for name in record.refusals]),
            notices=_counts([name for record in records for name in record.notices]),
        )


def _boundary(
    start: tuple[Decimal, Decimal, bool], before: Sequence[TurnRecord]
) -> tuple[Decimal, Decimal, bool]:
    """Bir sonraki parçanın başlangıcı: önceki parçanın son turunun kasası, açık pozisyonlarının
    gerçekleşmemiş değeri ve durdurması; önceki parçada tur yoksa önceki parçanın başlangıcı."""
    if not before:
        return start
    last = before[-1]
    return last.equity, unrealized(last.positions, last.marks), last.halted


def run_metrics(
    opening_equity: Decimal,
    records: Sequence[TurnRecord],
    split_at: datetime,
    pairs: Sequence[str],
    holdout_at: datetime | None = None,
) -> RunMetrics:
    """R-9: kesintisiz koşu ayrım anında ikiye bölünür; tüm koşu tek parçadır. Spec 0042:
    `holdout_at` verilirse örneklem dışı o anda biter, saklı dönem o an ve sonrasıdır."""
    opening = (opening_equity, Decimal(0), False)
    inside = [record for record in records if record.at < split_at]
    outside = [
        record
        for record in records
        if record.at >= split_at and (holdout_at is None or record.at < holdout_at)
    ]
    out_start = _boundary(opening, inside)
    holdout = None
    if holdout_at is not None:
        held = [record for record in records if record.at >= holdout_at]
        holdout = part_metrics(*_boundary(out_start, outside), held, pairs)
    return RunMetrics(
        part_metrics(*opening, inside, pairs),
        part_metrics(*out_start, outside, pairs),
        part_metrics(*opening, records, pairs),
        holdout,
    )
