"""Spec 0025 AC-8 (R-9, R-10): parça metrikleri el hesabıyla.

Senaryo (açılış 1000 USDT, ayrım 2. günün 00:00'ı):
- t1 1. gün 00:00: pozisyon yok, kasa 1000.
- t2 1. gün 01:00: 1 birim alım, maliyet 100, alım komisyonu 0.1; fiyat 100, kasa 999.9.
- t3 2. gün 00:00 (ayrım): fiyat 110, kasa 1009.9, gerçekleşmemiş 9.9.
- t4 2. gün 01:00: kapanış, gelir 109.89, gerçekleşen 9.79, kasa 1009.79, pozisyon yok.
"""

from datetime import UTC, datetime, timedelta
from decimal import Context, Decimal, localcontext
from typing import Any

from crytobot.backtest import TurnRecord, part_metrics, run_metrics, unrealized
from crytobot.portfolio import CloseReason, Closure, Position

BTC = "BTC/USDT"
ETH = "ETH/USDT"
DAY1 = datetime(2026, 1, 1, tzinfo=UTC)
DAY2 = DAY1 + timedelta(days=1)
HOUR = timedelta(hours=1)
# the module divides in 60 digits; the hand computation does the same
SIXTY = Context(prec=60)
POSITION = Position(
    "cb-1", BTC, Decimal(1), Decimal(100), Decimal("0.1"), Decimal(90), Decimal(120), DAY1 + HOUR
)


def closure(realized: Any, at: datetime = DAY2 + HOUR) -> Closure:
    value = Decimal(realized)
    return Closure(
        "cx-1",
        POSITION,
        Decimal(1),
        Decimal(110),
        Decimal("0.11"),
        CloseReason.TARGET,
        at,
        Decimal("109.89"),
        value,
    )


def record(at: datetime, equity: str, **changes: Any) -> TurnRecord:
    values: dict[str, Any] = {
        "at": at,
        "equity": Decimal(equity),
        "positions": (),
        "marks": {},
        "closures": (),
        "fees": Decimal(0),
        "slippage": Decimal(0),
        "daily_loss": False,
        "halted": False,
        "missing": (),
        "no_proposals": (),
        "refusals": (),
        "notices": (),
    }
    return TurnRecord(**{**values, **changes})


RECORDS = [
    record(DAY1, "1000"),
    record(
        DAY1 + HOUR,
        "999.9",
        positions=(POSITION,),
        marks={BTC: Decimal(100)},
        fees=Decimal("0.1"),
        slippage=Decimal("0.05"),
    ),
    record(DAY2, "1009.9", positions=(POSITION,), marks={BTC: Decimal(110)}),
    record(
        DAY2 + HOUR,
        "1009.79",
        marks={BTC: Decimal(110)},
        closures=(closure("9.79"),),
        fees=Decimal("0.11"),
        slippage=Decimal("0.11"),
    ),
]


def test_unrealized_is_value_minus_cost() -> None:
    assert unrealized((POSITION,), {BTC: Decimal(110)}) == Decimal("9.9")
    assert unrealized((), {}) == 0


def test_in_sample_by_hand() -> None:
    part = run_metrics(Decimal(1000), RECORDS, DAY2, (BTC,)).in_sample
    assert (part.first_turn, part.last_turn, part.turns) == (DAY1, DAY1 + HOUR, 2)
    assert (part.start_equity, part.end_equity, part.net) == (
        Decimal(1000),
        Decimal("999.9"),
        Decimal("-0.1"),
    )
    assert part.return_ratio == Decimal("-0.0001")
    assert (part.realized, part.unrealized) == (Decimal(0), Decimal("-0.1"))
    assert (part.trades, part.winners, part.losers) == (0, 0, 0)
    assert part.win_rate is None and part.profit_factor is None  # no trade, no loser: undefined
    assert part.max_drawdown == Decimal("0.0001")
    assert part.average_daily_return == Decimal("-0.0001")
    assert (part.fees, part.slippage) == (Decimal("0.1"), Decimal("0.05"))


def test_out_of_sample_starts_with_split_equity_and_position() -> None:
    """R-9: ayrım anındaki kasa ve açık pozisyon; işlem kapandığı parçada sayılır."""
    part = run_metrics(Decimal(1000), RECORDS, DAY2, (BTC,)).out_of_sample
    assert part.start_equity == Decimal("999.9")
    assert part.end_equity == Decimal("1009.79")
    assert part.net == Decimal("9.89")
    assert part.realized == Decimal("9.79")
    assert part.unrealized == Decimal("0.1")  # 0 at the end, -0.1 at the split
    assert part.realized + part.unrealized == part.net
    assert (part.trades, part.winners, part.losers, part.win_rate) == (1, 1, 0, Decimal(1))
    assert part.profit_factor is None
    with localcontext(SIXTY):
        # its own peak: 1009.9 inside the part, not the run's
        assert part.max_drawdown == (Decimal("1009.9") - Decimal("1009.79")) / Decimal("1009.9")
        day2 = (Decimal("1009.79") - Decimal("999.9")) / Decimal("999.9")
    assert part.average_daily_return == day2


