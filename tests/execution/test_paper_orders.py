"""Spec 0006 AC-1…AC-6, AC-10: onaylı öneriden paper emir (BR-9)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from crytobot.execution import (
    EMPTY_EXECUTION,
    ExecutionState,
    OrderOutcome,
    OrderRequest,
    OrderResult,
    OrderStatus,
    PaperExchange,
    place_order,
)
from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    AccountState,
    ApprovalReason,
    PairRules,
    TradeApproval,
    TradeIntent,
    approve_trade,
    observe,
)

PAIR = "BTC/USDT"
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
# spec 0005 AC-1: approved, amount 19.249
ACCOUNT = AccountState(Decimal("10000"), Decimal("5000"), 0)
RULES = PairRules(Decimal("0.001"), Decimal("0.001"), Decimal("5"))
INTENT = TradeIntent(PAIR, "buy", Decimal("100"), Decimal("95"), Decimal("110"))
FEE, SLIPPAGE = Decimal("0.001"), Decimal("0.001")


def judge(intent: TradeIntent = INTENT) -> TradeApproval:
    state = observe(EMPTY_STATE, NOW, ACCOUNT.equity, DEFAULT_LIMITS).state
    pairs = frozenset({PAIR, "ETH/USDT"})
    return approve_trade(
        intent, DEFAULT_LIMITS, ACCOUNT, RULES, pairs, FEE, Decimal("0.0005"), SLIPPAGE, state, NOW
    )


APPROVAL = judge()


def request(**overrides: Any) -> OrderRequest:
    base: dict[str, Any] = {
        "intent_id": "s1-btc-0001",
        "intent": INTENT,
        "approval": APPROVAL,
        "rules": RULES,
        "price": Decimal("100"),
        "fee": FEE,
        "slippage": SLIPPAGE,
        "mode": "paper",
    }
    return OrderRequest(**(base | overrides))


def place(state: ExecutionState = EMPTY_EXECUTION, now: Any = NOW, **overrides: Any) -> OrderResult:
    return place_order(state, request(**overrides), PaperExchange(), now)


def test_approved_intent_fills_at_price_plus_slippage() -> None:
    """AC-1 (R-1, R-5, R-8): miktar 19.249, dolum 100 * 1.001 = 100.1, komisyon 1.9268249."""
    assert APPROVAL.approved and APPROVAL.amount == Decimal("19.249")

    result = place()

    order = result.order
    assert result.outcome is OrderOutcome.CREATED and order is not None
    assert order.status is OrderStatus.FILLED and order.amount == Decimal("19.249")
    assert order.fill_price == Decimal("100.1") and order.fee == Decimal("1.9268249")
    assert (order.intent_id, order.pair, order.side) == ("s1-btc-0001", PAIR, "buy")
    assert (order.entry, order.stop, order.target) == (Decimal(100), Decimal(95), Decimal(110))
    assert order.created_at == NOW
    assert dict(result.state.orders) == {order.client_order_id: order}
    assert "dolum fiyatı 100.1" in result.message


ETH = replace(INTENT, pair="ETH/USDT")
LOW_EDGE = replace(INTENT, target=Decimal("100.3"))
NOTHING: Any = None  # a field value outside its type, as a hand-built value may carry
UNAPPROVED: dict[str, dict[str, Any]] = {
    # spec 0005: cost 0.4506, threshold 0.9012, profit 0.3 -> insufficient edge
    "rejected": {"approval": judge(LOW_EDGE), "intent": LOW_EDGE},
    # a rejection that still carries an amount: the reason alone refuses it
    "rejected_with_amount": {
        "approval": replace(APPROVAL, reason=ApprovalReason.INSUFFICIENT_EDGE)
    },
    "not_an_approval": {"approval": None},
    "no_amount": {"approval": replace(APPROVAL, amount=None)},
    "zero_amount": {"approval": replace(APPROVAL, amount=Decimal(0))},
    "negative_amount": {"approval": replace(APPROVAL, amount=Decimal(-1))},
    "nan_amount": {"approval": replace(APPROVAL, amount=Decimal("NaN"))},
    "other_pair": {"intent": ETH},
    "other_side": {"intent": replace(INTENT, side="sell")},
    "other_entry": {"intent": replace(INTENT, entry=Decimal("101"))},
    "other_stop": {"intent": replace(INTENT, stop=Decimal("94"))},
    "other_target": {"intent": replace(INTENT, target=Decimal("111"))},
    # a hand-built approval whose judged intent is not one: refused, no exception (R-12)
    "judged_not_an_intent": {"approval": replace(APPROVAL, intent=NOTHING)},
    "judged_pair_not_text": {"approval": replace(APPROVAL, intent=replace(INTENT, pair=NOTHING))},
}


@pytest.mark.parametrize("case", list(UNAPPROVED))
def test_unapproved_intent_creates_no_order(case: str) -> None:
    """AC-2 (R-2, R-13): ret, miktarsız onay ya da başka bir öneri için verilmiş onay → emir yok."""
    result = place(**UNAPPROVED[case])

    assert result.outcome is OrderOutcome.UNAPPROVED and result.order is None
    assert result.state is EMPTY_EXECUTION
    assert "onaysız öneri" in result.message


@pytest.mark.parametrize("mode", ["live", "backtest", "PAPER", "", None])
def test_unsupported_mode_creates_no_order(mode: Any) -> None:
    """AC-3 (R-3): mod `paper` değilse emir oluşmaz."""
    result = place(mode=mode)

    assert result.outcome is OrderOutcome.UNSUPPORTED_MODE and result.order is None
    assert result.state is EMPTY_EXECUTION


RULE_BREAKS: dict[str, tuple[dict[str, Any], str]] = {
    "off_step": ({"approval": replace(APPROVAL, amount=Decimal("19.2495"))}, "(0.001) katı değil"),
    "below_min_amount": (
        {"rules": replace(RULES, min_amount=Decimal("20"))},
        "asgari miktarın (20)",
    ),
    # notional at the fill price: 19.249 * 100.1 = 1926.8249
    "below_min_notional": (
        {"rules": replace(RULES, min_notional=Decimal("1926.82491"))},
        "asgari tutarın (1926.82491)",
    ),
}


@pytest.mark.parametrize("case", list(RULE_BREAKS))
def test_exchange_rule_is_checked_not_rounded(case: str) -> None:
    """AC-4 (R-4): adımın katı olmayan, asgari miktarın ya da asgari tutarın altındaki miktar →
    "borsa kuralı", ihlal edilen kural, değeri ve miktar adlandırılır; miktar yuvarlanmaz."""
    overrides, rule = RULE_BREAKS[case]

    result = place(**overrides)

    assert result.outcome is OrderOutcome.EXCHANGE_RULE and result.order is None
    assert "borsa kuralı" in result.message and rule in result.message
    assert "miktar 19.249" in result.message


def test_notional_equal_to_minimum_is_accepted() -> None:
    """AC-4 (R-4): dolum fiyatıyla tutarı asgari tutara tam eşit emir kabul edilir."""
    result = place(
        rules=replace(RULES, min_amount=Decimal("19.249"), min_notional=Decimal("1926.8249"))
    )

    assert result.created and result.order is not None
    assert result.order.amount == Decimal("19.249")


def test_same_intent_id_returns_the_existing_order() -> None:
    """AC-5 (R-7): aynı kimlik ve içerik → "zaten var", tek emir; fiyat ve zaman içerik değildir."""
    first = place()

    again = place(first.state)
    later = place(first.state, now=NOW + timedelta(minutes=5), price=Decimal("120"))

    for result in (again, later):
        assert result.outcome is OrderOutcome.ALREADY_EXISTS and result.order == first.order
        assert result.state is first.state and len(result.state.orders) == 1
    assert later.order is not None and later.order.fill_price == Decimal("100.1")


CONFLICTS: dict[str, dict[str, Any]] = {
    "amount": {"approval": replace(APPROVAL, amount=Decimal("19.248"))},
    "pair": {"intent": ETH},
    "side": {"intent": replace(INTENT, side="sell")},
    "entry": {"intent": replace(INTENT, entry=Decimal("101"))},
    "stop": {"intent": replace(INTENT, stop=Decimal("94"))},
    "target": {"intent": replace(INTENT, target=Decimal("120"))},
}


@pytest.mark.parametrize("field", list(CONFLICTS))
def test_changed_content_is_an_id_conflict(field: str) -> None:
    """AC-5 (R-7): aynı kimlik farklı çift, yön, giriş, stop, hedef ya da miktarla → "kimlik
    çakışması", emir değişmez."""
    overrides = CONFLICTS[field]
    if "intent" in overrides:
        overrides = overrides | {"approval": judge(overrides["intent"])}
    first = place()

    result = place(first.state, **overrides)

    assert result.outcome is OrderOutcome.ID_CONFLICT and result.order is None
    assert result.state is first.state
    assert "kimlik çakışması" in result.message


