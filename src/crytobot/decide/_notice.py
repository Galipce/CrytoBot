"""Telegram metinleri: her turun tek satırlık özeti ve atlanan tur (spec 0061 CB-3, G-2), geçerli
`al` için ayrıntılı mesaj (spec 0059 R-6); hepsi "paper öncesi" işaretiyle.

Gerekçe Claude'un metnidir, güvenilmeyen girdidir: HTML kaçışıyla ve kısaltılarak girer.
"""

import html
from datetime import datetime, timedelta
from typing import Final

from crytobot.decide._store import Turn
from crytobot.decide._validate import Decision, Status

MARK: Final = "paper öncesi — uygulanmıyor"
_REASON_SHOWN: Final = 160


def _level(value: float | None) -> str:
    return "-" if value is None else f"{value:.8g}"


def buy_notice(decision: Decision, turn: datetime) -> str | None:
    """Geçerli `al` için mesaj; diğerleri için `None`."""
    if decision.status is not Status.BUY or decision.valid_hours is None:
        return None
    until = turn + timedelta(hours=decision.valid_hours)
    reasons = "\n".join(f"• {html.escape(r[:_REASON_SHOWN])}" for r in decision.reasons)
    return (
        f"<b>LLM karar: {html.escape(decision.coin)} al</b> ({MARK})\n"
        f"Giriş: {_level(decision.entry_low)} - {_level(decision.entry_high)}\n"
        f"Stop: {_level(decision.stop)} · Hedef: {_level(decision.target)}\n"
        f"Geçerli: {until.strftime('%Y-%m-%d %H:%M')} UTC'ye kadar"
        f" · Güven: {decision.confidence}/5\n"
        f"{reasons}"
    )


_COUNTED = (Status.BUY, Status.WAIT, Status.INCONSISTENT, Status.SCHEMA, Status.NO_DATA)


def _hour(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%MZ")


def turn_notice(turn: Turn) -> str:
    """Spec 0061 CB-3: kayda yazılan turun tek satırı - an, sonuç, sayılar, `al` coinleri."""
    counts = " ".join(
        f"{status.value.replace(' ', '_')}={sum(d.status is status for d in turn.decisions)}"
        for status in _COUNTED
    )
    buys = [d.coin for d in turn.decisions if d.status is Status.BUY]
    listed = f" ({', '.join(html.escape(coin) for coin in buys)})" if buys else ""
    outcome = html.escape(turn.outcome)
    return f"LLM karar {_hour(turn.at)} · {outcome} · {counts}{listed} · {MARK}"


def skipped_notice(boundary: datetime) -> str:
    """Spec 0061 G-2: geç kalındığı için atlanan tur (kayda yazılmaz)."""
    return f"LLM karar {_hour(boundary)} · tur atlandı (geç kalındı) · {MARK}"
