"""Spec 0028 AC-5 (R-3) ve rapor ayrıştırma testleri (plan Adım 1); spec 0040 CB-1, CB-4.

Spec 0042 (plan Risk 8): örnek rapor son değerlendirme biçiminde (kapı yalnız onu okur); assert'ler
aynen. Varsayılan rapor `NOT_FINAL`, "aday yok" `NO_CANDIDATE_MARK`, strateji adı okunur (AC-8)."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from crytobot.backtest import (
    CANDIDATE_MARK,
    CONDITIONS,
    GENERATED_LABEL,
    NOT_ENOUGH_TRADES,
    PASSED,
    CandidateResult,
    ReportFacts,
    ReportReadProblem,
    final_report_text,
    parse_report,
    read_report,
    report_fingerprint,
    report_text,
    run_metrics,
)
from tests.backtest.test_metrics import BTC, DAY1, DAY2, RECORDS
from tests.backtest.test_report import CONDITION_FACTS, GENERATED, HOLDOUT

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
    **CONDITION_FACTS,
    strategy_name="S0",
    holdout_at=HOLDOUT,
)


def sample_report() -> str:
    """Son değerlendirme, tek aday geçti (paper adayı)."""
    return sample_report_with(FACTS)


def sample_report_with(facts: ReportFacts) -> str:
    metrics = run_metrics(Decimal(1000), RECORDS, DAY2, (BTC,), HOLDOUT)
    assert facts.strategy is not None and facts.strategy_name is not None
    result = CandidateResult(
        facts.strategy_name,
        "1h",
        facts.strategy,
        metrics.in_sample,
        metrics.out_of_sample,
        metrics.holdout,
        PASSED,
    )
    return final_report_text(facts, 1, [result], 0, metrics)


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

    # spec 0040: üretim anı, rapor koşulları ve dosyanın ham baytlarının parmak izi
    assert data.generated_at == GENERATED
    assert dict(data.conditions) == {name: Decimal(CONDITION_FACTS[name]) for name in CONDITIONS}
    assert res.sha256 == hashlib.sha256(report_file.read_bytes()).hexdigest()


def _without(report: str, *labels: str) -> str:
    return "".join(
        row for row in report.splitlines(keepends=True) if row.split(":", 1)[0] not in labels
    )


def test_old_header_parses_without_facts() -> None:
    """Spec 0040 CB-4: yeni başlık satırları, spread ve strateji yoksa bozuk değil, boş."""
    old = _without(sample_report(), GENERATED_LABEL, "spread", "strateji", *CONDITIONS)
    res = parse_report(old)
    assert res.problem is None and res.data is not None
    assert res.data.generated_at is None
    assert res.data.spread is None
    assert res.data.strategy is None
    assert dict(res.data.conditions) == {}
    partial = parse_report(_without(sample_report(), "fee", "opening_balance"))
    assert partial.data is not None
    assert set(partial.data.conditions) == set(CONDITIONS) - {"fee", "opening_balance"}


@pytest.mark.parametrize(
    ("row", "replacement"),
    [
        ("fee: 0.001", "fee: bir"),
        ("fee: 0.001", "fee: NaN"),
        ("max_open_positions: 5", "max_open_positions: sNaN"),
        ("üretim anı: 2026-11-01T12:00:00+00:00", "üretim anı: dün"),
        ("üretim anı: 2026-11-01T12:00:00+00:00", "üretim anı: 2026-11-01T12:00:00"),
        ("spread: 0.0005", "spread: Infinity"),
        ("rsi_threshold=70", "rsi_threshold=NaN"),
    ],
)
def test_a_present_but_broken_fact_is_corrupt(row: str, replacement: str) -> None:
    report = sample_report()
    assert row in report
    res = parse_report(report.replace(row, replacement, 1))
    assert res.problem is ReportReadProblem.CORRUPT
    assert res.data is None


def test_generated_at_is_read_as_utc() -> None:
    local = sample_report().replace(
        "üretim anı: 2026-11-01T12:00:00+00:00", "üretim anı: 2026-11-01T15:00:00+03:00"
    )
    res = parse_report(local)
    assert res.data is not None
    assert res.data.generated_at == GENERATED
    assert res.data.generated_at.tzinfo is UTC


def test_fingerprint_is_of_the_raw_bytes_as_read(tmp_path: Path) -> None:
    """Spec 0040 G-1, plan Risk 4: CRLF dosya aynı ayrışır ama parmak izi kendi baytlarınındır."""
    report = sample_report()
    lf, crlf = tmp_path / "lf.txt", tmp_path / "crlf.txt"
    lf.write_bytes(report.encode("utf-8"))
    crlf.write_bytes(report.replace("\n", "\r\n").encode("utf-8"))
    from_lf, from_crlf = read_report(lf), read_report(crlf)
    assert from_lf.data == from_crlf.data
    assert from_lf.sha256 == report_fingerprint(report)
    assert from_crlf.sha256 == hashlib.sha256(crlf.read_bytes()).hexdigest()
    assert from_lf.sha256 != from_crlf.sha256


def test_unreadable_text_still_carries_its_fingerprint(tmp_path: Path) -> None:
    broken = tmp_path / "bozuk.txt"
    broken.write_bytes(b"\xff\xfe bozuk")
    res = read_report(broken)
    assert res.problem is ReportReadProblem.UNREADABLE
    assert res.sha256 == hashlib.sha256(b"\xff\xfe bozuk").hexdigest()


def test_non_final_report_is_named_before_the_mark() -> None:
    """AC-8: varsayılan rapor kapıya giremez; aday işaretinden önce denetlenir."""
    default = report_text(FACTS, run_metrics(Decimal(1000), RECORDS, DAY2, (BTC,)))
    res = parse_report(default)
    assert res.problem is ReportReadProblem.NOT_FINAL
    assert res.detail == "rapor son değerlendirme değil"
    assert res.data is None
    # a default report that somehow carried the mark is still not a final one
    marked = default + f"\n== örneklem dışı — {CANDIDATE_MARK} ==\n== tüm koşu ==\n"
    assert parse_report(marked).problem is ReportReadProblem.NOT_FINAL


def test_no_candidate_final_report_has_no_mark() -> None:
    unselected = CandidateResult("S0", "4h", None, None, None, None, NOT_ENOUGH_TRADES)
    report = final_report_text(FACTS, 1, [unselected], None, None)
    res = parse_report(report)
    assert res.problem is ReportReadProblem.NO_CANDIDATE_MARK
    assert res.detail == "rapor aday işareti taşımıyor"


def test_strategy_name_is_read() -> None:
    res = parse_report(sample_report())
    assert res.data is not None
    assert res.data.strategy_name == "S0"
    assert res.data.strategy is not None and res.data.strategy["fast_period"] == 12
    unnamed = parse_report(sample_report().replace("strateji: S0 fast=", "strateji: fast="))
    assert unnamed.data is not None and unnamed.data.strategy_name is None


# --- spec 0043 (plan Risk 8): adayların parametre satırı yazılır ve okunur ---

CANDIDATE_LINES = {
    "S1": (
        {
            "fast_period": 12,
            "slow_period": 26,
            "rsi_period": 14,
            "rsi_threshold": Decimal("70"),
            "atr_period": 14,
            "k": Decimal("1.5"),
            "r": Decimal("2"),
            "trend_period": 150,
        },
        "strateji: S1 fast=12 slow=26 rsi=14 rsi_threshold=70 atr=14 k=1.5 r=2 trend_period=150",
    ),
    "S2": (
        {"breakout_period": 55, "atr_period": 14, "k": Decimal("3"), "r": Decimal("2")},
        "strateji: S2 breakout_period=55 atr=14 k=3 r=2",
    ),
    "S3": (
        {
            "rsi_period": 14,
            "rsi_threshold": Decimal("35"),
            "atr_period": 14,
            "k": Decimal("2"),
            "r": Decimal("2"),
        },
        "strateji: S3 rsi=14 rsi_threshold=35 atr=14 k=2 r=2",
    ),
}


@pytest.mark.parametrize("name", sorted(CANDIDATE_LINES))
def test_candidate_parameters_round_trip(name: str) -> None:
    """Yeni adaylar yalnız kendi parametrelerini yazar; okuyucu hepsini aynı değerle geri verir.
    S0'ın satırı bugünküyle aynıdır (`test_report.py`)."""
    strategy, line = CANDIDATE_LINES[name]
    facts = replace(FACTS, strategy=strategy, strategy_name=name)
    report = sample_report_with(facts)
    assert line in report.splitlines()
    res = parse_report(report)
    assert res.data is not None and res.data.strategy_name == name
    assert res.data.strategy == strategy
