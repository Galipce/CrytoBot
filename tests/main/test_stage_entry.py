"""Spec 0028 AC-1, AC-2, AC-3, AC-8: BR-10 aşama kapısı CLI ve fail-closed başlatma testleri."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from crytobot.__main__ import EXIT_OK, EXIT_REFUSED
from crytobot.app import TRIAL_MARK
from crytobot.backtest import (
    CANDIDATE_MARK,
    ReportFacts,
    report_text,
    run_metrics,
)
from tests.backtest.test_metrics import BTC, DAY1, DAY2
from tests.main.test_entry import Bot, config_text, event_lines


def make_valid_report_text() -> str:
    """AC-1 için geçerli, tüm eşikleri karşılayan ve adayı olan backtest raporu."""
    facts = ReportFacts(
        start=DAY1,
        end=DAY1 + timedelta(days=10),
        candle_interval="1h",
        turn_interval="1h",
        split_at=DAY2,
        pairs=(BTC, "ETH/USDT"),
        downloaded_at=datetime(2026, 11, 1, tzinfo=UTC),
        candle_count=200,
        spread=Decimal("0.0005"),
        strategy={
            "fast_period": 12,
            "slow_period": 26,
            "rsi_period": 14,
            "rsi_threshold": Decimal("70"),
            "atr_period": 14,
            "k": Decimal("2"),
            "r": Decimal("2"),
        },
    )
    metrics = run_metrics(Decimal(10000), (), DAY2, (BTC, "ETH/USDT"))
    text = report_text(facts, metrics)
    old_part = f"== örneklem dışı — {CANDIDATE_MARK} =="
    new_part = f"""{old_part}
turlar: 120 (ilk 2026-01-02T00:00:00+00:00, son 2026-01-07T00:00:00+00:00)
başlangıç kasası: 10000.00000000 USDT
bitiş kasası: 10500.00000000 USDT
net kâr/zarar: 500.00000000 USDT (getiri %5.0000)
gerçekleşen kâr/zarar: 500.00000000 USDT
gerçekleşmemiş kâr/zarar: 0.00000000 USDT
işlem: 15 (kazanan 10, zararlı 5)
kazanma oranı: %66.6667
kâr faktörü: 2.0000
en büyük drawdown: %4.0000
ortalama günlük getiri: %1.0000
ödenen komisyon: 10.00000000 USDT
ödenen slippage: 10.00000000 USDT
günlük zarar durdurmalı gün: 0
drawdown durdurması: yok
fiyatı ya da verisi eksik tur (çift başına): yok
öneri yok (nedene göre): yok
ret (nedene göre): yok
gönderilmeyen durum bildirimi (türe göre): yok"""
    return text.replace(
        text.partition(old_part)[2].partition("\n== ")[0],
        new_part.partition(old_part)[2],
    )


def test_confirmed_start_happy_path(tmp_path: Path) -> None:
    """AC-1: Mutlu yol — geçerli [stage] ve backtest raporuyla kanıtlı başlatma."""
    report_file = tmp_path / "backtest-report.txt"
    report_file.write_text(make_valid_report_text(), encoding="utf-8")

    stage_toml = f"""
[stage]
report_path = "{report_file.as_posix()}"
approved_by = "Galip Badem"
approved_at = "2026-11-08T12:00:00Z"
min_trades = 10
min_profit_factor = "1.5"
"""
    bot = Bot(tmp_path)
    base_text = config_text(tmp_path)
    (tmp_path / "crytobot.toml").write_text(base_text + stage_toml, encoding="utf-8")

    # Önce hazırlık
    assert bot.run("prepare")[0] == EXIT_OK

    # Kanıtlı başlatma (start, --trial yok)
    code, console = bot.run("start", trial=False)
    assert code == EXIT_OK
    log = bot.log_lines()

    # Başlatma çıktısı onaylayan adını ve rapor yolunu taşır
    (start_line,) = event_lines(console, "başlatma")
    assert "onaylı: onaylayan=Galip Badem" in start_line
    assert f"rapor={report_file.as_posix()}" in start_line
    assert TRIAL_MARK not in start_line

    # Tur özetlerinde TRIAL_MARK yer almaz
    summaries = event_lines(console, "tur")
    assert len(summaries) >= 1
    assert all(TRIAL_MARK not in row for row in summaries)

    # Kayıt dosyasında da TRIAL_MARK yer almaz
    log_text = "\n".join(log)
    assert TRIAL_MARK not in log_text
    assert "onaylı: onaylayan=Galip Badem" in log_text


def test_start_without_stage_refused(tmp_path: Path) -> None:
    """AC-2: Varsayılan başlatmada [stage] veya zorunlu alanlar eksikken ret."""
    bot = Bot(tmp_path)

    # 1. [stage] bölümü hiç yokken varsayılan start
    code, console = bot.run("start", trial=False)
    assert code == EXIT_REFUSED
    assert "başlatma reddedildi: ayar eksik: stage" in console

    # 2. report_path eksik
    stage_no_rp = """
[stage]
approved_by = "Galip"
approved_at = "2026-11-08T12:00:00Z"
"""
    (tmp_path / "crytobot.toml").write_text(config_text(tmp_path) + stage_no_rp, encoding="utf-8")
    code, console = bot.run("start", trial=False)
    assert code == EXIT_REFUSED
    assert "stage.report_path" in console

    # 3. approved_by eksik
    stage_no_ab = """
[stage]
report_path = "rep.txt"
approved_at = "2026-11-08T12:00:00Z"
"""
    (tmp_path / "crytobot.toml").write_text(config_text(tmp_path) + stage_no_ab, encoding="utf-8")
    code, console = bot.run("start", trial=False)
    assert code == EXIT_REFUSED
    assert "stage.approved_by" in console

    # 4. approved_at eksik
    stage_no_at = """
[stage]
report_path = "rep.txt"
approved_by = "Galip"
"""
    (tmp_path / "crytobot.toml").write_text(config_text(tmp_path) + stage_no_at, encoding="utf-8")
    code, console = bot.run("start", trial=False)
    assert code == EXIT_REFUSED
    assert "stage.approved_at" in console


def test_start_trial_mode_skips_gate(tmp_path: Path) -> None:
    """AC-3: crytobot start --trial kapıyı atlar ve TRIAL_MARK taşır."""
    bot = Bot(tmp_path)
    assert bot.run("prepare")[0] == EXIT_OK

    code, console = bot.run("start", "--trial")
    assert code == EXIT_OK

    (start_line,) = event_lines(console, "başlatma")
    assert TRIAL_MARK in start_line
    summaries = event_lines(console, "tur")
    assert summaries and all(TRIAL_MARK in row for row in summaries)


def test_fail_closed_touches_no_store_or_network(tmp_path: Path) -> None:
    """AC-8: Reddedilen başlatmada depo açılmaz, kilit alınmaz, ağa çıkılmaz."""
    bot = Bot(tmp_path)
    store = tmp_path / "bot.db"
    lock = tmp_path / "bot.db.lock"

    code, console = bot.run("start", trial=False)
    assert code == EXIT_REFUSED
    assert "başlatma reddedildi:" in console

    # Depo ve kilit dosyası oluşturulmaz / dokunulmaz
    assert not store.exists()
    assert not lock.exists()

    # Borsaya hiçbir çağrı gitmez
    assert bot.exchange.touched == []
