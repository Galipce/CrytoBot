"""Spec 0003 AC-5…AC-9: işlem önerisinin reddi ve ret nedeninin sırası (BR-2, BR-3, BR-7)."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    HARD_CAPS,
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
WHITELIST = frozenset({PAIR, "ETH/USDT"})
INTENT = TradeIntent(PAIR, "buy", Decimal("100"), Decimal("95"), Decimal("200"))
ACCOUNT = AccountState(Decimal("10000"), Decimal("5000"), 0)
RULES = PairRules(Decimal("0.001"), Decimal("0.001"), Decimal("5"))
FEE = Decimal("0.001")


# spec 0004 R-7: approval takes a risk state; a fresh one (no lock, same equity) keeps 0003 as is
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)


def fresh_state(account: AccountState, limits: RiskLimits) -> RiskState:
    return observe(EMPTY_STATE, NOW, account.equity, limits).state


def approve(
    intent: TradeIntent = INTENT,
    limits: RiskLimits = DEFAULT_LIMITS,
    account: AccountState = ACCOUNT,
    rules: PairRules = RULES,
    whitelist: frozenset[str] = WHITELIST,
    fee: Any = FEE,
) -> TradeApproval:
    state = fresh_state(account, limits)
    return approve_trade(
        intent, limits, account, rules, whitelist, fee, Decimal(0), Decimal(0), state, NOW
    )


def with_limit(name: str, value: Any) -> RiskLimits:
    return replace(DEFAULT_LIMITS, **{name: value})


def assert_rejected(result: TradeApproval, reason: ApprovalReason, value: object) -> None:
    """AC-9: ret = miktar yok, neden adlandırılır, mesaj çifti ve ilgili değeri taşır."""
    assert result.reason is reason
    assert result.amount is None and not result.approved
    assert PAIR in result.message and str(value) in result.message


INVALID_STOPS = {
    "missing": None,
    "zero": Decimal("0"),
    "negative": Decimal("-1"),
    "equal_entry": Decimal("100"),
    "above_entry": Decimal("100.01"),
    "nan": Decimal("NaN"),
    "inf": Decimal("Infinity"),
    "float": 95.0,
    "string": "95",
}


@pytest.mark.parametrize("case", list(INVALID_STOPS))
def test_invalid_stop_is_rejected(case: str) -> None:
    """AC-5 (BR-3): stop yok, sıfır, negatif, girişte/üstünde veya sayı değilse öneri reddedilir."""
    stop = INVALID_STOPS[case]

    result = approve(replace(INTENT, stop=stop))

    assert_rejected(result, ApprovalReason.INVALID_STOP, "stop" if stop is None else stop)


INVALID_ENTRIES = {
    "zero": Decimal("0"),
    "negative": Decimal("-100"),
    "nan": Decimal("NaN"),
    "inf": Decimal("Infinity"),
    "bool": True,
}


@pytest.mark.parametrize("case", list(INVALID_ENTRIES))
def test_invalid_entry_is_rejected(case: str) -> None:
    """AC-5: giriş sonlu ve sıfırdan büyük olmalı."""
    entry = INVALID_ENTRIES[case]

    result = approve(replace(INTENT, entry=entry))

    assert_rejected(result, ApprovalReason.INVALID_ENTRY, entry)


@pytest.mark.parametrize("side", ["sell", "BUY", " buy"])
def test_non_buy_side_is_rejected(side: str) -> None:
    """AC-6 (BR-2): yalnızca spot alım; yön birebir `buy` değilse reddedilir."""
    result = approve(replace(INTENT, side=side))

    assert_rejected(result, ApprovalReason.NOT_BUY, side)


@pytest.mark.parametrize(
    "pair", ["SOL/USDT", "btc/usdt", " BTC/USDT"], ids=["unknown", "case", "space"]
)
def test_pair_outside_whitelist_is_rejected(pair: str) -> None:
    """AC-6 (BR-2): çift beyaz listede birebir yoksa reddedilir."""
    result = approve(replace(INTENT, pair=pair))

    assert result.reason is ApprovalReason.NOT_WHITELISTED
    assert result.amount is None and pair in result.message


@pytest.mark.parametrize("offset", [0, 1], ids=["at", "above"])
def test_position_limit_reached_is_rejected(offset: int) -> None:
    """AC-7 (BR-7): açık pozisyon limitte veya üstündeyse yeni pozisyon açılmaz."""
    positions = DEFAULT_LIMITS.max_open_positions + offset

    result = approve(account=replace(ACCOUNT, open_positions=positions))

    assert_rejected(result, ApprovalReason.POSITION_LIMIT, positions)


# each case names the field and its value together: a bare "0" or "-1" would also match another
# field's message, so a rejection for the wrong reason could pass (VERIFY G-1)
INVALID_INPUTS: dict[str, tuple[dict[str, Any], str]] = {
    # free balance 0 too, or "free balance above equity" would reject it instead of the equity check
    "equity_zero": (
        {"account": replace(ACCOUNT, equity=Decimal("0"), free_balance=Decimal("0"))},
        "kasa Decimal('0')",
    ),
    "equity_negative": ({"account": replace(ACCOUNT, equity=Decimal("-1"))}, "kasa Decimal('-1')"),
    "equity_nan": ({"account": replace(ACCOUNT, equity=Decimal("NaN"))}, "kasa Decimal('NaN')"),
    "free_negative": (
        {"account": replace(ACCOUNT, free_balance=Decimal("-1"))},
        "serbest bakiye Decimal('-1')",
    ),
    "free_above_equity": (
        {"account": replace(ACCOUNT, free_balance=Decimal("10001"))},
        "serbest bakiye 10001 kasadan",
    ),
    "free_inf": (
        {"account": replace(ACCOUNT, free_balance=Decimal("Infinity"))},
        "serbest bakiye Decimal('Infinity')",
    ),
    "positions_negative": ({"account": replace(ACCOUNT, open_positions=-1)}, "açık pozisyon -1"),
    "positions_fraction": (
        {"account": replace(ACCOUNT, open_positions=Decimal("1.5"))},
        "açık pozisyon Decimal('1.5')",
    ),
    "positions_bool": ({"account": replace(ACCOUNT, open_positions=True)}, "açık pozisyon True"),
    "fee_negative": ({"fee": Decimal("-0.001")}, "ücret Decimal('-0.001')"),
    "fee_one": ({"fee": Decimal("1")}, "ücret Decimal('1')"),
    "fee_float": ({"fee": 0.001}, "ücret 0.001"),
    "step_zero": (
        {"rules": replace(RULES, amount_step=Decimal("0"))},
        "miktar adımı Decimal('0')",
    ),
    "min_amount_negative": (
        {"rules": replace(RULES, min_amount=Decimal("-1"))},
        "asgari miktar Decimal('-1')",
    ),
    "min_notional_nan": (
        {"rules": replace(RULES, min_notional=Decimal("NaN"))},
        "asgari tutar Decimal('NaN')",
    ),
}


@pytest.mark.parametrize("case", list(INVALID_INPUTS))
def test_invalid_input_is_rejected_naming_it(case: str) -> None:
    """AC-8: kendi içinde geçersiz onay girdisi reddedilir; mesaj alanı ve değerini adlandırır."""
    overrides, named = INVALID_INPUTS[case]

    result = approve(**overrides)

    assert_rejected(result, ApprovalReason.INVALID_INPUT, named)


ABOVE_CAP = {
    "per_trade_risk": Decimal("0.0200001"),
    "daily_loss_limit": Decimal("0.0500001"),
    "max_drawdown": Decimal("0.2500001"),
    "max_open_positions": 9,
}


@pytest.mark.parametrize("name", sorted(ABOVE_CAP))
def test_limits_above_cap_are_rejected(name: str) -> None:
    """AC-8 (B-3): limitler nereden gelirse gelsin, üst sınırı aşan biri varsa öneri reddedilir."""
    limits = with_limit(name, ABOVE_CAP[name])

    result = approve(limits=limits)

    assert_rejected(result, ApprovalReason.INVALID_INPUT, ABOVE_CAP[name])
    assert name in result.message and str(getattr(HARD_CAPS, name)) in result.message


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("max_drawdown", Decimal("0")),
        ("daily_loss_limit", Decimal("NaN")),
        ("per_trade_risk", 0.01),
    ],
    ids=["zero", "nan", "float"],
)
def test_invalid_limit_is_rejected(name: str, value: object) -> None:
    """AC-8: onayda kullanılmayan limit de dahil geçersiz bir limit öneriyi reddettirir."""
    result = approve(limits=with_limit(name, value))

    assert_rejected(result, ApprovalReason.INVALID_INPUT, value)
    assert name in result.message


FIRST_REASON: dict[str, tuple[dict[str, Any], ApprovalReason]] = {
    # every case also breaks every later rule in the R-8 order
    "input_before_side": (
        {
            "account": replace(ACCOUNT, equity=Decimal("0"), open_positions=9),
            "intent": TradeIntent("SOL/USDT", "sell", Decimal("0"), None, Decimal("200")),
        },
        ApprovalReason.INVALID_INPUT,
    ),
    "side_before_whitelist": (
        {
            "account": replace(ACCOUNT, open_positions=9),
            "intent": TradeIntent("SOL/USDT", "sell", Decimal("0"), None, Decimal("200")),
        },
        ApprovalReason.NOT_BUY,
    ),
    "whitelist_before_entry": (
        {
            "account": replace(ACCOUNT, open_positions=9),
            "intent": TradeIntent("SOL/USDT", "buy", Decimal("0"), None, Decimal("200")),
        },
        ApprovalReason.NOT_WHITELISTED,
    ),
    "entry_before_stop": (
        {
            "account": replace(ACCOUNT, open_positions=9),
            "intent": TradeIntent(PAIR, "buy", Decimal("0"), None, Decimal("200")),
        },
        ApprovalReason.INVALID_ENTRY,
    ),
    "stop_before_positions": (
        {"account": replace(ACCOUNT, open_positions=9), "intent": replace(INTENT, stop=None)},
        ApprovalReason.INVALID_STOP,
    ),
    "positions_before_minimum": (
        {
            "account": replace(ACCOUNT, free_balance=Decimal("0"), open_positions=9),
        },
        ApprovalReason.POSITION_LIMIT,
    ),
}


@pytest.mark.parametrize("case", list(FIRST_REASON))
def test_first_reason_in_order_wins(case: str) -> None:
    """AC-9 (R-8): birden fazla sorunda sıradaki ilk neden döner."""
    overrides, reason = FIRST_REASON[case]

    result = approve(**overrides)

    assert result.reason is reason
    assert result.amount is None


def test_far_stop_is_accepted() -> None:
    """AC-5 (BR-3): stop'un girişe uzaklığına üst sınır yok; uzak stop yalnız miktarı küçültür."""
    result = approve(replace(INTENT, stop=Decimal("0.01")))

    near_stop = approve().amount

    assert result.approved and result.amount is not None and near_stop is not None
    assert result.amount < near_stop


