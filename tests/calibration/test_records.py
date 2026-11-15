"""Spec 0045 R-10, AC-9: sinyal kayıt dosyası alanları, sırası ve belirlenimciliği."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from crytobot.calibration import Measured, records_text, stage_one
from tests.calibration.helpers import NO_COSTS, SHORT_PERIODS, small_data

MOMENT = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
SIGNAL_FIELDS = {
    "kind",
    "indicator",
    "setting",
    "label",
    "pair",
    "interval",
    "period",
    "time",
    "direction",
    "entry",
    "hit",
    "unusual",
    "gapped",
}


@pytest.fixture(scope="module")
def measured() -> Measured:
    return stage_one(small_data(), NO_COSTS, periods_of=SHORT_PERIODS)


def test_record_fields(measured: Measured) -> None:
    lines = records_text(measured, final=False, generated_at=MOMENT).splitlines()
    header = json.loads(lines[0])
    assert header == {
        "format": "crytobot-calibration-records",
        "version": 1,
        "stage": "1",
        "generated_at": MOMENT.isoformat(),
    }
    rows = [json.loads(line) for line in lines[1:]]
    signals = [row for row in rows if row["kind"] == "signal"]
    unusual = [row for row in rows if row["kind"] == "unusual"]
    assert len(signals) + len(unusual) == len(rows)
    assert len(signals) == sum(len(m.positions) for m in measured.measurements)
    assert all(set(row) == SIGNAL_FIELDS for row in signals)
    assert {row["direction"] for row in signals} == {"al", "sat"}
    assert all(type(row["hit"]) is bool and type(row["unusual"]) is bool for row in signals)
    assert all(type(row["entry"]) is float and row["entry"] > 0 for row in signals)
    first = signals[0]
    assert (first["indicator"], first["interval"], first["period"]) == ("RSI", "1h", "ayarlama")
    assert first["label"].startswith("n=") and "üst=" in first["label"]
    assert unusual and all(
        set(row) == {"kind", "pair", "interval", "time", "rules"} for row in unusual
    )
    assert all(row["rules"] and set(row["rules"]) <= set("abcd") for row in unusual)
    times = [(row["pair"], row["time"]) for row in unusual]
    assert len(set(times)) == len(times)  # tuning and cross test share dates: one line per candle


def test_two_texts_equal_but_the_header(measured: Measured) -> None:
    one = records_text(measured, final=False, generated_at=MOMENT).splitlines()
    two = records_text(measured, final=False, generated_at=MOMENT + timedelta(days=1)).splitlines()
    assert one[1:] == two[1:] and one[0] != two[0]
