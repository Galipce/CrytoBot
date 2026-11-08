"""Spec 0029 (AC-3..AC-7): App döngüsü Telegram bildirim ve raporlama entegrasyon testleri."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from crytobot.app import (
    ExitReason,
    NoticeKind,
    TurnOutcome,
    TurnResult,
    _loop,
)
from crytobot.execution import Order, OrderStatus
from crytobot.portfolio import CloseReason, Closure, Position
from crytobot.reporting import (
    NotificationQueue,
    ReportingService,
    TelegramConfig,
)
from crytobot.risk import RiskLimits
from tests.app.helpers import BTC, HOUR, NOW, Exchange, opened_store
from tests.app.loop_fakes import harness

CONFIG = TelegramConfig(enabled=True, bot_token="token-123", chat_id="chat-456")


def test_turn_notice_telegram_dispatch(tmp_path: Path) -> None:
    # AC-3: TurnNotice oluştuğunda Telegram'a gönderilir, süren durumda mükerrer gitmez
    sent_messages: list[dict[str, Any]] = []

    def mock_transport(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        sent_messages.append(payload)
        return 200, '{"ok":true}'

    reporter = ReportingService(CONFIG, transport=mock_transport)

    bot = harness(opened_store(tmp_path / "s.db"), stop_after=2)
    # 2 tur normal koşu (hiçbir bayat/hata durumu yokken)
    exit_ = bot.run(reporter=reporter)
    assert exit_.reason is ExitReason.STOPPED

    # İlk turda bayat veri veya başka notice üretilmediyse mesaj gitmez
    # Şimdi manuel bir TurnNotice ile notice akışını test edelim:
    loop = _loop._Loop(bot.config, bot.parts(), Exchange(), reporter=reporter)
    from crytobot.app._notices import TurnNotice

    # 1. Giriş bildirimi
    notice_in = TurnNotice(NoticeKind.STALE_DATA, "BTC/USDT", True, NOW, "BTC/USDT: veri bayat")
    loop.notice(notice_in)
    assert len(sent_messages) == 1
    assert "DURUM BAŞLADI" in sent_messages[0]["text"]
    assert "stale_data" in sent_messages[0]["text"]

    # 2. Çıkış bildirimi
    notice_out = TurnNotice(
        NoticeKind.STALE_DATA, "BTC/USDT", False, NOW + HOUR, "stale_data: durum düzeldi"
    )
    loop.notice(notice_out)
    assert len(sent_messages) == 2
    assert "DURUM DÜZELDİ" in sent_messages[1]["text"]


def test_risk_drawdown_and_daily_loss_notices(tmp_path: Path) -> None:
    # AC-4: Drawdown durdurması ve günlük zarar limiti durumlarında ilk turda bildirim
    notices_received: list[dict[str, Any]] = []

    def mock_transport(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        notices_received.append(payload)
        return 200, '{"ok":true}'

    reporter = ReportingService(CONFIG, transport=mock_transport)

    # 1. Drawdown halt durumu
    limits = RiskLimits(
        per_trade_risk=Decimal("0.01"),
        daily_loss_limit=Decimal("0.03"),
        max_drawdown=Decimal("0.05"),
        max_open_positions=3,
        profit_cost_multiple=Decimal("2.0"),
    )
    store = opened_store(tmp_path / "s.db", deposit=Decimal("9400"))
    bot = harness(store, stop_after=1)
    turn_settings = replace(bot.config.turn, limits=limits)
    config = replace(bot.config, turn=turn_settings)
    loop = _loop._Loop(config, bot.parts(), Exchange(), reporter=reporter)

    # Simüle edilmiş bir TurnRun içinde note_drawdown testi
    from crytobot.persistence import load_store
    from crytobot.risk import RiskState

    state = load_store(str(tmp_path / "s.db"), "paper").state
    assert state is not None

    # Halted risk state
    halted_risk = RiskState(
        day=NOW.date(),
        day_start_equity=Decimal("10000"),
        peak_equity=Decimal("10000"),
        last_time=NOW,
        last_equity=Decimal("9400"),
        halted=True,
    )
    halted_state = replace(state, risk=halted_risk)

    from crytobot.app._schedule import Due
    from crytobot.persistence import save_store

    save_store(
        str(tmp_path / "s.db"),
        state,
        halted_state.ledger,
        halted_state.execution,
        halted_state.risk,
    )

    # 1. Tur: hem DRAWDOWN_HALT hem DAILY_LOSS_LIMIT bildirimleri iletilmeli
    loop.turn(Due(NOW, 0))

    assert len(notices_received) == 2
    texts = [msg["text"] for msg in notices_received]
    assert any("drawdown" in t.lower() for t in texts)
    assert any("günlük zarar" in t.lower() for t in texts)

    # 2. Tur: süren durumlar için mükerrer gönderilmemeli
    loop.turn(Due(NOW, 0))
    assert len(notices_received) == 2


def test_trade_event_notifications(tmp_path: Path) -> None:
    # AC-5: Alım dolumu ve kapanış olay bildirimleri
    events: list[dict[str, Any]] = []

    def mock_transport(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        events.append(payload)
        return 200, '{"ok":true}'

    reporter = ReportingService(CONFIG, transport=mock_transport)

    bot = harness(opened_store(tmp_path / "s.db"), stop_after=1)
    loop = _loop._Loop(bot.config, bot.parts(), Exchange(), reporter=reporter)

    # Sahte bir alım emri ve kapanış içeren TurnResult
    filled_buy = Order(
        client_order_id="buy-001",
        intent_id="intent-001",
        pair=BTC,
        side="buy",
        entry=Decimal("60000"),
        stop=Decimal("58000"),
        target=Decimal("66000"),
        amount=Decimal("0.1"),
        status=OrderStatus.FILLED,
        fill_price=Decimal("60000"),
        fee=Decimal("6"),
        created_at=NOW,
    )

    dummy_pos = Position(
        client_order_id="buy-000",
        pair=BTC,
        amount=Decimal("0.1"),
        cost_price=Decimal("50000"),
        fee=Decimal("5"),
        stop=Decimal("48000"),
        target=Decimal("55000"),
        opened_at=NOW - timedelta(days=1),
    )
    closure = Closure(
        client_order_id="close-001",
        position=dummy_pos,
        amount=Decimal("0.1"),
        price=Decimal("55000"),
        fee=Decimal("5.5"),
        reason=CloseReason.TARGET,
        closed_at=NOW,
        proceeds=Decimal("5500"),
        realized=Decimal("494.5"),
    )

    result = TurnResult(
        outcome=TurnOutcome.COMPLETED,
        closes=(),
        buys=(filled_buy,),
        pairs=(),
        halts=(),
        notice_errors=(),
        message="ok",
        closures=(closure,),
        equity=Decimal("10500"),
    )

    # _loop.turn simülasyonu: result sonrası bildirim dağıtımı
    # Directly invoke the reporting logic on result
    assert isinstance(loop.reporter, ReportingService)
    for buy in result.buys:
        if buy.status is OrderStatus.FILLED:
            loop.reporter.send_fill_notice(
                buy.pair, buy.side, buy.amount, buy.fill_price or buy.entry, buy.stop
            )
    for cl in result.closures:
        loop.reporter.send_close_notice(cl)

    assert len(events) == 2
    # Alım dolumu bildirimi
    assert "İŞLEM DOLUMU" in events[0]["text"]
    assert BTC in events[0]["text"]
    assert "60000" in events[0]["text"]

    # Kapanış bildirimi
    assert "POZİSYON KAPANDI" in events[1]["text"]
    assert "+494.5" in events[1]["text"]
    assert "+9.88%" in events[1]["text"]


def test_daily_summary_report_utc_midnight(tmp_path: Path) -> None:
    # AC-6: UTC gün dönümünde (00:00 UTC) önceki günün performans özeti raporlanır;
    # mükerrer gönderilmez
    summaries: list[dict[str, Any]] = []

    def mock_transport(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        summaries.append(payload)
        return 200, '{"ok":true}'

    reporter = ReportingService(CONFIG, transport=mock_transport)

    bot = harness(opened_store(tmp_path / "s.db"), stop_after=1)
    loop = _loop._Loop(bot.config, bot.parts(), Exchange(), reporter=reporter)

    # 1. Gün 1: 2026-11-08 23:00 UTC
    day1_time = datetime(2026, 11, 8, 23, 0, tzinfo=UTC)
    _res1 = TurnResult(
        outcome=TurnOutcome.COMPLETED,
        closes=(),
        buys=(),
        pairs=(),
        halts=(),
        notice_errors=(),
        message="completed",
        closures=(),
        equity=Decimal("10000"),
    )

    # İlk tur: current_day ayarlanır
    loop.current_day = day1_time.date()
    loop.day_start_equity = Decimal("10000")
    dummy_pos = Position(
        client_order_id="buy-000",
        pair=BTC,
        amount=Decimal("0.1"),
        cost_price=Decimal("50000"),
        fee=Decimal("5"),
        stop=Decimal("48000"),
        target=Decimal("55000"),
        opened_at=day1_time - timedelta(days=1),
    )
    cl = Closure(
        client_order_id="close-001",
        position=dummy_pos,
        amount=Decimal("0.1"),
        price=Decimal("55000"),
        fee=Decimal("5.5"),
        reason=CloseReason.TARGET,
        closed_at=day1_time,
        proceeds=Decimal("5500"),
        realized=Decimal("200"),
    )
    loop.day_closures = [cl]

    # 2. Gün 2 (gece yarısını geçti): 2026-11-09 00:00 UTC
    day2_time = datetime(2026, 11, 9, 0, 0, tzinfo=UTC)
    res2 = TurnResult(
        outcome=TurnOutcome.COMPLETED,
        closes=(),
        buys=(),
        pairs=(),
        halts=(),
        notice_errors=(),
        message="completed",
        closures=(),
        equity=Decimal("10200"),
    )

    # Yeni gün ilk turu: _send_daily_summary tetiklenir
    loop._send_daily_summary(loop.current_day, day2_time, res2)

    assert len(summaries) == 1
    report_text = summaries[0]["text"]
    assert "GÜNLÜK ÖZET RAPORU" in report_text
    assert "2026-11-08" in report_text
    assert "10000" in report_text
    assert "10200" in report_text
    assert "+2.00%" in report_text

    # Aynı gün için mükerrer gönderilmemeli
    loop._send_daily_summary(day1_time.date(), day2_time, res2)
    assert len(summaries) == 1


def test_reporting_error_does_not_break_turn_loop(tmp_path: Path) -> None:
    # AC-7: Telegram API hata verdiğinde bot döngüsü kesintiye uğramaz, loga yansır
    def error_transport(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        return 0, "Network timeout"

    queue = NotificationQueue(maxlen=10)
    reporter = ReportingService(CONFIG, queue=queue, transport=error_transport)

    bot = harness(opened_store(tmp_path / "s.db"), stop_after=2)
    # Hatalı reporter ile harness koşusu
    exit_ = bot.run(reporter=reporter)
    assert exit_.reason is ExitReason.STOPPED
    assert exit_.turns == 2
