"""Spec 0017 AC-14: kullanılamayan çift ve bildirilmemiş kural (R-14, BR-2)."""

from decimal import Decimal
from typing import Any

import pytest

from crytobot.market_data import read_market_data
from crytobot.market_data._pairs import PairSpec, pair_spec
from crytobot.market_data._types import IssueReason, MarketRules, ReadField, ReadIssue
from tests.market_data.helpers import (
    BTC,
    FakeExchange,
    clock_at,
    make_settings,
    market,
    recorded_client,
)

UNUSABLE: list[tuple[str, dict[str, Any], IssueReason]] = [
    ("not_listed", {}, IssueReason.NOT_LISTED),
    ("not_usdt", {BTC: market(BTC, quote="BTC")}, IssueReason.NOT_USDT),
    ("ccxt_says_not_spot", {BTC: market(BTC, spot=False)}, IssueReason.NOT_SPOT),
    (
        "exchange_says_not_spot",
        {BTC: market(BTC, info={"isSpotTradingAllowed": False})},
        IssueReason.NOT_SPOT,
    ),
    ("spot_flag_absent", {BTC: market(BTC, info={})}, IssueReason.NOT_SPOT),
    ("closed", {BTC: market(BTC, active=False)}, IssueReason.NOT_TRADING),
    ("active_unknown", {BTC: market(BTC, active=None)}, IssueReason.NOT_TRADING),
    ("not_a_market", {BTC: "text"}, IssueReason.MALFORMED_RESPONSE),
    ("other_symbol", {BTC: market("ETH/USDT")}, IssueReason.MALFORMED_RESPONSE),
    ("id_with_path", {BTC: market(BTC, id="BTC/../x")}, IssueReason.MALFORMED_RESPONSE),
]


@pytest.mark.parametrize(
    ("markets", "reason"),
    [(markets, reason) for _, markets, reason in UNUSABLE],
    ids=[name for name, _, _ in UNUSABLE],
)
def test_unusable_pair_has_one_named_reason(markets: dict[str, Any], reason: IssueReason) -> None:
    assert pair_spec(BTC, markets) is reason


def test_good_pair_gives_exact_tick_and_rules() -> None:
    spec = pair_spec(BTC, {BTC: market(BTC)})
    assert spec == PairSpec(
        "BTCUSDT",
        Decimal("0.01"),
        MarketRules(Decimal("0.001"), Decimal("0.001"), Decimal(5)),
        (),
    )


@pytest.mark.parametrize(
    "broken",
    [
        {"precision": {"price": "0.01"}},
        {"precision": {"price": "0.01", "amount": None}},
        {"limits": {"cost": {"min": "5"}}},
        {"limits": {"amount": {"min": None}, "cost": {"min": "5"}}},
        {"limits": {"amount": {"min": "0.001"}}},
        {"limits": {"amount": {"min": "0.001"}, "cost": {"min": None}}},
        {"limits": None},
    ],
)
def test_unreported_rule_leaves_rules_missing(broken: dict[str, Any]) -> None:
    spec = pair_spec(BTC, {BTC: market(BTC, **broken)})
    assert isinstance(spec, PairSpec)
    assert spec.rules is None
    assert ReadIssue(ReadField.RULES, IssueReason.RULE_NOT_REPORTED) in spec.issues


def test_reported_zero_minimum_is_kept_as_reported() -> None:
    limits = {"amount": {"min": "0.00000000"}, "cost": {"min": "0.00000000"}}
    spec = pair_spec(BTC, {BTC: market(BTC, limits=limits)})
    assert isinstance(spec, PairSpec)
    assert spec.rules is not None
    assert spec.rules.min_amount == 0


