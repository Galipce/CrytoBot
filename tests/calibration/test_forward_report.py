"""Spec 0053 AC-7, AC-8 (R-4, R-6, R-7, R-8; plan Risk 1, 3): tablo kalemleri, olağandışı ve
yardımcı tablonun hükme etkisizliği, gölge bölümü, örnek dosyasının alanları."""

import json
from datetime import UTC, datetime

from crytobot.calibration import (
    GENERATED_PREFIX,
    SAMPLES_FORMAT,
    CoinPrices,
    ForwardInputs,
    ForwardMeasured,
    ForwardReportFacts,
    forward_report_text,
    measure_forward,
    samples_text,
)
from tests.calibration.forward_helpers import (
    DOWN_HIT,
    FIRST_HOUR,
    NO_COSTS,
    UNUSUAL_DOWN,
    UP_HIT,
    WHITELIST,
    at,
    event,
    inputs,
    priced,
    scored_hour,
    spaced,
    spaced_inputs,
    turn,
)

FACTS = ForwardReportFacts(
    datetime(2027, 1, 1, tzinfo=UTC),
    "/x/score.db",
    2,
    "/x/news.db",
    "/x/shadow.jsonl",
    1,
    "/x/prices.db",
    None,
    None,
)


def _measured(given: ForwardInputs, report: datetime, prices: object) -> ForwardMeasured:
    assert isinstance(prices, dict)
    return measure_forward(given, report, prices, NO_COSTS)


def test_verdict_table_items() -> None:
    hours, prices = spaced(3)
    results, events = spaced_inputs(hours)
    events.append(event(1, "SOL"))
    measured = _measured(
        inputs(results, events, shadow=[], sources={1: "binance-duyuru", 2: "rss"}),
        at(hours[-1] + 25),
        {"BTC": prices, "SOL": priced(hours[-1] + 30)},
    )
    text = forward_report_text(measured, FACTS)
    for item in (
        "## Hüküm tablosu",
        "örnek=3 sayılan=3 örtüşen=0 beyaz liste dışı=1",
        "düşüş: isabet=100.00% taban=0.00% fark=+100.00 puan",
        "yükseliş (bilgi): isabet=0.00% taban=0.00% fark=+0.00 puan",
        "olağandışıya denk gelenler çıkarılmış (bilgi): örnek=3",
        "ölçülmeyen: çift yok=0 ölçüm bekliyor=0 fiyat verisi yok=0 "
        "giriş mumu yok ya da geç=0 mum yetmiyor=0",
        "kaynak: bilinmiyor=1 binance-duyuru=1 rss=1",
        "olay türü: hack=3",
        "şiddet: 2=3",
        "coin: BTC=3",
        "olağandışı kuralı: a, c — b hacim yok, d beş çift yok,"
        " c pencerenin son 3 mumunda sonraki mumları göremez",
        "skor kaydı: /x/score.db atlanan satır=2",
        "gölge kayıt: /x/shadow.jsonl bozuk satır=1",
        "maliyet: ücret=0 slippage=0 spread=0",
        "hüküm: hüküm yok: süre yetersiz",
        "## Hüküm dışı — eski üçlüler",
        "## Hüküm dışı — yardımcı tablo (beyaz liste genişlemez)",
    ):
        assert item in text, item
    assert text.count(GENERATED_PREFIX) == 1


def test_unusual_rates_do_not_change_verdict() -> None:
    """Plan Risk 3: bütün isabetler olağandışı mumda; olağandışısız küme boş kalır, hüküm yine
    bütün sayılanlarla verilir."""
    hours, prices = spaced(30, UNUSUAL_DOWN)
    results, events = spaced_inputs(hours)
    measured = _measured(inputs(results, events), at(hours[-1] + 25), {"BTC": prices})
    assert measured.table is not None
    assert all(r.unusual for r in measured.results)
    assert (measured.table.rates.count, measured.table.clean.count) == (30, 0)
    assert measured.verdict.kind == "olumlu"
    plain_hours, plain = spaced(30, DOWN_HIT)
    same = _measured(inputs(results, events), at(hours[-1] + 25), {"BTC": plain})
    assert plain_hours == hours and not any(r.unusual for r in same.results)
    assert same.verdict == measured.verdict


def test_side_table_non_whitelist_no_effect() -> None:
    hours, prices = spaced(30)
    results, events = spaced_inputs(hours)
    report = at(hours[-1] + 25)
    alone = _measured(inputs(results, events), report, {"BTC": prices})
    extra = [event(k + 1, "SOL") for k in range(30)] + [event(1, "XYZ")]
    wider = _measured(
        inputs(results, [*events, *extra]),
        report,
        {"BTC": prices, "SOL": spaced(30, UP_HIT)[1], "XYZ": CoinPrices(False, ())},
    )
    assert wider.table is not None and alone.table is not None
    assert wider.verdict == alone.verdict and wider.table.rates == alone.table.rates
    assert wider.table.outside == 31
    assert wider.side is not None and wider.side.judged is False
    assert dict(wider.side.by_coin) == {"BTC": 30, "SOL": 30}
    assert wider.side.outside == 30
    text = forward_report_text(wider, FACTS)
    assert "coin: BTC=30 SOL=30" in text


