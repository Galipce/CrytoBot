"""Spec 0025 AC-9 (R-11, R-12) ve rapor biçimi (plan Risk 9); spec 0040 CB-2, CB-3, PB-3.

Spec 0042 R-1 (plan Risk 3): örneklem dışı ve tüm koşu bölümlerini denetleyen testler son
değerlendirme raporuna (`final_text`) taşındı, assert'leri aynen; varsayılan rapor yalnız örneklem
içini yazar (AC-1)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from crytobot.backtest import (
    ASSUMPTIONS,
    CANDIDATE_MARK,
    CONDITIONS,
    FINAL_TITLE,
    NOT_ENOUGH_TRADES,
    OOS_NET,
    PASSED,
    TITLE,
    CandidateResult,
    ReportFacts,
    final_report_text,
    money,
    percent,
    ratio,
    report_text,
    run_metrics,
)
from tests.backtest.test_metrics import BTC, DAY1, DAY2, RECORDS

GENERATED = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
# spec 0040: generation time and the report conditions (the test bot's settings, tests.app)
CONDITION_FACTS: dict[str, Any] = {
    "generated_at": GENERATED,
    "fee": Decimal("0.001"),
    "slippage": Decimal("0.001"),
    "per_trade_risk": Decimal("0.01"),
    "daily_loss_limit": Decimal("0.03"),
    "max_drawdown": Decimal("0.15"),
    "max_open_positions": 5,
    "profit_cost_multiple": Decimal("2"),
    "opening_balance": Decimal("10000"),
}

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
    **CONDITION_FACTS,
)


STRATEGY: dict[str, int | Decimal | str] = {
    "fast_period": 12,
    "slow_period": 26,
    "rsi_period": 14,
    "rsi_threshold": Decimal("70"),
    "atr_period": 14,
    "k": Decimal("2"),
    "r": Decimal("2"),
}
HOLDOUT = DAY2 + timedelta(hours=2)  # after the last record: the earlier parts are as before
FINAL_FACTS = replace(FACTS, strategy=STRATEGY, strategy_name="S0", holdout_at=HOLDOUT)


def text() -> str:
    return report_text(FACTS, run_metrics(Decimal(1000), RECORDS, DAY2, (BTC,)))


def final_metrics() -> Any:
    return run_metrics(Decimal(1000), RECORDS, DAY2, (BTC,), HOLDOUT)


def passed(name: str = "S0", interval: str = "1h", verdict: str = PASSED) -> CandidateResult:
    metrics = final_metrics()
    return CandidateResult(
        name, interval, STRATEGY, metrics.in_sample, metrics.out_of_sample, metrics.holdout, verdict
    )


def final_text() -> str:
    """Tek aday, geçti: paper adayı odur."""
    return final_report_text(FINAL_FACTS, 1, [passed()], 0, final_metrics())


def period_sections(report: str) -> dict[str, str]:
    return {title: body for title, body in sections(report).items() if not title.startswith("aday")}


def sections(report: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for block in report.split("\n== ")[1:]:
        title, _, body = block.partition(" ==\n")
        found[title] = body
    return found


def test_report_states_every_assumption_and_marks_only_out_of_sample() -> None:
    """R-11: her varsayım (boşluklu düşüş dahil, F-11), koşu bilgisi; işaret örneklem dışında.
    Spec 0042: son değerlendirmede; saklı dönem bölümü örneklem dışından sonra gelir."""
    report = final_text()
    for assumption in ASSUMPTIONS:
        assert f"- {assumption}\n" in report
    assert any("boşluklu düşüş hesaba katılmaz" in assumption for assumption in ASSUMPTIONS)
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
    assert list(period_sections(report)) == [
        "örneklem içi",
        f"örneklem dışı — {CANDIDATE_MARK}",
        "saklı dönem",
        "tüm koşu",
    ]


def test_report_never_says_pass_or_fail() -> None:
    report = text().casefold()
    for word in ("geçti", "kaldı", "başarılı", "başarısız", "onaylandı", "pass", "fail"):
        assert word not in report


def test_each_part_carries_every_metric() -> None:
    """R-10: her parça aynı satırları, aynı sırayla taşır (spec 0042: saklı dönem dahil)."""
    parts = period_sections(final_text())
    labels = [
        [row.split(":", 1)[0] for row in body.strip().splitlines()] for body in parts.values()
    ]
    assert labels[0] == labels[1] == labels[2] == labels[3]
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
    body = sections(final_text())[f"örneklem dışı — {CANDIDATE_MARK}"]
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


def header(report: str) -> list[str]:
    return report.partition("\n\nvarsayımlar:")[0].splitlines()


def test_header_carries_generated_at() -> None:
    """Spec 0040 CB-2, CB-3: üretim anı ve rapor koşulları başlığın sonuna, sabit sırayla."""
    rows = header(text())
    assert rows[-9:] == [
        "üretim anı: 2026-11-01T12:00:00+00:00",
        "fee: 0.001",
        "slippage: 0.001",
        "per_trade_risk: 0.01",
        "daily_loss_limit: 0.03",
        "max_drawdown: 0.15",
        "max_open_positions: 5",
        "profit_cost_multiple: 2",
        "opening_balance: 10000",
    ]
    assert [row.split(":", 1)[0] for row in rows[-8:]] == list(CONDITIONS)


def test_generated_at_is_written_in_utc() -> None:
    local = GENERATED.astimezone(timezone(timedelta(hours=3)))
    metrics = run_metrics(Decimal(1000), (), DAY2, (BTC,))
    report = report_text(replace(FACTS, generated_at=local), metrics)
    assert "üretim anı: 2026-11-01T12:00:00+00:00\n" in report


def test_only_the_generation_line_differs_between_moments() -> None:
    """Spec 0040, 0025 R-12 (plan Risk 1): farklı üretim anı → yalnız o satır farklı."""
    metrics = run_metrics(Decimal(1000), RECORDS, DAY2, (BTC,))
    first = report_text(FACTS, metrics).splitlines()
    later = report_text(replace(FACTS, generated_at=GENERATED + timedelta(hours=5)), metrics)
    differing = [
        (old, new) for old, new in zip(first, later.splitlines(), strict=True) if old != new
    ]
    assert differing == [
        ("üretim anı: 2026-11-01T12:00:00+00:00", "üretim anı: 2026-11-01T17:00:00+00:00")
    ]


def test_existing_header_rows_keep_their_order() -> None:
    """PB-3: mevcut satırlar yerinde; yeni satırlar yalnız eklenir."""
    rows = header(text())
    assert [row.split(":", 1)[0] for row in rows[:-9]] == [
        "CrytoBot backtest raporu",
        "dönem",
        "mum aralığı",
        "tur aralığı",
        "ayrım anı",
        "çiftler",
        "indirme anı",
        "ısınma mumu (candle_count)",
        "spread",
    ]


# --- spec 0042 AC-1, AC-6: iki biçim ---


def test_default_report_shows_in_sample_only() -> None:
    """AC-1: varsayılan rapor yalnız örneklem içi; örneklem dışı ya da saklı dönemden rakam yok."""
    report = text()
    assert report.splitlines()[0] == TITLE
    assert list(sections(report)) == ["örneklem içi"]
    assert CANDIDATE_MARK not in report
    assert "saklı dönem" not in report and "tüm koşu" not in report
    assert "örneklem dışı" not in report
    assert "geçti" not in report and "geçmedi" not in report
    assert "9.89000000" not in report  # the out-of-sample net
    assert "1009.79000000" not in report  # the run's end


def test_final_report_has_three_sections() -> None:
    """AC-1: son değerlendirme başlığında belirtilir; üç dönem ayrı bölümlerde."""
    report = final_text()
    rows = report.splitlines()
    assert rows[0] == FINAL_TITLE
    assert "saklı dönem başı: 2026-01-02T02:00:00+00:00 (bu an ve sonrası)" in rows
    assert "strateji: S0 fast=12 slow=26 rsi=14 rsi_threshold=70 atr=14 k=2 r=2" in rows
    assert "sınanan kombinasyon: 1" in rows
    assert "paper adayı: S0 1h" in rows
    titles = list(sections(report))
    assert titles == [
        "aday: S0 1h",
        "örneklem içi",
        f"örneklem dışı — {CANDIDATE_MARK}",
        "saklı dönem",
        "tüm koşu",
    ]
    held = sections(report)["saklı dönem"]
    assert "turlar: 0 (ilk -, son -)\n" in held
    assert "başlangıç kasası: 1009.79000000 USDT\n" in held


def test_final_header_keeps_the_shared_rows_in_order() -> None:
    rows = header(final_text())
    assert [row.split(":", 1)[0] for row in rows] == [
        FINAL_TITLE,
        "dönem",
        "mum aralığı",
        "tur aralığı",
        "ayrım anı",
        "saklı dönem başı",
        "çiftler",
        "indirme anı",
        "ısınma mumu (candle_count)",
        "spread",
        "strateji",
        "üretim anı",
        *CONDITIONS,
        "sınanan kombinasyon",
        "paper adayı",
    ]


def test_candidate_section_writes_setting_periods_and_verdict() -> None:
    """R-3, Risk 6: hüküm, dayandığı değerlerin yanında."""
    body = sections(final_text())["aday: S0 1h"]
    assert body.splitlines() == [
        "seçilen ayar: fast=12 slow=26 rsi=14 rsi_threshold=70 atr=14 k=2 r=2",
        "örneklem içi: işlem 0, kâr faktörü tanımsız, net kâr/zarar -0.10000000 USDT,"
        " en büyük drawdown %0.0100",
        "örneklem dışı: işlem 1, kâr faktörü tanımsız, net kâr/zarar 9.89000000 USDT,"
        " en büyük drawdown %0.0109",
        "saklı dönem: işlem 0, kâr faktörü tanımsız, net kâr/zarar 0.00000000 USDT,"
        " en büyük drawdown %0.0000",
        "sonuç: geçti",
    ]


def test_no_candidate_report_has_only_the_shared_header() -> None:
    """AC-6: hiçbiri geçmezse "aday yok"; başlık yalnız ortak bilgiler; dönem bölümü yok."""
    metrics = final_metrics()
    unselected = CandidateResult("S0", "1h", None, None, None, None, NOT_ENOUGH_TRADES)
    failed = CandidateResult(
        "S0", "4h", STRATEGY, metrics.in_sample, metrics.out_of_sample, metrics.holdout, OOS_NET
    )
    report = final_report_text(FINAL_FACTS, 2, [unselected, failed], None, None)
    assert header(report) == [
        FINAL_TITLE,
        "spread: 0.0005",
        "üretim anı: 2026-11-01T12:00:00+00:00",
        "fee: 0.001",
        "slippage: 0.001",
        "per_trade_risk: 0.01",
        "daily_loss_limit: 0.03",
        "max_drawdown: 0.15",
        "max_open_positions: 5",
        "profit_cost_multiple: 2",
        "opening_balance: 10000",
        "sınanan kombinasyon: 2",
        "paper adayı: aday yok",
    ]
    assert list(sections(report)) == ["aday: S0 1h", "aday: S0 4h"]
    assert sections(report)["aday: S0 1h"].splitlines() == [
        "seçilen ayar: yok",
        "sonuç: geçmedi: örneklem içi işlem yetersiz",
    ]
    last = sections(report)["aday: S0 4h"].splitlines()[-1]
    assert last == "sonuç: geçmedi: örneklem dışı net kâr"
    assert CANDIDATE_MARK not in report


def test_mark_only_on_the_paper_candidate() -> None:
    """Plan Risk 3: işaret yalnız paper adayının örneklem dışı bölümünde, bir kez."""
    metrics = final_metrics()
    report = final_report_text(FINAL_FACTS, 2, [passed("S0", "1h"), passed("S0", "4h")], 1, metrics)
    assert report.count(CANDIDATE_MARK) == 1
    assert "paper adayı: S0 4h" in report.splitlines()
    assert report == final_report_text(
        FINAL_FACTS, 2, [passed("S0", "1h"), passed("S0", "4h")], 1, metrics
    )
