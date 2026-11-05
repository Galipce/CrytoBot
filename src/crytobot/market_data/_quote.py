"""Ticker yanıtından fiyat, zaman ve spread (spec 0017 R-7, R-8, R-12; plan Risk 3, 4, 15).

Saat yanıttan sonra okunur: okuma başındaki saat, sonra gelen damgayı "gelecek" gösterirdi (Risk 4).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_CEILING, Context, Decimal
from typing import Final

from crytobot.market_data._numbers import exact_decimal, utc_from_ms
from crytobot.market_data._types import IssueReason, ReadField, ReadIssue

# 40 digits against the 18 decimals of a tick needs at most 58 digits; both are bounded at the gate
_EXACT: Final = Context(prec=120)
# Spread enters the risk gate as a cost: the rounding never understates it. 28 digits is what the
# order and ledger modules accept (docs/conventions.md).
_SPREAD_CONTEXT: Final = Context(prec=28, rounding=ROUND_CEILING)
_ZERO: Final = Decimal(0)
_ONE: Final = Decimal(1)
_TWO: Final = Decimal(2)


@dataclass(frozen=True, slots=True)
class Quote:
    price: Decimal | None
    price_at: datetime | None
    spread: Decimal | None
    issues: tuple[ReadIssue, ...]


def _missing_price(reason: IssueReason) -> tuple[ReadIssue, ...]:
    return ReadIssue(ReadField.PRICE, reason), ReadIssue(ReadField.PRICE_AT, reason)


def _price_part(
    answer: Mapping[str, object], tick: Decimal | None, now: datetime
) -> tuple[Decimal | None, datetime | None, tuple[ReadIssue, ...]]:
    text = answer.get("lastPrice")
    if text is None:
        return None, None, _missing_price(IssueReason.NO_LAST_PRICE)
    price = exact_decimal(text)
    if price is None:
        return None, None, _missing_price(IssueReason.MALFORMED_RESPONSE)
    if price == _ZERO:  # how Binance reports a pair with no trade yet
        return None, None, _missing_price(IssueReason.NO_LAST_PRICE)
    stamp = answer.get("closeTime")
    if stamp is None:
        return None, None, _missing_price(IssueReason.NO_STAMP)
    price_at = utc_from_ms(stamp)
    if price_at is None:
        return None, None, _missing_price(IssueReason.MALFORMED_RESPONSE)
    # With no tick the format cannot be judged; the price stays (R-3) and the turn halts buying
    # for this pair because the tick is missing
    if tick is not None and _EXACT.remainder(price, tick) != _ZERO:
        return None, None, _missing_price(IssueReason.PRICE_FINER_THAN_TICK)
    if price_at > now:
        return price, price_at, (ReadIssue(ReadField.PRICE_AT, IssueReason.CLOCK_DRIFT),)
    return price, price_at, ()


def _side(text: object, missing: IssueReason) -> Decimal | IssueReason:
    if text is None:
        return missing
    value = exact_decimal(text)
    if value is None:
        return IssueReason.MALFORMED_RESPONSE
    return missing if value == _ZERO else value  # zero: an empty side of the book


def _spread_part(answer: Mapping[str, object]) -> Decimal | IssueReason:
    bid = _side(answer.get("bidPrice"), IssueReason.NO_BID)
    if isinstance(bid, IssueReason):
        return bid
    ask = _side(answer.get("askPrice"), IssueReason.NO_ASK)
    if isinstance(ask, IssueReason):
        return ask
    if bid > ask:
        return IssueReason.BID_ABOVE_ASK
    mid = _EXACT.divide(_EXACT.add(bid, ask), _TWO)
    ratio = _SPREAD_CONTEXT.divide(_EXACT.subtract(ask, bid), mid)
    return IssueReason.SPREAD_TOO_WIDE if ratio >= _ONE else ratio


def parse_quote(response: object, market_id: str, tick: Decimal | None, now: datetime) -> Quote:
    """Borsa yanıtından fiyat tarafı ve spread; biri eksikken diğeri etkilenmez (R-12)."""
    if not isinstance(response, Mapping) or response.get("symbol") != market_id:
        # Another pair's answer is a bad answer (plan Risk 3)
        issues = _missing_price(IssueReason.MALFORMED_RESPONSE)
        spread_issue = ReadIssue(ReadField.SPREAD, IssueReason.MALFORMED_RESPONSE)
        return Quote(None, None, None, (*issues, spread_issue))
    price, price_at, issues = _price_part(response, tick, now)
    spread = _spread_part(response)
    if isinstance(spread, IssueReason):
        return Quote(price, price_at, None, (*issues, ReadIssue(ReadField.SPREAD, spread)))
    return Quote(price, price_at, spread, issues)