def test_rejected_request_does_not_use_up_the_id() -> None:
    """AC-5 (R-7): emir oluşturmayan bir istek kimliği tüketmez."""
    refused = place(mode="live")

    result = place(refused.state)

    assert refused.state is EMPTY_EXECUTION and result.created


def test_client_order_id_is_prefixed_intent_id() -> None:
    """AC-6 (R-6): `clientOrderId` = `cb-` + kimlik; aynı kimlik aynı değeri verir; 32 karakter."""
    one = place(intent_id="a1-B_2").order
    two = place(EMPTY_EXECUTION, intent_id="a1-B_2").order
    longest = place(intent_id="x" * 32).order

    assert one is not None and two is not None and longest is not None
    assert one.client_order_id == two.client_order_id == "cb-a1-B_2"
    assert longest.client_order_id == "cb-" + "x" * 32 and len(longest.client_order_id) == 35


@pytest.mark.parametrize(
    "intent_id",
    ["", "x" * 33, "a b", "ğüş", "a.b", "a/b", " a1", 42, None],
    ids=["empty", "33_chars", "space", "unicode", "dot", "slash", "leading_space", "int", "none"],
)
def test_invalid_intent_id_is_invalid_input(intent_id: Any) -> None:
    """AC-6 (R-6): biçime uymayan ya da metin olmayan kimlik → "geçersiz girdi"."""
    result = place(intent_id=intent_id)

    assert result.outcome is OrderOutcome.INVALID_INPUT and result.order is None
    assert "öneri kimliği" in result.message


