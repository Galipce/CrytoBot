"""Spec 0029 (AC-7, AC-8, R-7, R-8): ReportingService ve hata izolasyon testleri."""

from datetime import date
from decimal import Decimal
from typing import Any

from crytobot.reporting import (
    NotificationQueue,
    ReportingService,
    TelegramConfig,
)

CONFIG = TelegramConfig(enabled=True, bot_token="token123", chat_id="chat456")


def test_module_boundaries_and_no_direct_network() -> None:
    # AC-8: ReportingService enjekte edilebilir transport ile çalışır, testlerde sokete çıkmaz
    sent_payloads: list[dict[str, Any]] = []

    def mock_transport(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        sent_payloads.append(payload)
        return 200, '{"ok":true}'

    service = ReportingService(CONFIG, transport=mock_transport)
    assert service.is_active

    err = service.send_turn_notice("stale_data", "BTC/USDT", True, "Stale for 60s")
    assert err is None
    assert len(sent_payloads) == 1
    assert "BTC/USDT" in sent_payloads[0]["text"]
    assert len(service.queue) == 0


def test_service_fail_safe_network_error_and_queue_drain() -> None:
    # AC-7: Ağ hatası oluştuğunda istisna fırlatmaz, mesajı kuyruğa alır ve hata adını döner
    network_ok = False
    sent_texts: list[str] = []

    def flaky_transport(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        if not network_ok:
            return 0, "Network unreachable"
        sent_texts.append(payload["text"])
        return 200, '{"ok":true}'

    queue = NotificationQueue(maxlen=10)
    service = ReportingService(CONFIG, queue=queue, transport=flaky_transport)

    # 1. Ağ kapalı iken 3 bildirim gönder
    err1 = service.send_turn_notice("reconciliation", "", True, "Mismatch 5.0")
    assert err1 == "network_error"
    assert len(service.queue) == 1

    err2 = service.send_fill_notice(
        pair="ETH/USDT",
        side="buy",
        amount=Decimal("1.5"),
        price=Decimal("3000"),
        stop=Decimal("2900"),
    )
    assert err2 == "network_error"
    assert len(service.queue) == 2

    err3 = service.send_close_notice(
        pair="BTC/USDT",
        reason="take_profit",
        realized_pnl=Decimal("250"),
        pnl_pct=Decimal("2.5"),
    )
    assert err3 == "network_error"
    assert len(service.queue) == 3

    assert len(sent_texts) == 0

    # 2. Ağ geri geldiğinde yeni bir bildirim (örn. günlük rapor) gönderildiğinde kuyruk eritilir
    network_ok = True
    err4 = service.send_daily_summary(
        day=date(2026, 11, 8),
        start_equity=Decimal("10000"),
        end_equity=Decimal("10250"),
        realized_pnl=Decimal("250"),
        pnl_pct=Decimal("2.5"),
        open_positions_count=1,
        closed_trades_count=2,
    )
    assert err4 is None
    # Kuyruktaki 3 mesaj + yeni günlük rapor gönderilmiş olmalı (toplam 4)
    assert len(service.queue) == 0
    assert len(sent_texts) == 4
    assert "reconciliation" in sent_texts[0]
    assert "ETH/USDT" in sent_texts[1]
    assert "BTC/USDT" in sent_texts[2]
    assert "GÜNLÜK ÖZET RAPORU" in sent_texts[3]


def test_service_disabled_config_is_noop() -> None:
    disabled_config = TelegramConfig(enabled=False, bot_token="", chat_id="")
    called = False

    def transport(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        nonlocal called
        called = True
        return 200, "{}"

    service = ReportingService(disabled_config, transport=transport)
    assert not service.is_active

    err = service.send_turn_notice("stale_data", "", True, "Message")
    assert err is None
    assert not called
    assert len(service.queue) == 0
