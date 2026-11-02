"""Spec 0007 AC-1…AC-10: dolan paper alımlardan defter (portföy / defter)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from crytobot.portfolio import (
    EMPTY_LEDGER,
    EntryKind,
    Fill,
    Ledger,
    LedgerOutcome,
    LedgerResult,
    SnapshotOutcome,
    account_state,
    open_ledger,
    record_fill,
)

OPENED = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
NOW = OPENED + timedelta(hours=1)
# spec 0006 AC-1: 19.249 @ 100 * 1.001 = 100.1, fee 19.249 * 100.1 * 0.001 = 1.9268249
FILL = Fill(
    "cb-s1-btc-0001",
    "BTC/USDT",
    "buy",
    Decimal("19.249"),
    Decimal("100.1"),
    Decimal("1.9268249"),
    Decimal("95"),
    Decimal("110"),
    NOW,
)
NOTHING: Any = None  # a field value outside its type, as a hand-built value may carry


def opened(amount: Any = Decimal("10000")) -> Ledger:
    return open_ledger(EMPTY_LEDGER, amount, OPENED).ledger


def record(ledger: Ledger | None = None, **overrides: Any) -> LedgerResult:
    return record_fill(opened() if ledger is None else ledger, replace(FILL, **overrides))


def test_opening_sets_the_balance() -> None:
    """AC-1 (R-1): boş defter 10000 USDT ile açılır; açılış ilk kayıttır, pozisyon yok."""
    result = open_ledger(EMPTY_LEDGER, Decimal("10000"), OPENED)

    ledger = result.ledger
    assert result.outcome is LedgerOutcome.OPENED and result.accepted
    assert ledger.balance == Decimal("10000") and dict(ledger.positions) == {}
    assert [(e.kind, e.at, e.usdt, e.position) for e in ledger.entries] == [
        (EntryKind.OPENING, OPENED, Decimal("10000"), None)
    ]
    assert EMPTY_LEDGER.balance is None and EMPTY_LEDGER.entries == ()


def test_fill_debits_cost_and_opens_a_position() -> None:
    """AC-2 (R-4): 10000 - 19.249 * 100.1 - 1.9268249 = 8071.2482751; tek pozisyon."""
    result = record()

    position = result.position
    assert result.outcome is LedgerOutcome.RECORDED and position is not None
    assert result.ledger.balance == Decimal("8071.2482751")
    assert (position.client_order_id, position.pair, position.amount) == (
        "cb-s1-btc-0001",
        "BTC/USDT",
        Decimal("19.249"),
    )
    assert (position.cost_price, position.stop, position.target) == (
        Decimal("100.1"),
        Decimal("95"),
        Decimal("110"),
    )
    assert position.opened_at == NOW
    assert dict(result.ledger.positions) == {"cb-s1-btc-0001": position}
    entry = result.ledger.entries[-1]
    assert (entry.kind, entry.at, entry.usdt, entry.position) == (
        EntryKind.FILL,
        NOW,
        Decimal("1928.7517249"),
        position,
    )


def test_insufficient_balance_changes_nothing() -> None:
    """AC-5 (R-5): tutar + komisyon bakiyeyi aşarsa "yetersiz bakiye", gereken ve bakiye adlanır."""
    ledger = opened(Decimal("1928.7517248"))

    result = record(ledger)

    assert result.outcome is LedgerOutcome.INSUFFICIENT_BALANCE and result.position is None
    assert result.ledger is ledger
    assert "yetersiz bakiye" in result.message
    assert "gereken 1928.7517249" in result.message and "bakiye 1928.7517248" in result.message


def test_exact_balance_is_accepted() -> None:
    """AC-5 (R-5): tam eşit dolum kabul edilir, bakiye sıfır olur."""
    result = record(opened(Decimal("1928.7517249")))

    assert result.outcome is LedgerOutcome.RECORDED and result.ledger.balance == 0


def test_same_fill_is_already_recorded() -> None:
    """AC-6 (R-6): aynı `clientOrderId` ve içerik, farklı zaman → "zaten kayıtlı", tek pozisyon."""
    first = record()

    again = record(first.ledger, at=NOW + timedelta(minutes=5))

    assert again.outcome is LedgerOutcome.ALREADY_RECORDED and again.position == first.position
    assert again.ledger is first.ledger and len(again.ledger.positions) == 1
    assert "zaten kayıtlı" in again.message


CONFLICTS: dict[str, dict[str, Any]] = {
    "pair": {"pair": "ETH/USDT"},
    "side": {"side": "sell"},
    "amount": {"amount": Decimal("19.248")},
    "price": {"price": Decimal("100.2")},
    "fee": {"fee": Decimal("1.9")},
    "stop": {"stop": Decimal("94")},
    "target": {"target": Decimal("111")},
}


@pytest.mark.parametrize("field", list(CONFLICTS))
def test_changed_fill_is_a_conflict(field: str) -> None:
    """AC-6, AC-9 (R-6, R-10): aynı `clientOrderId` farklı içerikle → "kayıt çakışması"; satış yönü
    de önce çakışmaya takılır; kayıt değişmez."""
    first = record()

    result = record(first.ledger, **CONFLICTS[field])

    assert result.outcome is LedgerOutcome.RECORD_CONFLICT and result.position is None
    assert result.ledger is first.ledger and "kayıt çakışması" in result.message


def test_rejected_fill_does_not_use_up_the_id() -> None:
    """AC-6 (R-6): reddedilen bir istek `clientOrderId`'yi tüketmez."""
    ledger = opened()
    refused = record(ledger, side="sell")

    result = record(refused.ledger)

    assert refused.ledger is ledger and result.outcome is LedgerOutcome.RECORDED