def test_position_below_limit_is_approved() -> None:
    """AC-7 (BR-7): açık pozisyon limitin bir altındayken yeni pozisyon açılabilir."""
    positions = DEFAULT_LIMITS.max_open_positions - 1

    result = approve(account=replace(ACCOUNT, open_positions=positions))

    assert result.approved


def test_open_position_in_same_pair_is_not_a_reason() -> None:
    """AC-7: aynı çiftte açık pozisyon ayrıca ret nedeni değil; yalnız toplam sayıya girer."""
    # the BTC/USDT position already open is the one counted here; nothing else refers to the pair
    result = approve(account=replace(ACCOUNT, open_positions=1))

    assert result.approved and result.amount == Decimal("19.249")


@pytest.mark.parametrize("whitelist", ["BTC/USDT", ["BTC/USDT"]], ids=["str", "list"])
def test_whitelist_must_be_a_set_of_pairs(whitelist: Any) -> None:
    """AC-8 (BR-2): beyaz liste küme değilse (ör. dize: alt dize eşleşmesi) girdi geçersizdir."""
    result = approve(replace(INTENT, pair="BTC"), whitelist=whitelist)

    assert result.reason is ApprovalReason.INVALID_INPUT and result.amount is None
    assert "beyaz liste" in result.message


class _UnhashableText(str):
    __hash__ = None  # type: ignore[assignment]


@pytest.mark.parametrize(
    "pair",
    [["BTC/USDT"], {"pair": "BTC/USDT"}, {"BTC/USDT"}, _UnhashableText("BTC/USDT")],
    ids=["list", "dict", "set", "unhashable_text"],
)
def test_unhashable_pair_is_not_whitelisted(pair: Any) -> None:
    """Spec 0016 R-15 (B-6): istisna yok, BR-2 reddi."""
    result = approve(TradeIntent(pair, "buy", Decimal("100"), Decimal("95"), Decimal("200")))

    assert result.reason is ApprovalReason.NOT_WHITELISTED
    assert result.amount is None


@pytest.mark.parametrize("pair", [1, None, b"BTC/USDT"], ids=["int", "none", "bytes"])
def test_non_text_pair_is_not_whitelisted(pair: Any) -> None:
    """Spec 0016 R-15: listede aynı değer olsa bile metin olmayan çift listede sayılmaz."""
    whitelist: Any = frozenset({PAIR, pair})
    intent = TradeIntent(pair, "buy", Decimal("100"), Decimal("95"), Decimal("200"))

    assert approve(intent, whitelist=whitelist).reason is ApprovalReason.NOT_WHITELISTED
