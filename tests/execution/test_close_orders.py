"""Spec 0009 AC-3…AC-11: kapanış onayından paper piyasa satışı."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, tzinfo
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest

from crytobot.execution import (
    EMPTY_EXECUTION,
    CloseOrderRequest,
    CloseOrderResult,
    ExecutionState,
    NotificationKind,
    OrderOutcome,
    OrderRequest,
    OrderStatus,
    PaperExchange,
    QueryOutcome,
    place_close_order,
    place_order,
    query_order,
)
from crytobot.portfolio import (
    EMPTY_LEDGER,
    Close,
    CloseOutcome,
    CloseReason,
    Fill,
    close_position,
    exit_decisions,
    open_ledger,
    record_fill,
)
from crytobot.risk import (
    CloseApproval,
    CloseRefusal,
    CloseRequest,
    PairRules,
    TradeApproval,
    TradeIntent,
    approve_close,
)

PAIR = "BTC/USDT"
NOW = datetime(2026, 11, 2, 11, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)
REQUEST = CloseRequest("cb-s1-btc-0001", PAIR, Decimal("19.249"), "hedef")
APPROVAL = approve_close(REQUEST)
RULES = PairRules(Decimal("0.001"), Decimal("0.001"), Decimal("5"))
ORDER = CloseOrderRequest(
    APPROVAL, RULES, Decimal("110"), Decimal("0.001"), Decimal("0.0005"), "paper"
)
VENUE = PaperExchange()
CID = "cx-s1-btc-0001"
NOTHING: Any = None  # a field value outside its type, as a hand-built value may carry


def place(
    state: ExecutionState = EMPTY_EXECUTION,
    venue: PaperExchange = VENUE,
    now: Any = NOW,
    **overrides: Any,
) -> CloseOrderResult:
    return place_close_order(state, replace(ORDER, **overrides), venue, now)


def approved(**fields: Any) -> CloseApproval:
    approval = approve_close(replace(REQUEST, **fields))
    assert approval.approved, approval.message
    return approval


def test_close_sells_at_target() -> None:
    """AC-3 (R-3, R-7, R-8, R-10): BTC 110 → `cx-s1-btc-0001`, `sell`, 19.249 @ 109.945, komisyon
    2.116331305, `dolu`; pozisyon kimliği ve neden kayıtlı."""
    result = place()

    order = result.order
    assert result.outcome is OrderOutcome.CREATED and result.created and order is not None
    assert (order.client_order_id, order.position_id, order.pair, order.side) == (
        CID,
        "cb-s1-btc-0001",
        PAIR,
        "sell",
    )
    assert (order.amount, order.reason, order.status) == (
        Decimal("19.249"),
        "hedef",
        OrderStatus.FILLED,
    )
    assert (order.fill_price, order.fee) == (Decimal("109.945"), Decimal("2.116331305"))
    assert order.created_at == NOW and dict(result.state.orders) == {CID: order}
    assert result.notifications == () and result.state.unknown == ()
    assert result.message.startswith(f"'{PAIR}': {CID} filled")  # the pair as in every message


def test_close_fill_closes_the_ledger_position() -> None:
    """AC-4 (R-14): karar → kapanış onayı → kapanış emri → defter: spec 0008 AC-3'ün sayıları."""
    opened = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
    fill = Fill(
        "cb-s1-btc-0001", PAIR, "buy", Decimal("19.249"), Decimal("100.1"),
        Decimal("1.9268249"), Decimal("95"), Decimal("110"), opened + timedelta(hours=1),
    )  # fmt: skip
    ledger = record_fill(open_ledger(EMPTY_LEDGER, Decimal("10000"), opened).ledger, fill).ledger

    (decision,) = exit_decisions(ledger, {PAIR: Decimal("110")}).decisions
    request = CloseRequest(
        decision.client_order_id, decision.pair, decision.amount, decision.reason.value
    )
    order = place(approval=approve_close(request), price=decision.price).order
    assert order is not None and order.fill_price is not None and order.fee is not None
    closed = close_position(
        ledger,
        Close(
            order.client_order_id, order.position_id, order.amount, order.fill_price, order.fee,
            CloseReason(order.reason), order.created_at,
        ),
    )  # fmt: skip

    assert closed.outcome is CloseOutcome.CLOSED, closed.message
    assert closed.ledger.balance == Decimal("10185.463248795")
    assert closed.ledger.realized == Decimal("185.463248795")