def test_ledger_must_be_opened_once() -> None:
    """AC-7 (R-1): açılmamış deftere dolum → "defter açılmamış"; ikinci açılış → "defter zaten
    açık"; ikisi de defteri değiştirmez."""
    unopened = record_fill(EMPTY_LEDGER, FILL)
    ledger = opened()
    twice = open_ledger(ledger, Decimal("5000"), NOW)

    assert unopened.outcome is LedgerOutcome.NOT_OPENED and unopened.ledger is EMPTY_LEDGER
    assert "defter açılmamış" in unopened.message
    assert twice.outcome is LedgerOutcome.ALREADY_OPEN and twice.ledger is ledger
    assert "defter zaten açık" in twice.message


def test_sell_is_unsupported() -> None:
    """AC-7 (R-3): satış yönlü dolum → "desteklenmeyen yön", defter değişmez."""
    ledger = opened()

    result = record(ledger, side="sell")

    assert result.outcome is LedgerOutcome.UNSUPPORTED_SIDE and result.ledger is ledger
    assert "desteklenmeyen yön 'sell'" in result.message


LONG = Decimal("1." + "2" * 28)  # 29 significant digits
TOO_LONG = "<29 basamaklı sayı> 28 anlamlı basamaktan uzun"
FIELDS = ("amount", "price", "stop", "target")
LABELS = {"amount": "miktar", "price": "dolum fiyatı", "stop": "stop", "target": "hedef"}
BAD_POSITIVE: dict[str, tuple[Any, str]] = {
    "zero": (Decimal(0), "sıfırdan büyük"),
    "negative": (Decimal(-1), "sıfırdan büyük"),
    "nan": (Decimal("NaN"), "sıfırdan büyük"),
    "float": (100.0, "sıfırdan büyük"),
    "bool": (True, "sıfırdan büyük"),
    "huge_int": (-(10**4300), "sıfırdan büyük"),
    "out_of_scale": (Decimal("1E+1000000"), "ölçeği varsayılan üs aralığı"),
    "29_digits": (LONG, TOO_LONG),
}
INVALID: dict[str, tuple[dict[str, Any], str]] = {
    f"{field}-{case}": ({field: value}, f"{LABELS[field]} ")
    for field in FIELDS
    for case, (value, _) in BAD_POSITIVE.items()
}
INVALID |= {
    "fee-negative": ({"fee": Decimal("-0.001")}, "komisyon"),
    "fee-nan": ({"fee": Decimal("NaN")}, "komisyon"),
    "fee-tiny": ({"fee": Decimal("1E-1000000")}, "komisyon 1E-1000000 ölçeği"),
    "id-empty": ({"client_order_id": ""}, "clientOrderId"),
    "id-37_chars": ({"client_order_id": "x" * 37}, "clientOrderId"),
    "id-space": ({"client_order_id": "cb a"}, "clientOrderId"),
    "id-unicode": ({"client_order_id": "cb-ğüş"}, "clientOrderId"),
    "id-not_text": ({"client_order_id": 42}, "clientOrderId"),
    "pair-not_text": ({"pair": NOTHING}, "çift None ve yön 'buy' metin"),
    "side-not_text": ({"side": NOTHING}, "çift 'BTC/USDT' ve yön None metin"),
    "at-no_zone": ({"at": datetime(2026, 11, 2, 10, 0)}, "dolum zamanı"),
    "at-not_time": ({"at": "2026-11-02"}, "dolum zamanı"),
    "at-before_opening": ({"at": OPENED - timedelta(seconds=1)}, "açılıştan"),
}


