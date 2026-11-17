"""Skorlayıcının durumu (spec 0051 R-9, AC-9). Saf: kayıtların okunmuş hâlini satırlara çevirir;
ağa, LLM'e ve kilide dokunmaz. Kayıt yoksa "henüz skor yok"."""

from collections.abc import Sequence
from datetime import datetime

from crytobot.news._score_config import ScoreConfig
from crytobot.news._score_prompt import DIRECTIONS, SEVERITIES
from crytobot.news._score_store import ResultKind, ScoreSnapshot
from crytobot.news._store import ForwardItem

NO_SCORES = "henüz skor yok"


def score_status_lines(
    config: ScoreConfig,
    snapshot: ScoreSnapshot | None,
    forward: Sequence[ForwardItem] | None,
) -> list[str]:
    """`forward`: başlangıç anından sonra görülen haberler; haber kaydı yoksa `None`."""
    head = f"skor kaydı: {config.store_path} model={config.model}"
    if snapshot is None:
        return [head, NO_SCORES]
    counts = {kind: snapshot.results.get(kind.value, 0) for kind in ResultKind}
    if forward is None:
        pending = "bilinmiyor (haber kaydı yok)"
    else:
        pending = str(sum(item.record_id not in snapshot.resulted_ids for item in forward))
    scores = sum(snapshot.scores.values())
    grid = " ".join(
        f"{direction}/{severity}={snapshot.scores.get((direction, severity), 0)}"
        for direction in DIRECTIONS
        for severity in SEVERITIES
    )
    rejected = sum(snapshot.rejections.values())
    reasons = "".join(f" {reason}={count}" for reason, count in sorted(snapshot.rejections.items()))
    last: datetime | None = snapshot.last_scored_at
    return [
        head,
        f"başlangıç anı: {snapshot.started_at.isoformat()}",
        f"haber: skorlandı={counts[ResultKind.SCORED]} şema_dışı={counts[ResultKind.SCHEMA]}"
        f" bayat={counts[ResultKind.STALE]} bekleyen={pending}",
        f"olay skoru: toplam={scores} {grid}",
        f"reddedilen olay skoru: toplam={rejected}{reasons}",
        f"bugünkü çağrı (UTC): {snapshot.calls_today}/{config.daily_call_limit}",
        f"son başarılı skor: {'yok' if last is None else last.isoformat()}",
        f"son hata: {snapshot.last_error or 'yok'}",
    ]
