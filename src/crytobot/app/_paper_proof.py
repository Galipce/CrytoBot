"""BR-10 canlı kapısında paper kanıtı (spec 0038 CB-2…CB-5; plan Adım 4, A-1…A-4).

`check_paper_proof` `start --live`'ın ayar ve rapor kapılarından sonra, kimlik ve yetki
denetiminden (ağa çıkan tek adım) önce çalışır. Paper kanıt deposunu salt okunur açar, hiçbir şey
yazmaz, kilitlemez. Denetim sırası (G-6): aynı dosya → dosya yok → kullanımda → yükleme →
başlatma kayıtları → eşikler (a)…(d) → onay sırası; ilk sorun adıyla döner.

Dosya işi `__main__`'dedir: kilit yoklaması (`is_busy`), aynı dosya (`same_file`) ve mutlak yol
(`resolve`) çağrıyla gelir (plan A-2). Net sonuç ve düşüş `portfolio`'nun gerçekleşmiş kasa
eğrisinden hesaplanır (plan A-1); açık pozisyon eşiğe girmez, yalnız sayısı gösterilir (G-3).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext

from crytobot.app._config import BotConfig
from crytobot.app._stage import StageConfig
from crytobot.persistence import (
    StartRecord,
    StoredState,
    StoreOutcome,
    load_start_records,
    load_store,
)
from crytobot.portfolio import closed_trades, realized_curve

DRAWDOWN_CEILING = Decimal("0.25")  # the same ceiling as the backtest gate (0028 R-4)
_DAY = timedelta(days=1)
_PREPARED_REVISION = 1  # create (0) + opening balance (1): nothing else before the first start


@dataclass(frozen=True)
class PaperProof:
    """Geçen kanıtın başlatma satırına giden özeti (CB-5)."""

    path: str
    days: int
    trades: int
    net: Decimal
    open_positions: int


@dataclass(frozen=True)
class PaperProofResult:
    """`summary` yalnız `passed` iken doludur."""

    passed: bool
    message: str
    summary: PaperProof | None = None


def _refused(message: str) -> PaperProofResult:
    return PaperProofResult(False, message)


def _proof(text: str) -> PaperProofResult:
    return _refused(f"paper kanıtı: {text}")


def _threshold(name: str) -> PaperProofResult:
    return _refused(f"paper eşiği karşılanmadı: {name}")


def _drawdown_exceeds(curve: Sequence[Decimal], limit: Decimal) -> bool:
    """Tepe→dip oranı `limit`'i aşıyor mu (backtest `_drawdown`'un formülü; bölmesiz, tam)."""
    peak = curve[0]
    with localcontext(prec=80):
        for equity in curve:
            peak = max(peak, equity)
            if peak - equity > limit * peak:
                return True
    return False


def _store_problem(loaded_outcome: StoreOutcome, message: str) -> PaperProofResult:
    if loaded_outcome is StoreOutcome.NOT_FOUND:
        return _proof("paper deposu yok")
    if loaded_outcome is StoreOutcome.BUSY:
        return _proof("paper deposu kullanımda")
    if loaded_outcome is StoreOutcome.MODE_MISMATCH:
        return _proof("paper deposu live modunda")
    return _proof(message)


def _history_problem(
    records: Sequence[StartRecord],
    state: StoredState,
    stage: StageConfig,
    resolve: Callable[[str], str],
) -> PaperProofResult | None:
    """CB-3: kayıt yok · deneme var · kayıt eksik (kayıt öncesi geçmiş, G-8) · rapor uyuşmazlığı:
    yol ve spec 0040 CB-5'in parmak izi (parmak izi olmayan eski kayıt da uyuşmaz)."""
    if not records:
        return _proof("başlatma kaydı yok")
    if any(record.trial for record in records):
        return _proof("deneme koşusu var")
    first = records[0].at
    before = (
        records[0].revision > _PREPARED_REVISION
        or any(entry.at < first for entry in state.ledger.entries[1:])
        or (state.last_turn is not None and state.last_turn < first)
    )
    if before:
        return _proof("başlatma kaydı eksik")
    linked = {resolve(record.report_path or "") for record in records}
    if linked != {resolve(stage.report_path)} or any(
        record.report_sha256 != stage.report_sha256 for record in records
    ):
        return _proof("rapor uyuşmazlığı")
    return None


def check_paper_proof(
    stage: StageConfig,
    bot: BotConfig,
    live_store_path: str,
    now: datetime,
    is_busy: Callable[[str], bool],
    *,
    same_file: Callable[[str, str], bool],
    resolve: Callable[[str], str],
) -> PaperProofResult:
    """CB-2…CB-5: paper kanıt deposunu denetler; geçerse özetiyle, geçmezse ilk nedeniyle döner."""
    path = stage.paper_store_path
    if path is None:
        return _refused("ayar eksik: stage.paper_store_path")
    if same_file(path, live_store_path):
        return _proof("paper deposu canlı deponun kendisi")
    loaded = load_store(path, "paper", readonly=True)
    if loaded.outcome is StoreOutcome.NOT_FOUND:
        return _store_problem(loaded.outcome, loaded.message)
    if is_busy(path):
        return _proof("paper deposu kullanımda")
    if loaded.state is None:
        return _store_problem(loaded.outcome, loaded.message)
    if loaded.conflicts:  # plan A-4
        return _proof("depo bozuk (mutabakat tutmuyor)")
    state = loaded.state
    if state.ledger.balance is None:
        return _proof("defter açılmamış")
    started = load_start_records(path, readonly=True)
    if started.outcome is not StoreOutcome.LOADED:
        return _store_problem(started.outcome, started.message)
    history = _history_problem(started.records, state, stage, resolve)
    if history is not None:
        return history

    first, last = started.records[0].at, state.last_turn
    if last is None or last - first < stage.paper_min_days * _DAY:  # (a), G-1: 24 h, UTC
        return _threshold("paper_min_days")
    trades = closed_trades(state.ledger)
    if trades < stage.paper_min_trades:  # (b), G-2
        return _threshold("paper_min_trades")
    curve = realized_curve(state.ledger)
    if not curve:
        return _proof("kasa eğrisi hesaplanamıyor")
    with localcontext(prec=80):
        net = curve[-1] - curve[0]
    if net <= 0:  # (c)
        return _threshold("net kâr sıfırdan büyük olmalı")
    if _drawdown_exceeds(curve, min(bot.turn.limits.max_drawdown, DRAWDOWN_CEILING)):  # (d)
        return _threshold("max_drawdown")

    approved = stage.live_approved_at
    if approved is None:
        return _refused("ayar eksik: stage.live_approved_at")
    # CB-5: a close written after the last mark (mark not written) is still a paper result (F-1)
    result_at = max([last, *(entry.at for entry in state.ledger.entries)])
    if approved <= result_at:  # CB-5
        return _refused("stage.live_approved_at: onay paper sonucundan önce")
    if approved > now:
        return _refused("stage.live_approved_at: onay gelecekte")
    summary = PaperProof(path, (last - first) // _DAY, trades, net, len(state.ledger.positions))
    return PaperProofResult(True, "paper kanıtı geçerli", summary)
