"""Spec 0037 AC-3 (defter yarısı), AC-7: canlıda kısmi kapanış, orantılı maliyet, kalan pozisyon."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from crytobot.portfolio import (
    EMPTY_LEDGER,
    Close,
    CloseOutcome,
    CloseReason,
    Fill,
    Ledger,
    close_position,
    ledger_problems,
    open_ledger,
    record_fill,
    remaining_position,
)

OPENED = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
NOW = OPENED + timedelta(hours=1)
LATER = NOW + timedelta(hours=1)
LAST = LATER + timedelta(hours=1)
# 10 @ 100, fee 0.3: cost 1000.3
FILL = Fill(
    "cb-p1",
    "BTC/USDT",
    "buy",
    Decimal("10"),
    Decimal("100"),
    Decimal("0.3"),
    Decimal("95"),
    Decimal("110"),
    NOW,
)


def bought(fill: Fill = FILL, deposit: Decimal = Decimal("10000")) -> Ledger:
    ledger = open_ledger(EMPTY_LEDGER, deposit, OPENED).ledger
    return record_fill(ledger, fill).ledger


def sale(
    cid: str, amount: str, price: str = "110", fee: str = "0.1", at: datetime = LATER
) -> Close:
    return Close(
        cid, "cb-p1", Decimal(amount), Decimal(price), Decimal(fee), CloseReason.TARGET, at
    )


def test_partial_close_cost_is_proportional() -> None:
    """AC-3 (R-3, G-7): 4 / 10 kısmı kapanınca maliyet 4 / 10 * (10 * 100 + 0.3) = 400.12; kâr/zarar
    o kısım için yazılır, kalan 6 aynı kimlik, maliyet fiyatı, stop ve hedefle açık kalır, ücreti
    0.18'dir. Defter kayıtlarından aynen türer."""
    ledger = bought()

    result = close_position(ledger, sale("cx-p1", "4"), partial=True)

    assert result.outcome is CloseOutcome.CLOSED
    closure = result.closure
    assert closure is not None
    assert closure.proceeds == Decimal("439.9")  # 4 * 110 - 0.1
    assert closure.realized == Decimal("439.9") - Decimal("400.12")
    assert closure.position == ledger.positions["cb-p1"]  # the position before the part
    rest = result.ledger.positions["cb-p1"]
    assert (rest.amount, rest.cost_price, rest.fee) == (
        Decimal("6"),
        Decimal("100"),
        Decimal("0.18"),
    )
    assert (rest.stop, rest.target, rest.opened_at) == (Decimal("95"), Decimal("110"), NOW)
    assert ledger.balance is not None
    assert result.ledger.balance == ledger.balance + Decimal("439.9")
    assert result.ledger.realized == closure.realized
    assert "kısmen kapandı" in result.message and "kalan miktar 6" in result.message
    assert ledger_problems(result.ledger) == []


def test_rest_closes_in_full_with_its_own_cost() -> None:
    """AC-3 (R-3): kalan pozisyon sonraki kapanışta tamamen kapanır; maliyeti kalan miktar *
    maliyet fiyatı + kalan ücrettir, pozisyon defterden çıkar."""
    first = close_position(bought(), sale("cx-p1", "4"), partial=True).ledger

    result = close_position(first, sale("cx2-p1", "6", at=LAST), partial=True)

    assert result.outcome is CloseOutcome.CLOSED and result.closure is not None
    assert result.closure.realized == Decimal("659.9") - Decimal("600.18")
    assert result.ledger.positions == {}
    assert list(result.ledger.closures) == ["cx-p1", "cx2-p1"]
    assert ledger_problems(result.ledger) == []
    assert result.ledger.bought("cb-p1") == bought().positions["cb-p1"]
    assert result.ledger.filled_position("cb-p1") == bought().positions["cb-p1"]
    assert result.ledger.parts("cb-p1") == 2


def test_partial_close_needs_the_flag() -> None:
    """AC-7 (R-7): bayraksız (paper, backtest) kısmi kapanış bugünkü gibi reddedilir; bayrakla da
    miktardan büyük kısım reddedilir."""
    ledger = bought()
    for flag in (False, True):
        amount = "4" if not flag else "11"
        result = close_position(ledger, sale("cx-p1", amount), partial=flag)
        assert result.outcome is CloseOutcome.INVALID_INPUT and result.ledger is ledger
        assert "miktar pozisyonla uyuşmuyor" in result.message


