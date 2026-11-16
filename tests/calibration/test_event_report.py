"""Spec 0048 AC-1, AC-3, AC-6, AC-7, AC-8 (R-6…R-9; plan Risk 9, 11): rapor metni (tablo, sayılar,
etiket denetimi, başlık satırları) ve kütüphane dosyası metni."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from typing import Any

from crytobot.calibration import (
    AFTER,
    BEFORE,
    GENERATED_PREFIX,
    LIBRARY_FORMAT,
    EventMeasured,
    EventReportFacts,
    EventSample,
    Reason,
    SampleResult,
    event_report_text,
    library_text,
    table_rows,
)
from tests.calibration.test_events import COSTS, CUTOFF, TYPES, announcement, at, measure

FINGERPRINT = "f" * 64
FACTS = EventReportFacts(
    generated_at=datetime(2026, 11, 16, 10, 0, tzinfo=UTC),
    sources_read_at=datetime(2026, 11, 16, 9, 59, tzinfo=UTC),
    prices_read_at=datetime(2026, 11, 16, 9, 59, 30, tzinfo=UTC),
    archive_path="C:/data/archive.db",
    archive_records=12,
    forward_path="C:/data/news.db",
    forward_records=3,
    price_path="C:/data/prices.db",
    exchange_info_at=datetime(2026, 11, 15, 8, 0, tzinfo=UTC),
    downloaded_first=datetime(2026, 11, 15, 8, 0, tzinfo=UTC),
    downloaded_last=datetime(2026, 11, 15, 9, 0, tzinfo=UTC),
    download_seconds=3600.5,
    rules_fingerprint=FINGERPRINT,
    library_fingerprint="a" * 64,
)
VERDICT_WORDS = ("kullanılabilir", "geçti", "kaldı", "hüküm", "başarılı", "başarısız", "onay")


def measured_rows(count: int, *, period: str = BEFORE, name: str = "spot listeleme") -> list[Any]:
    rows = []
    for index in range(count):
        item = announcement(f"{name}-{index}", event_type=name, coins=(f"C{index}",))
        sample = EventSample(item, f"C{index}", at(index), False)
        rows.append(
            SampleResult(
                sample,
                None,
                period,
                at(index + 1),
                100.0,
                index % 2 == 0,
                False,
                Fraction(1, 4),
                Fraction(0),
                at(index + 25),
            )
        )
    return rows


def synthetic(*results: SampleResult) -> EventMeasured:
    return EventMeasured(tuple(results), TYPES, COSTS, CUTOFF)


def test_fingerprint_in_report() -> None:
    text = event_report_text(measure(announcement()), FACTS)
    assert f"kural seti parmak izi: {FINGERPRINT}" in text
    assert f"kütüphane dosyası parmak izi: {'a' * 64}" in text


def test_costs_in_report() -> None:
    text = event_report_text(measure(announcement()), FACTS)
    assert "maliyet: ücret=0.001 slippage=0.001 spread=0.0005" in text
    assert f"giriş fiyatının {COSTS.factor() * 100:.4f}%'i" in text
    assert "hedef max(2xATR, maliyet), stop 1xATR, ATR(14)" in text


def test_reason_counts() -> None:
    measured = measure(
        announcement("1", published=None),
        announcement("2", coins=()),
        announcement("3", coins=("XYZ",)),
        announcement("4"),
    )
    text = event_report_text(measured, FACTS)
    assert "duyuru=4 örnek=4 ölçülen=1" in text
    for reason in Reason:
        expected = 1 if reason in (Reason.NO_TIME, Reason.NO_COIN, Reason.NO_PAIR) else 0
        assert f"  {reason.value}: {expected}\n" in text


def test_row_columns() -> None:
    rows = measured_rows(4)
    text = event_report_text(synthetic(*rows), FACTS)
    line = (
        "  kesimden önce: duyuru=4 örnek=4 ölçülen=4 çakışan=0 isabet=50.00% taban=25.00%"
        " fark=+25.00"
    )
    assert line + " [yetersiz örnek]\n" in text
    assert "spot listeleme — yükseliş" in text.split("## Ana sonuç")[1].split("## Öteki yön")[0]
    assert "spot listeleme — düşüş" in text.split("## Öteki yön")[1].split("## Nötr")[0]
    neutral = text.split("## Nötr türler")[1].split("## Etiket")[0]
    assert (
        "askıya alma ve bakım — yükseliş" in neutral and "askıya alma ve bakım — düşüş" in neutral
    )


def test_cutoff_moment_is_after() -> None:
    measured = measure(announcement("1", published=CUTOFF, coins=()))
    assert [r.period for r in measured.results] == [AFTER]
    text = event_report_text(measured, FACTS)
    assert "model kesim anı: 2024-06-01T00:00:00+00:00" in text
    assert "kesimden sonra: duyuru=1 örnek=1 ölçülen=0" in text


def test_29_flagged_30_not() -> None:
    def main_rows(count: int) -> dict[str, Any]:
        rows = table_rows(synthetic(*measured_rows(count)))
        return {r.period: r for r in rows if r.main and r.event_type == "spot listeleme"}

    assert (main_rows(29)[BEFORE].measured, main_rows(29)[BEFORE].few) == (29, True)
    assert (main_rows(30)[BEFORE].measured, main_rows(30)[BEFORE].few) == (30, False)
    text = event_report_text(synthetic(*measured_rows(30)), FACTS)
    assert "kesimden önce: duyuru=30 örnek=30 ölçülen=30" in text
    line = next(row for row in text.splitlines() if "ölçülen=30" in row and "önce" in row)
    assert "yetersiz örnek" not in line


def test_no_verdict_words() -> None:
    text = event_report_text(synthetic(*measured_rows(40)), FACTS)
    rows = [line for line in text.splitlines() if line.startswith("  kesim") or "toplam:" in line]
    assert rows
    for line in text.splitlines():
        assert not any(word in line.lower() for word in VERDICT_WORDS), line


def test_audit_titles_and_other_patterns() -> None:
    listings = [
        announcement(f"L{index:02d}", title=f"Binance Will List C{index} (C{index})", coins=())
        for index in range(25)
    ]
    others = [
        announcement(
            f"O{index}",
            title=f"Weekly {index}",
            event_type="diğer",
            direction="nötr",
            coins=(),
            pattern="Weekly #",
        )
        for index in range(3)
    ] + [
        announcement(
            "O9", title="Odd one", event_type="diğer", direction="nötr", coins=(), pattern="Odd one"
        )
    ]
    text = event_report_text(measure(*listings, *others), FACTS)
    audit = text.split("## Etiket denetimi (R-8)")[1]
    section = audit.split("listeden çıkarma:")[0]
    shown = [line for line in section.splitlines() if line.startswith('  "')]
    assert "spot listeleme: duyuru=25" in section
    assert len(shown) == 20
    assert (
        shown[0] == '  "Binance Will List C0 (C0)"'
    )  # the earliest by reference moment, then evenly
    assert '"diğer" türüne düşen duyuru: 4; en sık 20 kalıp:' in audit
    assert audit.index('  3 x "Weekly #"') < audit.index('  1 x "Odd one"')


def test_library_fields() -> None:
    measured = measure(
        announcement("1"),
        announcement("2", published=None, first_seen=at(800), coins=()),
    )
    lines = library_text(measured, FINGERPRINT).splitlines()
    header = json.loads(lines[0])
    assert header == {
        "format": LIBRARY_FORMAT,
        "version": 1,
        "rules_fingerprint": FINGERPRINT,
        "model_cutoff": "2024-06-01T00:00:00+00:00",
        "costs": {"fee": "0.001", "slippage": "0.001", "spread": "0.0005"},
    }
    first, second = (json.loads(line) for line in lines[1:])
    assert set(first) == {
        "article_id", "origin", "catalog", "title", "published", "first_seen",
        "reference_from_first_seen", "event_type", "direction", "coin", "period", "entry_time",
        "entry_price", "up_hit", "down_hit", "base_up", "base_down", "overlapping", "reason",
    }  # fmt: skip
    assert first["article_id"] == "1" and first["coin"] == "ABC" and first["reason"] is None
    assert first["entry_time"] == at(801).isoformat() and first["entry_price"] == 100.0
    assert (first["up_hit"], first["down_hit"], first["base_up"]) == (False, False, "0/1")
    assert (second["reason"], second["coin"], second["reference_from_first_seen"]) == (
        "coin yok",
        None,
        True,
    )
    assert second["first_seen"] == at(800).isoformat() and second["published"] is None


def test_hostile_title_verbatim() -> None:
    hostile = 'Binance\u0000 "{{x}}" $(rm -rf /) \x1b[31m\n<script>alert(1)</script> %s ${a}'
    measured = measure(announcement("1", title=hostile, coins=()))
    library = library_text(measured, FINGERPRINT)
    assert json.loads(library.splitlines()[1])["title"] == hostile
    assert len(library.splitlines()) == 2  # the newline is escaped, not a new record
    report = event_report_text(replace(measured, types=(("spot listeleme", "olumlu"),)), FACTS)
    assert json.dumps(hostile, ensure_ascii=False) in report
    assert "\x1b" not in report and "\u0000" not in report


def test_generated_line_is_the_only_changing_line() -> None:
    measured = measure(announcement())
    later = replace(
        FACTS,
        generated_at=FACTS.generated_at + timedelta(days=1),
        sources_read_at=FACTS.sources_read_at + timedelta(days=1),
        prices_read_at=FACTS.prices_read_at + timedelta(days=1),
    )
    first = event_report_text(measured, FACTS).splitlines()
    second = event_report_text(measured, later).splitlines()
    differing = [a for a, b in zip(first, second, strict=True) if a != b]
    assert len(differing) == 1 and differing[0].startswith(GENERATED_PREFIX)
    assert "okunma anları: kaynak kayıtlar 2026-11-16T09:59:00+00:00" in differing[0]


def test_no_forward_store_said() -> None:
    text = event_report_text(measure(announcement()), replace(FACTS, forward_records=None))
    assert "ileriye dönük kayıt yok: C:/data/news.db (yalnız arşivle)" in text


def test_input_record_counts() -> None:
    """R-9 (review round 1 F-6): the record counts of all three inputs, the price data included."""
    facts = replace(
        FACTS,
        price_pairs=420,
        price_symbols=37,
        price_candles=28_000,
        price_spans=41,
        price_empty_spans=4,
    )
    text = event_report_text(measure(announcement()), facts)
    assert "arşiv: C:/data/archive.db kayıt=12" in text
    assert "binance-duyuru kaydı=3" in text
    assert "kayıt: USDT çifti=420 mumlu çift=37 mum=28000 aralık=41 boş aralık=4" in text
