"""Spec 0030 AC-1, AC-3, AC-4, AC-5, AC-6: App kontrol kapıları ve tur davranışı testleri."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from crytobot.app import (
    BotConfig,
    BuyHalt,
    ExitReason,
    TurnOutcome,
    engage_kill_switch,
    query_status,
    request_stop,
    resume_operations,
    run_loop,
)
from crytobot.control import clear_stop_flag, stop_flag_path
from crytobot.execution import OrderStatus
from crytobot.market_data import ReadSettings
from crytobot.risk import ApprovalReason
from tests.app.helpers import (
    BTC,
    DEPOSIT,
    ETH,
    Bot,
    make_settings,
    opened_store,
    pair_market,
)
from tests.app.loop_fakes import Harness

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def make_bot_config(db_path: Path, log_path: Path) -> BotConfig:
    turn_settings = make_settings(whitelist=(BTC, ETH))
    read_settings = ReadSettings(
        "binance",
        timedelta(hours=1),
        4,
        timedelta(seconds=5),
        timedelta(seconds=30),
    )
    return BotConfig(
        store_path=str(db_path),
        log_path=str(log_path),
        turn_interval=timedelta(hours=1),
        opening_balance=DEPOSIT,
        read=read_settings,
        turn=turn_settings,
    )


def test_turn_with_active_kill_switch(tmp_path: Path) -> None:
    """AC-3 (R-5): Kill switch devredeyken yeni alım durur, kapanışlar engellenmez."""
    db_path = opened_store(tmp_path / "bot.db")
    log_path = tmp_path / "crytobot.log"
    config = make_bot_config(db_path, log_path)

    bot = Bot(db_path, settings=config.turn)
    # Tur 1: Normal alım - BTC pozisyonu açılır (fiyat=10.0), ETH flat (sinyal yok)
    res1 = bot.turn({BTC: pair_market(), ETH: pair_market(closes=[10.0, 10.0, 10.0, 10.0])}, now=T0)
    assert res1.outcome is TurnOutcome.COMPLETED
    assert len(res1.buys) == 1
    assert res1.buys[0].status is OrderStatus.FILLED

    # Kill switch devreye alınıyor
    ks_res = engage_kill_switch(config, clock=lambda: T0)
    assert ks_res.success

    # Tur 2: Kill switch devrede. BTC fiyatı stop seviyesine düşüyor (8.0 -> stop tetiklenir).
    # ETH için yeni bir alım fırsatı var.
    t1 = T0 + timedelta(hours=1)
    res2 = bot.turn(
        {
            BTC: pair_market(price=Decimal("7.9"), closed_at=t1),  # stop 8.0'ın altında -> kapanış
            ETH: pair_market(closed_at=t1),  # yeni alım fırsatı (CROSS)
        },
        now=t1,
    )

    assert res2.outcome is TurnOutcome.COMPLETED
    # 1. Açık pozisyon stop kapanışı başarılı (approve_close engellenmedi)
    assert len(res2.closes) == 1
    assert res2.closes[0].pair == BTC

    # 2. Yeni alım önerisi KILL_SWITCH_ACTIVE ile reddedildi
    assert BuyHalt.KILL_SWITCH in res2.halts
    eth_outcome = next((p for p in res2.pairs if p.pair == ETH), None)
    assert eth_outcome is not None
    assert eth_outcome.reason is ApprovalReason.KILL_SWITCH_ACTIVE


def test_query_status_command(tmp_path: Path) -> None:
    """AC-1 (R-1): Durum sorgulama tüm metrikleri doğru basar ve depoyu değiştirmez."""
    db_path = opened_store(tmp_path / "bot.db")
    log_path = tmp_path / "crytobot.log"
    config = make_bot_config(db_path, log_path)

    before_bytes = db_path.read_bytes()
    status_res = query_status(config, clock=lambda: T0)

    assert status_res.success
    msg = status_res.message
    assert "Süreç Durumu: durdu" in msg
    assert "Çalışma Modu: paper" in msg
    assert "Serbest Bakiye: 10000 USDT" in msg
    assert "Toplam Kasa: 10000 USDT" in msg
    assert "Drawdown Oranı: %0.00" in msg
    assert "Aktif Durdurmalar: yok" in msg
    assert "Açık Pozisyonlar (0)" in msg
    assert "Son Tur / Gözlem:" in msg
    # Depo içeriği değişmemiştir
    assert db_path.read_bytes() == before_bytes


def test_engage_and_resume_operations(tmp_path: Path) -> None:
    """AC-2, AC-4, AC-5: Kill switch devreye alma, kaldırma ve ret akışı."""
    db_path = opened_store(tmp_path / "bot.db")
    log_path = tmp_path / "crytobot.log"
    config = make_bot_config(db_path, log_path)

    # Bot en az bir tur atıp kasayı gözlemiş olsun
    bot = Bot(db_path)
    bot.turn({BTC: pair_market()}, now=T0)

    # 1. Devreye alma
    res_ks = engage_kill_switch(config, clock=lambda: T0)
    assert res_ks.success
    status1 = query_status(config, clock=lambda: T0)
    assert "kill switch" in status1.message

    # Zaten devredeyken tekrar devreye alma
    res_ks_again = engage_kill_switch(config, clock=lambda: T0)
    assert res_ks_again.success
    assert "zaten devrede" in res_ks_again.message

    # 2. Kaldırma (resume)
    res_resume = resume_operations(config, clock=lambda: T0)
    assert res_resume.success
    assert "durdurma kaldırıldı" in res_resume.message
    status2 = query_status(config, clock=lambda: T0)
    assert "Aktif Durdurmalar: yok" in status2.message

    # 3. Durdurma yokken resume reddedilir (AC-5)
    res_resume_none = resume_operations(config, clock=lambda: T0)
    assert not res_resume_none.success
    assert "durdurma yok" in res_resume_none.message


def test_request_stop_behavior(tmp_path: Path) -> None:
    """AC-6 (R-4): Çalışmayan botta ret, bayrak ile durdurma ve bayrak temizliği."""
    db_path = opened_store(tmp_path / "bot.db")
    log_path = tmp_path / "crytobot.log"
    config = make_bot_config(db_path, log_path)

    # 1. Bot çalışmıyorken stop reddedilir
    res_stop_idle = request_stop(config, clock=lambda: T0, is_running=False)
    assert not res_stop_idle.success
    assert "çalışan bot süreci yok" in res_stop_idle.message

    # 2. Stop bayrağı varken loop başladığında temiz biçimde çıkar
    flag = stop_flag_path(db_path)
    flag.write_text("stop", encoding="utf-8")
    assert flag.exists()

    harness = Harness(db_path, config)
    if flag.exists():
        harness.stop.request("cli-stop")
    exit_res = run_loop(config, harness.parts())
    assert exit_res.reason is ExitReason.STOPPED
    # Çıkışta bayrak temizlenir
    clear_stop_flag(db_path)
    assert not flag.exists()
