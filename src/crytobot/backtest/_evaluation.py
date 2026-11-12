"""Strateji değerlendirme kuralı (spec 0042 R-2…R-5; plan Risk 5, 6). Saf hesap.

Eşikler kodda sabittir, ayardan okunmaz (R-3): örneklem dışında net kâr > 0, kâr faktörü ≥ 1.2, en
az 30 kapanmış işlem, en büyük drawdown < %15; saklı dönemde net kâr > 0 ve drawdown < %15 (işlem
asgarisi yok). Karşılaştırma kesin `Decimal` değerlerledir, rapordaki yuvarlanmış metinle değil
(Risk 6). Kâr faktörü tanımsızsa (zararlı işlem yok) en yüksek sayılır ve eşiği geçer (AC-4).

- `select_combination` (R-2) yalnız örneklem içi metrikleri alır: imzası örneklem dışını ve saklı
  dönemi göremez (AC-3). En az 30 işlemli kombinasyonlar arasında en yüksek kâr faktörü; eşitlikte
  örneklem içi net kâr, sonra ızgara sırası (ilk gelen).
- `verdict` (R-3) ilk tutmayan eşiği yazım sırasıyla adlandırır (Risk 5).
- `paper_candidate` (R-4) geçen adaylar arasında min(örneklem içi, örneklem dışı) kâr faktörü en
  yüksek olanı seçer; eşitlikte örneklem dışı net kâr, sonra değerlendirme sırası.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from crytobot.backtest._metrics import PartMetrics

MIN_TRADES: Final = 30
MIN_PROFIT_FACTOR: Final = Decimal("1.2")
MAX_DRAWDOWN: Final = Decimal("0.15")

PASSED: Final = "geçti"
_FAILED = "geçmedi: "
NOT_ENOUGH_TRADES: Final = f"{_FAILED}örneklem içi işlem yetersiz"
OOS_NET: Final = f"{_FAILED}örneklem dışı net kâr"
OOS_PROFIT_FACTOR: Final = f"{_FAILED}örneklem dışı kâr faktörü"
OOS_TRADES: Final = f"{_FAILED}örneklem dışı işlem sayısı"
OOS_DRAWDOWN: Final = f"{_FAILED}örneklem dışı drawdown"
HOLDOUT_NET: Final = f"{_FAILED}saklı dönem net kâr"
HOLDOUT_DRAWDOWN: Final = f"{_FAILED}saklı dönem drawdown"


@dataclass(frozen=True)
class Assessed:
    """Hükmü verilmiş bir aday: seçilen kombinasyonun örneklem içi ve örneklem dışı metrikleri ve
    hüküm. R-4 yalnız geçenler (`verdict == PASSED`) arasında seçer."""

    in_sample: PartMetrics
    out_of_sample: PartMetrics
    verdict: str


def _factor_key(value: Decimal | None) -> tuple[int, Decimal]:
    """Tanımsız kâr faktörü (zararlı işlem yok) her tanımlı değerden yüksektir."""
    return (1, Decimal(0)) if value is None else (0, value)


def select_combination(in_sample: Sequence[PartMetrics]) -> int | None:
    """R-2: seçilen kombinasyonun sırası; en az 30 işlemli yoksa `None`."""
    best: int | None = None
    for index, part in enumerate(in_sample):
        if part.trades < MIN_TRADES:
            continue
        if best is None:
            best = index
            continue
        current = in_sample[best]
        key = (_factor_key(part.profit_factor), part.net)
        if key > (_factor_key(current.profit_factor), current.net):
            best = index  # strict: an equal one keeps the earlier combination
    return best


def _below_factor(value: Decimal | None) -> bool:
    return value is not None and value < MIN_PROFIT_FACTOR


def verdict(out_of_sample: PartMetrics, holdout: PartMetrics) -> str:
    """R-3: `PASSED` ya da ilk tutmayan eşik (örneklem dışı, sonra saklı dönem)."""
    if out_of_sample.net <= 0:
        return OOS_NET
    if _below_factor(out_of_sample.profit_factor):
        return OOS_PROFIT_FACTOR
    if out_of_sample.trades < MIN_TRADES:
        return OOS_TRADES
    if out_of_sample.max_drawdown >= MAX_DRAWDOWN:
        return OOS_DRAWDOWN
    if holdout.net <= 0:
        return HOLDOUT_NET
    if holdout.max_drawdown >= MAX_DRAWDOWN:
        return HOLDOUT_DRAWDOWN
    return PASSED


def _floor_factor(candidate: Assessed) -> tuple[int, Decimal]:
    return min(
        _factor_key(candidate.in_sample.profit_factor),
        _factor_key(candidate.out_of_sample.profit_factor),
    )


def paper_candidate(candidates: Sequence[Assessed]) -> int | None:
    """R-4: paper adayının sırası; geçen yoksa `None`."""
    best: int | None = None
    for index, candidate in enumerate(candidates):
        if candidate.verdict != PASSED:
            continue
        if best is None:
            best = index
            continue
        current = candidates[best]
        key = (_floor_factor(candidate), candidate.out_of_sample.net)
        if key > (_floor_factor(current), current.out_of_sample.net):
            best = index
    return best
