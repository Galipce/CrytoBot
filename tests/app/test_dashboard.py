"""Spec 0031 AC-6, AC-7 (R-5, R-6): Pano durum verisi, açık pozisyonlu/pozisyonsuz ve
hata durumları testleri.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

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
    positions = data["positions"]
    assert isinstance(positions, list)
    assert len(positions) == 1

    pos = positions[0]
    assert isinstance(pos, dict)
    assert pos["pair"] == BTC
    assert pos["direction"] == "ALIM"
    assert isinstance(pos["amount"], (int, float)) and pos["amount"] > 0
    assert isinstance(pos["entry_price"], (int, float)) and pos["entry_price"] > 0
    assert isinstance(pos["current_price"], (int, float)) and pos["current_price"] > 0
    assert isinstance(pos["stop_loss"], (int, float)) and pos["stop_loss"] > 0
    assert isinstance(pos["take_profit"], (int, float)) and pos["take_profit"] > 0


def test_dashboard_handles_missing_or_corrupt_store(tmp_path: Path) -> None:
    """AC-7 (R-6): Depo yokken veya bozukken sunucu çökmez, adıyla hata durumu döner."""
    log_path = tmp_path / "crytobot.log"

    # 1. Depo dosyası henüz yokken
    missing_db = tmp_path / "olmayan_depo.db"
    missing_config = make_bot_config(missing_db, log_path)

    code, data = get_dashboard_status(missing_config, clock=lambda: T0, is_running=False)
    assert code == 503
    err_missing = data["error"]
    assert isinstance(err_missing, str)
    assert "Depo bulunamadı" in err_missing
    assert "prepare" in err_missing

    # 2. Depo dosyası bozukken
    corrupt_db = tmp_path / "bozuk_depo.db"
    corrupt_db.write_bytes(b"bu bir sqlite veritabani degildir ve bozuktur")
    corrupt_config = make_bot_config(corrupt_db, log_path)

    code, data = get_dashboard_status(corrupt_config, clock=lambda: T0, is_running=False)
    assert code == 503
    err_corrupt = data["error"]
    assert isinstance(err_corrupt, str)
    assert "Depo okunamıyor" in err_corrupt


def test_live_store_status_has_live_mode(tmp_path: Path) -> None:
    """Spec 0035 AC-4 (R-1, R-3): pano canlı depoyu okur, modu `live` döner."""
    import dataclasses

    from tests.app.test_control_live import store_in

    db_path = store_in(tmp_path / "bot.db", "live")
    config = dataclasses.replace(make_bot_config(db_path, tmp_path / "bot.log"), mode="live")
    code, data = get_dashboard_status(config, clock=lambda: T0)
    assert code == 200
    assert data["mode"] == "live"
    assert data["mode_mismatch"] is None
    assert data["free_balance"] == float(DEPOSIT)


def test_mismatch_warning(tmp_path: Path) -> None:
    """Spec 0035 AC-7 (R-2): uyuşmazlıkta pano deponun gerçek modunu ve uyarıyı döner."""
    from tests.app.test_control_live import store_in

    db_path = store_in(tmp_path / "bot.db", "live")
    config = make_bot_config(db_path, tmp_path / "bot.log")  # ayar: paper
    code, data = get_dashboard_status(config, clock=lambda: T0)
    assert code == 200
    assert data["mode"] == "live"
    assert data["mode_mismatch"] == "mod uyuşmazlığı: ayar=paper, depo=live"


def test_api_status_network_only_on_testnet(tmp_path: Path) -> None:
    """Spec 0041 CB-5, G-3: `/api/status` ağı yalnız testnet deposunda taşır; mainnet'te alan
    yoktur, yanıtın geri kalanı aynıdır."""
    import dataclasses

    from tests.app.test_control_live import store_in, store_on_testnet

    testnet_db = store_on_testnet(tmp_path / "tn.db")
    testnet = dataclasses.replace(make_bot_config(testnet_db, tmp_path / "tn.log"), mode="live")
    code, data = get_dashboard_status(testnet, clock=lambda: T0)
    assert code == 200
    assert data["network"] == "testnet"
    assert data["mode"] == "live"

    mainnet_db = store_in(tmp_path / "mn.db", "live")
    mainnet = dataclasses.replace(make_bot_config(mainnet_db, tmp_path / "mn.log"), mode="live")
    code, plain = get_dashboard_status(mainnet, clock=lambda: T0)
    assert code == 200
    assert "network" not in plain
    assert {key: value for key, value in data.items() if key != "network"} == plain