class ForgedApproval(CloseApproval):
    """Claims approval while it carries a refusal: the refusal decides (plan 0009 A-4)."""

    @property
    def approved(self) -> bool:
        return True


UNAPPROVED: dict[str, Any] = {
    "forged_approved": ForgedApproval(CloseRefusal.INVALID_INPUT, "elle kuruldu", REQUEST),
    "refused": approve_close(replace(REQUEST, reason="elle")),
    "refused_valid_request": CloseApproval(CloseRefusal.INVALID_INPUT, "elle kuruldu", REQUEST),
    "trade_approval": TradeApproval(
        Decimal("1"), None, False, "", TradeIntent(PAIR, "buy", 100, 95, 110)
    ),
    "not_an_approval": NOTHING,
    # an approved approval built by hand around something that is no close request
    "request_is_text": CloseApproval(None, "elle kuruldu", "junk"),
    "request_is_an_intent": CloseApproval(
        None, "elle kuruldu", TradeIntent(PAIR, "buy", 100, 95, 110)
    ),
}


@pytest.mark.parametrize("case", list(UNAPPROVED))
def test_unapproved_close_is_refused(case: str) -> None:
    """AC-5 (R-4, BR-9): ret taşıyan kapanış onayı, işlem önerisi onayı ya da onay olmayan değer →
    "onaysız kapanış", emir oluşmaz."""
    result = place(approval=UNAPPROVED[case])

    assert result.outcome is OrderOutcome.UNAPPROVED and result.order is None
    assert not result.created
    assert result.state is EMPTY_EXECUTION and "onaysız kapanış" in result.message


def test_trade_approval_sells_nothing() -> None:
    """AC-5 (R-4, BR-9): elle kurulmuş bir işlem önerisi onayıyla satış önerisi → "onaysız öneri",
    satış emri oluşmaz; satış yalnızca kapanış onayından çıkar."""
    sell = TradeIntent(PAIR, "sell", Decimal("100"), Decimal("95"), Decimal("110"))
    request = OrderRequest(
        "s1-btc-0002", sell, TradeApproval(Decimal("1"), None, False, "", sell), RULES,
        Decimal("100"), Decimal("0.001"), Decimal("0.001"), "paper",
    )  # fmt: skip

    result = place_order(EMPTY_EXECUTION, request, VENUE, NOW)

    assert result.outcome is OrderOutcome.UNAPPROVED and result.order is None
    assert result.state is EMPTY_EXECUTION and "onaysız öneri" in result.message

    # before the exchange rules, as every unapproved request (spec 0006 R-11)
    small = place_order(EMPTY_EXECUTION, replace(request, rules=TOO_SMALL), VENUE, NOW)
    assert small.outcome is OrderOutcome.UNAPPROVED


def test_close_approval_buys_nothing() -> None:
    """AC-5 (R-4): kapanış onayıyla alım isteği → alımın "onaysız öneri"si."""
    intent = TradeIntent(PAIR, "buy", Decimal("100"), Decimal("95"), Decimal("110"))
    buy = OrderRequest(
        "s1-btc-0002", intent, APPROVAL, RULES, Decimal("100"), Decimal("0.001"), Decimal("0.001"),
        "paper",
    )  # fmt: skip

    result = place_order(EMPTY_EXECUTION, buy, VENUE, NOW)

    assert result.outcome is OrderOutcome.UNAPPROVED and "onaysız öneri" in result.message


EXCHANGE: dict[str, tuple[dict[str, Any], str]] = {
    "off_step": (
        {"rules": replace(RULES, amount_step=Decimal("0.01"))},
        "miktar 19.249 miktar adımının (0.01) katı değil",
    ),
    "below_min_amount": (
        {"rules": replace(RULES, min_amount=Decimal("20"))},
        "miktar 19.249 asgari miktarın (20) altında",
    ),
    # 19.249 * 0.25 * 0.9995 = 4.80984... < 5
    "below_min_notional": ({"price": Decimal("0.25")}, "asgari tutarın (5) altında"),
    # at the current price it would pass (2117.39); the notional is on the fill price (2116.331305)
    "notional_on_the_fill": (
        {"rules": replace(RULES, min_notional=Decimal("2116.331306"))},
        "asgari tutarın (2116.331306) altında",
    ),
}


