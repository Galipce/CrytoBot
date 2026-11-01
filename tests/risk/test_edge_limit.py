"""Spec 0005 AC-6, AC-7: kâr/maliyet katının yüklenmesi ve değiştirilmesi (BR-8, BR-13)."""

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest

from crytobot.risk import (
    DEFAULT_LIMITS,
    HARD_FLOOR_MULTIPLE,
    LimitChange,
    RejectReason,
    RiskConfigError,
    decide_change,
    load_limits,
)

NAME = "profit_cost_multiple"


def problems_of(toml_text: str) -> tuple[str, ...]:
    with pytest.raises(RiskConfigError) as raised:
        load_limits(toml_text)
    return raised.value.problems


def test_multiple_defaults_to_two() -> None:
    """AC-6 (BR-8): config'te yazılmamış kat `2`'dir ve varsayılandan geldiği belirtilir."""
    loaded = load_limits("[risk]\nper_trade_risk = 0.01\n")

    assert loaded.limits.profit_cost_multiple == DEFAULT_LIMITS.profit_cost_multiple == Decimal("2")
    assert NAME in loaded.defaulted


@pytest.mark.parametrize("value", ["1", "1.0", "3.5", "1E+999999"])
def test_multiple_at_floor_or_above_is_accepted(value: str) -> None:
    """AC-6 (R-4): alt sınıra (`1`) eşit ya da üstündeki kat geçerlidir; üst sınır yoktur."""
    loaded = load_limits(f"[risk]\n{NAME} = {value}\n")

    assert loaded.limits.profit_cost_multiple == Decimal(value)
    assert NAME not in loaded.defaulted


def test_multiple_at_floor_is_accepted() -> None:
    """AC-6 (R-4): alt sınır `1`'dir."""
    floor = HARD_FLOOR_MULTIPLE

    assert floor == Decimal("1")
    assert load_limits(f"[risk]\n{NAME} = 1\n").limits.profit_cost_multiple == HARD_FLOOR_MULTIPLE


INVALID = {
    "below_floor": ("0.99", "alt sınır"),
    "zero": ("0", "alt sınır"),
    "negative": ("-2", "alt sınır"),
    "nan": ("nan", "sonlu"),
    "inf": ("inf", "sonlu"),
    "bool": ("true", "sayı değil"),
    "string": ('"2"', "sayı değil"),
    "huge_exponent": ("1E+1000000", "ölçeği"),
}


@pytest.mark.parametrize("case", list(INVALID))
def test_invalid_multiple_is_rejected(case: str) -> None:
    """AC-6 (R-4): geçersiz kat yüklemeyi reddeder; mesaj limiti, değeri, alt sınırı adlandırır."""
    value, named = INVALID[case]

    [problem] = problems_of(f"[risk]\n{NAME} = {value}\n")

    assert NAME in problem and named in problem
    if named == "alt sınır":
        assert value in problem and "(1)" in problem


CHANGES: dict[str, tuple[str, Any, RejectReason | None]] = {
    "telegram-raise": ("telegram", Decimal("3"), None),
    "telegram-same": ("telegram", Decimal("2"), None),
    "telegram-lower": ("telegram", Decimal("1.5"), RejectReason.TELEGRAM_DECREASE),
    "cli-raise": ("cli", Decimal("3"), None),
    "cli-lower-to-floor": ("cli", Decimal("1"), None),
    "cli-below-floor": ("cli", Decimal("0.5"), RejectReason.BELOW_FLOOR),
    "telegram-below-floor": ("telegram", Decimal("0.5"), RejectReason.BELOW_FLOOR),
    "cli-nan": ("cli", Decimal("NaN"), RejectReason.INVALID_VALUE),
    "cli-huge-exponent": ("cli", Decimal("1E+1000000"), RejectReason.INVALID_VALUE),
    "unknown-channel": ("sms", Decimal("3"), RejectReason.UNKNOWN_CHANNEL),
}


@pytest.mark.parametrize("case", list(CHANGES))
def test_multiple_change(case: str) -> None:
    """AC-7 (R-5): Telegram'dan yalnız yükseltme; düşürme yalnız CLI'den, en az alt sınır."""
    channel, value, reason = CHANGES[case]

    decision = decide_change(DEFAULT_LIMITS, LimitChange(NAME, value, channel))

    assert decision.reason is reason
    if reason is None:
        assert decision.limits == replace(DEFAULT_LIMITS, profit_cost_multiple=value)
    else:
        assert decision.limits == DEFAULT_LIMITS
        assert NAME in decision.message or channel in decision.message