def test_whole_run_counts_the_split_day_once() -> None:
    whole = run_metrics(Decimal(1000), RECORDS, DAY2, (BTC,)).whole
    assert (whole.start_equity, whole.end_equity, whole.net) == (
        Decimal(1000),
        Decimal("1009.79"),
        Decimal("9.79"),
    )
    assert (whole.realized, whole.unrealized) == (Decimal("9.79"), Decimal(0))
    with localcontext(SIXTY):
        day1 = Decimal("-0.0001")
        day2 = (Decimal("1009.79") - Decimal("999.9")) / Decimal("999.9")
        average = (day1 + day2) / 2
    assert whole.average_daily_return == average
    assert (whole.fees, whole.slippage) == (Decimal("0.21"), Decimal("0.16"))


def test_split_inside_a_day_counts_that_day_in_both_parts() -> None:
    """R-10: ayrım anına denk gelen gün iki parçada ayrı, tüm koşuda tek gündür."""
    records = [record(DAY1, "1000"), record(DAY1 + HOUR, "1010"), record(DAY1 + 2 * HOUR, "1030")]
    run = run_metrics(Decimal(1000), records, DAY1 + HOUR, (BTC,))
    assert run.in_sample.average_daily_return == 0
    assert run.out_of_sample.average_daily_return == Decimal("0.03")  # 1030 / 1000, its own turns
    assert run.whole.average_daily_return == Decimal("0.03")


def test_win_rate_and_profit_factor() -> None:
    """R-10: net sıfır işlem kazanan da zararlı da değildir."""
    closures = tuple(closure(value) for value in ("5", "-2", "0", "3"))
    part = part_metrics(
        Decimal(1000), Decimal(0), False, [record(DAY1, "1006", closures=closures)], ()
    )
    assert (part.trades, part.winners, part.losers) == (4, 2, 1)
    assert part.win_rate == Decimal("0.5")
    assert part.profit_factor == 4
    assert part.realized == 6


def test_drawdown_measured_from_running_peak() -> None:
    records = [
        record(DAY1 + i * HOUR, value) for i, value in enumerate(("1100", "990", "1200", "1080"))
    ]
    part = part_metrics(Decimal(1000), Decimal(0), False, records, ())
    assert part.max_drawdown == Decimal("0.1")  # 1100 -> 990 and 1200 -> 1080


def test_daily_loss_days_and_halt_start() -> None:
    records = [
        record(DAY1, "1000", daily_loss=True),
        record(DAY1 + HOUR, "990", daily_loss=True),
        record(DAY2, "980", daily_loss=True, halted=True),
        record(DAY2 + HOUR, "975", halted=True),
    ]
    run = run_metrics(Decimal(1000), records, DAY2, (BTC,))
    assert run.in_sample.daily_loss_days == 1
    assert run.out_of_sample.daily_loss_days == 1
    assert run.whole.daily_loss_days == 2
    assert (run.in_sample.halt_started, run.in_sample.halted_at_start) == (None, False)
    assert (run.out_of_sample.halt_started, run.out_of_sample.halted_at_start) == (DAY2, False)
    assert run.whole.halt_started == DAY2


def test_halt_begun_before_the_part_is_shown_as_lasting() -> None:
    records = [record(DAY1, "1000", halted=True), record(DAY2, "990", halted=True)]
    run = run_metrics(Decimal(1000), records, DAY2, (BTC,))
    assert (run.out_of_sample.halt_started, run.out_of_sample.halted_at_start) == (None, True)
    assert run.in_sample.halt_started == DAY1


def test_counts_by_pair_and_by_name() -> None:
    records = [
        record(
            DAY1, "1000", missing=(ETH,), no_proposals=("no_crossover",), notices=("stale_data",)
        ),
        record(
            DAY1 + HOUR,
            "1000",
            missing=(ETH, BTC),
            no_proposals=("no_crossover", "insufficient_history"),
            refusals=("risk.daily_loss_limit",),
        ),
    ]
    part = part_metrics(Decimal(1000), Decimal(0), False, records, (BTC, ETH, "SOL/USDT"))
    assert part.missing == ((BTC, 1), (ETH, 2), ("SOL/USDT", 0))
    assert part.no_proposals == (("insufficient_history", 1), ("no_crossover", 2))
    assert part.refusals == (("risk.daily_loss_limit", 1),)
    assert part.notices == (("stale_data", 1),)


def test_empty_part_keeps_its_start() -> None:
    part = part_metrics(Decimal(1000), Decimal(0), False, [], (BTC,))
    assert (part.turns, part.end_equity, part.net) == (0, Decimal(1000), Decimal(0))
    assert part.average_daily_return is None
    assert part.missing == ((BTC, 0),)
