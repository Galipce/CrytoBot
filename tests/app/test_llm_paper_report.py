"""Spec 0060 AC-6, AC-8, AC-9: pencere ve dönemler, rapor alanları, hüküm."""

from datetime import timedelta
from decimal import Decimal

import pytest

from crytobot.app._llm_paper import HOUR, ExitKind, PaperDecision, PaperTrade, Replay, Status
from crytobot.app._llm_paper_config import MEASUREMENT_END, MEASUREMENT_START, OPENING_BALANCE
from crytobot.app._llm_paper_random import RandomResult
from crytobot.app._llm_paper_report import (
    INSUFFICIENT,
    NEGATIVE,
    POSITIVE,
    RUNNING,
    Counts,
    Metrics,
    Period,
    RecordDecision,
    RecordTurn,
    ReportFacts,
    S0Summary,
    active_period,
    buy_decisions,
    counts,
    metrics,
    periods,
    report_text,
    trade_rows,
    verdict,
)

START = MEASUREMENT_START
D = Decimal
PERIOD = Period("m", "p", START, MEASUREMENT_END)


def turn(hours: int, model: str = "m", prompt: str = "p", called: bool = True) -> RecordTurn:
    return RecordTurn(START + HOUR * hours, model, prompt, "ok" if called else "sınır", called)


def row(hours: int, coin: str, status: str, action: str | None) -> RecordDecision:
    buy = status == "al"
    return RecordDecision(
        START + HOUR * hours,
        coin,
        status,
        action,
        D("99") if buy else None,
        D("100") if buy else None,
        D("95") if buy else None,
        D("110") if buy else None,
        4 if buy else None,
    )


def test_window_and_wait_rows_excluded() -> None:
    rows = [
        row(-1, "BTC", "al", "al"),  # before the start
        row(0, "BTC", "al", "al"),
        row(0, "ETH", "bekle", "bekle"),  # Claude's own wait
        row(1, "ETH", "bekle", None),  # a no-decision turn's wait
        row(1, "SOL", "veri yok", None),
        row(2, "SOL", "tutarsız", "al"),
        row(3, "ADA", "şema dışı", None),
    ]
    turns = [turn(-1), turn(0), turn(1, called=False), turn(2), turn(3)]
    tally = counts(turns, rows, PERIOD)
    assert (tally.turns, tally.called) == (4, 3)
    assert (tally.asked, tally.buys, tally.waits, tally.inconsistent, tally.schema) == (
        4,
        1,
        1,
        1,
        1,
    )
    assert [d.turn for d in buy_decisions(rows, PERIOD)] == [START]
    late = row(int(timedelta(days=90) / HOUR), "BTC", "al", "al")
    assert buy_decisions([late], PERIOD) == []


def test_fingerprint_change_restarts() -> None:
    turns = [turn(0), turn(5), turn(10, prompt="q"), turn(11, prompt="q")]
    found = periods(turns)
    assert [(p.prompt_fingerprint, p.start) for p in found] == [
        ("p", START),
        ("q", START + 10 * HOUR),
    ]
    assert found[0].end == START + 10 * HOUR
    assert found[1].end == START + 10 * HOUR + timedelta(days=90)
    assert active_period(turns) == found[1]
    assert active_period([]).start == START


