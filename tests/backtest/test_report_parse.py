"""Spec 0028 AC-5 (R-3) ve rapor ayrıştırma testleri (plan Adım 1)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from crytobot.backtest import (
    CANDIDATE_MARK,
    ReportFacts,
    ReportReadProblem,
    parse_report,
    read_report,
    report_text,
    run_metrics,
)
from tests.backtest.test_metrics import BTC, DAY1, DAY2, RECORDS

FACTS = ReportFacts(
    start=DAY1,
    end=DAY1 + timedelta(days=2),
    candle_interval="1h",
    turn_interval="1h",
    split_at=DAY2,
    pairs=(BTC, "ETH/USDT"),
    downloaded_at=datetime(2026, 2, 1, 12, 30, tzinfo=UTC),
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


def sample_report() -> str:
    return report_text(FACTS, run_metrics(Decimal(1000), RECORDS, DAY2, (BTC,)))


def test_report_candidate_mark_and_existence(tmp_path: Path) -> None:
    """AC-5: Rapor dosyası varlığı ve aday işareti denetimi."""
    # 1. Dosya yok
    missing_read = read_report(tmp_path / "nonexistent.txt")
    assert missing_read.problem is ReportReadProblem.MISSING
    assert missing_read.data is None
    assert "dosyası yok" in (missing_read.detail or "")

    # 2. Dosya boş
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("", encoding="utf-8")
    empty_read = read_report(empty_file)
    assert empty_read.problem is ReportReadProblem.EMPTY
    assert empty_read.data is None
    assert "boş" in (empty_read.detail or "")

    # 3. Aday işareti yok
    valid_text = sample_report()
    no_mark_text = valid_text.replace(CANDIDATE_MARK, "başka metin")
    no_mark_read = parse_report(no_mark_text)
    assert no_mark_read.problem is ReportReadProblem.NO_CANDIDATE_MARK
    assert no_mark_read.data is None
    assert "aday işareti taşımıyor" in (no_mark_read.detail or "")

    # 4. Tamamlanmamış (tüm koşu eksik)
    incomplete_text = valid_text.partition("== tüm koşu ==")[0]
    incomplete_read = parse_report(incomplete_text)
    assert incomplete_read.problem is ReportReadProblem.INCOMPLETE
    assert incomplete_read.data is None

    # 5. Bozuk rapor
    corrupt_read = parse_report("Geçersiz metin\nçöp veri")
    assert corrupt_read.problem is ReportReadProblem.CORRUPT
    assert corrupt_read.data is None


def test_valid_report_parsing(tmp_path: Path) -> None:
    """Geçerli raporun başlık ve aday metriklerinin doğru çıkarımı."""
    report = sample_report()
    report_file = tmp_path / "report.txt"
    report_file.write_text(report, encoding="utf-8")

    res = read_report(report_file)
    assert res.problem is None
    assert res.data is not None

    data = res.data
    assert data.candle_interval == "1h"
    assert data.turn_interval == "1h"
    assert data.pairs == (BTC, "ETH/USDT")
    assert data.spread == Decimal("0.0005")

    # Strateji
    assert data.strategy is not None
    assert data.strategy["fast_period"] == 12
    assert data.strategy["slow_period"] == 26
    assert data.strategy["rsi_period"] == 14
    assert data.strategy["rsi_threshold"] == Decimal("70")
    assert data.strategy["atr_period"] == 14
    assert data.strategy["k"] == Decimal("2")
    assert data.strategy["r"] == Decimal("2")

    # Aday metrikleri
    cand = data.candidate
    assert cand.net == Decimal("9.89000000")
    assert cand.trades == 1
    assert cand.max_drawdown == Decimal("0.000109")
    assert cand.profit_factor is None  # "tanımsız"
