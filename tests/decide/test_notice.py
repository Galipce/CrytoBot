"""Spec 0059 AC-6: yalnız geçerli `al` bildirilir, "paper öncesi — uygulanmıyor" işaretiyle."""

from crytobot.decide import MARK, Decision, Status, buy_notice
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