@pytest.mark.parametrize("case", list(INVALID))
def test_invalid_fill_is_named(case: str) -> None:
    """AC-8 (R-2, R-11): sayı kuralına, ölçeğe, 28 basamağa ya da biçime uymayan girdi ve açılıştan
    önceki dolum → "geçersiz girdi", girdi adlandırılır, istisna yok, defter değişmez."""
    overrides, label = INVALID[case]
    ledger = opened()

    result = record(ledger, **overrides)

    assert result.outcome is LedgerOutcome.INVALID_INPUT and result.position is None
    assert result.ledger is ledger
    assert "geçersiz girdi" in result.message and label in result.message
    assert len(result.message) < 500


@pytest.mark.parametrize("case", list(BAD_POSITIVE))
def test_invalid_opening_is_named(case: str) -> None:
    """AC-8 (R-1, R-11): geçersiz başlangıç tutarı → "geçersiz girdi", defter açılmaz."""
    value, rule = BAD_POSITIVE[case]

    result = open_ledger(EMPTY_LEDGER, value, OPENED)

    assert result.outcome is LedgerOutcome.INVALID_INPUT and result.ledger is EMPTY_LEDGER
    assert "başlangıç tutarı" in result.message and rule in result.message


@pytest.mark.parametrize("at", [datetime(2026, 11, 2, 9, 0), None], ids=["no_zone", "none"])
def test_opening_time_needs_a_zone(at: Any) -> None:
    """AC-8 (R-11): zaman dilimi taşımayan açılış zamanı → "geçersiz girdi"."""
    result = open_ledger(EMPTY_LEDGER, Decimal("10000"), at)

    assert result.outcome is LedgerOutcome.INVALID_INPUT and "açılış zamanı" in result.message


HUGE = 10**4300  # one significant digit, exponent 4300: in scale (R-11); a bound is backlog B-15


def test_positive_huge_int_is_in_scale() -> None:
    """AC-8 (R-11; plan 0007 A-1): pozitif `10**4300` geçerlidir: açılış "açıldı", stop ya da
    hedefte "kaydedildi", miktarda "ölçek hesaplanamıyor"; istisna yok, mesaj kısa."""
    opening = open_ledger(EMPTY_LEDGER, HUGE, OPENED)
    stop = record(stop=HUGE)
    target = record(target=HUGE)
    amount = record(amount=HUGE)

    assert opening.outcome is LedgerOutcome.OPENED and opening.ledger.balance == HUGE
    assert stop.outcome is LedgerOutcome.RECORDED and stop.position is not None
    assert stop.position.stop == HUGE
    assert target.outcome is LedgerOutcome.RECORDED and target.position is not None
    assert target.position.target == HUGE
    assert amount.outcome is LedgerOutcome.INVALID_INPUT and amount.position is None
    assert "ölçek hesaplanamıyor" in amount.message
    assert "miktar <4301 basamaklı sayı>" in amount.message
    assert all(len(r.message) < 500 for r in (opening, stop, target, amount))


UNREPRESENTABLE: dict[str, tuple[Decimal, dict[str, Any], str]] = {
    # in scale and within 28 significant digits each, but their sum or difference is not
    "tiny_fee": (Decimal("10000"), {"fee": Decimal("1E-999999")}, "komisyon 1E-999999"),
    "huge_balance": (Decimal("1E+999999"), {}, "bakiye 1E+999999"),
    "long_amount": (
        Decimal("10000"),
        {"amount": Decimal("19249" + "0" * 999_990)},
        "miktar <999995 basamaklı sayı>",
    ),
}