LONG = Decimal("1." + "2" * 28)  # 29 significant digits
TOO_LONG = "<29 basamaklı sayı> 28 anlamlı basamaktan uzun"  # not the bounded calculation
INVALID: dict[str, tuple[dict[str, Any], str]] = {
    "price-none": ({"price": None}, "fiyat"),
    "price-zero": ({"price": Decimal(0)}, "fiyat"),
    "price-negative": ({"price": Decimal(-1)}, "fiyat"),
    "price-nan": ({"price": Decimal("NaN")}, "fiyat"),
    "price-float": ({"price": 100.0}, "fiyat"),
    "price-bool": ({"price": True}, "fiyat"),
    "price-out_of_scale": ({"price": Decimal("1E+1000000")}, "fiyat"),
    "price-29_digits": ({"price": LONG}, "fiyat " + TOO_LONG),
    "price-negative_huge_int": ({"price": -(10**4300)}, "fiyat"),
    "amount-29_digits": ({"approval": replace(APPROVAL, amount=LONG)}, "miktar " + TOO_LONG),
    "fee-one": ({"fee": Decimal(1)}, "ücret"),
    "fee-negative": ({"fee": Decimal("-0.001")}, "ücret"),
    "fee-huge_int": ({"fee": 10**4300}, "ücret"),
    "slippage-huge_int": ({"slippage": -(10**4300)}, "slippage"),
    "slippage-above_one": ({"slippage": Decimal("1.5")}, "slippage"),
    "slippage-none": ({"slippage": None}, "slippage"),
    "step-zero": ({"rules": replace(RULES, amount_step=Decimal(0))}, "miktar adımı"),
    "min_amount-negative": ({"rules": replace(RULES, min_amount=Decimal(-1))}, "asgari miktar"),
    "min_notional-nan": ({"rules": replace(RULES, min_notional=Decimal("NaN"))}, "asgari tutar"),
    "rules-missing": ({"rules": None}, "borsa kuralları"),
    "intent-missing": ({"intent": None}, "öneri"),
    "entry-tiny": ({"intent": replace(INTENT, entry=Decimal("1E-1000000"))}, "giriş"),
    # each named by its own rule, not by the bounded calculation that would also refuse it
    "fee-tiny": ({"fee": Decimal("1E-1000000")}, "ücret 1E-1000000 ölçeği"),
    "min_amount-huge": (
        {"rules": replace(RULES, min_amount=Decimal("1E+1000000"))},
        "asgari miktar 1E+1000000 ölçeği",
    ),
    "amount-out_of_scale": (
        {"approval": replace(APPROVAL, amount=Decimal("1E+1000000"))},
        "miktar 1E+1000000 ölçeği",
    ),
    "pair-not_text": ({"intent": replace(INTENT, pair=NOTHING)}, "çift None ve yön 'buy' metin"),
}


@pytest.mark.parametrize("case", list(INVALID))
def test_invalid_input_is_named(case: str) -> None:
    """AC-10 (R-12): sayı kuralına, ölçeğe ya da 28 basamağa uymayan girdi → "geçersiz girdi",
    girdi adlandırılır, istisna yok."""
    overrides, label = INVALID[case]

    result = place(**overrides)

    assert result.outcome is OrderOutcome.INVALID_INPUT and result.order is None
    assert "geçersiz girdi" in result.message and label in result.message