def _metrics(
    closed: int = 40, net: str = "10", pf: str | None = "1.5", dd: str = "0.05"
) -> Metrics:
    return Metrics(closed, closed // 2, D(net), None if pf is None else D(pf), D(dd), D("12"))


CHANCE = RandomResult(tuple(D(i) / 10 for i in range(100)), 0)  # 95th percentile 9.4
GOOD = Counts(10, 10, {"ok": 10}, 100, 20, 70, 5, 5)


def test_verdict_running_insufficient_each_threshold_positive() -> None:
    before = MEASUREMENT_END - HOUR
    assert verdict(PERIOD, before, _metrics(), CHANCE, GOOD).name == RUNNING
    assert verdict(PERIOD, MEASUREMENT_END, _metrics(closed=29), CHANCE, GOOD).name == INSUFFICIENT
    assert verdict(PERIOD, MEASUREMENT_END, _metrics(), CHANCE, GOOD).name == POSITIVE
    for changes, name in (
        ({"net": "0"}, "net kâr ≤ 0"),
        ({"pf": "1.1"}, "kâr faktörü < 1.2"),
        ({"dd": "0.16"}, "drawdown > %15"),
        ({"net": "9"}, "rastgelenin 95. yüzdeliğini geçmiyor"),
    ):
        judged = verdict(PERIOD, MEASUREMENT_END, _metrics(**changes), CHANCE, GOOD)  # type: ignore[arg-type]
        assert judged.name == NEGATIVE and name in judged.failed, changes


def test_quality_blocks_positive() -> None:
    bad = Counts(10, 10, {"ok": 10}, 100, 20, 59, 11, 10)  # 21 % bad
    judged = verdict(PERIOD, MEASUREMENT_END, _metrics(), CHANCE, bad)
    assert judged.name == NEGATIVE and "karar kalitesi düşük" in judged.failed
    edge = Counts(10, 10, {"ok": 10}, 100, 20, 60, 10, 10)  # exactly 20 %: allowed
    assert verdict(PERIOD, MEASUREMENT_END, _metrics(), CHANCE, edge).name == POSITIVE


def _replay() -> Replay:
    d = PaperDecision(START, "SOL", D("99"), D("100"), D("95"), D("110"), 4)
    closed = PaperTrade(
        d,
        Status.CLOSED,
        None,
        START,
        D("100.1"),
        D("0.1"),
        START + 3 * HOUR,
        D("109.89"),
        ExitKind.TARGET,
        D("0.95"),
    )
    rejected = PaperTrade(d, Status.REJECTED, "maliyet katı")
    unmeasured = PaperTrade(d, Status.UNMEASURABLE)
    curve = ((START, OPENING_BALANCE), (START + HOUR, D("99")), (START + 3 * HOUR, D("100.95")))
    return Replay((closed, rejected, unmeasured), curve, None, D("100.95"))


def _facts(s0: S0Summary | None) -> ReportFacts:
    return ReportFacts(
        START + 5 * HOUR,
        START + 5 * HOUR,
        "decide.db",
        0,
        "prices.db",
        "2026-11-20T03:00:00+00:00",
        s0,
        0,
    )


def test_report_fields() -> None:
    result = _replay()
    found = metrics(result)
    assert found.closed == 1 and found.net == D("0.95") and found.max_drawdown == D("0.01")
    s0 = S0Summary(2, 1, D("-1.5"), D("0.5"))
    text = report_text(
        [PERIOD],
        PERIOD,
        GOOD,
        result,
        found,
        CHANCE,
        verdict(PERIOD, START, found, CHANCE, GOOD),
        _facts(s0),
    )
    for part in (
        "## Dönemler", "etkin dönem: 2026-11-20T03:00Z → 2027-02-18T03:00Z",
        "karar_istenen=100 al=20 claude_bekle=70 tutarsız=5 şema_dışı=5",
        "risk reddi: maliyet_katı=1", "kapanış: hedef=1", "ölçülemedi_(mum_eksik)=1",
        "net kâr (maliyetlerden sonra): 0.95 USDT", "## Eşlenik rastgele", "tohum=60",
        "kapanmış=2 açık=1 net=-1.50", "hüküm: ölçüm sürüyor", "spread 0 (varsayım)",
    ):  # fmt: skip
        assert part in text, part


def test_s0_missing() -> None:
    result = _replay()
    found = metrics(result)
    text = report_text(
        [PERIOD],
        PERIOD,
        GOOD,
        result,
        found,
        CHANCE,
        verdict(PERIOD, START, found, CHANCE, GOOD),
        _facts(None),
    )
    assert "S0 yok" in text


def test_unmeasurable_named() -> None:
    rows = list(trade_rows(_replay().trades))
    assert [r["status"] for r in rows] == ["kapandı", "reddedildi", "ölçülemedi (mum eksik)"]
    assert rows[0]["exit_kind"] == "hedef" and rows[0]["net"] == "0.95"
    assert rows[1]["rejection"] == "maliyet katı"


@pytest.mark.parametrize("pf", [None])
def test_no_losses_profit_factor_none(pf: None) -> None:
    judged = verdict(PERIOD, MEASUREMENT_END, _metrics(pf=pf), CHANCE, GOOD)
    assert judged.name == POSITIVE  # no losing trade: the factor is unbounded, not failing
