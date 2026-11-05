"""Çiftin borsadaki durumu, tick ve kurallar (spec 0017 R-14, BR-2; plan Risk 3).

`ccxt`'nin `spot` alanına yetmez: `isSpotTradingAllowed: false` olan `BTCUP/USDT`'yi de `spot` sayar
(kayıtlı yanıtla ölçüldü), karar ham alandan verilir.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from crytobot.market_data._numbers import exact_decimal
from crytobot.market_data._types import IssueReason, MarketRules, ReadField, ReadIssue

_MARKET_ID: Final = re.compile(r"[A-Z0-9]{2,32}")
_QUOTE: Final = "USDT"
_ZERO: Final = Decimal(0)


@dataclass(frozen=True, slots=True)
class PairSpec:
    """İşlem görebilir bir çift; `tick` ve `rules` piyasalar yanıtından gelir."""

    market_id: str
    tick: Decimal | None
    rules: MarketRules | None
    issues: tuple[ReadIssue, ...]


def _nested(mapping: object, *keys: str) -> object:
    value = mapping
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _unusable(market: Mapping[str, object]) -> IssueReason | None:
    if market.get("quote") != _QUOTE:
        return IssueReason.NOT_USDT
    allowed = market.get("spot") is True and _nested(market, "info", "isSpotTradingAllowed") is True
    if not allowed:
        return IssueReason.NOT_SPOT
    return None if market.get("active") is True else IssueReason.NOT_TRADING


def _tick(market: Mapping[str, object]) -> Decimal | IssueReason:
    text = _nested(market, "precision", "price")
    if text is None:
        return IssueReason.TICK_NOT_REPORTED
    value = exact_decimal(text)
    if value is None or value == _ZERO:
        return IssueReason.MALFORMED_RESPONSE
    return value


def _rules(market: Mapping[str, object]) -> MarketRules | IssueReason:
    texts = (
        _nested(market, "precision", "amount"),
        _nested(market, "limits", "amount", "min"),
        _nested(market, "limits", "cost", "min"),
    )
    if any(text is None for text in texts):
        return IssueReason.RULE_NOT_REPORTED
    step, min_amount, min_notional = (exact_decimal(text) for text in texts)
    if step is None or min_amount is None or min_notional is None or step == _ZERO:
        return IssueReason.MALFORMED_RESPONSE
    return MarketRules(step, min_amount, min_notional)


def pair_spec(pair: str, markets: Mapping[str, object]) -> PairSpec | IssueReason:
    """Kullanılamayan çiftte tüm alanların ortak nedeni; aksi halde tick ve kurallar (R-14)."""
    market = markets.get(pair)
    if market is None:
        return IssueReason.NOT_LISTED
    if not isinstance(market, Mapping) or market.get("symbol") != pair:
        return IssueReason.MALFORMED_RESPONSE
    market_id = market.get("id")
    if not (isinstance(market_id, str) and _MARKET_ID.fullmatch(market_id)):
        return IssueReason.MALFORMED_RESPONSE
    unusable = _unusable(market)
    if unusable is not None:
        return unusable
    tick = _tick(market)
    rules = _rules(market)
    issues: list[ReadIssue] = []
    if isinstance(tick, IssueReason):
        issues.append(ReadIssue(ReadField.TICK, tick))
    if isinstance(rules, IssueReason):
        issues.append(ReadIssue(ReadField.RULES, rules))
    return PairSpec(
        market_id,
        None if isinstance(tick, IssueReason) else tick,
        None if isinstance(rules, IssueReason) else rules,
        tuple(issues),
    )
