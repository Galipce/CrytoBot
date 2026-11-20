"""Spec 0059 AC-6: yalnız geçerli `al` bildirilir, "paper öncesi — uygulanmıyor" işaretiyle."""

from crytobot.decide import (
    MARK,
    PROMPT_FINGERPRINT,
    Decision,
    Status,
    Turn,
    buy_notice,
    skipped_notice,
    turn_notice,
)
from tests.decide.helpers import BOUNDARY


def test_only_valid_buy_notified_marked() -> None:
    buy = Decision("SOL", Status.BUY, 98.0, 100.0, 95.0, 105.0, 4, 3, ("rsi <b>yüksek</b>",))
    text = buy_notice(buy, BOUNDARY)
    assert text is not None
    assert MARK == "paper öncesi — uygulanmıyor" and MARK in text
    assert "SOL al" in text and "Giriş: 98 - 100" in text and "Stop: 95" in text
    assert "Hedef: 105" in text and "2026-11-20 14:00 UTC'ye kadar" in text and "3/5" in text
    assert "&lt;b&gt;yüksek&lt;/b&gt;" in text  # Claude's text is escaped
    for status in (Status.WAIT, Status.INCONSISTENT, Status.SCHEMA, Status.NO_DATA):
        assert buy_notice(Decision("SOL", status, 98.0, 100.0, 95.0, 105.0, 4, 3), BOUNDARY) is None


def test_turn_notice() -> None:
    """Spec 0061 CB-3: an, sonuç, sayılar, `al` coinleri, işaret; tek satır."""
    decisions = (
        Decision("SOL", Status.BUY, 98.0, 100.0, 95.0, 105.0, 4, 3, ("a",)),
        Decision("ETH", Status.WAIT),
        Decision("ADA", Status.INCONSISTENT, reason="stop"),
        Decision("TRX", Status.NO_DATA, reason="veri yok"),
    )
    text = turn_notice(Turn(BOUNDARY, "m", PROMPT_FINGERPRINT, None, "ok", True, decisions))
    assert text == (
        "LLM karar 2026-11-20 10:00Z · ok · al=1 bekle=1 tutarsız=1 şema_dışı=0 veri_yok=1 (SOL)"
        f" · {MARK}"
    )
    assert "\n" not in text


def test_skipped_notice() -> None:
    assert (
        skipped_notice(BOUNDARY)
        == f"LLM karar 2026-11-20 10:00Z · tur atlandı (geç kalındı) · {MARK}"
    )
