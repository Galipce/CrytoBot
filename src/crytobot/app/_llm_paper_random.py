"""Eşlenik rastgele giriş (spec 0060 C-5, G-5, R-5, AC-7). Saf, belirlenimli.

LLM'in dolan her işlemi (kapanmış ya da açık) için aynı turda listeden düzgün rastgele bir coin
seçilir; ikiz turun son kapanmış 1h mumunun kapanışından piyasa kararı olarak girer, stop ve hedef
LLM işleminin giriş bölgesi üst ucuna göre yüzde mesafeleriyle konur. Risk modülünün reddettiği,
dolmayan, atlanan ya da ölçülemeyen LLM kararına ikiz kurulmaz. Her tekrar kendi kasasıyla aynı
oynatma çekirdeğinden geçer. Tohum ve tekrar sayısı ön kayıtlıdır; aynı girdiler aynı dağılımı
verir. İkizin giriş mumu yoksa o ikiz kurulmaz (sayılır); çekiliş yine yapılır, sıra kaymaz.
Çekiliş `app`'in izinli modülleriyle belirlenimlidir: tohum, tekrar ve işlemin sırası SHA-256'dan
geçer (`random` kullanılmaz; tests/app/test_boundaries.py).
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from crytobot.app._llm_paper import HOUR, Bars, PaperDecision, PaperTrade, Status, replay
from crytobot.app._llm_paper_config import RANDOM_REPEATS, RANDOM_SEED
from crytobot.risk import PairRules

FILLED = (Status.CLOSED, Status.OPEN)


@dataclass(frozen=True)
class RandomResult:
    """`nets`: her tekrarın kapanmış işlemlerinin net kârı; `missing`: kurulamayan ikiz sayısı."""

    nets: tuple[Decimal, ...]
    missing: int

    def percentile(self, p: int) -> Decimal | None:
        """En yakın sıra yüzdeliği; tekrar yoksa `None`."""
        if not self.nets:
            return None
        ordered = sorted(self.nets)
        rank = max(1, (p * len(ordered) + 99) // 100)
        return ordered[rank - 1]

    def rank_of(self, value: Decimal) -> Decimal | None:
        """`value`'nun altında kalan tekrarların yüzdesi."""
        if not self.nets:
            return None
        below = sum(net < value for net in self.nets)
        return Decimal(below * 100) / Decimal(len(self.nets))


def closed_net(trades: Sequence[PaperTrade]) -> Decimal:
    return sum(
        (t.net for t in trades if t.status is Status.CLOSED and t.net is not None), Decimal(0)
    )


def pick(coins: Sequence[str], repeat: int, index: int) -> str:
    """Tohum, tekrar ve işlemin sırasından belirlenimli, düzgün bir coin."""
    digest = hashlib.sha256(f"{RANDOM_SEED}:{repeat}:{index}".encode()).digest()
    return coins[int.from_bytes(digest[:8], "big") % len(coins)]


def twins(
    trades: Sequence[PaperTrade], bars: Bars, coins: Sequence[str], repeat: int
) -> tuple[list[PaperDecision], int]:
    made: list[PaperDecision] = []
    missing = 0
    filled = [trade for trade in trades if trade.status in FILLED]
    for index, trade in enumerate(filled):
        decision = trade.decision
        coin = pick(coins, repeat, index)
        previous = bars.get(coin, {}).get(decision.turn - HOUR)
        if previous is None:
            missing += 1
            continue
        entry = previous.close
        stop_share = (decision.entry_high - decision.stop) / decision.entry_high
        target_share = (decision.target - decision.entry_high) / decision.entry_high
        made.append(
            PaperDecision(
                decision.turn,
                coin,
                entry,
                entry,
                entry * (1 - stop_share),
                entry * (1 + target_share),
                1,
                market=True,
            )
        )
    made.sort(key=lambda d: (d.turn, d.coin))
    return made, missing


def random_distribution(
    trades: Sequence[PaperTrade],
    bars: Bars,
    rules: Mapping[str, PairRules],
    coins: Sequence[str],
    window: tuple[datetime, datetime, datetime],
    repeats: int = RANDOM_REPEATS,
) -> RandomResult:
    """`window`: (başlangıç, bitiş, ufuk) - LLM oynatmasıyla aynı."""
    start, end, horizon = window
    nets: list[Decimal] = []
    missing = 0
    for repeat in range(repeats):
        decisions, lost = twins(trades, bars, coins, repeat)
        missing += lost
        result = replay(decisions, bars, rules, start, end, horizon)
        nets.append(closed_net(result.trades))
    return RandomResult(tuple(nets), missing)