@pytest.mark.parametrize("case", list(EXCHANGE))
def test_close_exchange_rules(case: str) -> None:
    """AC-6 (R-6): adımın katı olmayan, asgari miktarın ya da asgari tutarın altındaki satış →
    "borsa kuralı", pozisyon, kural ve değeri adlandırılır; miktar yuvarlanmaz."""
    overrides, fragment = EXCHANGE[case]

    result = place(**overrides)

    assert result.outcome is OrderOutcome.EXCHANGE_RULE and result.state is EMPTY_EXECUTION
    assert "borsa kuralı: cb-s1-btc-0001 kapanışı" in result.message and fragment in result.message


def test_close_at_the_minimum_notional() -> None:
    """AC-6 (R-6): satış tutarı asgari tutara tam eşit → kabul."""
    result = place(rules=replace(RULES, min_notional=Decimal("2116.331305")))

    assert result.outcome is OrderOutcome.CREATED


@pytest.mark.parametrize(
    "rules",
    [replace(RULES, min_amount=Decimal("19.249")), replace(RULES, min_amount=0, min_notional=0)],
    ids=["amount_at_the_minimum", "zero_minimums"],
)
def test_close_at_the_minimums(rules: PairRules) -> None:
    """AC-6 (R-6, R-13): asgari miktara eşit miktar ve sıfır asgariler geçerlidir."""
    result = place(rules=rules)

    assert result.outcome is OrderOutcome.CREATED


@pytest.mark.parametrize("status", list(OrderStatus))
def test_same_close_already_exists(status: OrderStatus) -> None:
    """AC-7 (R-9): aynı pozisyonun kapanışı farklı fiyat ve zamanla yeniden → "zaten var", tek emir;
    durumu `reddedildi` ya da `bilinmiyor` olan kapanış emri de."""
    venue = PaperExchange(placements=MappingProxyType({CID: status}))
    first = place(venue=venue)

    again = place(first.state, venue, LATER, price=Decimal("120"))

    assert first.outcome is OrderOutcome.CREATED
    assert again.outcome is OrderOutcome.ALREADY_EXISTS and again.order == first.order
    assert again.state is first.state and len(again.state.orders) == 1
    assert again.message.startswith(f"'{PAIR}': {CID} zaten var")


CONFLICTS: dict[str, dict[str, Any]] = {
    "amount": {"amount": Decimal("19.248")},
    "reason": {"reason": "stop"},
    "pair": {"pair": "ETH/USDT"},
}


@pytest.mark.parametrize("field", list(CONFLICTS))
def test_changed_close_is_an_id_conflict(field: str) -> None:
    """AC-7 (R-9): aynı pozisyon kimliğiyle farklı miktar, neden ya da çift → "kimlik çakışması",
    mevcut emir değişmez."""
    first = place()

    result = place(first.state, approval=approved(**CONFLICTS[field]))

    assert result.outcome is OrderOutcome.ID_CONFLICT and result.state is first.state
    assert f"kimlik çakışması: {CID}" in result.message


def test_refused_close_does_not_use_up_the_id() -> None:
    """AC-7 (R-9): reddedilen istek (emir oluşmadı) kimliği tüketmez."""
    refused = place(rules=replace(RULES, min_amount=Decimal("20")))

    result = place(refused.state)

    assert refused.outcome is OrderOutcome.EXCHANGE_RULE
    assert result.outcome is OrderOutcome.CREATED


INTENT = TradeIntent(PAIR, "buy", Decimal("100"), Decimal("95"), Decimal("110"))
BUY_APPROVAL = TradeApproval(Decimal("1"), None, False, "", INTENT)


