"""Spec 0020 AC-3…AC-12: dolum fiyatında config risk limiti ve BR-8 kapıları.

Aksi yazılmadıkça `helpers`'ın senaryosu: kasa 10000, işlem riski %1, sabit üst sınır %2, ücret
0.001, slippage 0.001, spread 0.0005, kat 2, adım 0.001, giriş 10, stop 8, hedef 14; onaylı miktar
49.309. Dolumdaki risk = miktar * ((dolum - stop) + dolum * ücret + stop * ücret); tutarlar elle
hesaplanmıştır.
"""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import PairNote, TurnOutcome, TurnResult, TurnSettings, _buys
from crytobot.execution import place_order
from crytobot.risk import PairRules
from tests.app.helpers import (
    BTC,
    ETH,
    FIRST_AMOUNT,
    FLAT,
    LATER,
    RULES,
    STRATEGY,
    Bot,
    limits,
    make_settings,
    opened_store,
    pair_market,
)

LIMIT, EDGE = PairNote.RISK_LIMIT_AT_FILL, PairNote.INSUFFICIENT_EDGE_AT_FILL
# AC-7: hedef 12, adım 25: 100 // (25 * 2.02801) = 1 adım, miktar 25
EDGE_SETTINGS = make_settings(strategy=replace(STRATEGY, r=Decimal(1)))
STEP_25 = PairRules(Decimal(25), RULES.min_amount, RULES.min_notional)
# AC-8: seri 99, 97, 98, 99: ATR 1, k=9 → stop 90; r=0.2223 → hedef 101.0007, tick'e 101
EDGE_EXACT_SERIES = (99.0, 97.0, 98.0, 99.0)
EDGE_EXACT_SETTINGS = make_settings(
    strategy=replace(STRATEGY, k=Decimal(9), r=Decimal("0.2223")),
    fee=Decimal(0),
    slippage=Decimal(0),
)
STEP_10 = PairRules(Decimal(10), RULES.min_amount, RULES.min_notional)


def fresh(tmp_path: Path, name: str = "s.db", **kwargs: Any) -> Bot:
    return Bot(opened_store(tmp_path / name), **kwargs)


def reasons(result: TurnResult) -> list[Any]:
    return [p.reason for p in result.pairs]


def assert_no_trace(bot: Bot, result: TurnResult) -> None:
    """R-7: emir, defter, durdurma ve bildirim yok."""
    assert result.outcome is TurnOutcome.COMPLETED
    assert result.buys == () and result.halts == () and bot.notices == []
    stored = bot.stored()
    assert stored.execution.orders == {} and stored.ledger.positions == {}
    assert bot.conflicts() == ()


def test_price_at_entry_buys_the_sized_amount(tmp_path: Path) -> None:
    """AC-3 (R-1, R-2): fiyat 10, dolum 10.01, risk 49.309 * 2.02801 = 99.998... <= 100."""
    bot = fresh(tmp_path)

    result = bot.turn({BTC: pair_market(price=Decimal(10))})

    assert [o.amount for o in result.buys] == [Decimal("49.309")] == [FIRST_AMOUNT]
    assert [o.fill_price for o in result.buys] == [Decimal("10.01")]


@pytest.mark.parametrize("price", [Decimal("10.01"), Decimal(11)])
def test_risk_over_config_limit_places_no_order(tmp_path: Path, price: Decimal) -> None:
    """AC-4 (R-2): 10.01'de dolum 10.02001, risk 49.309 * 2.03803001 ~ 100.49; 11'de dolum 11.011,
    risk 49.309 * 3.030011 ~ 149.41 (sabit üst sınır 200'ün altında)."""
    bot = fresh(tmp_path)

    result = bot.turn({BTC: pair_market(price=price)})

    assert reasons(result) == [LIMIT]
    assert_no_trace(bot, result)


ZERO_COSTS = make_settings(fee=Decimal(0), slippage=Decimal(0))
STEP_1 = PairRules(Decimal(1), RULES.min_amount, RULES.min_notional)


def test_risk_exactly_at_limit_buys(tmp_path: Path) -> None:
    """AC-5 (R-2): ücret ve slippage 0, adım 1: 100 // 2 = 50; fiyat 10'da risk 50 * 2 = 100."""
    bot = fresh(tmp_path, settings=ZERO_COSTS)

    result = bot.turn({BTC: pair_market(price=Decimal(10), rules=STEP_1)})

    assert [o.amount for o in result.buys] == [Decimal(50)]


