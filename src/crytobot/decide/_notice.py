"""Telegram metni (spec 0059 R-6, AC-6): yalnız geçerli `al` kararları, "paper öncesi" işaretiyle.

Gerekçe Claude'un metnidir, güvenilmeyen girdidir: HTML kaçışıyla ve kısaltılarak girer.
"""

import html
from datetime import datetime, timedelta
from typing import Final

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
