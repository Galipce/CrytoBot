"""Spec 0017 AC-7: fiyat zamanı borsanın damgasıdır, kayma değiştirilmeden raporlanır (R-7)."""

from datetime import timedelta
from decimal import Decimal

from crytobot.market_data._numbers import ms_from_utc
from crytobot.market_data._quote import parse_quote
from crytobot.market_data._types import IssueReason, ReadField, ReadIssue
from tests.market_data.helpers import CLOSE_MS, NOW, at_ms, ticker

TICK = Decimal("0.01")


def test_stamp_is_the_exchange_stamp_in_aware_utc() -> None:
    quote = parse_quote(ticker(), "BTCUSDT", TICK, NOW)
    assert quote.price_at == at_ms(CLOSE_MS)
    assert quote.price_at is not None
    assert quote.price_at.utcoffset() == timedelta(0)
    assert quote.issues == ()


def test_missing_stamp_leaves_price_and_time_missing() -> None:
    quote = parse_quote(ticker(closeTime=None), "BTCUSDT", TICK, NOW)
    assert quote.price is None
    assert quote.price_at is None
    assert quote.issues == (
        ReadIssue(ReadField.PRICE, IssueReason.NO_STAMP),
        ReadIssue(ReadField.PRICE_AT, IssueReason.NO_STAMP),
    )


def test_future_stamp_is_unchanged_and_reported() -> None:
    stamp = ms_from_utc(NOW) + 1
    quote = parse_quote(ticker(closeTime=stamp), "BTCUSDT", TICK, NOW)
    assert quote.price == Decimal("10.50")
    assert quote.price_at == at_ms(stamp)
    assert quote.issues == (ReadIssue(ReadField.PRICE_AT, IssueReason.CLOCK_DRIFT),)


def test_stamp_equal_to_the_clock_is_not_drift() -> None:
    quote = parse_quote(ticker(), "BTCUSDT", TICK, at_ms(CLOSE_MS))
    assert quote.issues == ()


def test_unreadable_stamp_is_malformed_not_replaced() -> None:
    for stamp in ("1793880000000", 1.5, -1, True):
        quote = parse_quote(ticker(closeTime=stamp), "BTCUSDT", TICK, NOW)
        assert quote.price is None
        assert quote.price_at is None
        assert ReadIssue(ReadField.PRICE_AT, IssueReason.MALFORMED_RESPONSE) in quote.issues
