"""Spec 0045 AC-3, AC-9: rapor bölümleri, bütün sinyallerle ve olağandışısız oranlar,
belirlenimcilik."""

from datetime import UTC, datetime, timedelta

import pytest

from crytobot.calibration import (
    GENERATED_PREFIX,
    DataFacts,
    Direction,
    GapRow,
    Measured,
    ReportFacts,
    final_stage,
    report_text,
    stage_one,
)
from tests.calibration.helpers import BTC, NO_COSTS, SHORT_PERIODS, at, small_data

MOMENT = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
SHA = "ab" * 32
DATA = (DataFacts("1h", "veri-1h.jsonl", "cd" * 32, MOMENT - timedelta(days=1)),)
GAPS = (GapRow("1h", "ayarlama", BTC, at(100), at(101), 2),)


@pytest.fixture(scope="module")
def first() -> Measured:
    return stage_one(small_data(), NO_COSTS, periods_of=SHORT_PERIODS)


@pytest.fixture(scope="module")
def last(first: Measured) -> Measured:
    return final_stage(small_data(), NO_COSTS, first.choices, periods_of=SHORT_PERIODS)


def facts(final: bool, moment: datetime = MOMENT) -> ReportFacts:
    if final:
        return ReportFacts(True, moment, NO_COSTS, DATA, GAPS, SHA, "Galip", MOMENT)
    return ReportFacts(False, moment, NO_COSTS, DATA, GAPS, SHA)


def test_report_sections(first: Measured, last: Measured) -> None:
    text = report_text(first, facts(False))
    lines = text.splitlines()
    assert lines[0] == "CrytoBot kalibrasyon raporu — 1. aşama (ayarlama ve çapraz sınama)"
    assert lines[1] == f"{GENERATED_PREFIX}{MOMENT.isoformat()} (ayar seti parmak izi: {SHA})"
    for needle in (
        "maliyet: ücret=0 slippage=0 spread=0",
        "dönem ayarlama: ",
        "dönem çapraz sınama: ",
        "not: görülmemiş dönem 0044'te yalnız S0…S3'ün hükümleriyle görüldü",
        f"1h: veri-1h.jsonl sha256={'cd' * 32}",
        "## veri boşlukları (doldurulmaz)",
        f"1h {BTC} ayarlama: {at(100).isoformat()} → {at(101).isoformat()} (2 mum)",
        "## olağandışı mumlar (ölçümden çıkarılmaz)",
        "## taban oran (her mum sinyal sayılarak)",
        "### RSI 1h (al)",
        "varsayılan: n=14 alt=30 üst=70",
        "## ayarlama ızgarası (BTC/USDT, ayarlama dönemi, al)",
        "## çıkış sinyalleri (sat; seçimi ve hükmü etkilemez)",
        "### Donchian 1h (sat)",
    ):
        assert needle in text, needle
    assert "görülmemiş birleşik" not in text and "hüküm:" not in text  # stage 1 never measures it
    assert sum(line.startswith("ayarlı: ") for line in lines) == 16  # 8 indicators, al + sat

    final = report_text(last, facts(True))
    for needle in (
        "CrytoBot kalibrasyon raporu — son ölçüm (üç dönem, hüküm)",
        f"ayar seti parmak izi: {SHA}",
        f"ayar seti onayı: Galip, {MOMENT.isoformat()}",
        "dönem görülmemiş: ",
        "varsayılan görülmemiş birleşik: ",
        f"varsayılan görülmemiş {BTC}: ",
        "## hüküm özeti (görülmemiş dönem, beş çift birleşik)",
    ):
        assert needle in final, needle
    assert sum(line.startswith("hüküm: ") for line in final.splitlines()) == 8
    assert "## ayarlama ızgarası" not in final


def test_rates_with_and_without_unusual(first: Measured) -> None:
    """AC-3, R-8: her satır bütün sinyallerle ve olağandışısız oranı, ikisinin tabanıyla yazar."""
    text = report_text(first, facts(False))
    row = next(
        m
        for m in first.measurements
        if m.indicator == "RSI" and m.setting == (14, 30) and m.direction is Direction.BUY
    )
    base = next(
        b.tally
        for b in first.bases
        if b.pair == BTC and b.period == "ayarlama" and b.direction is Direction.BUY
    )

    def pct(hits: int, signals: int) -> str:
        return "-" if signals == 0 else f"{hits / signals * 100:.2f}%"

    expected = (
        f"varsayılan ayarlama {BTC}: sinyal={row.tally.all.signals} "
        f"isabet={pct(row.tally.all.hits, row.tally.all.signals)} "
        f"taban={pct(base.all.hits, base.all.signals)} | olağandışısız "
        f"sinyal={row.tally.clean.signals} "
        f"isabet={pct(row.tally.clean.hits, row.tally.clean.signals)} "
        f"taban={pct(base.clean.hits, base.clean.signals)} | boşluklu={row.tally.gapped}"
    )
    assert expected in text.splitlines()
    assert base.clean.signals < base.all.signals  # the volume spike at 150 marks 25 windows


def test_only_the_generated_line_changes(first: Measured, last: Measured) -> None:
    for measured, final in ((first, False), (last, True)):
        one = report_text(measured, facts(final)).splitlines()
        two = report_text(measured, facts(final, MOMENT + timedelta(hours=1))).splitlines()
        assert len(one) == len(two)
        differ = [i for i, (a, b) in enumerate(zip(one, two, strict=True)) if a != b]
        assert differ == [1] and one[1].startswith(GENERATED_PREFIX)
