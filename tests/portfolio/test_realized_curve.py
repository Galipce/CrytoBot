"""Spec 0038 CB-4 (b)-(d), plan A-1, Risk 3: gerçekleşmiş kasa eğrisi ve kapanmış işlem sayısı."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crytobot.portfolio import (
    EMPTY_LEDGER,
    Close,
    CloseReason,
    Fill,
    Ledger,
    close_position,
    closed_trades,
    open_ledger,
    realized_curve,
    record_fill,
)

OPENED = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def fill(cid: str, at: datetime) -> Fill:
    # 10 @ 100, fee 0.3: cost 1000.3
    return Fill(
        cid,
        "BTC/USDT",
        "buy",
        Decimal(10),
        Decimal(100),
        Decimal("0.3"),
        Decimal(95),
        Decimal(110),
        at,
    )


def sale(cid: str, position: str, amount: str, price: str, at: datetime) -> Close:
    return Close(
        cid, position, Decimal(amount), Decimal(price), Decimal("0.1"), CloseReason.TARGET, at
    )


def opened() -> Ledger:
    return open_ledger(EMPTY_LEDGER, Decimal(10000), OPENED).ledger


def bought(ledger: Ledger, cid: str, hours: int) -> Ledger:
    result = record_fill(ledger, fill(cid, OPENED + timedelta(hours=hours)))
    assert result.accepted, result.message
    return result.ledger


def closed(ledger: Ledger, close: Close, *, partial: bool = False) -> Ledger:
    result = close_position(ledger, close, partial=partial)
    assert result.closure is not None, result.message
    return result.ledger


def test_unopened_ledger_has_no_curve_and_no_trades() -> None:
    assert realized_curve(EMPTY_LEDGER) == ()
    assert closed_trades(EMPTY_LEDGER) == 0


def test_opened_ledger_starts_the_curve_at_the_deposit() -> None:
    assert realized_curve(opened()) == (Decimal(10000),)


def test_curve_adds_each_closure_in_order_and_ignores_open_positions() -> None:
    ledger = bought(bought(bought(opened(), "a", 1), "b", 2), "c", 3)
    at = OPENED + timedelta(hours=4)
    ledger = closed(ledger, sale("sa", "a", "10", "110", at))  # 1100 - 0.1 - 1000.3 = 99.6
    ledger = closed(ledger, sale("sb", "b", "10", "90", at))  # 900 - 0.1 - 1000.3 = -100.4

    assert realized_curve(ledger) == (
        Decimal(10000),
        Decimal("10099.6"),
        Decimal("9999.2"),
    )
    assert closed_trades(ledger) == 2  # "c" is still open


def test_partial_closes_count_once_and_only_when_the_position_is_gone() -> None:
    """Plan Risk 3: kısmi kapanışın gerçekleşen kısmı eğriye girer; işlem tam kapanınca 1'dir."""
    at = OPENED + timedelta(hours=2)
    ledger = closed(bought(opened(), "a", 1), sale("s1", "a", "4", "110", at), partial=True)

    assert closed_trades(ledger) == 0
    assert len(realized_curve(ledger)) == 2

    ledger = closed(ledger, sale("s2", "a", "6", "110", at + timedelta(minutes=1)))

    assert closed_trades(ledger) == 1
    assert len(realized_curve(ledger)) == 3


def test_a_curve_that_does_not_fit_is_empty() -> None:
    ledger = closed(
        bought(opened(), "a", 1), sale("sa", "a", "10", "110", OPENED + timedelta(hours=2))
    )
    (closure,) = ledger.closures.values()
    huge = replace(closure, realized=Decimal("1E+999999"))
    broken = replace(ledger, closures={"sa": huge, "sb": replace(huge, client_order_id="sb")})

    assert realized_curve(broken) == ()


def test_ledger_not_starting_with_an_opening_has_no_curve() -> None:
    ledger = bought(opened(), "a", 1)
    broken = replace(ledger, entries=ledger.entries[1:])

    assert realized_curve(broken) == ()