def test_closed_position_names_its_last_close() -> None:
    """Kısmi kapanıştan sonra tamamen kapanan pozisyon, son kapanışın kimliğiyle "kapalı" denir."""
    first = close_position(bought(), sale("cx-p1", "4"), partial=True).ledger
    done = close_position(first, sale("cx2-p1", "6", at=LAST), partial=True).ledger

    result = close_position(done, sale("cx3-p1", "1", at=LAST), partial=True)

    assert result.outcome is CloseOutcome.POSITION_CLOSED
    assert "cx2-p1 ile kapandı" in result.message


def test_remaining_position_refuses_bad_parts() -> None:
    """Saf yardımcı: kısım sıfırdan büyük ve miktardan küçük olmalı; kalan miktar 28 basamağa
    sığmalı."""
    position = bought().positions["cb-p1"]
    for part in (Decimal(0), Decimal(10), Decimal(11), Decimal("-1")):
        with pytest.raises(ValueError):
            remaining_position(position, part)
    with pytest.raises(ValueError):
        remaining_position(position, Decimal("1E-40"))


def test_replay_refuses_tampered_rest() -> None:
    """Kalan pozisyonu kayıtlardan türeyenden farklı olan defter bozuk sayılır."""
    ledger = close_position(bought(), sale("cx-p1", "4"), partial=True).ledger
    rest = ledger.positions["cb-p1"]
    tampered = replace(ledger, positions={"cb-p1": replace(rest, fee=Decimal("0.2"))})

    assert ledger_problems(tampered) == ["açık pozisyonlar kayıtlardan türeyenle aynı değil"]


def test_replay_refuses_a_close_above_the_position() -> None:
    """Pozisyondan büyük kapanış kaydı türetilemez."""
    ledger = close_position(bought(), sale("cx-p1", "10")).ledger
    entry = ledger.entries[-1]
    assert entry.closure is not None
    big = replace(entry.closure, amount=Decimal("11"))
    tampered = replace(ledger, entries=(*ledger.entries[:-1], replace(entry, closure=big)))

    assert ledger_problems(tampered) == ["cx-p1: miktar pozisyonla uyuşmuyor"]


AMOUNTS = st.integers(min_value=2, max_value=10**8).map(lambda n: Decimal(n).scaleb(-4))
FEES = st.integers(min_value=0, max_value=10**9).map(lambda n: Decimal(n).scaleb(-9))
PRICES = st.integers(min_value=1, max_value=10**9).map(lambda n: Decimal(n).scaleb(-3))


@settings(max_examples=300, deadline=None)
@given(
    amount=AMOUNTS,
    fee=FEES,
    price=PRICES,
    cuts=st.lists(st.integers(min_value=1, max_value=99), min_size=1, max_size=6),
)
def test_parts_sum_to_full_close(
    amount: Decimal, fee: Decimal, price: Decimal, cuts: list[int]
) -> None:
    """AC-3 (G-7, plan Risk 1; özellik): bir pozisyon rastgele parçalarla kapandığında parçaların
    maliyet toplamı tam kapanışın maliyetine (miktar * fiyat + ücret) birebir eşittir; bakiye ve
    gerçekleşen toplam aynıdır; her ara defter kayıtlarından aynen türer."""
    fill = replace(FILL, amount=amount, price=price, fee=fee)
    start = bought(fill, Decimal("1E+15"))
    assert start.positions, "the deposit covers every generated buy"
    full = close_position(start, sale("cx-full", str(amount), "1", "0"))
    assert full.closure is not None

    ledger, rest, at = start, amount, LATER
    parts: list[Decimal] = []
    for index, cut in enumerate(cuts):
        part = (rest * cut / 100).quantize(Decimal("0.0001"))
        if not 0 < part < rest:
            continue
        cid = "cx-p1" if index == 0 else f"cx{index + 1}-p1"
        result = close_position(ledger, sale(cid, str(part), "1", "0", at), partial=True)
        assert result.outcome is CloseOutcome.CLOSED, result.message
        ledger, rest = result.ledger, rest - part
        parts.append(part)
        at += timedelta(minutes=1)
    last = close_position(ledger, sale("cx-last", str(rest), "1", "0", at), partial=True)
    assert last.outcome is CloseOutcome.CLOSED, last.message
    ledger = last.ledger

    with localcontext(prec=200):  # every share is exact; the default 28 digits would round
        costs = [c.proceeds - c.realized for c in ledger.closures.values()]
        assert sum(costs) == amount * price + fee
    assert ledger.positions == {}
    assert ledger.balance == full.ledger.balance
    assert ledger.realized == full.ledger.realized
    assert ledger_problems(ledger) == []