def test_shadow_section_items() -> None:
    hour = FIRST_HOUR
    shadow = [
        turn(scored_hour(hour), state="bastırılırdı", reason="olumsuz olay", buy=True),
        turn(scored_hour(hour), pair="ETH/USDT", state="filtre yok", reason="skorlayıcı durmuş"),
        turn(scored_hour(hour + 1), state="bastırılmazdı", buy=True),
        turn(scored_hour(hour + 1), pair="ETH/USDT", state="filtre yok", reason="skor kaydı yok"),
        turn(at(hour + 26), state="bastırılmazdı", buy=True),
        turn(at(hour + 100), state="bastırılırdı"),  # after the report time
    ]
    measured = _measured(
        inputs([], shadow=shadow),
        at(hour + 26),
        {"BTC": priced(hour + 30, {hour + 5: UP_HIT})},
    )
    section = measured.shadow
    assert section is not None
    assert (section.rows, section.turns) == (5, 3)
    assert section.first_at == scored_hour(hour) and section.last_at == at(hour + 26)
    text = forward_report_text(measured, FACTS)
    for item in (
        "satır=5 tur=3",
        "BTC/USDT: bastırılırdı=1 bastırılmazdı=2 bastırılmazdı — eksik bilgi=0 filtre yok=0",
        "ETH/USDT: bastırılırdı=0 bastırılmazdı=0 bastırılmazdı — eksik bilgi=0 filtre yok=2",
        '"filtre yok" nedenleri: skor kaydı yok=1 skorlayıcı durmuş=1',
        "bastırılırdı: al=1 ölçülen=1 isabet=100.00% taban=0.00%",
        "bastırılmazdı: al=2 ölçülen=1 isabet=100.00% taban=0.00% ölçülmeyen: çift yok=0 "
        "ölçüm bekliyor=1",
    ):
        assert item in text, item


def test_no_shadow_record_same_verdict() -> None:
    hours, prices = spaced(30)
    results, events = spaced_inputs(hours)
    report = at(hours[-1] + 25)
    shadow = [turn(at(h), whitelist=WHITELIST) for h in hours]
    with_shadow = _measured(inputs(results, events, shadow=shadow), report, {"BTC": prices})
    without = _measured(inputs(results, events), report, {"BTC": prices})
    assert without.shadow is None and with_shadow.shadow is not None
    assert without.verdict == with_shadow.verdict and without.verdict.kind == "olumlu"
    text = forward_report_text(without, FACTS)
    assert "gölge kayıt yok: /x/shadow.jsonl" in text
    assert "## Gölge kayıt (bilgi; hükme şart olarak girmez)\ngölge kayıt yok" in text


def test_samples_file_has_all_fields() -> None:
    hours, prices = spaced(2)
    results, events = spaced_inputs(hours)
    events.append(event(1, "ZZZ"))
    measured = _measured(
        inputs(results, events, sources={1: "rss"}), at(hours[-1] + 25), {"BTC": prices}
    )
    lines = samples_text(measured).splitlines()
    header = json.loads(lines[0])
    assert header["format"] == SAMPLES_FORMAT and header["version"] == 1
    assert header["report_at"] == at(hours[-1] + 25).isoformat()
    assert header["costs"] == {"fee": "0", "slippage": "0", "spread": "0"}
    assert header["current_triple"]["model"] == "claude-sonnet"
    assert header["verdict"] == measured.verdict.line
    rows = [json.loads(line) for line in lines[1:]]
    assert len(rows) == 3
    assert set(rows[0]) == {
        "news_id",
        "source",
        "event_type",
        "severity",
        "coin",
        "scored_at",
        "triple",
        "whitelisted",
        "entry_time",
        "entry_price",
        "down_hit",
        "up_hit",
        "base_down",
        "base_up",
        "unusual",
        "overlapping",
        "reason",
    }
    measured_row = rows[0]
    assert measured_row["source"] == "rss" and measured_row["down_hit"] is True
    assert measured_row["base_down"] == "0/1" and measured_row["overlapping"] is False
    assert measured_row["entry_time"] == at(hours[0] + 1).isoformat()
    no_pair = next(row for row in rows if row["coin"] == "ZZZ")
    assert no_pair["reason"] == "çift yok" and no_pair["overlapping"] is None
    assert no_pair["whitelisted"] is False
