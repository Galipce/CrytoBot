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


def test_dispatch_avoids_redundant_network_call_when_queue_not_drained() -> None:
    # F-02: Kuyruk boşaltılamadığında yeni mesaj için gereksiz ağ çağrısı yapılmaz,
    # doğrudan kuyruğa eklenir (çift timeout ve FIFO bozulması önlenir).
    transport_calls = 0

    def failing_transport(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        nonlocal transport_calls
        transport_calls += 1
        return 0, "Network unreachable"

    queue = NotificationQueue(maxlen=10)
    service = ReportingService(CONFIG, queue=queue, transport=failing_transport)

    # 1. İlk mesaj: kuyruk boş olduğu için doğrudan gönderilmeye çalışılır (1 çağrı)
    err1 = service.dispatch("Message 1")
    assert err1 == "network_error"
    assert transport_calls == 1
    assert len(service.queue) == 1

    # 2. İkinci mesaj: drain_queue() Message 1'i dener ve başarısız olur (1 çağrı).
    # Message 2 için ağa gitmeden doğrudan kuyruğa ekler (toplam çağrı 2 kalır, 3 olmaz).
    err2 = service.dispatch("Message 2")
    assert err2 == "network_error"
    assert transport_calls == 2
    assert len(service.queue) == 2

    # Sıranın FIFO kaldığı doğrulanır:
    msg1 = service.queue.pop()
    assert msg1 is not None and msg1.text == "Message 1"
    msg2 = service.queue.pop()
    assert msg2 is not None and msg2.text == "Message 2"


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


def _closure(part: Decimal, proceeds: Decimal, realized: Decimal) -> Any:
    from datetime import UTC, datetime

    from crytobot.portfolio import CloseReason, Closure, Position

    at = datetime(2026, 11, 11, tzinfo=UTC)
    position = Position(
        client_order_id="buy-1",
        pair="BTC/USDT",
        amount=Decimal("10"),
        cost_price=Decimal("100"),
        fee=Decimal("0.3"),
        stop=Decimal("90"),
        target=Decimal("110"),
        opened_at=at,
    )
    return Closure(
        client_order_id="cx-buy-1",
        position=position,
        amount=part,
        price=Decimal("110"),
        fee=Decimal("0.1"),
        reason=CloseReason.TARGET,
        closed_at=at,
        proceeds=proceeds,
        realized=realized,
    )


def test_partial_close_notice_shows_part_rate_and_rest() -> None:
    # Spec 0037 R-3, review F-1: kısmi kapanış "KISMEN KAPANDI" der, oran kapanan kısmın
    # maliyetine (300.09) göre hesaplanır ve kalan miktar yazılır; tam kapanış metni değişmez.
    texts: list[str] = []

    def transport(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        texts.append(payload["text"])
        return 200, '{"ok":true}'

    service = ReportingService(CONFIG, transport=transport)
    service.send_close_notice(_closure(Decimal("3"), Decimal("329.9"), Decimal("29.81")))
    service.send_close_notice(_closure(Decimal("10"), Decimal("1099.9"), Decimal("99.6")))

    partial, full = texts
    assert "[POZİSYON KISMEN KAPANDI]" in partial
    assert "+29.81" in partial
    assert "+9.93%" in partial
    assert "Kalan Miktar: <code>7</code>" in partial
    assert "[POZİSYON KAPANDI]" in full
    assert "KISMEN" not in full
    assert "Kalan Miktar" not in full
    assert "+9.96%" in full


# --- spec 0041 CB-5 (G-4): a testnet run labels every Telegram message --------------------------

_PARSE_ERROR = (
    400,
    '{"ok":false,"error_code":400,"description":"Bad Request: can\'t parse entities"}',
)


def test_testnet_label_prefixes_every_message_including_fallback() -> None:
    """Ret, hata, güvenli mod, kill-switch bildirimi; kuyruktan çıkan mesaj ve 400 sonrası düz
    metin yedeği: hepsi `[TESTNET]` ile başlar, önek bir kez yazılır."""
    replies: list[tuple[int, str]] = [(0, "Network unreachable")]
    sent: list[dict[str, Any]] = []

    def transport(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        sent.append(dict(payload))
        return replies.pop(0) if replies else (200, '{"ok":true}')

    service = ReportingService(CONFIG, transport=transport, label="[TESTNET]")

    # queued while the network is down, delivered with the next message
    assert service.send_turn_notice("kill_switch", "", True, "kill-switch devrede") is not None
    queued = service.queue.peek()
    assert queued is not None and queued.text.startswith("[TESTNET] ")
    assert service.send_turn_notice("safe_mode", "BTC/USDT", True, "güvenli mod") is None
    # the HTML attempt fails to parse; the plain-text fallback carries the prefix too
    replies.append(_PARSE_ERROR)
    assert service.send_turn_notice("refusal", "ETH/USDT", True, "<b>ret") is None
    service.send_fill_notice("BTC/USDT", "buy", Decimal(1), Decimal(100), Decimal(90))
    service.send_close_notice(pair="BTC/USDT", reason="stop", realized_pnl=Decimal(-1))
    service.send_daily_summary(date(2026, 11, 12), Decimal(100), Decimal(99))
    service.dispatch("döngü hatası: okuma OSError", parse_mode=None)

    delivered = [m["text"] for m in sent]
    assert len(delivered) >= 8
    assert all(text.startswith("[TESTNET] ") for text in delivered)
    assert not any(text.startswith("[TESTNET] [TESTNET]") for text in delivered)
    fallback = [m for m in sent if "parse_mode" not in m and "ETH/USDT" in m["text"]]
    assert fallback and fallback[0]["text"].startswith("[TESTNET] ")


def test_no_label_no_prefix() -> None:
    """PB-1: mainnet'te (etiket yok) mesaj metni bugünküyle aynıdır."""
    sent: list[str] = []

    def transport(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        sent.append(payload["text"])
        return 200, '{"ok":true}'

    service = ReportingService(CONFIG, transport=transport)

    service.dispatch("düz metin", parse_mode=None)
    service.send_turn_notice("kill_switch", "", True, "kill-switch devrede")

    assert sent[0] == "düz metin"
    assert "TESTNET" not in "".join(sent)
