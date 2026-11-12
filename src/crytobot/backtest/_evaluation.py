"""Strateji değerlendirme kuralı (spec 0042 R-2…R-5; plan Risk 5, 6). Saf hesap.

Eşikler kodda sabittir, ayardan okunmaz (R-3): örneklem dışında net kâr > 0, kâr faktörü ≥ 1.2, en
az 30 kapanmış işlem, en büyük drawdown < %15; saklı dönemde net kâr > 0 ve drawdown < %15 (işlem
asgarisi yok). Karşılaştırma kesin `Decimal` değerlerledir, rapordaki yuvarlanmış metinle değil
(Risk 6). Kâr faktörü tanımsızsa (zararlı işlem yok) en yüksek sayılır ve eşiği geçer (AC-4).

- `select_combination` (R-2) yalnız örneklem içi metrikleri alır: imzası örneklem dışını ve saklı
  dönemi göremez (AC-3). En az 30 işlemli kombinasyonlar arasında en yüksek kâr faktörü; eşitlikte
  örneklem içi net kâr, sonra ızgara sırası (ilk gelen).
- `verdict` (R-3) ilk tutmayan eşiği yazım sırasıyla adlandırır (Risk 5). Spec 0043 R-6 (plan Risk
  6; 0042 R-3/AC-4'ün satır biçimini geçersiz kılar): satır tutmayan değeri ve eşiği de yazar,
  `geçmedi: <eşik> (<değer> <işaret> <eşik değeri>)`; değer rapor biçimiyle (para, oran, yüzde).
  `not_enough_trades` örneklem içi satırıdır; değeri ızgaradaki en yüksek işlem sayısıdır.
- `paper_candidate` (R-4) geçen adaylar arasında min(örneklem içi, örneklem dışı) kâr faktörü en
  yüksek olanı seçer; eşitlikte örneklem dışı net kâr, sonra değerlendirme sırası.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Final

from crytobot.backtest._metrics import PartMetrics
from crytobot.backtest._report import money, percent, ratio

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
_DRAWDOWN_TEXT = f"%{(MAX_DRAWDOWN * 100).normalize():f}"  # "%15"
_FACTOR_PLACES = Decimal("0.0001")  # the report's ratio places (`ratio`)


def _failed(line: str, value: str, sign: str, threshold: object) -> str:
    """R-6: `<satır> (<değer> <işaret> <eşik>)`."""
    return f"{line} ({value} {sign} {threshold})"


def not_enough_trades(in_sample: Sequence[PartMetrics]) -> str:
    """R-6: örneklem içinde 30 işlemli kombinasyon yok; değer ızgaranın en yüksek işlem sayısı."""
    most = max((part.trades for part in in_sample), default=0)
    return _failed(NOT_ENOUGH_TRADES, str(most), "<", MIN_TRADES)


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


def _failing_factor(value: Decimal) -> str:
    """Tutmayan kâr faktörü aşağı kesilir: 1.19996 `1.2000 < 1.2` değil `1.1999 < 1.2` yazılır."""
    return ratio(value.quantize(_FACTOR_PLACES, rounding=ROUND_DOWN))


def verdict(out_of_sample: PartMetrics, holdout: PartMetrics) -> str:
    """R-3: `PASSED` ya da ilk tutmayan eşik (örneklem dışı, sonra saklı dönem); spec 0043 R-6:
    satır değeri ve eşiği taşır. Karar kesin değerledir, yazılan değer rapor biçimindedir."""
    if out_of_sample.net <= 0:
        return _failed(OOS_NET, money(out_of_sample.net), "≤", 0)
    factor = out_of_sample.profit_factor
    if factor is not None and factor < MIN_PROFIT_FACTOR:
        return _failed(OOS_PROFIT_FACTOR, _failing_factor(factor), "<", MIN_PROFIT_FACTOR)
    if out_of_sample.trades < MIN_TRADES:
        return _failed(OOS_TRADES, str(out_of_sample.trades), "<", MIN_TRADES)
    if out_of_sample.max_drawdown >= MAX_DRAWDOWN:
        drawdown = percent(out_of_sample.max_drawdown)
        return _failed(OOS_DRAWDOWN, drawdown, "≥", _DRAWDOWN_TEXT)
    if holdout.net <= 0:
        return _failed(HOLDOUT_NET, money(holdout.net), "≤", 0)
    if holdout.max_drawdown >= MAX_DRAWDOWN:
        return _failed(HOLDOUT_DRAWDOWN, percent(holdout.max_drawdown), "≥", _DRAWDOWN_TEXT)
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
