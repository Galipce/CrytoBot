"""Spec 0015 AC-6, AC-7: fiyat geçerliliği ve tick'e yuvarlama.

Property testlerinde kesişim rastgele seride nadirdir; sabit `CROSS` serisi ölçeklenir, `k`, `r` ve
tick üretilir (plan 0015, Risk 9). Beklenen fiyatlar `Fraction` ile bağımsız hesaplanır.
"""

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest
from hypothesis import find, given
from hypothesis import strategies as st

from crytobot.analysis import atr
from crytobot.risk import TradeIntent
from crytobot.strategy import NoProposal, NoProposalReason, propose
from crytobot.strategy._proposal import _round_up, _shortest
from tests.analysis.helpers import from_closes
from tests.strategy.helpers import CROSS, CROSS_FROM_EQUAL, PAIR, make_settings, run

INVALID_PRICES = NoProposal(NoProposalReason.INVALID_PRICES)
TICKS = ["0.00000001", "0.00001", "0.01", "0.25", "0.5", "1", "3", "5", "100"]


@dataclass(frozen=True)
class PriceCase:
    closes: tuple[float, ...]
    k: Decimal
    r: Decimal
    tick: Decimal

    def result(self) -> TradeIntent | NoProposal:
        return propose(
            pair=PAIR,
            candles=from_closes(self.closes),
            position_open=False,
            tick=self.tick,
            settings=make_settings(k=self.k, r=self.r),
        )


def price_cases() -> st.SearchStrategy[PriceCase]:
    return st.builds(
        PriceCase,
        closes=st.floats(min_value=1e-8, max_value=1e5).map(
            lambda scale: tuple(close * scale for close in CROSS)
        ),
        k=st.decimals(min_value=Decimal("0.01"), max_value=Decimal(1000), places=2),
        r=st.decimals(min_value=Decimal("0.01"), max_value=Decimal(1000), places=2),
        tick=st.sampled_from(TICKS).map(Decimal),
    )


def as_fraction(value: object) -> Fraction:
    assert isinstance(value, Decimal)
    return Fraction(value)


@pytest.mark.parametrize("k", [10, Decimal(11), Decimal("1E+30")])
def test_stop_at_or_below_zero_is_invalid_prices(k: Any) -> None:
    """Giriş 10, ATR 1: `k = 10` stop'u tam sıfıra, büyüğü sıfırın altına indirir."""
    assert run(k=k) == INVALID_PRICES


def test_stop_rounding_to_zero_is_invalid_prices() -> None:
    """Ham stop 0.5 pozitiftir, tick 1 ile sıfıra iner."""
    assert run(k=Decimal("9.5")) == INVALID_PRICES


def test_tick_breaking_order_is_invalid_prices() -> None:
    """Tick 5: giriş 10, stop 8 → 5, hedef 14 → 10; hedef girişi geçmiyor."""
    assert run(tick=5) == INVALID_PRICES


@given(case=price_cases())
def test_proposal_prices_are_ordered(case: PriceCase) -> None:
    """Sinyal her örnekte vardır: sonuç ya sıralı öneri ya da `INVALID_PRICES`; kısmi sonuç yok."""
    result = case.result()
    if isinstance(result, TradeIntent):
        assert 0 < as_fraction(result.stop) < as_fraction(result.entry) < as_fraction(result.target)
    else:
        assert result == INVALID_PRICES


def test_price_property_is_not_vacuous() -> None:
    """`find` örnek bulamazsa `NoSuchExample` fırlatır: iki sonuç da gerçekten üretiliyor."""
    found = find(price_cases(), lambda case: isinstance(case.result(), TradeIntent))
    assert isinstance(found.result(), TradeIntent)
    assert find(price_cases(), lambda case: case.result() == INVALID_PRICES).result() == (
        INVALID_PRICES
    )


@given(case=price_cases())
def test_prices_are_decimal_tick_multiples(case: PriceCase) -> None:
    result = case.result()
    if not isinstance(result, TradeIntent):
        return
    tick = Fraction(case.tick)
    entry, stop, target = (as_fraction(p) for p in (result.entry, result.stop, result.target))
    for price in (entry, stop, target):
        assert (price / tick).denominator == 1
    atr_value = atr(from_closes(case.closes), period=2)[-1]
    assert atr_value is not None
    raw_entry = Fraction(Decimal(repr(case.closes[-1])))
    distance = Fraction(case.k) * Fraction(Decimal(repr(atr_value)))
    assert raw_entry <= entry < raw_entry + tick
    assert stop <= raw_entry - distance < stop + tick
    assert target <= raw_entry + Fraction(case.r) * distance < target + tick


def test_entry_rounds_up_stop_and_target_round_down() -> None:
    """Kapanış 10.125, ATR 1.1875 (`k = r = 1`): 8.9375 → 8.75, 11.3125 → 11.25, giriş → 10.25."""
    result = run((10.0, 8.0, 8.5, 10.125), k=1, r=1, tick=Decimal("0.25"))
    assert result == TradeIntent(PAIR, "buy", Decimal("10.25"), Decimal("8.75"), Decimal("11.25"))


def test_non_power_of_ten_tick() -> None:
    """Tick 3: giriş 10 → 12, stop 8 → 6, hedef 10 + 3 * 2 = 16 → 15."""
    assert run(r=3, tick=3) == TradeIntent(PAIR, "buy", Decimal(12), Decimal(6), Decimal(15))


@pytest.mark.parametrize("tick", [1, Decimal("0.5"), Decimal("0.01")])
def test_tick_multiple_is_unchanged(tick: Any) -> None:
    assert run(tick=tick) == TradeIntent(PAIR, "buy", Decimal(10), Decimal(8), Decimal(14))


def test_float_close_keeps_shortest_form() -> None:
    """AC-7'nin `0.1` ve tick `0.1` örneği yalnız giriş yuvarlamasında görülür: `0.1`'in altında
    tick'in pozitif katı yok, stop sıfıra iner ve öneri çıkmaz. `1.1` aynı artığı public yoldan
    sınar.
    """
    assert _round_up(_shortest(0.1), Decimal("0.1")) == Decimal("0.1")
    assert str(_round_up(_shortest(0.1), Decimal("0.1"))) == "0.1"
    result = run((1.0, 0.8, 0.85, 1.1), rsi_threshold=80, tick=Decimal("0.1"))
    assert isinstance(result, TradeIntent)
    assert result.entry == Decimal("1.1")
    assert run((0.1, 0.08, 0.085, 0.1), tick=Decimal("0.1")) == INVALID_PRICES


def test_integer_close_and_tick() -> None:
    result = run(tuple(int(close) for close in CROSS_FROM_EQUAL), tick=1, k=2, r=2)
    assert isinstance(result, TradeIntent)
    assert all(isinstance(p, Decimal) for p in (result.entry, result.stop, result.target))
    assert (result.entry, result.stop, result.target) == (10, 8, 14)
