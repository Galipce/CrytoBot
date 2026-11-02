"""Spec 0010 AC-1…AC-6: dolan her emir deftere yazılır; hesap sınırı 60 basamak, girdi sınırı 28."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from crytobot.portfolio import (
    EMPTY_LEDGER,
    Close,
    CloseOutcome,
    CloseReason,
    Fill,
    Ledger,
    LedgerOutcome,
    close_position,
    open_ledger,
    record_fill,
)

OPENED = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
NOW = OPENED + timedelta(hours=1)
LATER = NOW + timedelta(hours=1)
PAIR = "ADA/USDT"
AMOUNT = Decimal("12345.67890123")
LONG_60 = Decimal("1." + "2" * 59)  # 60 significant digits
LONG_61 = Decimal("1." + "2" * 60)
LONG_29 = Decimal("1." + "2" * 28)


def fill(**overrides: Any) -> Fill:
    values: dict[str, Any] = {
        "client_order_id": "cb-a", "pair": PAIR, "side": "buy", "amount": AMOUNT,
        "price": Decimal("0.12"), "fee": Decimal("1.11"), "stop": Decimal("0.1"),
        "target": Decimal("0.2"), "at": NOW,
    }  # fmt: skip
    return Fill(**(values | overrides))


def close(**overrides: Any) -> Close:
    values: dict[str, Any] = {
        "client_order_id": "cx-a", "position_id": "cb-a", "amount": AMOUNT,
        "price": Decimal("0.2"), "fee": Decimal("1"), "reason": CloseReason.TARGET, "at": LATER,
    }  # fmt: skip
    return Close(**(values | overrides))


def opened(amount: Decimal = Decimal("100000")) -> Ledger:
    return open_ledger(EMPTY_LEDGER, amount, OPENED).ledger


@pytest.mark.parametrize("field", ["price", "fee"])
def test_ledger_takes_sixty_digit_fills(field: str) -> None:
    """AC-4 (R-3): dolum fiyatı ve komisyon 60 basamakla kabul, 61 → "geçersiz girdi"; alımda ve
    kapanışta."""
    one = {"amount": Decimal(1), "price": Decimal(1), "fee": Decimal(0)}
    ledger = opened(Decimal(9))  # a balance small enough to leave the digits to the fill
    held = record_fill(ledger, fill(**one)).ledger
    sale = {"amount": Decimal(1), "price": Decimal(2), "fee": Decimal(1)}

    bought = record_fill(ledger, fill(**(one | {field: LONG_60})))
    too_long = record_fill(ledger, fill(**(one | {field: LONG_61})))
    closed = close_position(held, close(**(sale | {field: LONG_60})))
    close_long = close_position(held, close(**(sale | {field: LONG_61})))

    assert bought.outcome is LedgerOutcome.RECORDED, bought.message
    assert closed.outcome is CloseOutcome.CLOSED, closed.message
    assert too_long.outcome is LedgerOutcome.INVALID_INPUT and too_long.ledger is ledger
    assert close_long.outcome is CloseOutcome.INVALID_INPUT and close_long.ledger is held
    assert "60 anlamlı basamaktan uzun" in too_long.message
    assert "60 anlamlı basamaktan uzun" in close_long.message


INPUTS: dict[str, Any] = {
    "buy-amount": lambda: record_fill(opened(), fill(amount=LONG_29)),
    "buy-stop": lambda: record_fill(opened(), fill(stop=LONG_29)),
    "buy-target": lambda: record_fill(opened(), fill(target=LONG_29)),
    "close-amount": lambda: close_position(
        record_fill(opened(), fill()).ledger, close(amount=LONG_29)
    ),
    "opening": lambda: open_ledger(EMPTY_LEDGER, LONG_29, OPENED),
}


@pytest.mark.parametrize("case", list(INPUTS))
def test_inputs_stay_at_twenty_eight_digits(case: str) -> None:
    """AC-4 (R-1): miktar, stop, hedef ve başlangıç tutarı hâlâ en fazla 28 anlamlı basamak."""
    result = INPUTS[case]()

    assert result.outcome.value == "invalid_input"
    assert "28 anlamlı basamaktan uzun" in result.message
