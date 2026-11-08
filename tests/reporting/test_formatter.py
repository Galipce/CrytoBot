"""Spec 0029 (AC-3, R-3..R-6): Biçimlendirici ve HTML kaçış testleri."""

from datetime import date
from decimal import Decimal

from crytobot.reporting._formatter import (
    escape_html,
    format_close_notice,
    format_daily_summary,
    format_fill_notice,
    format_turn_notice,
)


def test_turn_notice_escaping_and_fallback() -> None:
    # 1. HTML kaçış kontrolü
    raw = "BTC/USDT: price < 50000 & target > 60000"
    escaped = escape_html(raw)
    assert "<" not in escaped
    assert ">" not in escaped
    assert "&lt;" in escaped
    assert "&gt;" in escaped
    assert "&amp;" in escaped

    # 2. Standart turn notice (entering & exiting)
    notice_in = format_turn_notice("stale_data", "BTC/USDT", True, "Veri 120 saniyedir bayat")
    assert "🔴 <b>[DURUM BAŞLADI]</b>" in notice_in
    assert "<code>stale_data</code>" in notice_in
    assert "BTC/USDT" in notice_in
    assert "Veri 120 saniyedir bayat" in notice_in

    notice_out = format_turn_notice("stale_data", "BTC/USDT", False, "Veri akışı normale döndü")
    assert "🟢 <b>[DURUM DÜZELDİ]</b>" in notice_out

    # 3. Drawdown durdurması (R-4, B-42)
    dd_in = format_turn_notice("drawdown_halt", "", True, "Zirve: 10000, Kasa: 9000, Limit: 0.05")
    assert "🚨 <b>[RİSK DURDURMASI]</b> Drawdown limiti aşıldı!" in dd_in
    assert "Kasa: 9000" in dd_in

    dd_out = format_turn_notice("drawdown_halt", "", False, "Durdurma kaldırıldı")
    assert "🟢 <b>[RİSK DURDURMASI KALKTI]</b>" in dd_out

    # 4. Günlük zarar limiti durdurması (R-4, B-42)
    dl_in = format_turn_notice(
        "daily_loss_limit", "", True, "Gün başı: 10000, Kasa: 9600, Limit: 0.03"
    )
    assert "🚨 <b>[RİSK DURDURMASI]</b> Günlük zarar limiti aşıldı!" in dl_in
    assert "Kasa: 9600" in dl_in

    dl_out = format_turn_notice("daily_loss_limit", "", False, "Yeni gün sıfırlandı")
    assert "🟢 <b>[RİSK DURDURMASI KALKTI]</b> Günlük zarar limiti yeni günde sıfırlandı." in dl_out


def test_format_fill_notice() -> None:
    text = format_fill_notice(
        pair="BTC/USDT",
        side="buy",
        amount=Decimal("0.05"),
        price=Decimal("65000"),
        stop=Decimal("63000"),
    )
    assert "🔵 <b>[İŞLEM DOLUMU]</b> BTC/USDT ALIM" in text
    assert "0.05" in text
    assert "65000" in text
    assert "63000 USDT" in text


def test_format_close_notice() -> None:
    # Kârlı kapanış
    win = format_close_notice(
        pair="ETH/USDT",
        reason="take_profit",
        realized_pnl=Decimal("150.50"),
        pnl_pct=Decimal("3.5"),
    )
    assert "🟢 <b>[POZİSYON KAPANDI]</b> ETH/USDT (take_profit)" in win
    assert "<code>+150.50</code> USDT" in win
    assert "<code>+3.5%</code>" in win

    # Zararlı kapanış
    loss = format_close_notice(
        pair="SOL/USDT",
        reason="stop_loss",
        realized_pnl=Decimal("-45.20"),
        pnl_pct=Decimal("-1.2"),
    )
    assert "🔴 <b>[POZİSYON KAPANDI]</b> SOL/USDT (stop_loss)" in loss
    assert "<code>-45.20</code> USDT" in loss
    assert "<code>-1.2%</code>" in loss


def test_format_daily_summary() -> None:
    today = date(2026, 11, 8)
    summary = format_daily_summary(
        day=today,
        start_equity=Decimal("10000"),
        end_equity=Decimal("12200"),
        realized_pnl=Decimal("2200"),
        pnl_pct=Decimal("22.0"),
        open_positions_count=2,
        closed_trades_count=5,
    )
    assert "📊 <b>[GÜNLÜK ÖZET RAPORU]</b> Tarih: 2026-11-08" in summary
    assert "<code>10000</code> USDT" in summary
    assert "<code>12200</code> USDT" in summary
    assert "<code>+2200</code> USDT" in summary
    assert "Hedef aralığında (%20-25)" in summary
    assert "Açık Pozisyon: 2" in summary
    assert "Tamamlanan İşlem: 5" in summary
