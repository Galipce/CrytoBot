"""Spec 0008 AC-1…AC-11: açık pozisyonun stop ya da hedefte kapanışı ve gerçekleşen kâr/zarar."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from crytobot.portfolio import (
    EMPTY_LEDGER,
    Close,
    CloseOutcome,
    CloseReason,
    CloseResult,
    Fill,
    Ledger,
    LedgerOutcome,
    account_state,
    close_position,
    open_ledger,
    record_fill,
)

OPENED = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
NOW = OPENED + timedelta(hours=1)
LATER = NOW + timedelta(hours=1)
# spec 0007 AC-2: 19.249 @ 100.1, fee 1.9268249; cost 1928.7517249, USDT 8071.2482751
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
# sold at 110 * (1 - 0.0005) = 109.945, fee 19.249 * 109.945 * 0.001 = 2.116331305
CLOSE = Close(
    "cb-x1",
    "cb-s1-btc-0001",
    Decimal("19.249"),
    Decimal("109.945"),
    Decimal("2.116331305"),
    CloseReason.TARGET,
    LATER,
)
NOTHING: Any = None  # a field value outside its type, as a hand-built value may carry


def bought(amount: Any = Decimal("10000")) -> Ledger:
    ledger = open_ledger(EMPTY_LEDGER, amount, OPENED).ledger
    return record_fill(ledger, FILL).ledger


def close(ledger: Ledger | None = None, **overrides: Any) -> CloseResult:
    return close_position(bought() if ledger is None else ledger, replace(CLOSE, **overrides))


def test_close_at_target_realizes_profit() -> None:
    """AC-3 (R-5, R-6, R-11): hedefte kapanış → USDT 10185.463248795, açık pozisyon 0, kapanmış 1,
    gerçekleşen kâr 185.463248795; kasa fiyat istemeden aynı."""
    result = close()

    ledger = result.ledger
    assert result.outcome is CloseOutcome.CLOSED and result.closure is not None
    assert ledger.balance == Decimal("10185.463248795")
    assert dict(ledger.positions) == {} and list(ledger.closures) == ["cb-x1"]
    assert result.closure.realized == ledger.realized == Decimal("185.463248795")
    assert result.closure.proceeds == Decimal("2114.214973695")
    assert result.closure.position.client_order_id == "cb-s1-btc-0001"
    snapshot = account_state(ledger, {}).snapshot
    assert snapshot is not None
    assert snapshot.equity == snapshot.free_balance == Decimal("10185.463248795")
    assert snapshot.open_positions == 0 and snapshot.realized == Decimal("185.463248795")
    assert "hedefte kapandı" in result.message


def test_close_at_stop_realizes_loss() -> None:
    """AC-4 (R-5, R-6): stop'ta kapanış → zarar -122.058929197, USDT 9877.941070803; açılış - Σ açık
    alış maliyeti + Σ K/Z = USDT."""
    result = close(price=Decimal("93.953"), fee=Decimal("1.808501297"), reason=CloseReason.STOP)

    assert result.outcome is CloseOutcome.CLOSED and result.closure is not None
    assert result.closure.realized == result.ledger.realized == Decimal("-122.058929197")
    assert result.ledger.balance == Decimal("9877.941070803")
    assert Decimal("10000") - 0 + result.ledger.realized == result.ledger.balance
    assert "stop'ta kapandı" in result.message


@pytest.mark.parametrize("amount", [Decimal("19.248"), Decimal("19.25")])
def test_partial_close_is_refused(amount: Decimal) -> None:
    """AC-5 (R-4): miktar pozisyonunkine eşit değil → "miktar pozisyonla uyuşmuyor", iki miktar
    adlandırılır, defter değişmez."""
    ledger = bought()

    result = close(ledger, amount=amount)

    assert result.outcome is CloseOutcome.INVALID_INPUT and result.ledger is ledger
    assert "miktar pozisyonla uyuşmuyor" in result.message
    assert f"kapanış {amount}" in result.message and "pozisyon 19.249" in result.message


SALE = Decimal("2116.331305")  # 19.249 * 109.945


def test_fee_above_the_sale_is_refused() -> None:
    """AC-6 (R-7): komisyon satış tutarını aşar → "geçersiz girdi", defter değişmez."""
    ledger = bought()

    result = close(ledger, fee=SALE + Decimal("0.000000001"))

    assert result.outcome is CloseOutcome.INVALID_INPUT and result.ledger is ledger
    assert "satış tutarından (2116.331305) büyük" in result.message


def test_fee_equal_to_the_sale_is_accepted() -> None:
    """AC-6 (R-7): komisyon satış tutarına eşit → kabul, gelir 0, bakiye değişmez, zarar alış
    maliyeti."""
    result = close(fee=SALE)

    assert result.outcome is CloseOutcome.CLOSED and result.closure is not None
    assert result.closure.proceeds == 0 and result.ledger.balance == Decimal("8071.2482751")
    assert result.ledger.realized == Decimal("-1928.7517249")


def test_same_close_is_already_recorded() -> None:
    """AC-7 (R-9): aynı kapanış kimliği ve içerik, farklı zaman → "zaten kayıtlı", tek kapanış."""
    first = close()

    again = close(first.ledger, at=LATER + timedelta(minutes=5))

    assert again.outcome is CloseOutcome.ALREADY_RECORDED and again.ledger is first.ledger
    assert again.closure == first.closure and len(again.ledger.closures) == 1
    assert "zaten kayıtlı" in again.message


CONFLICTS: dict[str, dict[str, Any]] = {
    "position": {"position_id": "cb-s1-btc-0002"},
    "amount": {"amount": Decimal("19.248")},
    "price": {"price": Decimal("109.9")},
    "fee": {"fee": Decimal("2")},
    "reason": {"reason": CloseReason.STOP},
}


@pytest.mark.parametrize("field", list(CONFLICTS))
def test_changed_close_is_a_conflict(field: str) -> None:
    """AC-7 (R-9): aynı kapanış kimliği farklı içerikle → "kayıt çakışması", kayıt değişmez."""
    first = close()

    result = close(first.ledger, **CONFLICTS[field])

    assert result.outcome is CloseOutcome.RECORD_CONFLICT and result.ledger is first.ledger
    assert "kayıt çakışması: cb-x1" in result.message


def test_close_with_a_buy_id_is_a_conflict() -> None:
    """AC-7 (R-9): alımın kimliğiyle gelen kapanış → "kayıt çakışması"."""
    ledger = bought()

    result = close(ledger, client_order_id="cb-s1-btc-0001")

    assert result.outcome is CloseOutcome.RECORD_CONFLICT and result.ledger is ledger
    assert "bir alımın kimliği" in result.message


def test_buy_with_a_close_id_is_a_conflict() -> None:
    """AC-7 (R-9): kapanışın kimliğiyle gelen alım → "kayıt çakışması"."""
    ledger = close().ledger

    result = record_fill(ledger, replace(FILL, client_order_id="cb-x1"))

    assert result.outcome is LedgerOutcome.RECORD_CONFLICT and result.ledger is ledger
    assert "bir kapanışın kimliği" in result.message


def test_closed_buy_stays_recorded() -> None:
    """AC-7 (R-9; plan 0008 Risk 2): kapanmış pozisyonun alımı yeniden gelirse ikinci kez yazılmaz:
    aynı içerik "zaten kayıtlı", farklı içerik "kayıt çakışması"."""
    ledger = close().ledger

    again = record_fill(ledger, replace(FILL, at=LATER))
    changed = record_fill(ledger, replace(FILL, amount=Decimal("1")))

    assert again.outcome is LedgerOutcome.ALREADY_RECORDED and again.ledger is ledger
    assert again.position is not None and again.position.client_order_id == "cb-s1-btc-0001"
    assert changed.outcome is LedgerOutcome.RECORD_CONFLICT and changed.ledger is ledger


def test_rejected_close_does_not_use_up_the_id() -> None:
    """AC-7 (R-9): reddedilen bir istek kapanış kimliğini tüketmez."""
    refused = close(amount=Decimal("1"))

    result = close(refused.ledger)

    assert refused.outcome is CloseOutcome.INVALID_INPUT
    assert result.outcome is CloseOutcome.CLOSED


def test_unknown_position_is_not_found() -> None:
    """AC-8 (R-10): olmayan pozisyon → "pozisyon bulunamadı", kimlik adlandırılır."""
    ledger = bought()

    result = close(ledger, position_id="cb-none")

    assert result.outcome is CloseOutcome.POSITION_NOT_FOUND and result.ledger is ledger
    assert "pozisyon bulunamadı: cb-none" in result.message


def test_closed_position_is_closed() -> None:
    """AC-8 (R-10): başka kimlikle zaten kapanmış pozisyon → "pozisyon kapalı", kapatan kimlik
    adlandırılır."""
    ledger = close().ledger

    result = close(ledger, client_order_id="cb-x2")

    assert result.outcome is CloseOutcome.POSITION_CLOSED and result.ledger is ledger
    assert "pozisyon kapalı: cb-s1-btc-0001 cb-x1 ile kapandı" in result.message


LONG = Decimal("1." + "2" * 28)  # 29 significant digits
BAD_POSITIVE: dict[str, tuple[Any, str]] = {
    "zero": (Decimal(0), "sıfırdan büyük"),
    "negative": (Decimal(-1), "sıfırdan büyük"),
    "nan": (Decimal("NaN"), "sıfırdan büyük"),
    "float": (109.945, "sıfırdan büyük"),
    "bool": (True, "sıfırdan büyük"),
    "huge_int": (-(10**4300), "sıfırdan büyük"),
    "out_of_scale": (Decimal("1E+1000000"), "ölçeği varsayılan üs aralığı"),
    "29_digits": (LONG, "<29 basamaklı sayı> 28 anlamlı basamaktan uzun"),
}
LABELS = {"amount": "miktar", "price": "dolum fiyatı"}
# (overrides, message fragments): the input's name and, for numbers, the rule
INVALID: dict[str, tuple[dict[str, Any], tuple[str, ...]]] = {
    f"{field}-{case}": ({field: value}, (f"{LABELS[field]} ", rule))
    for field in LABELS
    for case, (value, rule) in BAD_POSITIVE.items()
}
INVALID |= {
    "fee-negative": ({"fee": Decimal("-0.001")}, ("komisyon", "negatif olmayan")),
    "fee-nan": ({"fee": Decimal("NaN")}, ("komisyon", "negatif olmayan")),
    "id-empty": ({"client_order_id": ""}, ("kapanış clientOrderId",)),
    "id-37_chars": ({"client_order_id": "x" * 37}, ("kapanış clientOrderId",)),
    "id-unicode": ({"client_order_id": "cb-ğüş"}, ("kapanış clientOrderId",)),
    "id-not_text": ({"client_order_id": 42}, ("kapanış clientOrderId",)),
    "position-space": ({"position_id": "cb a"}, ("pozisyon clientOrderId",)),
    "position-not_text": ({"position_id": NOTHING}, ("pozisyon clientOrderId",)),
    "reason-text": ({"reason": "hedef"}, ("neden 'hedef'",)),
    "reason-none": ({"reason": NOTHING}, ("neden None",)),
    "at-no_zone": ({"at": datetime(2026, 11, 2, 11, 0)}, ("dolum zamanı",)),
    "at-not_time": ({"at": "2026-11-02"}, ("dolum zamanı",)),
    "at-before_position": ({"at": NOW - timedelta(seconds=1)}, ("pozisyonun açılışından",)),
}


@pytest.mark.parametrize("case", list(INVALID))
def test_invalid_close_is_named(case: str) -> None:
    """AC-9 (R-8, R-14): sayı kuralına, biçime uymayan girdi ve pozisyonun açılışından önceki
    kapanış → "geçersiz girdi", girdi adlandırılır, istisna yok, defter değişmez."""
    overrides, fragments = INVALID[case]
    ledger = bought()

    result = close(ledger, **overrides)

    assert result.outcome is CloseOutcome.INVALID_INPUT and result.closure is None
    assert result.ledger is ledger
    assert "geçersiz girdi" in result.message
    assert all(fragment in result.message for fragment in fragments), result.message
    assert len(result.message) < 500


UNREPRESENTABLE: dict[str, tuple[Decimal, dict[str, Any], str]] = {
    # in scale and within 28 significant digits each, but the sale or the new balance is not
    "long_price": (
        Decimal("10000"),
        {"price": Decimal("109.9450000000000000000000001")},
        "dolum fiyatı 109.9450000000000000000000001",
    ),
    # 1E+21 - 1928.7517249 fits in 28 digits; adding 2114.214973695 does not
    "long_balance": (Decimal("1E+21"), {}, "gelir 2114.214973695"),
}


@pytest.mark.parametrize("case", list(UNREPRESENTABLE))
def test_unrepresentable_close_is_named(case: str) -> None:
    """AC-9 (R-13, R-14; plan 0008 Risk 5): tam sonucu 28 basamağa sığmayan satış tutarı ya da
    bakiye yuvarlanmaz, "ölçek hesaplanamıyor" ile reddedilir; mesaj kısa kalır."""
    opening, overrides, number = UNREPRESENTABLE[case]
    ledger = bought(opening)

    result = close(ledger, **overrides)

    assert result.outcome is CloseOutcome.INVALID_INPUT and result.ledger is ledger
    assert "ölçek hesaplanamıyor" in result.message and number in result.message
    assert len(result.message) < 500


REFUSALS: dict[str, tuple[str, dict[str, Any], CloseOutcome]] = {
    # (ledger, overrides): two problems each; the first in R-13's order wins
    "invalid_and_not_opened": ("empty", {"amount": Decimal(0)}, CloseOutcome.INVALID_INPUT),
    "repeat_and_not_found": (
        "closed",
        {"position_id": "cb-none"},
        CloseOutcome.RECORD_CONFLICT,
    ),
    "same_repeat_and_closed": ("closed", {}, CloseOutcome.ALREADY_RECORDED),
    "not_found_and_amount": (
        "bought",
        {"position_id": "cb-none", "amount": Decimal("1")},
        CloseOutcome.POSITION_NOT_FOUND,
    ),
    "closed_and_amount": (
        "closed",
        {"client_order_id": "cb-x2", "amount": Decimal("1")},
        CloseOutcome.POSITION_CLOSED,
    ),
}


@pytest.mark.parametrize("case", list(REFUSALS))
def test_close_refusal_order(case: str) -> None:
    """AC-10 (R-13): geçersiz girdi → defter açılmamış → zaten kayıtlı / çakışma → pozisyon
    bulunamadı → pozisyon kapalı → miktar uyuşmuyor."""
    kind, overrides, expected = REFUSALS[case]
    ledgers = {"empty": EMPTY_LEDGER, "bought": bought(), "closed": close().ledger}

    result = close(ledgers[kind], **overrides)

    assert result.outcome is expected and result.ledger is ledgers[kind]
