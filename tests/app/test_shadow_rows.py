"""Spec 0052 R-2, AC-1, AC-8 (plan step 4, Risk 1, 5, 7): `TurnResult`'tan satır kurma — teknik al
(var / yok ve nedeni / değerlendirilmedi ve nedeni) ve risk sonucu. Durdurma senaryoları gerçek
turlarla kurulur; tur kodu değişmez."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from crytobot.app import (
    BuyHalt,
    PairFilter,
    PairNote,
    PairOutcome,
    TurnOutcome,
    TurnResult,
    engage_kill_switch,
    shadow_rows,
)
from crytobot.execution import OrderOutcome, OrderStatus
from crytobot.risk import ApprovalReason
from crytobot.strategy import NoProposalReason
from tests.app.helpers import (
    BTC,
    ETH,
    FLAT,
    LATER,
    MAX_PRICE_AGE,
    MINUTE,
    NOW,
    Bot,
    Exchange,
    limits,
    make_settings,
    opened_store,
    pair_market,
)
from tests.app.test_control_commands import make_bot_config

PAIRS = (BTC, ETH)
SUPPRESS = PairFilter("bastırılırdı", "olumsuz olay", ((7, 3),), (1, 0, 2), "kota beklemesi")
PASS = PairFilter("bastırılmazdı", "olumsuz olay yok", (), (0, 0, 0), None)
VIEW = {BTC: SUPPRESS, ETH: PASS}
FIELDS = {
    "version",
    "turn_at",
    "pair",
    "whitelist",
    "state",
    "reason",
    "events",
    "missing",
    "held",
    "technical_buy",
    "technical_reason",
    "risk",
    "order",
}


def technical(result: TurnResult, at: object = NOW) -> dict[str, tuple[object, object, object]]:
    assert isinstance(at, type(NOW))
    rows = shadow_rows(result, at, PAIRS, VIEW)
    return {
        str(row["pair"]): (row["technical_buy"], row["technical_reason"], row["risk"])
        for row in rows
    }


def test_row_carries_every_field(tmp_path: Path) -> None:
    bot = Bot(opened_store(tmp_path / "s.db"), settings=make_settings(PAIRS))
    result = bot.turn({BTC: pair_market(), ETH: pair_market(FLAT)})
    rows = shadow_rows(result, NOW, PAIRS, VIEW)
    assert [row["pair"] for row in rows] == [BTC, ETH]
    assert all(set(row) == FIELDS for row in rows)
    assert rows[0] == {
        "version": "1",
        "turn_at": NOW.isoformat(),
        "pair": BTC,
        "whitelist": [BTC, ETH],
        "state": "bastırılırdı",
        "reason": "olumsuz olay",
        "events": [{"news_id": 7, "severity": 3}],
        "missing": {"pending": 1, "schema": 0, "stale": 2},
        "held": "kota beklemesi",
        "technical_buy": "var",
        "technical_reason": None,
        "risk": "onay",
        "order": None,
    }
    assert rows[1]["technical_buy"] == "yok"
    assert rows[1]["technical_reason"] == NoProposalReason.NO_CROSSOVER.value
    assert rows[1]["risk"] is None


def test_no_filter_row_has_no_missing() -> None:
    result = TurnResult(TurnOutcome.COMPLETED, (), (), (), (), (), "tur tamamlandı")
    view = {pair: PairFilter("filtre yok", "skorlayıcı durmuş") for pair in PAIRS}
    rows = shadow_rows(result, NOW, PAIRS, view)
    assert [(row["state"], row["reason"], row["missing"], row["events"]) for row in rows] == [
        ("filtre yok", "skorlayıcı durmuş", None, []),
    ] * 2


def test_not_evaluated_with_halt_safe_mode(tmp_path: Path) -> None:
    bot = Bot(opened_store(tmp_path / "s.db"), settings=make_settings(PAIRS))
    unknown = Exchange(place={"cb-": OrderStatus.UNKNOWN})
    bot.turn({BTC: pair_market(), ETH: pair_market()}, exchange=unknown)
    later = NOW + MINUTE
    market = {pair: pair_market(price_at=later) for pair in PAIRS}
    result = bot.turn(market, now=later, exchange=unknown)  # safe mode: the buy path stops
    assert BuyHalt.UNKNOWN_ORDERS in result.halts and result.buys == ()
    assert technical(result, later) == {
        BTC: ("değerlendirilmedi", "unknown_orders", None),
        ETH: ("değerlendirilmedi", "unknown_orders", None),
    }


def test_not_evaluated_with_halt_stale_data(tmp_path: Path) -> None:
    now = NOW + MINUTE
    bot = Bot(opened_store(tmp_path / "s.db"), settings=make_settings(PAIRS))
    stale = pair_market(price_at=now - MAX_PRICE_AGE - timedelta(microseconds=1))
    result = bot.turn({BTC: pair_market(price_at=now), ETH: stale}, now=now)
    assert result.halts == (BuyHalt.STALE_DATA,)
    assert technical(result, now) == {
        BTC: ("değerlendirilmedi", "stale_data", None),
        ETH: ("değerlendirilmedi", "stale_data", None),
    }


def test_kill_switch_risk_refusal(tmp_path: Path) -> None:
    """Plan Risk 1 (a): kill switch alım yolunu durdurmaz; öneri risk reddiyle yazılır."""
    store = opened_store(tmp_path / "bot.db")
    config = make_bot_config(store, tmp_path / "bot.log")
    bot = Bot(store, settings=config.turn)
    bot.turn({BTC: pair_market(), ETH: pair_market(FLAT)}, now=NOW)
    assert engage_kill_switch(config, clock=lambda: NOW).success
    later = NOW + timedelta(hours=1)
    result = bot.turn(
        {
            BTC: pair_market(price=Decimal("7.9"), closed_at=later),
            ETH: pair_market(closed_at=later),
        },
        now=later,
    )
    assert BuyHalt.KILL_SWITCH in result.halts
    assert technical(result, later)[ETH] == ("var", None, "ret: kill_switch_active")


def test_daily_loss_risk_refusal(tmp_path: Path) -> None:
    settings = make_settings(PAIRS, limits=limits(daily_loss_limit=Decimal("0.01")))
    bot = Bot(opened_store(tmp_path / "s.db"), settings=settings)
    bot.turn({BTC: pair_market(), ETH: pair_market(FLAT)})
    result = bot.turn(
        {BTC: pair_market(price=Decimal(7), price_at=LATER), ETH: pair_market(price_at=LATER)},
        now=LATER,
    )
    assert technical(result, LATER)[ETH] == ("var", None, "ret: daily_loss_limit")


@pytest.mark.parametrize(
    ("reason", "expected", "order"),
    [
        (NoProposalReason.POSITION_OPEN, ("yok", "position_open", None), None),
        (ApprovalReason.DRAWDOWN_HALT, ("var", None, "ret: drawdown_halt"), None),
        (PairNote.ALREADY_ORDERED, ("var", None, "değerlendirilmedi: already_ordered"), None),
        (PairNote.FILL_EXCEEDS_BALANCE, ("var", None, "onay"), "fill_exceeds_balance"),
        (OrderOutcome.CREATED, ("var", None, "onay"), "created"),
    ],
)
def test_pair_outcome_mapping(reason: object, expected: tuple[object, ...], order: object) -> None:
    outcome = PairOutcome(BTC, reason, "m")  # type: ignore[arg-type]
    result = TurnResult(TurnOutcome.COMPLETED, (), (), (outcome,), (), (), "tur tamamlandı")
    rows = shadow_rows(result, NOW, PAIRS, VIEW)
    assert (rows[0]["technical_buy"], rows[0]["technical_reason"], rows[0]["risk"]) == expected
    assert rows[0]["order"] == order


def test_halts_named_in_value_order_informational_left_out() -> None:
    halts = (BuyHalt.SAVE_REFUSED, BuyHalt.KILL_SWITCH, BuyHalt.DRAWDOWN, BuyHalt.INVALID_DATA)
    result = TurnResult(TurnOutcome.COMPLETED, (), (), (), halts, (), "tur tamamlandı")
    assert technical(result)[BTC] == ("değerlendirilmedi", "invalid_data,save_refused", None)
    only_info = TurnResult(
        TurnOutcome.COMPLETED, (), (), (), (BuyHalt.KILL_SWITCH,), (), "tur tamamlandı"
    )
    assert technical(only_info)[BTC] == ("değerlendirilmedi", "alım yolu çalışmadı", None)