@pytest.mark.parametrize("case", list(UNREPRESENTABLE))
def test_unrepresentable_calculation_is_named(case: str) -> None:
    """AC-8 (R-11; plan 0007 Risk 3): tam sonucu 28 basamağa sığmayan hesap yuvarlanmaz, "ölçek
    hesaplanamıyor" ile reddedilir; uzun sayı basamak sayısıyla yazılır, mesaj kısa kalır."""
    balance, overrides, number = UNREPRESENTABLE[case]
    ledger = opened(balance)

    result = record(ledger, **overrides)

    assert result.outcome is LedgerOutcome.INVALID_INPUT and result.ledger is ledger
    assert "ölçek hesaplanamıyor" in result.message and number in result.message
    assert len(result.message) < 500


REFUSALS: dict[str, tuple[str, dict[str, Any], LedgerOutcome]] = {
    # (ledger, overrides): two problems each; the first in R-10's order wins
    "invalid_and_not_opened": ("empty", {"amount": Decimal(0)}, LedgerOutcome.INVALID_INPUT),
    "repeat_and_sell": ("recorded", {"side": "sell"}, LedgerOutcome.RECORD_CONFLICT),
    "sell_and_insufficient": ("poor", {"side": "sell"}, LedgerOutcome.UNSUPPORTED_SIDE),
    "unrepresentable_and_repeat": (
        "recorded",
        {"fee": Decimal("1E-999999")},
        LedgerOutcome.INVALID_INPUT,
    ),
}


@pytest.mark.parametrize("case", list(REFUSALS))
def test_refusal_order(case: str) -> None:
    """AC-9 (R-10): geçersiz girdi → defter açılmamış → zaten kayıtlı / çakışma → desteklenmeyen
    yön → yetersiz bakiye."""
    kind, overrides, expected = REFUSALS[case]
    ledgers = {
        "empty": EMPTY_LEDGER,
        "recorded": record().ledger,
        "poor": opened(Decimal("1")),
    }

    result = record(ledgers[kind], **overrides)

    assert result.outcome is expected and result.ledger is ledgers[kind]


def test_entries_are_append_only() -> None:
    """AC-10 (R-9): yeni kayıttan sonra önceki kayıtlar ve sıraları aynıdır; reddedilen her istek
    defteri aynen bırakır."""
    first = record()
    second = record(first.ledger, client_order_id="cb-s1-btc-0002", at=NOW + timedelta(hours=1))
    refused = record(second.ledger, client_order_id="cb-s1-btc-0003", side="sell")

    assert second.ledger.entries[: len(first.ledger.entries)] == first.ledger.entries
    assert [e.kind for e in second.ledger.entries] == [
        EntryKind.OPENING,
        EntryKind.FILL,
        EntryKind.FILL,
    ]
    assert list(second.ledger.positions) == ["cb-s1-btc-0001", "cb-s1-btc-0002"]
    assert first.ledger.balance == Decimal("8071.2482751")
    assert refused.ledger is second.ledger


def test_opening_snapshot_needs_no_price() -> None:
    """AC-1 (R-7): yeni açılmış defter → serbest bakiye 10000, kasa 10000, açık pozisyon 0; fiyat
    verilmeden hesap durumu oluşur."""
    result = account_state(opened(), {})

    snapshot = result.snapshot
    assert result.outcome is SnapshotOutcome.READY and snapshot is not None
    assert (snapshot.equity, snapshot.free_balance, snapshot.open_positions) == (
        Decimal("10000"),
        Decimal("10000"),
        0,
    )
    assert snapshot.positions == ()


def test_equity_marks_the_position_at_the_current_price() -> None:
    """AC-2 (R-7): BTC 105 ile kasa 8071.2482751 + 19.249 * 105 = 10092.3932751."""
    recorded = record()

    result = account_state(recorded.ledger, {"BTC/USDT": Decimal("105")})

    snapshot = result.snapshot
    assert result.outcome is SnapshotOutcome.READY and snapshot is not None
    assert snapshot.equity == Decimal("10092.3932751")
    assert snapshot.free_balance == Decimal("8071.2482751") and snapshot.open_positions == 1
    assert snapshot.positions == (recorded.position,)


