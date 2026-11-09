"""Spec 0031 AC-6, AC-7 (R-5, R-6): Pano durum verisi, açık pozisyonlu/pozisyonsuz ve hata durumları testleri."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from crytobot.app import (
    BotConfig,
    get_dashboard_status,
)
from crytobot.market_data import ReadSettings
from tests.app.helpers import (
    BTC,
    DEPOSIT,
    ETH,
    Bot,
    make_settings,
    opened_store,
    pair_market,
)

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


def test_dashboard_positions_rendering(tmp_path: Path) -> None:
    """AC-6 (R-5): Açık pozisyon varken detaylar, yokken boş liste döner."""
    db_path = opened_store(tmp_path / "bot.db")
    log_path = tmp_path / "crytobot.log"
    config = make_bot_config(db_path, log_path)

    # 1. Pozisyonsuz durum
    code, data = get_dashboard_status(config, clock=lambda: T0, is_running=False)
    assert code == 200
    assert data["positions"] == []
    assert data["is_running"] is False
    assert data["equity"] == float(DEPOSIT)

    # 2. Pozisyon açılıyor
    bot = Bot(db_path, settings=config.turn)
    bot.turn({BTC: pair_market(), ETH: pair_market(closes=[10.0, 10.0, 10.0, 10.0])}, now=T0)

    code, data = get_dashboard_status(config, clock=lambda: T0, is_running=True)
    assert code == 200
    assert data["is_running"] is True
    assert len(data["positions"]) == 1

    pos = data["positions"][0]
    assert pos["pair"] == BTC
    assert pos["direction"] == "ALIM"
    assert pos["amount"] > 0
    assert pos["entry_price"] > 0
    assert pos["current_price"] > 0
    assert pos["stop_loss"] > 0
    assert pos["take_profit"] > 0


def test_dashboard_handles_missing_or_corrupt_store(tmp_path: Path) -> None:
    """AC-7 (R-6): Depo yokken veya bozukken sunucu çökmez, adıyla hata durumu döner."""
    log_path = tmp_path / "crytobot.log"

    # 1. Depo dosyası henüz yokken
    missing_db = tmp_path / "olmayan_depo.db"
    missing_config = make_bot_config(missing_db, log_path)

    code, data = get_dashboard_status(missing_config, clock=lambda: T0, is_running=False)
    assert code == 503
    assert "Depo bulunamadı" in data["error"]
    assert "prepare" in data["error"]

    # 2. Depo dosyası bozukken
    corrupt_db = tmp_path / "bozuk_depo.db"
    corrupt_db.write_bytes(b"bu bir sqlite veritabani degildir ve bozuktur")
    corrupt_config = make_bot_config(corrupt_db, log_path)

    code, data = get_dashboard_status(corrupt_config, clock=lambda: T0, is_running=False)
    assert code == 503
    assert "Depo okunamıyor" in data["error"]

