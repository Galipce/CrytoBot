"""Spec 0017 AC-8 (okuma bölümü): fiyat adımından ince fiyat eksik döner (R-8, B-43)."""

from decimal import Decimal

import pytest

from crytobot.market_data._numbers import exact_decimal
from crytobot.market_data._quote import parse_quote
from crytobot.market_data._types import IssueReason, ReadField, ReadIssue
from tests.market_data.helpers import NOW, ticker


@pytest.mark.parametrize(
    ("last", "tick"),
    [
        ("10.50", "0.01"),
        ("10.50000000", "0.01000000"),
        ("80231.48000000", "0.01000000"),
        ("10.5", "0.5"),
        ("12", "3"),
        ("0." + "0" * 17 + "1", "0." + "0" * 17 + "1"),
    ],
)
def test_price_on_tick_is_returned(last: str, tick: str) -> None:
    quote = parse_quote(ticker(lastPrice=last), "BTCUSDT", Decimal(tick), NOW)
    assert quote.price is not None
    assert format(quote.price, "f") == last
    assert quote.issues == ()


@pytest.mark.parametrize(
    ("last", "tick"),
    [("10.505", "0.01"), ("10.25", "0.5"), ("13", "3"), ("10.00000001", "0.0000001")],
)
def test_price_finer_than_tick_is_missing(last: str, tick: str) -> None:
    quote = parse_quote(ticker(lastPrice=last), "BTCUSDT", Decimal(tick), NOW)
    assert quote.price is None
    assert quote.price_at is None
    assert ReadIssue(ReadField.PRICE, IssueReason.PRICE_FINER_THAN_TICK) in quote.issues
    assert quote.spread is not None


def test_widest_values_the_gate_accepts_are_judged_exactly() -> None:
    last = "1" * 21 + "." + "0" * 17 + "1"
    tick = "0." + "0" * 17 + "1"
    assert exact_decimal(last) is not None
    quote = parse_quote(
        ticker(lastPrice=last, bidPrice="1", askPrice="1"), "BTCUSDT", Decimal(tick), NOW
    )
    assert str(quote.price) == last


def test_b43_price_with_26_decimals_cannot_pass() -> None:
    """B-43'ün alım fiyatı okumadan geçemez: 18 ondalık üst sınırdır."""
    last = "10.00000000000000000000000001"
    quote = parse_quote(ticker(lastPrice=last), "BTCUSDT", Decimal("0.01"), NOW)
    assert quote.price is None
    assert ReadIssue(ReadField.PRICE, IssueReason.MALFORMED_RESPONSE) in quote.issues


def test_without_a_tick_the_price_stays() -> None:
    """R-3: tick eksikliği fiyatı götürmez; tur tick eksikliğiyle alımı durdurur."""
    quote = parse_quote(ticker(lastPrice="10.505"), "BTCUSDT", None, NOW)
    assert quote.price == Decimal("10.505")