def test_each_fill_is_its_own_position() -> None:
    """AC-3 (R-4, R-7): aynı çiftte iki dolum iki pozisyon, eklenme sırasıyla; farklı çift kendi
    fiyatıyla değerlenir."""
    one = record()
    two = record(one.ledger, client_order_id="cb-s1-btc-0002", amount=Decimal("1"))
    eth = record(
        two.ledger,
        client_order_id="cb-s1-eth-0001",
        pair="ETH/USDT",
        amount=Decimal("2"),
        price=Decimal("50"),
        fee=Decimal("0.1"),
    )

    result = account_state(
        eth.ledger, {"BTC/USDT": Decimal("105"), "ETH/USDT": Decimal("60"), "XRP/USDT": 1}
    )

    snapshot = result.snapshot
    assert result.outcome is SnapshotOutcome.READY and snapshot is not None
    assert snapshot.open_positions == 3
    assert [p.client_order_id for p in snapshot.positions] == [
        "cb-s1-btc-0001",
        "cb-s1-btc-0002",
        "cb-s1-eth-0001",
    ]
    # balance 8071.2482751 - (1 * 100.1 + 1.9268249) - (2 * 50 + 0.1) = 7869.1214502
    assert snapshot.free_balance == Decimal("7869.1214502")
    assert snapshot.equity == Decimal("7869.1214502") + Decimal("20.249") * 105 + 2 * 60


MISSING: dict[str, Any] = {
    "absent": None,
    "zero": Decimal(0),
    "negative": Decimal(-1),
    "nan": Decimal("NaN"),
    "float": 105.0,
    "bool": True,
    "29_digits": LONG,
}


@pytest.mark.parametrize("case", list(MISSING))
def test_missing_price_for_an_open_position(case: str) -> None:
    """AC-4 (R-7): açık pozisyonu olan çiftin fiyatı yok ya da geçersiz → "fiyat eksik", çift
    adlandırılır, kasa hesaplanmaz."""
    ledger = record().ledger
    prices = {} if MISSING[case] is None else {"BTC/USDT": MISSING[case]}

    result = account_state(ledger, prices | {"ETH/USDT": Decimal("60")})

    assert result.outcome is SnapshotOutcome.MISSING_PRICE and result.snapshot is None
    assert "fiyat eksik" in result.message and "BTC/USDT" in result.message
    assert "ETH/USDT" not in result.message


def test_prices_without_positions_are_ignored() -> None:
    """AC-4 (R-7): pozisyonu olmayan çiftin fiyatı geçersiz olsa da yok sayılır."""
    result = account_state(opened(), {"ETH/USDT": Decimal("NaN"), 42: "x"})

    assert result.outcome is SnapshotOutcome.READY


def test_snapshot_of_an_unopened_ledger() -> None:
    """AC-7 (R-1): açılmamış defterin hesap durumu → "defter açılmamış"."""
    result = account_state(EMPTY_LEDGER, {})

    assert result.outcome is SnapshotOutcome.NOT_OPENED and "defter açılmamış" in result.message


@pytest.mark.parametrize("prices", [None, [("BTC/USDT", Decimal("105"))], "BTC/USDT"])
def test_prices_must_be_a_mapping(prices: Any) -> None:
    """AC-8 (R-7): eşleme olmayan fiyat girdisi → "geçersiz girdi", açılmamış defterde de önce."""
    for ledger in (record().ledger, EMPTY_LEDGER):
        result = account_state(ledger, prices)

        assert result.outcome is SnapshotOutcome.INVALID_INPUT and "fiyatlar" in result.message


def test_unrepresentable_equity_is_named() -> None:
    """AC-8 (R-11; plan 0007 Risk 3): 28 basamağa sığmayan kasa toplamı → "ölçek hesaplanamıyor"."""
    ledger = record().ledger

    result = account_state(ledger, {"BTC/USDT": Decimal("1E-999990")})

    assert result.outcome is SnapshotOutcome.INVALID_INPUT and result.snapshot is None
    assert "ölçek hesaplanamıyor" in result.message and "BTC/USDT 1E-999990" in result.message
