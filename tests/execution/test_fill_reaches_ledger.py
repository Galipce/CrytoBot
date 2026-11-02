"""Spec 0010 AC-1…AC-6: dolan her emir deftere yazılır; hesap sınırı 60 basamak, girdi sınırı 28."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from crytobot.execution import (
    EMPTY_EXECUTION,
    CloseOrderRequest,
    OrderOutcome,
    OrderRequest,
    PaperExchange,
    place_close_order,
    place_order,
)
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
from crytobot.risk import CloseRequest, PairRules, TradeApproval, TradeIntent, approve_close

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


PLAIN = PairRules(Decimal(1), Decimal(0), Decimal(0))  # no step or minimum in the way
# (amount, price, slippage, fee rate): the ledger could not take the fill
REFUSED: dict[str, tuple[Decimal, Decimal, Decimal, Decimal]] = {
    # the fill alone is out of scale: amount and fee rate bring the fee back in
    "fill_out_of_scale": (Decimal("1E+27"), Decimal("1E-999999"), Decimal("0.5"), Decimal("0.1")),
    "fee_out_of_scale": (Decimal(1), Decimal("1E-999990"), Decimal(0), Decimal("1E-20")),
    # the sale and the fee fit; the buy's cost and the close's proceeds need 61 digits
    "cost_beyond_the_bound": (Decimal("1E+20"), Decimal(1), Decimal(0), Decimal("1E-61")),
}


def buy_order(amount: Decimal, price: Decimal, slip: Decimal, rate: Decimal) -> Any:
    intent = TradeIntent(PAIR, "buy", price, Decimal("0.1"), Decimal("0.2"))
    approval = TradeApproval(amount, None, False, "", intent)
    request = OrderRequest("a", intent, approval, PLAIN, price, rate, slip, "paper")
    return place_order(EMPTY_EXECUTION, request, PaperExchange(), NOW)


def sell_order(amount: Decimal, price: Decimal, slip: Decimal, rate: Decimal) -> Any:
    approval = approve_close(CloseRequest("cb-a", PAIR, amount, "hedef"))
    request = CloseOrderRequest(approval, PLAIN, price, rate, slip, "paper")
    return place_close_order(EMPTY_EXECUTION, request, PaperExchange(), NOW)


# slippage only raises a buy's fill: only a close's fill can fall out of scale
CASES = [
    pytest.param(buy_order, "fee_out_of_scale", id="buy-fee_out_of_scale"),
    pytest.param(buy_order, "cost_beyond_the_bound", id="buy-cost_beyond_the_bound"),
    *[pytest.param(sell_order, case, id=f"close-{case}") for case in REFUSED],
]


@pytest.mark.parametrize(("place", "case"), CASES)
def test_order_the_ledger_cannot_take_is_refused(place: Any, case: str) -> None:
    """AC-5 (R-4): ölçek dışı dolum fiyatı ya da komisyon üreten, satış geliri ya da alım maliyeti
    sığmayan istek emir oluşturmaz: "ölçek hesaplanamıyor", durum değişmez."""
    result = place(*REFUSED[case])

    assert result.outcome is OrderOutcome.INVALID_INPUT, result.message
    assert result.state is EMPTY_EXECUTION and "ölçek hesaplanamıyor" in result.message
