"""Spec 0005 AC-1…AC-5, AC-7, AC-9: beklenen kâr efektif maliyetin katını geçmeli (BR-8)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    AccountState,
    ApprovalReason,
    PairRules,
    RiskLimits,
    RiskState,
    TradeApproval,
    TradeIntent,
    approve_trade,
    observe,
)

PAIR = "BTC/USDT"
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
# spec 0003 AC-1's account and pair rules: 19.249 is its approved amount
ACCOUNT = AccountState(Decimal("10000"), Decimal("5000"), 0)
RULES = PairRules(Decimal("0.001"), Decimal("0.001"), Decimal("5"))
INTENT = TradeIntent(PAIR, "buy", Decimal("100"), Decimal("95"), Decimal("110"))
FEE, SPREAD, SLIPPAGE = Decimal("0.001"), Decimal("0.0005"), Decimal("0.001")


def fresh(account: AccountState) -> RiskState:
    return observe(EMPTY_STATE, NOW, account.equity, DEFAULT_LIMITS).state


def approve(
    intent: TradeIntent = INTENT,
    limits: RiskLimits = DEFAULT_LIMITS,
    account: AccountState = ACCOUNT,
    rules: PairRules = RULES,
    fee: Any = FEE,
    spread: Any = SPREAD,
    slippage: Any = SLIPPAGE,
    state: RiskState | None = None,
) -> TradeApproval:
    state = fresh(account) if state is None else state
    return approve_trade(
        intent, limits, account, rules, frozenset({PAIR}), fee, spread, slippage, state, NOW
    )


def test_trade_clearing_the_threshold_is_sized_as_spec_0003() -> None:
    """AC-1 (R-3, R-9): maliyet 0.47, eşik 0.94, kâr 10 → onay; slippage 0'da miktar spec 0003
    AC-1 ile aynı.

    Spec 0020 R-1, spec 0034 B-51: slippage'lı giriş 100.1, stop 94.905, birim kayıp
    (100.1 - 94.905) + 100.1 * 0.001 + 94.905 * 0.001 = 5.390005; 100 // (0.001 * 5.390005) = 18552.
    """
    result = approve()

    assert result.approved and result.amount == Decimal("18.552")
    assert approve(slippage=Decimal(0)).amount == Decimal("19.249")


@pytest.mark.parametrize(
    ("target", "reason"),
    [("101", ApprovalReason.INSUFFICIENT_EDGE), ("101.01", None)],
    ids=["equal", "one_cent_above"],
)
def test_threshold_boundary(target: str, reason: ApprovalReason | None) -> None:
    """AC-2 (R-3): maliyet 0.5, kat 2 → eşik 1; kâr eşiğe eşitse ret, bir kuruş fazlasıysa onay."""
    result = approve(
        replace(INTENT, target=Decimal(target)), fee=Decimal(0), slippage=Decimal(0),
        spread=Decimal("0.005"),
    )  # fmt: skip

    assert result.reason is reason
    assert (result.amount is None) is (reason is not None)


def test_edge_rejection_names_profit_cost_multiple() -> None:
    """AC-2 (R-3): ret mesajı çifti, beklenen kârı, efektif maliyeti ve katı adlandırır."""
    result = approve(
        replace(INTENT, target=Decimal("101")), fee=Decimal(0), slippage=Decimal(0),
        spread=Decimal("0.005"),
    )  # fmt: skip

    assert PAIR in result.message and "yetersiz kâr beklentisi" in result.message
    assert "beklenen kâr 1," in result.message and "efektif maliyet 0.5" in result.message
    assert "kat 2" in result.message


INVALID_TARGETS: dict[str, Any] = {
    "none": None,
    "nan": Decimal("NaN"),
    "infinity": Decimal("Infinity"),
    "float": 110.0,
    "bool": True,
    "equal_entry": Decimal("100"),
    "below_entry": Decimal("99"),
}


@pytest.mark.parametrize("case", list(INVALID_TARGETS))
def test_invalid_target_is_rejected(case: str) -> None:
    """AC-3 (R-1): hedef yok, sayı değil ya da girişten büyük değilse "geçersiz hedef"."""
    result = approve(replace(INTENT, target=INVALID_TARGETS[case]))

    assert result.reason is ApprovalReason.INVALID_TARGET and result.amount is None
    assert "hedef" in result.message


INVALID_COSTS: dict[str, Any] = {
    "missing": None,
    "negative": Decimal("-0.001"),
    "one": Decimal("1"),
    "above_one": Decimal("1.5"),
    "nan": Decimal("NaN"),
    "float": 0.001,
}


@pytest.mark.parametrize("name", ["spread", "slippage"])
@pytest.mark.parametrize("case", list(INVALID_COSTS))
def test_invalid_spread_or_slippage_is_invalid_input(name: str, case: str) -> None:
    """AC-4 (R-2): verilmemiş ya da [0, 1) dışındaki spread/slippage "geçersiz girdi"; adı geçer."""
    value = INVALID_COSTS[case]

    result = approve(**{name: value})

    assert result.reason is ApprovalReason.INVALID_INPUT and result.amount is None
    assert f"{name} {value!r}" in result.message


def test_zero_spread_and_slippage_are_valid() -> None:
    """AC-4 (R-2): sıfır spread ve slippage geçerlidir."""
    assert approve(spread=Decimal(0), slippage=Decimal(0)).approved


LOW_EDGE = replace(INTENT, target=Decimal("100.5"))  # profit 0.5, threshold 2 * 0.451 = 0.902
FULL = replace(ACCOUNT, open_positions=5)


def daily_locked() -> RiskState:
    state = observe(EMPTY_STATE, NOW - timedelta(minutes=1), Decimal("10000"), DEFAULT_LIMITS).state
    return observe(state, NOW, Decimal("9700"), DEFAULT_LIMITS).state


ORDER: dict[str, tuple[dict[str, Any], ApprovalReason]] = {
    "stop_before_target": (
        {"intent": replace(INTENT, stop=None, target=None)},
        ApprovalReason.INVALID_STOP,
    ),
    "target_before_position_limit": (
        {"intent": replace(INTENT, target=None), "account": FULL},
        ApprovalReason.INVALID_TARGET,
    ),
    "edge_before_position_limit": (
        {"intent": LOW_EDGE, "account": FULL},
        ApprovalReason.INSUFFICIENT_EDGE,
    ),
    "daily_before_edge": (
        {
            "intent": LOW_EDGE,
            "account": replace(ACCOUNT, equity=Decimal("9700")),
            "state": daily_locked(),
        },
        ApprovalReason.DAILY_LOSS_LIMIT,
    ),
}


@pytest.mark.parametrize("case", list(ORDER))
def test_rejection_order(case: str) -> None:
    """AC-5 (R-6): … geçersiz stop → geçersiz hedef → yetersiz kâr beklentisi → pozisyon limiti."""
    overrides, reason = ORDER[case]

    result = approve(**overrides)

    assert result.reason is reason


def test_changed_multiple_applies_at_once() -> None:
    """AC-7 (R-3): AC-1 önerisi kat 2 ile onaylanır, kat 25 ile (eşik 11.75) reddedilir."""
    raised = replace(DEFAULT_LIMITS, profit_cost_multiple=Decimal("25"))

    assert approve().approved
    assert approve(limits=raised).reason is ApprovalReason.INSUFFICIENT_EDGE


@pytest.mark.parametrize(
    ("free", "amount", "limited"),
    [("1857.0552", "18.552", False), ("1857.0551", "18.551", True)],
    ids=["same_steps", "one_step_fewer"],
)
def test_spread_and_slippage_leave_the_balance_limit_as_spec_0003(
    free: str, amount: str, limited: bool
) -> None:
    """AC-1 (R-9): spread ve slippage sıfırdan büyükken bakiye sınırı spec 0003 AC-3 ile aynı.

    Spec 0020 R-1, spec 0034 B-51: riskle sınırlı miktar 18.552; bakiye koşulu slippage'sız,
    18.552 * 100 * 1.001 = 1857.0552 tam bu adım sayısını, 0.0001 eksiği bir adım azını verir.
    """
    result = approve(account=replace(ACCOUNT, free_balance=Decimal(free)))

    assert result.approved and result.amount == Decimal(amount)
    assert result.limited_by_balance is limited


UNREPRESENTABLE: dict[str, dict[str, Any]] = {
    "tiny_step": {
        "intent": TradeIntent(PAIR, "buy", Decimal("1"), Decimal("0.5"), Decimal("2")),
        "rules": PairRules(Decimal("1E-999999"), Decimal("0"), Decimal("0")),
    },
    # costs 0: with a fee, the threshold rejects first (entry * fee would exceed the profit)
    "huge_entry": {
        "intent": TradeIntent(
            PAIR, "buy", Decimal("9.999E+999999"), Decimal("1"), Decimal("9.9999E+999999")
        ),
        "rules": PairRules(Decimal("10"), Decimal("0"), Decimal("0")),
        "fee": Decimal(0),
        "spread": Decimal(0),
        "slippage": Decimal(0),
    },
}
NAMED = {
    "tiny_step": ["giriş 1", "stop 0.5", "hedef 2", "ücret 0.001", "spread 0.0005",
                  "slippage 0.001", "serbest bakiye 100000", "adım 1E-999999", "kasa 100000"],
    "huge_entry": ["giriş 9.999E+999999", "stop 1", "hedef 9.9999E+999999", "ücret 0", "spread 0",
                   "slippage 0", "serbest bakiye 100000", "adım 10", "kasa 100000"],
}  # fmt: skip


@pytest.mark.parametrize("case", list(UNREPRESENTABLE))
def test_unrepresentable_result_names_every_value(case: str) -> None:
    """AC-9 (R-8, B-5): aralık içi ama hesabı temsil edilemeyen girdi, tüm değerleriyle "ölçek"."""
    account = AccountState(Decimal("100000"), Decimal("100000"), 0)

    result = approve(account=account, **UNREPRESENTABLE[case])

    assert result.reason is ApprovalReason.INVALID_INPUT and result.amount is None
    assert "ölçek hesaplanamıyor" in result.message
    assert [value for value in NAMED[case] if value not in result.message] == []
