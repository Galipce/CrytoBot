"""Durum satırları (spec 0046 R-8, AC-6): ağsız, saf. Ayardaki her kaynak için son başarı, son hata
(adı ve anı), kayıt sayısı; ayrıca toplam kayıt ve boyut. Kayıt boşken bunu söyler."""

from crytobot.news._config import NewsConfig
from crytobot.news._store import SourceSummary, StoreSnapshot

EMPTY = "haber kaydı boş"
NEVER = "hiç başarılı olmadı"


def _source_line(name: str, enabled: bool, summary: SourceSummary | None) -> str:
    state = None if summary is None else summary.state
    success = NEVER
    if state is not None and state.last_success_at is not None:
        success = state.last_success_at.isoformat()
    error = "yok"
    if state is not None and state.last_error is not None and state.last_error_at is not None:
        error = f"{state.last_error}@{state.last_error_at.isoformat()}"
    records = 0 if summary is None else summary.records
    mark = "" if enabled else " (kapalı)"
    return f"kaynak={name}{mark} son_başarı={success} son_hata={error} kayıt={records}"


def status_lines(config: NewsConfig, snapshot: StoreSnapshot | None) -> list[str]:
    """`snapshot` yoksa depo hiç oluşmamıştır."""
    sources = {} if snapshot is None else snapshot.sources
    lines = [
        _source_line(source.name, source.enabled, sources.get(source.name))
        for source in config.sources
    ]
    if snapshot is None or snapshot.records == 0:
        size = 0 if snapshot is None else snapshot.size_bytes
        lines.append(f"{EMPTY} boyut={size} bayt")
        return lines
    lines.append(
        f"toplam: kayıt={snapshot.records} boyut={snapshot.size_bytes} bayt"
        f" ({snapshot.size_bytes / 1024:.1f} KB)"
    )
    return lines
