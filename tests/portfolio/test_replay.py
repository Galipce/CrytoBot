"""Spec 0011 R-6: `ledger_problems` motorun her defterini kabul eder, türetilemeyeni adlandırır."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from crytobot.portfolio import (
    EMPTY_LEDGER,
    Close,
    CloseOutcome,
    CloseReason,
    Entry,
    EntryKind,
    Fill,
    Ledger,
    LedgerOutcome,
    Position,
    close_position,
    ledger_problems,
    open_ledger,
    record_fill,
)

T0 = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
LATER = T0 + timedelta(hours=1)


hand_built: Any = replace  # deliberately wrong field types


def opened() -> Ledger:
    return open_ledger(EMPTY_LEDGER, Decimal("10000.10"), T0).ledger


def filled(cid: str = "cb-a") -> Ledger:
    fill = Fill(
        cid,
        "BTC/USDT",
        "buy",
        Decimal("2.50"),
        Decimal("100.10"),
        Decimal("0.25"),
        Decimal("95"),
        Decimal("110"),
        LATER,
    )
    result = record_fill(opened(), fill)
    assert result.outcome is LedgerOutcome.RECORDED
    return result.ledger


def closed() -> Ledger:
    close = Close(
        "cx-a", "cb-a", Decimal("2.50"), Decimal("110.5"), Decimal("0.3"), CloseReason.TARGET, LATER
    )
    result = close_position(filled(), close)
    assert result.outcome is CloseOutcome.CLOSED
    return result.ledger


@pytest.mark.parametrize("ledger", [EMPTY_LEDGER, opened(), filled(), closed()])
def test_ledgers_the_engine_builds_have_no_problems(ledger: Ledger) -> None:
    assert ledger_problems(ledger) == []


def _steps() -> st.SearchStrategy[list[tuple[str, Decimal, Decimal, Decimal]]]:
    numbers = st.decimals(min_value=Decimal("0.001"), max_value=Decimal("50"), places=3)
    fees = st.decimals(min_value=Decimal(0), max_value=Decimal("0.05"), places=4)
    return st.lists(
        st.tuples(st.sampled_from(["buy", "close"]), numbers, numbers, fees), max_size=15
    )


@given(steps=_steps())
@settings(max_examples=100)
def test_every_engine_ledger_replays_to_itself(
    steps: list[tuple[str, Decimal, Decimal, Decimal]],
) -> None:
    """Motorun ürettiği defterde bakiye, pozisyonlar, kapanışlar ve toplam yeniden türetilir."""
    ledger = opened()
    for index, (kind, amount, price, fee) in enumerate(steps):
        if kind == "buy":
            fill = Fill(
                f"cb-{index}",
                "BTC/USDT",
                "buy",
                amount,
                price,
                fee,
                Decimal("1"),
                Decimal("2"),
                LATER,
            )
            ledger = record_fill(ledger, fill).ledger
        elif ledger.positions:
            position = next(iter(ledger.positions.values()))
            close = Close(
                f"cx-{index}",
                position.client_order_id,
                position.amount,
                price,
                fee,
                CloseReason.STOP,
                LATER,
            )
            ledger = close_position(ledger, close).ledger
        assert ledger_problems(ledger) == []


def _fill_entry(**changes: Any) -> Ledger:
    ledger = filled()
    entry = ledger.entries[1]
    return replace(ledger, entries=(ledger.entries[0], replace(entry, **changes)))


def _opened_position() -> Position:
    position = filled().entries[1].position
    assert position is not None
    return position


def _position(**changes: Any) -> Ledger:
    return _fill_entry(position=replace(_opened_position(), **changes))


def _close_entry(**changes: Any) -> Ledger:
    ledger = closed()
    entry = ledger.entries[2]
    return replace(ledger, entries=(*ledger.entries[:2], replace(entry, **changes)))


def _closure(**changes: Any) -> Ledger:
    entry = closed().entries[2]
    assert entry.closure is not None
    return _close_entry(closure=replace(entry.closure, **changes))


def _second_position_close() -> Ledger:
    """Kapanmış pozisyon ikinci kez kapanıyor."""
    ledger = closed()
    entry = ledger.entries[2]
    assert entry.closure is not None
    again = replace(entry, closure=replace(entry.closure, client_order_id="cx-b"))
    return replace(ledger, entries=(*ledger.entries, again))


def _duplicate_fill() -> Ledger:
    ledger = filled()
    return replace(ledger, entries=(*ledger.entries, ledger.entries[1]))


def _fill_with_close_id() -> Ledger:
    ledger = closed()
    entry = ledger.entries[1]
    assert entry.position is not None
    return replace(
        ledger,
        entries=(
            *ledger.entries,
            replace(entry, position=replace(entry.position, client_order_id="cx-a")),
        ),
    )


def _close_id_taken() -> Ledger:
    entry = closed().entries[2]
    assert entry.closure is not None
    return _close_entry(closure=replace(entry.closure, client_order_id="cb-a"))


BROKEN: dict[str, Any] = {
    "not_a_ledger": "defter",
    "entries_not_a_tuple": hand_built(filled(), entries=list(filled().entries)),
    "positions_not_a_mapping": hand_built(filled(), positions=("x",)),
    "not_an_entry": hand_built(filled(), entries=("kayıt",)),
    "first_entry_not_opening": replace(filled(), entries=filled().entries[1:]),
    "second_opening": replace(opened(), entries=opened().entries * 2),
    "opening_with_position": replace(
        opened(), entries=(replace(opened().entries[0], position=filled().entries[1].position),)
    ),
    "opening_amount_bad": replace(
        opened(), entries=(replace(opened().entries[0], usdt=Decimal(0)),)
    ),
    "opening_time_naive": replace(
        opened(), entries=(replace(opened().entries[0], at=T0.replace(tzinfo=None)),)
    ),
    "kind_unknown": _fill_entry(kind="dolum"),
    "fill_with_closure": _fill_entry(closure=closed().entries[2].closure),
    "fill_without_position": _fill_entry(position=None),
    "bad_id": _position(client_order_id="a b"),
    "pair_not_text": _position(pair=1),
    "amount_nan": _position(amount=Decimal("NaN")),
    "amount_int": _position(amount=2),
    "amount_zero": _position(amount=Decimal(0)),
    "stop_too_long": _position(stop=Decimal("1." + "1" * 28)),
    "out_of_scale": _position(target=Decimal("1E+1000000")),
    "opened_naive": _position(opened_at=LATER.replace(tzinfo=None)),
    "duplicate_fill": _duplicate_fill(),
    "fill_with_close_id": _fill_with_close_id(),
    "fill_time_differs": _fill_entry(at=LATER + timedelta(seconds=1)),
    "fill_before_opening": replace(_position(opened_at=T0 - timedelta(days=1)), positions={}),
    "cost_differs": _fill_entry(usdt=Decimal("1")),
    "cost_trailing_zero": _fill_entry(usdt=Decimal(f"{filled().entries[1].usdt}0")),
    "balance_differs": replace(filled(), balance=Decimal("1")),
    "balance_trailing_zero": replace(opened(), balance=Decimal("10000.100")),
    "realized_differs": replace(closed(), realized=Decimal("1")),
    "position_missing": replace(filled(), positions=MappingProxyType({})),
    "position_extra": replace(opened(), positions=filled().positions),
    "position_value_differs": replace(
        filled(),
        positions=MappingProxyType(
            {"cb-a": replace(filled().positions["cb-a"], stop=Decimal("96"))}
        ),
    ),
    "closure_missing": replace(closed(), closures=MappingProxyType({})),
    "closure_without_record": _close_entry(closure=None),
    "closure_bad_id": _closure(client_order_id="a b"),
    "closure_id_taken": _close_id_taken(),
    "closure_bad_number": _closure(price=Decimal("NaN")),
    "closure_bad_reason": _closure(reason="stop"),
    "closure_naive": _closure(closed_at=LATER.replace(tzinfo=None)),
    "closure_amount_differs": _closure(amount=Decimal("2")),
    "closure_time_differs": _closure(closed_at=LATER + timedelta(seconds=1)),
    "closure_before_position": _closure(closed_at=LATER - timedelta(seconds=1)),
    "closure_position_differs": _closure(position=opened().entries[0]),
    "close_without_position": _close_entry(position=None),
    "close_position_differs": _close_entry(
        position=hand_built(filled().entries[1].position, stop=Decimal("96"))
    ),
    "proceeds_differ": _closure(proceeds=Decimal("1")),
    "realized_field_differs": _closure(realized=Decimal("1")),
    "close_amount_differs_entry": _close_entry(usdt=Decimal("1")),
    "close_time_differs": _close_entry(at=LATER + timedelta(seconds=1)),
    "second_close_of_position": _second_position_close(),
}


@pytest.mark.parametrize("case", list(BROKEN))
def test_ledger_that_does_not_derive_is_named(case: str) -> None:
    problems = ledger_problems(BROKEN[case])

    assert problems
    assert all(len(problem) < 200 for problem in problems)


def test_fee_larger_than_sale_is_named() -> None:
    assert ledger_problems(_closure(fee=Decimal("1000"))) == [
        "cx-a: komisyon satış tutarından büyük"
    ]


def test_cost_above_balance_is_named() -> None:
    """Kayıt tutarı doğru hesaplanmış olsa da bakiye negatife düşemez."""
    position = replace(_opened_position(), amount=Decimal("1000"))
    cost = position.amount * position.cost_price + position.fee

    ledger = _fill_entry(position=position, usdt=cost)

    assert ledger_problems(ledger) == ["cb-a: bakiye negatife düşüyor"]


def test_fill_before_the_opening_is_named() -> None:
    early = T0 - timedelta(days=1)

    ledger = _fill_entry(position=replace(_opened_position(), opened_at=early), at=early)

    assert ledger_problems(ledger) == ["dolum açılıştan önce"]


def test_close_before_the_position_opened_is_named() -> None:
    early = LATER - timedelta(seconds=1)
    entry = closed().entries[2]
    assert entry.closure is not None

    ledger = _close_entry(closure=replace(entry.closure, closed_at=early), at=early)

    assert ledger_problems(ledger) == ["cx-a: kapanış pozisyonun açılışından önce"]


def test_close_of_a_position_that_is_not_open_is_named() -> None:
    entry = closed().entries[2]
    assert entry.closure is not None
    ledger = closed()
    again = replace(entry, closure=replace(entry.closure, client_order_id="cx-b"))

    assert ledger_problems(replace(ledger, entries=(*ledger.entries, again))) == [
        "cx-b: kapatılan pozisyon açık değil"
    ]


def test_calculation_past_60_digits_is_named() -> None:
    long = Decimal("1." + "1" * 27)
    ledger = _position(amount=long, cost_price=Decimal("1." + "3" * 59))

    assert ledger_problems(ledger) == ["kayıtların hesabı 60 basamağa sığmıyor"]


def test_entry_kinds_are_exhausted() -> None:
    assert {kind.value for kind in EntryKind} == {"opening", "fill", "close"}
    assert isinstance(opened().entries[0], Entry)