def test_risk_just_over_limit_places_no_order(tmp_path: Path) -> None:
    """AC-5 (R-2): aynı senaryoda fiyat 10.01: risk 50 * 2.01 = 100.5."""
    bot = fresh(tmp_path, settings=ZERO_COSTS)

    result = bot.turn({BTC: pair_market(price=Decimal("10.01"), rules=STEP_1)})

    assert reasons(result) == [LIMIT]
    assert_no_trace(bot, result)


def test_limit_equal_to_hard_cap_names_the_cap(tmp_path: Path) -> None:
    """AC-6 (R-3, R-5): limit %2 = üst sınır: miktar 200 // (0.001 * 2.02801) * 0.001 = 98.618;
    fiyat 11'de risk 98.618 * 3.030011 ~ 298.8 > 200: neden sabit üst sınırdır."""
    settings = make_settings(limits=limits(per_trade_risk=Decimal("0.02")))
    bot = fresh(tmp_path, settings=settings)

    result = bot.turn({BTC: pair_market(price=Decimal(11))})

    assert reasons(result) == [PairNote.RISK_CAP_AT_FILL]
    assert_no_trace(bot, result)


def test_edge_below_multiple_places_no_order(tmp_path: Path) -> None:
    """AC-7 (R-4): fiyat 11.9: dolum 11.9119 < 12, risk 25 * 3.9318119 ~ 98.30 <= 100;
    kâr 0.1, maliyet 23.9 * 0.001 + 11.9 * 0.0005 + 23.9 * 0.001 = 0.05375, 2 * 0.05375 >= 0.1."""
    bot = fresh(tmp_path, settings=EDGE_SETTINGS)

    result = bot.turn({BTC: pair_market(price=Decimal("11.9"), rules=STEP_25)})

    assert reasons(result) == [EDGE]
    assert_no_trace(bot, result)


def test_edge_above_multiple_buys(tmp_path: Path) -> None:
    """AC-7 (R-4): fiyat 11: kâr 1, maliyet 0.0515, risk 25 * 3.030011 ~ 75.75."""
    bot = fresh(tmp_path, settings=EDGE_SETTINGS)

    result = bot.turn({BTC: pair_market(price=Decimal(11), rules=STEP_25)})

    assert [o.amount for o in result.buys] == [Decimal(25)]


def edge_exact_market(price: str) -> Any:
    return pair_market(
        EDGE_EXACT_SERIES, price=Decimal(price), rules=STEP_10, spread=Decimal("0.005")
    )


def test_edge_exactly_at_multiple_places_no_order(tmp_path: Path) -> None:
    """AC-8 (R-4): giriş 99, stop 90, hedef 101, miktar 100 // (10 * 9) * 10 = 10; fiyat 100'de
    risk 10 * 10 = 100 (limite eşit, geçer); kâr 1 = 2 * (100 * 0.005): kat geçilmez."""
    bot = fresh(tmp_path, settings=EDGE_EXACT_SETTINGS)

    result = bot.turn({BTC: edge_exact_market("100")})

    assert reasons(result) == [EDGE]
    assert_no_trace(bot, result)


def test_edge_just_above_multiple_buys(tmp_path: Path) -> None:
    """AC-8 (R-4): fiyat 99.9: kâr 1.1 > 2 * 0.4995 = 0.999; risk 10 * 9.9 = 99."""
    bot = fresh(tmp_path, settings=EDGE_EXACT_SETTINGS)

    result = bot.turn({BTC: edge_exact_market("99.9")})

    assert [(o.amount, o.entry, o.stop, o.target) for o in result.buys] == [
        (Decimal(10), Decimal(99), Decimal(90), Decimal(101))
    ]


def test_approved_edge_at_entry_passes_the_gate(tmp_path: Path) -> None:
    """AC-9 (R-4): `r=0.05`, hedef 10.10: kâr 0.1 > 2 * 0.0452; `risk` onayladı, kapı da geçer."""
    settings = make_settings(strategy=replace(STRATEGY, r=Decimal("0.05")))
    bot = fresh(tmp_path, settings=settings)

    result = bot.turn({BTC: pair_market(price=Decimal(10))})

    assert [(o.amount, o.target) for o in result.buys] == [(FIRST_AMOUNT, Decimal("10.1"))]