def buy(state: ExecutionState, intent_id: str, venue: PaperExchange = VENUE) -> Any:
    request = OrderRequest(
        intent_id, INTENT, BUY_APPROVAL, RULES, Decimal("100"), Decimal("0.001"), Decimal(0),
        "paper",
    )  # fmt: skip
    return place_order(state, request, venue, NOW)


def test_safe_mode_does_not_stop_a_close() -> None:
    """AC-8 (R-11, BR-11): durumu bilinmeyen bir alım varken kapanış emri oluşur; alım isteği
    "durum belirsiz" alır."""
    venue = PaperExchange(placements=MappingProxyType({"cb-a": OrderStatus.UNKNOWN}))
    unsure = buy(EMPTY_EXECUTION, "a", venue).state

    closed = place(unsure)
    blocked = buy(closed.state, "b")

    assert closed.outcome is OrderOutcome.CREATED and closed.notifications == ()
    assert blocked.outcome is OrderOutcome.STATUS_UNKNOWN


def test_unknown_close_enters_and_leaves_safe_mode() -> None:
    """AC-8 (R-10, R-11): durumu `bilinmiyor` dönen kapanış emri güvenli moda sokar (giriş
    bildirimi, alımlar durur); sorgu `dolu` dönünce dolum yazılır ve çıkış bildirimi üretilir;
    zaten güvenli moddayken ikinci bilinmeyen kapanış yeni giriş bildirimi üretmez."""
    venue = PaperExchange(
        placements=MappingProxyType({CID: OrderStatus.UNKNOWN}),
        resolutions=MappingProxyType({CID: OrderStatus.FILLED}),
    )
    entered = place(venue=venue)
    blocked = buy(entered.state, "b")
    resolved = query_order(entered.state, CID, venue, LATER)

    assert entered.state.unknown == (CID,)
    assert [n.kind for n in entered.notifications] == [NotificationKind.SAFE_MODE_ENTERED]
    assert blocked.outcome is OrderOutcome.STATUS_UNKNOWN
    assert resolved.outcome is QueryOutcome.UPDATED and resolved.order is not None
    assert (resolved.order.fill_price, resolved.order.fee) == (
        Decimal("109.945"),
        Decimal("2.116331305"),
    )
    assert [n.kind for n in resolved.notifications] == [NotificationKind.SAFE_MODE_EXITED]

    # a second unknown close while already in safe mode: no new entry (spec 0006 R-10)
    other = "cx-s1-eth-0001"
    two = PaperExchange(
        placements=MappingProxyType({CID: OrderStatus.UNKNOWN, other: OrderStatus.UNKNOWN})
    )
    first = place(venue=two)
    second = place(first.state, two, approval=approved(position_id="cb-s1-eth-0001"))

    assert second.outcome is OrderOutcome.CREATED and second.notifications == ()
    assert second.state.unknown == (CID, other)


