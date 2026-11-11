"""Konsol ve kayıt satırlarının metni (spec 0022 R-13, R-14; plan Risk 13).

Satır: `<UTC ISO an> <olay> <metin>`. İstisna metni hiçbir satıra girmez, yalnız tip adı (R-15):
metin sır taşıyabilir. Başlatma satırı ve her tur özeti deneme işaretini taşır (BR-10).
"""

from datetime import UTC, datetime, timedelta

from crytobot.app._notices import TurnNotice
from crytobot.app._paper_proof import PaperProof
from crytobot.app._result import TurnResult
from crytobot.market_data import CANDLE_INTERVALS, InputProblem

TRIAL_MARK = "BR-10 öncesi deneme, strateji kanıtı değil"


def stamp(at: object) -> str:
    """UTC ISO, saniyeye kadar; zaman olmayan değer `-` yazılır."""
    if not (isinstance(at, datetime) and at.utcoffset() is not None):
        return "-"
    return at.astimezone(UTC).isoformat(timespec="seconds")


def line(at: object, event: str, text: str) -> str:
    return f"{stamp(at)} {event} {text}"


def start_text(
    interval: timedelta,
    store_path: str,
    whitelist: tuple[str, ...],
    *,
    trial: bool = True,
    approved_by: str | None = None,
    report_path: str | None = None,
    paper_proof: PaperProof | None = None,
) -> str:
    """Spec 0038 CB-5: geçen canlı başlatmada satır paper kanıtını taşır; paper satırı aynıdır."""
    every = CANDLE_INTERVALS.get(interval, "?")
    pairs = ",".join(whitelist)
    prefix = f"başladı: mod=paper aralık={every} depo={store_path} çiftler={pairs}"
    if trial or approved_by is None or report_path is None:
        return f"{prefix} — {TRIAL_MARK}"
    text = f"{prefix} onaylı: onaylayan={approved_by} rapor={report_path}"
    if paper_proof is None:
        return text
    proof = paper_proof
    return (
        f"{text} paper={proof.path} gün={proof.days} işlem={proof.trades} net={proof.net}"
        f" açık={proof.open_positions}"
    )


def turn_text(
    result: TurnResult,
    at: object,
    missed: int,
    banned: bool,
    *,
    trial: bool = True,
) -> str:
    halts = ",".join(halt.value for halt in result.halts) or "-"
    data = " veri=yasak" if banned else ""
    suffix = f" — {TRIAL_MARK}" if trial else ""
    return (
        f"tur: an={stamp(at)} sonuç={result.outcome.value} kaçan_sınır={missed}"
        f" alım={len(result.buys)} kapanış={len(result.closes)} durdurma={halts}{data}"
        f" ({result.message}){suffix}"
    )


def notice_text(notice: TurnNotice) -> str:
    state = "başladı" if notice.entering else "bitti"
    subject = f" {notice.subject}" if notice.subject else ""
    return f"durum {state}: {notice.kind.value}{subject} — {notice.message}"


def read_refused_text(problem: InputProblem | None) -> str:
    name = "clock" if problem is None else problem.value
    return f"okuma reddedildi: {name}; tur atılmadı, döngü duruyor (yeniden başlatmayı insan yapar)"


def ban_started_text(until: datetime, reported: bool) -> str:
    if reported:
        return f"borsa yasağı başladı: bitiş {stamp(until)}; o ana kadar borsaya istek gitmez"
    return f"borsa yasağı başladı: bitiş bildirilmedi; sonraki okuma en erken {stamp(until)}"


def ban_ended_text(until: datetime) -> str:
    return f"borsa yasağı bitti: bitiş {stamp(until)}; okuma yeniden yapılıyor"


def error_text(step: str, error: BaseException) -> str:
    return f"döngü hatası: {step} {type(error).__name__}"


def stop_text(reason: str, last: TurnResult | None, turns: int) -> str:
    result = "yok" if last is None else last.outcome.value
    return f"durdu: neden={reason} son_tur={result} tur_sayısı={turns}"
