"""Spec 0044 AC-1 (biçim yarısı), R-2; plan Adım 5, Risk 2: son değerlendirme raporunun veri
bölümü. Her raporda (aday var ya da yok) varsayımlardan sonra, adaylardan önce, aralık başına."""

from datetime import timedelta

from crytobot.backtest import (
    NO_GAPS,
    NOT_ENOUGH_TRADES,
    CandidateResult,
    DataGap,
    IntervalData,
    final_report_text,
    parse_report,
)
from tests.backtest.test_metrics import BTC, DAY1, ETH
from tests.backtest.test_report import FINAL_FACTS, final_metrics, passed

SOL = "SOL/USDT"
END = DAY1 + timedelta(days=2)


def one_hour(gaps: tuple[DataGap, ...]) -> IntervalData:
    return IntervalData("1h", DAY1, END, END - timedelta(hours=1), gaps)


def four_hours(gaps: tuple[DataGap, ...] = ()) -> IntervalData:
    return IntervalData("4h", DAY1, END, END - timedelta(hours=4), gaps)


def gap(pair: str, first: int, last: int) -> DataGap:
    return DataGap(
        pair, DAY1 + timedelta(hours=first), DAY1 + timedelta(hours=last), last - first + 1
    )


def unselected() -> CandidateResult:
    return CandidateResult("S0", "1h", None, None, None, None, NOT_ENOUGH_TRADES)


def block(report: str) -> list[str]:
    """Varsayımlardan sonraki ve ilk adaydan önceki satırlar (boş satırlar dahil)."""
    lines = report.splitlines()
    after = lines.index("- mum boşlukları doldurulmaz") + 1
    before = next(i for i, line in enumerate(lines) if line.startswith("== aday:"))
    return lines[after:before]


def test_gap_lines_time_order_and_none() -> None:
    """AC-1: satır `<çift> <ilk eksik> → <son eksik> (<n> mum)`; zaman sırası ilk eksik muma
    göre, eşitlikte verilen (beyaz liste) sıra; tek eksik `n = 1`; boşluksuz aralık
    `veri boşluğu: yok`."""
    gaps = (gap(BTC, 20, 22), gap(ETH, 5, 5), gap(SOL, 5, 6), gap(BTC, 3, 3))
    data = (one_hour(gaps), four_hours())
    report = final_report_text(FINAL_FACTS, 2, [unselected()], None, None, data=data)
    assert block(report) == [
        "",
        "veri — 1h: dönem 2026-01-01T00:00:00+00:00 .. 2026-01-03T00:00:00+00:00 (bitiş hariç),"
        " saklı dönemin son mumu 2026-01-02T23:00:00+00:00",
        "BTC/USDT 2026-01-01T03:00:00+00:00 → 2026-01-01T03:00:00+00:00 (1 mum)",
        "ETH/USDT 2026-01-01T05:00:00+00:00 → 2026-01-01T05:00:00+00:00 (1 mum)",
        "SOL/USDT 2026-01-01T05:00:00+00:00 → 2026-01-01T06:00:00+00:00 (2 mum)",
        "BTC/USDT 2026-01-01T20:00:00+00:00 → 2026-01-01T22:00:00+00:00 (3 mum)",
        "",
        "veri — 4h: dönem 2026-01-01T00:00:00+00:00 .. 2026-01-03T00:00:00+00:00 (bitiş hariç),"
        " saklı dönemin son mumu 2026-01-02T20:00:00+00:00",
        NO_GAPS,
        "",
    ]


def test_data_section_in_a_report_with_a_paper_candidate() -> None:
    """R-2: aday varken de aynı yerde; adayların ve dönem bölümlerinin metni değişmez."""
    data = (one_hour((gap(BTC, 2, 3),)), four_hours())
    with_data = final_report_text(FINAL_FACTS, 1, [passed()], 0, final_metrics(), data=data)
    without = final_report_text(FINAL_FACTS, 1, [passed()], 0, final_metrics(), data=())
    assert "BTC/USDT 2026-01-01T02:00:00+00:00 → 2026-01-01T03:00:00+00:00 (2 mum)" in block(
        with_data
    )
    lines = without.splitlines()
    at = lines.index("- mum boşlukları doldurulmaz") + 1
    added = block(with_data)[:-1]  # the last blank line was already there, before the candidates
    assert with_data.splitlines() == lines[:at] + added + lines[at:]


def test_parse_reads_the_same_with_the_data_section() -> None:
    """Kapı raporu aynı okur: veri satırları başlık alanı değildir (AC-3 korunan davranış)."""
    data = (one_hour((gap(BTC, 2, 3),)), four_hours())
    with_data = parse_report(
        final_report_text(FINAL_FACTS, 1, [passed()], 0, final_metrics(), data=data)
    )
    without = parse_report(
        final_report_text(FINAL_FACTS, 1, [passed()], 0, final_metrics(), data=())
    )
    assert with_data.problem is None and with_data.data == without.data
