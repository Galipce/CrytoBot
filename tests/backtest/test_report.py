"""Spec 0025 AC-9 (R-11, R-12) ve rapor biçimi (plan Risk 9)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crytobot.backtest import (
    ASSUMPTIONS,
    CANDIDATE_MARK,
    ReportFacts,
    money,
    percent,
    ratio,
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
)


def text() -> str:
    return report_text(FACTS, run_metrics(Decimal(1000), RECORDS, DAY2, (BTC,)))


def sections(report: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for block in report.split("\n== ")[1:]:
        title, _, body = block.partition(" ==\n")
        found[title] = body
    return found


def test_report_states_every_assumption_and_marks_only_out_of_sample() -> None:
    """R-11: her varsayım (B-51 dahil), koşu bilgisi; işaret yalnız örneklem dışında."""
    report = text()
    for assumption in ASSUMPTIONS:
        assert f"- {assumption}\n" in report
    assert any(assumption.startswith("B-51:") for assumption in ASSUMPTIONS)
    for fact in (
        "dönem: 2026-01-01T00:00:00+00:00 .. 2026-01-03T00:00:00+00:00 (bitiş hariç)",
        "mum aralığı: 1h",
        "tur aralığı: 1h",
        "ayrım anı: 2026-01-02T00:00:00+00:00",
        "çiftler: BTC/USDT, ETH/USDT",
        "indirme anı: 2026-02-01T12:30:00+00:00",
        "spread: 0.0005",
    ):
        assert fact in report
    assert report.count(CANDIDATE_MARK) == 1
    assert list(sections(report)) == [
        "örneklem içi",
        f"örneklem dışı — {CANDIDATE_MARK}",
        "tüm koşu",
    ]


def test_report_never_says_pass_or_fail() -> None:
    report = text().casefold()
    for word in ("geçti", "kaldı", "başarılı", "başarısız", "onaylandı", "pass", "fail"):
        assert word not in report


def test_each_part_carries_every_metric() -> None:
    """R-10: her parça aynı satırları, aynı sırayla taşır."""
    parts = sections(text())
    labels = [
        [row.split(":", 1)[0] for row in body.strip().splitlines()] for body in parts.values()
    ]
    assert labels[0] == labels[1] == labels[2]
    assert labels[0] == [
        "turlar",
        "başlangıç kasası",
        "bitiş kasası",
        "net kâr/zarar",
        "gerçekleşen kâr/zarar",
        "gerçekleşmemiş kâr/zarar",
        "işlem",
        "kazanma oranı",
        "kâr faktörü",
        "en büyük drawdown",
        "ortalama günlük getiri",
        "ödenen komisyon",
        "ödenen slippage",
        "günlük zarar durdurmalı gün",
        "drawdown durdurması",
        "fiyatı ya da verisi eksik tur (çift başına)",
        "öneri yok (nedene göre)",
        "ret (nedene göre)",
        "gönderilmeyen durum bildirimi (türe göre)",
    ]


def test_out_of_sample_values() -> None:
    body = sections(text())[f"örneklem dışı — {CANDIDATE_MARK}"]
    assert "başlangıç kasası: 999.90000000 USDT\n" in body
    assert "net kâr/zarar: 9.89000000 USDT (getiri %0.9891)\n" in body  # 9.89 / 999.9 = 0.98910 %
    assert "kazanma oranı: %100.0000\n" in body
    assert "kâr faktörü: tanımsız\n" in body
    assert "fiyatı ya da verisi eksik tur (çift başına): BTC/USDT 0\n" in body
    assert "öneri yok (nedene göre): yok\n" in body
    assert "drawdown durdurması: yok\n" in body


def test_in_sample_undefined_rates() -> None:
    body = sections(text())["örneklem içi"]
    assert "kazanma oranı: tanımsız\n" in body
    assert "kâr faktörü: tanımsız\n" in body


def test_report_is_plain_lines_ending_with_newline() -> None:
    report = text()
    assert report.endswith("\n") and not report.endswith("\n\n")
    assert "\r" not in report
    assert report == text()  # the same input gives the same text


def test_number_formats_round_half_even() -> None:
    assert money(Decimal("1.000000005")) == "1.00000000 USDT"
    assert money(Decimal("1.000000015")) == "1.00000002 USDT"
    assert money(Decimal("-0.000000001")) == "0.00000000 USDT"  # never minus zero
    assert money(Decimal(-3)) == "-3.00000000 USDT"
    assert percent(Decimal("0.000000005")) == "%0.0000"
    assert percent(Decimal("0.0000015")) == "%0.0002"
    assert percent(None) == "tanımsız"
    assert ratio(Decimal("2.00005")) == "2.0000"
    assert ratio(None) == "tanımsız"