def test_limit_outranks_edge(tmp_path: Path) -> None:
    """AC-10 (R-5): hedef 12, fiyat 11.9, miktar 49.309: risk 49.309 * 3.9318119 ~ 193.9 (> 100,
    < 200) ve kat da bozulur (AC-7); ilk tutmayan koşul config limitidir."""
    bot = fresh(tmp_path, settings=EDGE_SETTINGS)

    result = bot.turn({BTC: pair_market(price=Decimal("11.9"))})

    assert reasons(result) == [LIMIT]


REFUSED: dict[str, tuple[TurnSettings, dict[str, Any], PairNote]] = {
    "limit": (make_settings(), {"price": Decimal(11)}, LIMIT),
    "edge": (EDGE_SETTINGS, {"price": Decimal("11.9"), "rules": STEP_25}, EDGE),
}


@pytest.mark.parametrize("case", list(REFUSED))
def test_refused_turn_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """AC-11 (R-6, R-7): emir denenmez (küçültülmüş miktarla da), defter ve risk durumu öneri
    olmayan turla aynıdır; bildirim, durdurma yok."""
    settings, market, note = REFUSED[case]
    placed: list[Any] = []

    def spy(*args: Any) -> Any:
        placed.append(args)
        return place_order(*args)

    monkeypatch.setattr(_buys, "place_order", spy)
    refused = fresh(tmp_path, settings=settings)
    idle = fresh(tmp_path, "idle.db", settings=settings)

    result = refused.turn({BTC: pair_market(**market)})
    idle.turn({BTC: pair_market(FLAT, **market)})

    assert reasons(result) == [note]
    assert placed == []
    assert_no_trace(refused, result)
    stored, baseline = refused.stored(), idle.stored()
    assert stored.ledger == baseline.ledger and stored.risk == baseline.risk


def test_other_pair_trades_in_the_same_turn(tmp_path: Path) -> None:
    """AC-11 (R-7): BTC fiyat 11'de döner, ETH aynı turda fiyat 10'da 49.309 alır."""
    bot = fresh(tmp_path, settings=make_settings((BTC, ETH)))

    result = bot.turn({BTC: pair_market(price=Decimal(11)), ETH: pair_market(price=Decimal(10))})

    assert [(p.pair, p.reason) for p in result.pairs] == [(BTC, LIMIT)]
    assert [(o.pair, o.amount) for o in result.buys] == [(ETH, FIRST_AMOUNT)]
    assert result.halts == () and bot.notices == []


def test_same_candle_retry_buys(tmp_path: Path) -> None:
    """AC-11 (R-8): aynı mumda fiyat 11 ile dönen çift, sonraki turda fiyat 10 ile 49.309 alır."""
    bot = fresh(tmp_path)

    refused = bot.turn({BTC: pair_market(price=Decimal(11))})
    retried = bot.turn({BTC: pair_market(price=Decimal(10), price_at=LATER)}, now=LATER)

    assert reasons(refused) == [LIMIT]
    assert [o.amount for o in retried.buys] == [FIRST_AMOUNT]


LONG = "0" * 80 + "1"  # past the gate's 60 digits, exact in `risk`'s approval


def test_unfit_risk_names_the_cap(tmp_path: Path) -> None:
    """AC-12 (R-9): slippage 60 basamağa sığmaz: dolumdaki risk hesaplanamaz, istisna yok."""
    bot = fresh(tmp_path, settings=make_settings(slippage=Decimal("0.001" + LONG)))

    result = bot.turn({BTC: pair_market(price=Decimal(10))})

    assert reasons(result) == [PairNote.RISK_CAP_AT_FILL]
    assert_no_trace(bot, result)


def test_unfit_edge_names_the_edge(tmp_path: Path) -> None:
    """AC-12 (R-9): spread 60 basamağa sığmaz: risk kapıları geçer, BR-8 hesaplanamaz."""
    bot = fresh(tmp_path)

    result = bot.turn({BTC: pair_market(price=Decimal(10), spread=Decimal("0.0005" + LONG))})

    assert reasons(result) == [EDGE]
    assert_no_trace(bot, result)