def test_telegram_decrease_names_the_reason() -> None:
    """AC-7 (R-5): Telegram'dan düşürme reddi nedeni ve yalnızca CLI'yi adlandırır."""
    decision = decide_change(DEFAULT_LIMITS, LimitChange(NAME, Decimal("1.5"), "telegram"))

    assert "Telegram'dan düşürme" in decision.message and "yalnızca CLI" in decision.message


@pytest.mark.parametrize("channel", ["cli", "telegram"])
def test_other_limits_keep_their_direction(channel: str) -> None:
    """AC-7: diğer dört limitte Telegram'dan düşürme kabul, artırma ret (spec 0002 R-6 aynen)."""
    lowered = decide_change(
        DEFAULT_LIMITS, LimitChange("per_trade_risk", Decimal("0.005"), channel)
    )
    raised = decide_change(DEFAULT_LIMITS, LimitChange("per_trade_risk", Decimal("0.015"), channel))

    assert lowered.accepted
    assert raised.accepted is (channel == "cli")


BIG: Any = 10**4300  # past Python 3.12's 4300-digit int -> str limit (review round 1 F-1)


def test_integer_past_the_str_limit_is_a_config_error() -> None:
    """AC-6 (R-4): tomllib'in okuyamadığı uzun tam sayı çıplak `ValueError` değil, config hatası."""
    problems = problems_of(f"[risk]\n{NAME} = 1{'0' * 4300}\n")

    assert len(problems) == 1 and "TOML olarak okunamadı" in problems[0]


LIMITS = ["per_trade_risk", "daily_loss_limit", "max_drawdown", "max_open_positions", NAME]


@pytest.mark.parametrize("sign", [1, -1], ids=["big", "negative_big"])
@pytest.mark.parametrize("channel", ["cli", "telegram"])
@pytest.mark.parametrize("limit", LIMITS)
def test_huge_int_change_is_decided(limit: str, channel: str, sign: int) -> None:
    """AC-6, AC-7 (R-4, R-5): dev `int` istek istisna değil karardır; yalnız kat yükseltilir."""
    decision = decide_change(DEFAULT_LIMITS, LimitChange(limit, sign * BIG, channel))

    assert decision.accepted is (limit == NAME and sign > 0)


@pytest.mark.parametrize(
    ("field", "reason"),
    [("limit", RejectReason.UNKNOWN_LIMIT), ("channel", RejectReason.UNKNOWN_CHANNEL)],
)
def test_huge_int_name_is_rejected(field: str, reason: RejectReason) -> None:
    """R-5: limit ya da kanal adı yerine dev `int` bilinmeyen ad olarak reddedilir."""
    change = replace(LimitChange(NAME, Decimal("3"), "cli"), **{field: BIG})

    assert decide_change(DEFAULT_LIMITS, change).reason is reason


@pytest.mark.parametrize("value", [Fraction(10**4300), [10**4300]], ids=["fraction", "list"])
@pytest.mark.parametrize("limit", LIMITS)
def test_repr_hiding_a_huge_int_is_an_invalid_value(limit: str, value: Any) -> None:
    """R-4 (F-1): `repr`'i dev `int` yazan değer `ValueError` değil, "geçersiz değer"."""
    decision = decide_change(DEFAULT_LIMITS, LimitChange(limit, value, "cli"))

    assert decision.reason is RejectReason.INVALID_VALUE and "gösterilemiyor" in decision.message


def test_telegram_cannot_lower_a_huge_int_multiple() -> None:
    """R-5 (F-2): elle kurulmuş dev `int` kattan Telegram'la düşürme `ValueError` değil, ret."""
    current = replace(DEFAULT_LIMITS, profit_cost_multiple=BIG)

    decision = decide_change(current, LimitChange(NAME, Decimal("3"), "telegram"))

    assert decision.reason is RejectReason.TELEGRAM_DECREASE and decision.limits == current
    assert f"1{'0' * 4300} → 3" in decision.message
