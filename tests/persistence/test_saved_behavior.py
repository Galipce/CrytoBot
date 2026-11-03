"""Spec 0011 AC-4 (R-4): yüklenen durumda tekrar koruması, güvenli mod, durdurma sürer (BR-6)."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

from crytobot.execution import (
    OrderOutcome,
    OrderRequest,
    OrderStatus,
    PaperExchange,
    QueryOutcome,
    place_order,
    query_order,
)
from crytobot.persistence import StoredState
from crytobot.risk import (
    DEFAULT_LIMITS,
    AccountState,
    ApprovalReason,
    PairRules,
    TrackingReason,
    TradeApproval,
    TradeIntent,
    approve_trade,
    observe,
    resume,
)
from tests.persistence.chain import (
    FEE,
    PAIR,
    RULES,
    SLIPPAGE,
    T1,
    bought,
    loaded,
    opened,
    placed,
    seen,
    stored,
)

ENTRY = Decimal("100.10")
INTENT = TradeIntent(PAIR, "buy", ENTRY, ENTRY / 2, ENTRY * 2)
APPROVAL = TradeApproval(Decimal("2.50"), None, False, "onay", INTENT)
BIG_INTENT = TradeIntent(PAIR, "buy", Decimal("100"), Decimal("95"), Decimal("200"))
APPROVAL_RULES = PairRules(Decimal("0.001"), Decimal("0.001"), Decimal("5"))


def request(intent_id: str = "a") -> OrderRequest:
    return OrderRequest(intent_id, INTENT, APPROVAL, RULES, ENTRY, FEE, SLIPPAGE, "paper")


def approval(state: StoredState, equity: str, now_delta: timedelta = timedelta(0)) -> TradeApproval:
    return approve_trade(
        BIG_INTENT,
        DEFAULT_LIMITS,
        AccountState(Decimal(equity), Decimal(equity), 0),
        APPROVAL_RULES,
        frozenset({PAIR}),
        FEE,
        Decimal(0),
        Decimal(0),
        state.risk,
        T1 + now_delta,
    )


def test_same_intent_after_restart_already_exists(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, bought(opened()))

    state = loaded(path)
    result = place_order(state.execution, request(), PaperExchange(), T1)

    assert result.outcome is OrderOutcome.ALREADY_EXISTS
    assert result.state is state.execution


def test_unknown_order_keeps_safe_mode_and_can_be_resolved(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, placed(opened(), "a", status=OrderStatus.UNKNOWN))

    state = loaded(path)

    assert state.execution.unknown == ("cb-a",)
    refused = place_order(state.execution, request("b"), PaperExchange(), T1)
    assert refused.outcome is OrderOutcome.STATUS_UNKNOWN
    exchange = PaperExchange(resolutions=MappingProxyType({"cb-a": OrderStatus.FILLED}))
    query = query_order(state.execution, "cb-a", exchange, T1)
    assert query.outcome is QueryOutcome.UPDATED
    assert query.state.unknown == ()
    assert query.state.orders["cb-a"].fill_price == state.execution.quotes["cb-a"][0]


def test_halt_survives_a_restart_and_only_the_cli_lifts_it(tmp_path: Path) -> None:
    """BR-6: durdurulmuş bot yeniden başlayınca da onay almaz; Telegram kaldıramaz, CLI kaldırır."""
    path = tmp_path / "depo.sqlite"
    world = seen(seen(opened(), "10000"), "5000")
    assert world.risk.halted
    stored(path, world)

    state = loaded(path)

    assert state.risk.halted
    refused = approval(state, "5000")
    assert refused.reason is ApprovalReason.DRAWDOWN_HALT and refused.amount is None
    telegram = resume(state.risk, "telegram")
    assert telegram.reason is TrackingReason.TELEGRAM_RESUME and telegram.state.halted
    assert not resume(state.risk, "cli").state.halted


def test_day_start_and_peak_are_not_reset_on_the_same_day(tmp_path: Path) -> None:
    path = tmp_path / "depo.sqlite"
    stored(path, seen(seen(opened(), "10000"), "11000"))

    state = loaded(path)
    after = observe(state.risk, T1 + timedelta(minutes=1), Decimal("10500"), DEFAULT_LIMITS).state

    assert after.day_start_equity == Decimal("10000")
    assert after.peak_equity == Decimal("11000")


def test_new_day_has_no_approval_before_an_observation(tmp_path: Path) -> None:
    """0004 R-7: yeni günde gözlem gelene kadar onay yoktur."""
    path = tmp_path / "depo.sqlite"
    stored(path, seen(opened(), "10000"))

    state = loaded(path)
    refused = approval(state, "10000", timedelta(days=1))

    assert refused.reason is ApprovalReason.INVALID_INPUT and refused.amount is None
    assert "bayat" in refused.message
