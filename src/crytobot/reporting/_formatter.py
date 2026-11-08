"""Telegram bildirim ve özet rapor metin biçimlendiricileri (spec 0029 R-3..R-6).

Mesajlar HTML parse_mode ile biçimlendirilir. Özel karakterler (`&`, `<`, `>`) katı bir
şekilde kaçırılır.
"""

import html
from datetime import date
from decimal import Decimal


def escape_html(text: str) -> str:
    """HTML parse_mode için özel karakterleri kaçırır (& -> &amp;, < -> &lt;, > -> &gt;)."""
    return html.escape(str(text), quote=False)


def format_turn_notice(kind: str, subject: str, entering: bool, message: str) -> str:
    """Sistem ve risk durum bildirimlerini biçimlendirir (R-3, R-4, B-42)."""
    safe_kind = escape_html(kind)
    safe_subj = f" ({escape_html(subject)})" if subject else ""
    safe_msg = escape_html(message)

    if kind == "drawdown_halt":
        if entering:
            return f"🚨 <b>[RİSK DURDURMASI]</b> Drawdown limiti aşıldı!{safe_subj}\n{safe_msg}"
        return (
            f"🟢 <b>[RİSK DURDURMASI KALKTI]</b> Drawdown durdurması kaldırıldı.{safe_subj}\n"
            f"{safe_msg}"
        )

    if kind == "daily_loss_limit":
        if entering:
            return f"🚨 <b>[RİSK DURDURMASI]</b> Günlük zarar limiti aşıldı!{safe_subj}\n{safe_msg}"
        return (
            "🟢 <b>[RİSK DURDURMASI KALKTI]</b> Günlük zarar limiti yeni günde sıfırlandı."
            f"{safe_subj}\n{safe_msg}"
        )

    if entering:
        return f"🔴 <b>[DURUM BAŞLADI]</b> <code>{safe_kind}</code>{safe_subj}\n{safe_msg}"
    return f"🟢 <b>[DURUM DÜZELDİ]</b> <code>{safe_kind}</code>{safe_subj}\n{safe_msg}"


def format_fill_notice(
    pair: str,
    side: str,
    amount: Decimal,
    price: Decimal,
    stop: Decimal | None = None,
) -> str:
    """Alım/satım emir dolum bildirimini biçimlendirir (R-5)."""
    safe_pair = escape_html(pair)
    side_tr = "ALIM" if side.lower() == "buy" else "SATIŞ"
    stop_text = f"{stop} USDT" if stop is not None else "Yok"
    return (
        f"🔵 <b>[İŞLEM DOLUMU]</b> {safe_pair} {side_tr} gerçekleşti.\n"
        f"• Miktar: <code>{amount}</code>\n"
        f"• Dolum Fiyatı: <code>{price}</code> USDT\n"
        f"• Stop-Loss: <code>{stop_text}</code>"
    )


def format_close_notice(
    pair: str,
    reason: str,
    realized_pnl: Decimal,
    pnl_pct: Decimal,
) -> str:
    """Pozisyon kapanış bildirimini biçimlendirir (R-5)."""
    safe_pair = escape_html(pair)
    safe_reason = escape_html(reason)
    emoji = "🟢" if realized_pnl >= 0 else "🔴"
    sign = "+" if realized_pnl > 0 else ""
    pct_sign = "+" if pnl_pct > 0 else ""
    return (
        f"{emoji} <b>[POZİSYON KAPANDI]</b> {safe_pair} ({safe_reason})\n"
        f"• Gerçekleşen PnL: <code>{sign}{realized_pnl}</code> USDT\n"
        f"• Kâr/Zarar Oranı: <code>{pct_sign}{pnl_pct}%</code>"
    )


def format_daily_summary(
    day: date,
    start_equity: Decimal,
    end_equity: Decimal,
    realized_pnl: Decimal,
    pnl_pct: Decimal,
    open_positions_count: int,
    closed_trades_count: int,
) -> str:
    """UTC gün dönümü performans özet raporunu biçimlendirir (R-6, BR-1)."""
    sign = "+" if realized_pnl > 0 else ""
    pct_sign = "+" if pnl_pct > 0 else ""

    # BR-1: Günlük %20-25 hedef kıyaslaması (karar kuralı değil, salt raporlanan metrik)
    if pnl_pct >= Decimal("25"):
        br1_cmp = "Hedefin üzerinde"
    elif pnl_pct >= Decimal("20"):
        br1_cmp = "Hedef aralığında (%20-25)"
    elif pnl_pct > Decimal("0"):
        br1_cmp = "Kârda (hedefin altında)"
    elif pnl_pct == Decimal("0"):
        br1_cmp = "Başabaş"
    else:
        br1_cmp = "Zararda"

    pnl_line = (
        f"• Net Kâr/Zarar: <code>{sign}{realized_pnl}</code> USDT"
        f" (<code>{pct_sign}{pnl_pct}%</code>)\n"
    )
    return (
        f"📊 <b>[GÜNLÜK ÖZET RAPORU]</b> Tarih: {day.isoformat()}\n"
        f"• Gün Başı Kasa: <code>{start_equity}</code> USDT\n"
        f"• Gün Sonu Kasa: <code>{end_equity}</code> USDT\n"
        f"{pnl_line}"
        f"• BR-1 Kıyaslaması: %20-25 hedef ({br1_cmp})\n"
        f"• Açık Pozisyon: {open_positions_count}\n"
        f"• Tamamlanan İşlem: {closed_trades_count}"
    )
