"""`decide status` satırları (spec 0059 R-7, AC-7). Saf: kaydın okunmuş hâlini satırlara çevirir."""

from datetime import date

from crytobot.decide._config import DecideConfig
from crytobot.decide._store import DecideSnapshot, statuses

NO_TURNS = "henüz tur yok"


def _level(value: float | None) -> str:
    return "-" if value is None else f"{value:.8g}"


def decide_status_lines(
    config: DecideConfig, snapshot: DecideSnapshot | None, today: date
) -> list[str]:
    head = f"karar kaydı: {config.store_path} model={config.model}"
    if snapshot is None or not snapshot.turns:
        return [head, NO_TURNS]
    lines = [
        head,
        f"bugünkü çağrı (UTC {today.isoformat()}):"
        f" {snapshot.calls_today}/{config.daily_call_limit}",
    ]
    lines.append("son turlar:")
    for turn in snapshot.turns:
        why = "" if turn.reason is None else f" neden={turn.reason}"
        lines.append(
            f"  {turn.at.isoformat()} sonuç={turn.outcome}"
            f" çağrı={'var' if turn.called else 'yok'}{why}"
        )
    lines.append("coin başına son karar:")
    for d in snapshot.latest:
        if d.status == "al":
            detail = (
                f" giriş={_level(d.entry_low)}-{_level(d.entry_high)} stop={_level(d.stop)}"
                f" hedef={_level(d.target)}"
            )
        else:
            detail = "" if d.reason is None else f" neden={d.reason}"
        lines.append(f"  {d.coin}: {d.status} ({d.at.isoformat()}){detail}")
    counts = (f"{name.replace(' ', '_')}={snapshot.counts.get(name, 0)}" for name in statuses())
    lines.append("toplam: " + " ".join(counts))
    return lines