@pytest.mark.parametrize(
    "broken",
    [
        {"precision": {"price": "0.01", "amount": "0"}},
        {"precision": {"price": "0.01", "amount": 0.001}},
        {"limits": {"amount": {"min": "abc"}, "cost": {"min": "5"}}},
    ],
)
def test_unreadable_rule_is_malformed(broken: dict[str, Any]) -> None:
    spec = pair_spec(BTC, {BTC: market(BTC, **broken)})
    assert isinstance(spec, PairSpec)
    assert spec.rules is None
    assert ReadIssue(ReadField.RULES, IssueReason.MALFORMED_RESPONSE) in spec.issues


@pytest.mark.parametrize(
    ("precision", "reason"),
    [
        ({"amount": "0.001"}, IssueReason.TICK_NOT_REPORTED),
        ({"price": "0", "amount": "0.001"}, IssueReason.MALFORMED_RESPONSE),
        ({"price": 0.01, "amount": "0.001"}, IssueReason.MALFORMED_RESPONSE),
    ],
)
def test_bad_tick_is_missing_and_rules_stay(precision: dict[str, Any], reason: IssueReason) -> None:
    spec = pair_spec(BTC, {BTC: market(BTC, precision=precision)})
    assert isinstance(spec, PairSpec)
    assert spec.tick is None
    assert spec.rules is not None
    assert spec.issues == (ReadIssue(ReadField.TICK, reason),)


@pytest.mark.parametrize(
    ("pair", "reason"),
    [
        ("ETH/BTC", IssueReason.NOT_USDT),
        ("EOS/USDT", IssueReason.NOT_TRADING),
        ("BTCUP/USDT", IssueReason.NOT_SPOT),
        ("NOPE/USDT", IssueReason.NOT_LISTED),
        ("BTC/USDT:USDT", IssueReason.NOT_LISTED),
    ],
)
def test_recorded_markets_classify_each_pair(pair: str, reason: IssueReason) -> None:
    client, _ = recorded_client()
    markets = client.markets(5.0)
    assert isinstance(markets, dict)
    assert pair_spec(pair, markets) is reason


def test_recorded_market_keeps_the_exchange_text() -> None:
    client, _ = recorded_client()
    markets = client.markets(5.0)
    assert isinstance(markets, dict)
    spec = pair_spec(BTC, markets)
    assert isinstance(spec, PairSpec)
    assert str(spec.tick) == "0.01000000"
    assert spec.rules is not None
    assert str(spec.rules.amount_step) == "0.00001000"
    assert str(spec.rules.min_amount) == "0.00001000"
    assert str(spec.rules.min_notional) == "5.00000000"


@pytest.mark.parametrize(
    ("pair", "reason"),
    [
        ("NOPE/USDT", IssueReason.NOT_LISTED),
        ("BTCUP/USDT", IssueReason.NOT_SPOT),
        ("EOS/USDT", IssueReason.NOT_TRADING),
        ("ETH/BTC", IssueReason.NOT_USDT),
    ],
)
def test_unusable_pair_misses_all_fields(pair: str, reason: IssueReason) -> None:
    """BR-2: tüm alanlar adıyla eksik; bu çift için mum ve fiyat çağrısı gitmez."""
    client, session = recorded_client()
    read = read_market_data((pair,), make_settings(), clock_at(), connect=lambda: client)
    result = read.pairs[0]
    assert result.pair == pair
    assert result.candles is None
    assert result.price is None
    assert result.price_at is None
    assert result.spread is None
    assert result.tick is None
    assert result.rules is None
    assert {issue.field for issue in result.issues} == set(ReadField)
    assert {issue.reason for issue in result.issues} == {reason}
    assert len(session.requests) == 1


def test_unreported_rule_reaches_the_result_without_a_zero() -> None:
    limits = {"amount": {"min": "0.001"}, "cost": {"min": None}}
    exchange = FakeExchange((BTC,), markets={BTC: market(BTC, limits=limits)})
    read = read_market_data((BTC,), make_settings(), clock_at(), connect=lambda: exchange)
    assert read.pairs[0].rules is None
    assert read.pairs[0].issues == (ReadIssue(ReadField.RULES, IssueReason.RULE_NOT_REPORTED),)