@pytest.mark.parametrize("now", [datetime(2026, 11, 2, 10, 0), "2026-11-02", None], ids=str)
def test_time_without_zone_is_invalid_input(now: Any) -> None:
    """AC-10 (R-12): zaman dilimi taşımayan zaman → "geçersiz girdi"."""
    result = place(now=now)

    assert result.outcome is OrderOutcome.INVALID_INPUT and "zaman" in result.message


TINY_STEP = replace(RULES, amount_step=Decimal("1E-999999"), min_amount=Decimal(0))
# in scale and within 28 significant digits, but a million digits written out (B-11)
LONG_PRICE = Decimal("1" + "0" * 999_990)
LONG_AMOUNT = Decimal("19249" + "0" * 999_990)
UNREPRESENTABLE: dict[str, tuple[dict[str, Any], str]] = {
    "tiny_slippage": ({"slippage": Decimal("1E-999999")}, "miktar 19.249"),
    "tiny_step": ({"rules": TINY_STEP}, "miktar 19.249"),
    "long_slippage": ({"slippage": Decimal("0.001" + "0" * 999_990 + "1")}, "miktar 19.249"),
    "long_price": ({"price": LONG_PRICE, "rules": TINY_STEP}, "fiyat <999991 basamaklı sayı>"),
    "long_amount": (
        {"approval": replace(APPROVAL, amount=LONG_AMOUNT)},
        "miktar <999995 basamaklı sayı>",
    ),
}


@pytest.mark.parametrize("case", list(UNREPRESENTABLE))
def test_unrepresentable_calculation_is_named(case: str) -> None:
    """AC-10 (R-5, R-12; plan 0006 Risk 3): tam sonucu 28 basamağa sığmayan hesap yuvarlanmaz,
    "ölçek hesaplanamıyor" ile reddedilir; mesaj kısa kalır, uzun sayı basamak sayısıyla (B-11)."""
    overrides, number = UNREPRESENTABLE[case]

    result = place(**overrides)

    assert result.outcome is OrderOutcome.INVALID_INPUT and result.order is None
    assert "ölçek hesaplanamıyor" in result.message and number in result.message
    assert len(result.message) < 500


ZEROS = "0" * 999_990
# (amount, rules, outcome): every message that names the amount
LONG_AMOUNTS: dict[str, tuple[Decimal, PairRules, OrderOutcome]] = {
    "created": (Decimal("19.249" + ZEROS), RULES, OrderOutcome.CREATED),
    "off_step": (Decimal("19.2495" + ZEROS), RULES, OrderOutcome.EXCHANGE_RULE),
    "below_min_amount": (
        Decimal("19.249" + ZEROS),
        replace(RULES, min_amount=Decimal("20")),
        OrderOutcome.EXCHANGE_RULE,
    ),
    "below_min_notional": (
        Decimal("19.249" + ZEROS),
        replace(RULES, min_notional=Decimal("1E+10")),
        OrderOutcome.EXCHANGE_RULE,
    ),
}


@pytest.mark.parametrize("case", list(LONG_AMOUNTS))
def test_long_amount_is_short_in_the_message(case: str) -> None:
    """AC-1, AC-4 (R-12, B-11): sondaki sıfırlarla milyon basamaklı miktar emir oluşturur ya da
    borsa kuralına takılır; mesaj kısa kalır."""
    amount, rules, outcome = LONG_AMOUNTS[case]

    result = place(approval=replace(APPROVAL, amount=amount), rules=rules)

    assert result.outcome is outcome
    digits = len(amount.as_tuple().digits)
    assert f"miktar <{digits} basamaklı sayı>" in result.message and len(result.message) < 500


def test_unrepresentable_calculation_is_refused_first() -> None:
    """AC-10 (R-11, R-12): hesaplanamayan girdi "geçersiz girdi" olarak mod, tekrar, güvenli mod ve
    onay kontrollerinden önce döner."""
    tiny: dict[str, Any] = {"slippage": Decimal("1E-999999")}
    filled = place()
    unknown = place_order(
        EMPTY_EXECUTION, request(intent_id="z"), PaperExchange({"cb-z": OrderStatus.UNKNOWN}), NOW
    )
    assert unknown.state.unknown == ("cb-z",)

    results = [
        place(mode="live", **tiny),
        place(filled.state, **tiny),
        place(unknown.state, **tiny),
        place(approval=replace(APPROVAL, amount=None), **tiny),
        place(approval=None, **tiny),
    ]

    for result in results:
        assert result.outcome is OrderOutcome.INVALID_INPUT and result.order is None
        assert "ölçek hesaplanamıyor" in result.message
