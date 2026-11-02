"""Spec 0010 AC-1…AC-6: dolan her emir deftere yazılır; hesap sınırı 60 basamak, girdi sınırı 28."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest

from crytobot.execution import (
    EMPTY_EXECUTION,
    CloseOrderRequest,
    OrderOutcome,
    OrderRequest,
    OrderStatus,
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
    account_state,
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


def close_with(amount: Any, price: Any, slip: Any, rate: Any) -> Any:
    approval = approve_close(CloseRequest("cb-a", PAIR, Decimal(amount), "hedef"))
    rules = PairRules(Decimal(1), Decimal(0), Decimal(0))
    request = CloseOrderRequest(
        approval, rules, Decimal(price), Decimal(rate), Decimal(slip), "paper"
    )
    return place_close_order(EMPTY_EXECUTION, request, PaperExchange(), NOW)


def order_with(**overrides: Any) -> Any:
    fields = {
        "stop": Decimal("0.1"),
        "target": Decimal("0.2"),
        "price": Decimal("0.12"),
    } | overrides
    intent = TradeIntent(PAIR, "buy", Decimal("0.12"), fields["stop"], fields["target"])
    approval = TradeApproval(AMOUNT, None, False, "", intent)
    rules = PairRules(Decimal("0.00000001"), Decimal(0), Decimal(0))
    request = OrderRequest(
        "a", intent, approval, rules, fields["price"], Decimal(0), Decimal(0), "paper"
    )
    return place_order(EMPTY_EXECUTION, request, PaperExchange(), NOW)


INPUTS: dict[str, Any] = {
    "buy-amount": lambda: record_fill(opened(), fill(amount=LONG_29)),
    "buy-stop": lambda: record_fill(opened(), fill(stop=LONG_29)),
    "buy-target": lambda: record_fill(opened(), fill(target=LONG_29)),
    "close-amount": lambda: close_position(
        record_fill(opened(), fill()).ledger, close(amount=LONG_29)
    ),
    "opening": lambda: open_ledger(EMPTY_LEDGER, LONG_29, OPENED),
    # the order refuses what the ledger would: it never fills first (plan 0010 A-2)
    "order-price": lambda: order_with(price=LONG_29),
    "close-order-price": lambda: close_with(AMOUNT, LONG_29, 0, 0),
    "order-stop": lambda: order_with(stop=LONG_29),
    "order-target": lambda: order_with(target=LONG_29),
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


STEP = PairRules(Decimal("0.00000001"), Decimal(0), Decimal(0))


def test_b19_close_reaches_the_ledger() -> None:
    """AC-1 (R-2, R-3, R-5, R-8; B-19): 8 ondalıklı olağan değerlerle kapanış emri dolar ve defter
    kabul eder; bakiye ve kâr tam aritmetikle, yuvarlamasız."""
    ledger = record_fill(opened(), fill()).ledger
    assert ledger.balance == Decimal("98517.4085318524")
    approval = approve_close(CloseRequest("cb-a", PAIR, AMOUNT, "hedef"))
    request = CloseOrderRequest(
        approval, STEP, Decimal("0.12345678"), Decimal("0.00075"), Decimal("0.0005"), "paper"
    )

    order = place_close_order(EMPTY_EXECUTION, request, PaperExchange(), LATER).order

    assert order is not None and order.fill_price is not None and order.fee is not None
    assert order.fill_price == Decimal("0.123395051610")
    assert order.fee == Decimal("1.1425467638833229568602250")
    closed = close_position(
        ledger,
        close(client_order_id=order.client_order_id, price=order.fill_price, fee=order.fee),
    )
    assert closed.outcome is CloseOutcome.CLOSED, closed.message
    assert closed.ledger.balance == Decimal("100039.661670266280619523439775")
    assert closed.ledger.realized == Decimal("39.661670266280619523439775")


def test_b19_buy_reaches_the_ledger() -> None:
    """AC-2 (R-2, R-3): aynı değerlerle alım emri dolar, defter dolumu kabul eder, bakiye tam
    tutar."""
    price, rate = Decimal("0.12345678"), Decimal("0.00075")
    intent = TradeIntent(PAIR, "buy", price, Decimal("0.1"), Decimal("0.2"))
    request = OrderRequest(
        "a", intent, TradeApproval(AMOUNT, None, False, "", intent), STEP, price, rate,
        Decimal("0.0005"), "paper",
    )  # fmt: skip

    order = place_order(EMPTY_EXECUTION, request, PaperExchange(), NOW).order

    assert order is not None and order.fill_price is not None and order.fee is not None
    result = record_fill(opened(), fill(price=order.fill_price, fee=order.fee))
    fill_price = Fraction(price) * (1 + Fraction("0.0005"))
    notional = Fraction(AMOUNT) * fill_price
    assert result.outcome is LedgerOutcome.RECORDED, result.message
    assert result.ledger.balance is not None
    assert Fraction(result.ledger.balance) == 100000 - notional * (1 + Fraction(rate))


def balance_after(deep: Decimal) -> Any:
    return record_fill(opened(Decimal("1E+20")), fill(amount=1, price=1, fee=deep))


def realized_after(deep: Decimal) -> Any:
    """A big realized profit, then the balance spent: only the realized total stays long."""
    ledger = record_fill(opened(Decimal(10)), fill(amount=1, price=1, fee=0)).ledger
    gain = close(amount=1, price=Decimal("1E+20"), fee=0)
    ledger = close_position(ledger, gain).ledger
    spend = fill(client_order_id="cb-b", amount=1, price=Decimal("1E+20"), fee=0)
    ledger = record_fill(ledger, spend).ledger
    third = fill(client_order_id="cb-c", amount=1, price=2, fee=0)
    ledger = record_fill(ledger, third).ledger
    last = close(client_order_id="cx-c", position_id="cb-c", amount=1, price=2, fee=deep)
    return close_position(ledger, last)


def equity_with(mark: Decimal) -> Any:
    ledger = record_fill(
        opened(Decimal(1)), fill(amount=1, price=Decimal("0.5"), fee=Decimal("1E-40"))
    ).ledger
    return account_state(ledger, {PAIR: mark})


# (what fits in exactly 60 digits, what needs 61): each one a calculation of R-2
BOUND: dict[str, tuple[Any, Any]] = {
    "fill": (
        lambda: close_with(1, 3, "1E-59", 0),
        lambda: close_with(1, 3, "1E-60", 0),
    ),
    "notional": (
        lambda: close_with(3, 1, "1E-59", 0),
        lambda: close_with(3, 1, "1E-60", 0),
    ),
    "fee": (
        lambda: close_with(1, 1, 0, "0." + "3" * 60),
        lambda: close_with(1, 1, 0, "0." + "3" * 61),
    ),
    "proceeds": (
        lambda: close_with("1E+20", 1, 0, "1E-60"),
        lambda: close_with("1E+20", 1, 0, "1E-61"),
    ),
    "balance": (
        lambda: balance_after(Decimal("1E-40")),
        lambda: balance_after(Decimal("1E-41")),
    ),
    "realized_total": (
        lambda: realized_after(Decimal("1E-40")),
        lambda: realized_after(Decimal("1E-41")),
    ),
    "equity": (
        lambda: equity_with(Decimal("1E+19")),
        lambda: equity_with(Decimal("1E+20")),
    ),
}


@pytest.mark.parametrize("case", list(BOUND))
def test_calculation_bound_is_sixty_digits(case: str) -> None:
    """AC-3 (R-2, R-8): 60 basamağa tam sığan hesap kabul, 61 gerektiren → "ölçek hesaplanamıyor";
    yuvarlama yok."""
    fits, too_long = BOUND[case]

    accepted, refused = fits(), too_long()

    assert "ölçek hesaplanamıyor" not in accepted.message, accepted.message
    assert accepted.outcome.value in ("created", "recorded", "closed", "ready")
    assert refused.outcome.value == "invalid_input" and "ölçek hesaplanamıyor" in refused.message


def test_balance_beyond_the_bound_diverges_by_name() -> None:
    """AC-6 (R-6): emir dolu, bakiye toplamı 60 basamağa sığmayan defter → "ölçek hesaplanamıyor",
    defter değişmez, emir dolu kalır, tekrar isteği "zaten var"."""
    ledger = record_fill(opened(Decimal("1E+48")), fill()).ledger
    approval = approve_close(CloseRequest("cb-a", PAIR, AMOUNT, "hedef"))
    request = CloseOrderRequest(
        approval, STEP, Decimal("0.12345678"), Decimal("0.00075"), Decimal("0.0005"), "paper"
    )
    placed = place_close_order(EMPTY_EXECUTION, request, PaperExchange(), LATER)
    order = placed.order
    assert order is not None and order.fill_price is not None and order.fee is not None

    result = close_position(ledger, close(price=order.fill_price, fee=order.fee))
    again = place_close_order(placed.state, request, PaperExchange(), LATER)

    assert result.outcome is CloseOutcome.INVALID_INPUT and result.ledger is ledger
    assert "ölçek hesaplanamıyor" in result.message
    assert order.status is OrderStatus.FILLED and list(ledger.positions) == ["cb-a"]
    assert again.outcome is OrderOutcome.ALREADY_EXISTS and again.order == order