class BadOffset(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(days=2)  # outside the range `datetime` accepts: ValueError

    def dst(self, dt: datetime | None) -> None:
        return None

    def tzname(self, dt: datetime | None) -> str:
        return "bad"


class RaisingOffset(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta:
        raise RuntimeError("no offset")

    def dst(self, dt: datetime | None) -> None:
        return None

    def tzname(self, dt: datetime | None) -> str:
        return "bad"


LONG = Decimal("1." + "2" * 28)  # 29 significant digits
INVALID: dict[str, tuple[dict[str, Any], str]] = {
    "price-zero": ({"price": Decimal(0)}, "fiyat Decimal('0') sıfırdan büyük"),
    "price-negative": ({"price": Decimal(-1)}, "fiyat Decimal('-1') sıfırdan büyük"),
    "price-nan": ({"price": Decimal("NaN")}, "fiyat Decimal('NaN') sıfırdan büyük"),
    "price-float": ({"price": 110.0}, "fiyat 110.0 sıfırdan büyük"),
    "price-bool": ({"price": True}, "fiyat True sıfırdan büyük"),
    "price-29_digits": ({"price": LONG}, "fiyat <29 basamaklı sayı> 28 anlamlı basamaktan uzun"),
    "price-out_of_scale": ({"price": Decimal("1E+1000000")}, "ölçeği varsayılan üs aralığı"),
    "fee-one": ({"fee": Decimal(1)}, "ücret Decimal('1') 0 ile 1 arasında"),
    "fee-negative": ({"fee": Decimal("-0.1")}, "ücret Decimal('-0.1') 0 ile 1 arasında"),
    "slippage-one": ({"slippage": Decimal(1)}, "slippage Decimal('1') 0 ile 1 arasında"),
    "rules-not_rules": ({"rules": NOTHING}, "borsa kuralları None çift kuralları"),
    "rules-zero_step": ({"rules": replace(RULES, amount_step=0)}, "miktar adımı 0 sıfırdan büyük"),
    "rules-negative_min": (
        {"rules": replace(RULES, min_notional=Decimal(-1))},
        "asgari tutar Decimal('-1') negatif olmayan",
    ),
    # an approved approval built by hand around a malformed request: checked again
    "request-position_id": (
        {"approval": CloseApproval(None, "", replace(REQUEST, position_id="s1-btc-0001"))},
        "pozisyon kimliği 's1-btc-0001'",
    ),
    "request-amount": (
        {"approval": CloseApproval(None, "", replace(REQUEST, amount=Decimal(0)))},
        "miktar 0 sıfırdan büyük",
    ),
    "request-reason": (
        {"approval": CloseApproval(None, "", replace(REQUEST, reason="elle"))},
        "neden 'elle' stop ya da hedef",
    ),
    "now-no_zone": ({"now": datetime(2026, 11, 2, 11, 0)}, "şu anki zaman"),
    "now-text": ({"now": "11:00"}, "şu anki zaman '11:00'"),
    "now-offset_out_of_range": ({"now": NOW.replace(tzinfo=BadOffset())}, "şu anki zaman"),
    "now-offset_raises": ({"now": NOW.replace(tzinfo=RaisingOffset())}, "şu anki zaman"),
}


@pytest.mark.parametrize("case", list(INVALID))
def test_invalid_close_order_is_named(case: str) -> None:
    """AC-9 (R-13): geçersiz fiyat, oran, kural ya da elle kurulmuş onaylı talep → "geçersiz girdi",
    girdi ve kuralı adlandırılır, istisna yok, durum değişmez, mesaj kısa."""
    overrides, fragment = INVALID[case]

    result = place(**overrides)

    assert result.outcome is OrderOutcome.INVALID_INPUT and result.state is EMPTY_EXECUTION
    assert "geçersiz girdi" in result.message and fragment in result.message, result.message
    assert len(result.message) < 500


class AlwaysPaper(str):
    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 0


@pytest.mark.parametrize(
    "mode",
    ["live", "backtest", "PAPER", "", NOTHING, 42, Decimal(1), AlwaysPaper("live")],
    ids=["live", "backtest", "upper", "empty", "none", "int", "decimal", "text_subclass"],
)
def test_unsupported_close_mode_is_named(mode: Any) -> None:
    """AC-9 (R-5): bilinmeyen ya da metin olmayan mod → "mod desteklenmiyor", "geçersiz girdi"
    değil; emir oluşmaz."""
    result = place(mode=mode)

    assert result.outcome is OrderOutcome.UNSUPPORTED_MODE and result.state is EMPTY_EXECUTION
    assert "desteklenmiyor: yalnızca paper" in result.message


UNREPRESENTABLE: dict[str, tuple[dict[str, Any], str]] = {
    # the fill fits, the notional does not: refused, never rounded (plan 0009 A-3)
    "long_notional": (
        {
            "approval": approved(amount=Decimal("1.234567890123456789012345678")),
            "price": Decimal("1234567890123456789012345.1"),
            "slippage": Decimal("1E-8"),
        },
        "miktar 1.2345",
    ),
    # the notional fits, the fee does not
    "long_fee": ({"fee": Decimal("0.001" + "0" * 52 + "1")}, "ücret <54 basamaklı sayı>"),
    # 1 - slippage fits (40 digits), the fill needs 68; the step's remainder does not fit either
    "long_price": (
        {"price": Decimal("109.9450000000000000000000001"), "slippage": Decimal("1E-40")},
        "fiyat 109.945",
    ),
    "tiny_step": ({"rules": replace(RULES, amount_step=Decimal("1E-999999"))}, "adım 1E-999999"),
}


@pytest.mark.parametrize("case", list(UNREPRESENTABLE))
def test_unrepresentable_close_order_is_named(case: str) -> None:
    """AC-9 (R-13; plan 0009 Risk 5): tam sonucu 60 basamağa sığmayan hesap yuvarlanmaz, "ölçek
    hesaplanamıyor"; mesaj kısa."""
    overrides, fragment = UNREPRESENTABLE[case]

    result = place(**overrides)

    assert result.outcome is OrderOutcome.INVALID_INPUT and result.state is EMPTY_EXECUTION
    assert "ölçek hesaplanamıyor" in result.message and fragment in result.message
    assert len(result.message) < 500


TOO_SMALL = replace(RULES, min_amount=Decimal("20"))
REFUSALS: dict[str, tuple[bool, dict[str, Any], OrderOutcome]] = {
    # (an existing close in the state, overrides): two problems each; R-12's order wins
    "invalid_and_mode": (False, {"price": Decimal(0), "mode": "live"}, OrderOutcome.INVALID_INPUT),
    # the fill depends on the order's own inputs only: its scale comes before the mode (plan A-1)
    "unrepresentable_fill_and_mode": (
        False,
        {
            "price": Decimal("109.9450000000000000000000001"),
            "slippage": Decimal("1E-40"),
            "mode": "live",
        },
        OrderOutcome.INVALID_INPUT,
    ),
    "mode_and_unapproved": (
        False,
        {"mode": "live", "approval": NOTHING},
        OrderOutcome.UNSUPPORTED_MODE,
    ),
    "unapproved_and_exchange": (
        False,
        {"approval": NOTHING, "rules": TOO_SMALL},
        OrderOutcome.UNAPPROVED,
    ),
    # the approved request's fields and scale come before the repeat check (R-12)
    "amount_scale_and_repeat": (
        True,
        {"rules": replace(RULES, amount_step=Decimal("1E-999999"))},
        OrderOutcome.INVALID_INPUT,
    ),
    "malformed_request_and_repeat": (
        True,
        {"approval": CloseApproval(None, "", replace(REQUEST, amount=Decimal(0)))},
        OrderOutcome.INVALID_INPUT,
    ),
    "repeat_and_exchange": (True, {"rules": TOO_SMALL}, OrderOutcome.ALREADY_EXISTS),
    "conflict_and_exchange": (
        True,
        {"rules": TOO_SMALL, "approval": approved(reason="stop")},
        OrderOutcome.ID_CONFLICT,
    ),
}


@pytest.mark.parametrize("case", list(REFUSALS))
def test_close_order_refusal_order(case: str) -> None:
    """AC-10 (R-12; plan 0009 Risk 4): emrin girdileri → mod → onaysız kapanış → talebin girdileri
    → zaten var / kimlik çakışması → borsa kuralı."""
    existing, overrides, expected = REFUSALS[case]
    state = place().state if existing else EMPTY_EXECUTION

    result = place(state, **overrides)

    assert result.outcome is expected
    assert (result.state is state) is (expected is not OrderOutcome.CREATED)


def test_refused_close_leaves_the_state() -> None:
    """AC-11 (R-15): durum değişmez bir değerdir; reddedilen istek durumu aynen bırakır, kabul
    edilen yeni bir durum döndürür."""
    first = place()

    refused = place(first.state, mode="live")
    other = place(first.state, approval=approved(position_id="cb-s1-eth-0001"))

    assert refused.state is first.state
    assert other.state is not first.state and list(first.state.orders) == [CID]
    assert list(other.state.orders) == [CID, "cx-s1-eth-0001"]


def test_close_state_and_order_are_immutable() -> None:
    """AC-11 (R-15): kapanış sonrası durum ve kapanış emri değişmez değerlerdir."""
    result = place()
    order = result.order
    assert order is not None

    with pytest.raises(FrozenInstanceError):
        order.amount = Decimal(1)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.state.orders = {}  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.state.orders[CID] = order  # type: ignore[index]
    with pytest.raises(TypeError):
        result.state.quotes[CID] = (Decimal(1), Decimal(1))  # type: ignore[index]
