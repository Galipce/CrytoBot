"""Spec 0017 AC-12: spread sınırları; fiyat alış ya da satıştan türetilmez (R-12)."""

from decimal import Decimal

import pytest

from crytobot.market_data._quote import parse_quote
from crytobot.market_data._types import IssueReason, ReadField, ReadIssue
from tests.market_data.helpers import NOW, ticker

TICK = Decimal("0.01")


def test_spread_is_exact_when_the_ratio_terminates() -> None:
    quote = parse_quote(ticker(bidPrice="9.00", askPrice="11.00"), "BTCUSDT", TICK, NOW)
    assert quote.spread == Decimal("0.2")


def test_rounding_never_understates_the_spread() -> None:
    quote = parse_quote(ticker(bidPrice="1", askPrice="2"), "BTCUSDT", TICK, NOW)
    assert quote.spread is not None
    assert quote.spread * 3 >= 2
    assert len(quote.spread.as_tuple().digits) == 28


def test_equal_bid_ask_is_zero_spread() -> None:
    quote = parse_quote(ticker(bidPrice="10.00", askPrice="10.00"), "BTCUSDT", TICK, NOW)
    assert quote.spread == 0
    assert quote.issues == ()


@pytest.mark.parametrize(
    ("bid", "ask", "reason"),
    [
        (None, "10.00", IssueReason.NO_BID),
        ("10.00", None, IssueReason.NO_ASK),
        ("0.00000000", "10.00", IssueReason.NO_BID),
        ("10.00", "0.00000000", IssueReason.NO_ASK),
        ("11.00", "10.00", IssueReason.BID_ABOVE_ASK),
        ("1.00", "3.00", IssueReason.SPREAD_TOO_WIDE),
        ("1.00", "4.00", IssueReason.SPREAD_TOO_WIDE),
        ("abc", "10.00", IssueReason.MALFORMED_RESPONSE),
        ("10.00", 10.5, IssueReason.MALFORMED_RESPONSE),
    ],
)
def test_spread_refusals_keep_price(bid: object, ask: object, reason: IssueReason) -> None:
    quote = parse_quote(ticker(bidPrice=bid, askPrice=ask), "BTCUSDT", TICK, NOW)
    assert quote.spread is None
    assert quote.issues == (ReadIssue(ReadField.SPREAD, reason),)
    assert quote.price == Decimal("10.50")
    assert quote.price_at is not None


@pytest.mark.parametrize("last", [None, "0.00000000"])
def test_price_is_not_derived_from_bid_or_ask(last: object) -> None:
    quote = parse_quote(ticker(lastPrice=last), "BTCUSDT", TICK, NOW)
    assert quote.price is None
    assert quote.price_at is None
    assert ReadIssue(ReadField.PRICE, IssueReason.NO_LAST_PRICE) in quote.issues
    assert quote.spread is not None


@pytest.mark.parametrize("response", ["text", None, [1], {"lastPrice": "10"}])
def test_answer_that_is_not_a_ticker_is_malformed(response: object) -> None:
    quote = parse_quote(response, "BTCUSDT", TICK, NOW)
    assert (quote.price, quote.price_at, quote.spread) == (None, None, None)
    assert {issue.reason for issue in quote.issues} == {IssueReason.MALFORMED_RESPONSE}


def test_another_pairs_answer_is_malformed() -> None:
    quote = parse_quote(ticker("ETH/USDT"), "BTCUSDT", TICK, NOW)
    assert quote.price is None
    assert {issue.reason for issue in quote.issues} == {IssueReason.MALFORMED_RESPONSE}
