"""Spec 0002 AC-1…AC-5: risk limitlerinin config'ten yüklenmesi ve doğrulanması (BR-4…BR-7)."""

import tomllib
from decimal import Decimal

import pytest

from crytobot.risk import DEFAULT_LIMITS, HARD_CAPS, RiskConfigError, RiskLimits, load_limits

LIMIT_NAMES = ["per_trade_risk", "daily_loss_limit", "max_drawdown", "max_open_positions"]
CAPS = {"per_trade_risk": "0.02", "daily_loss_limit": "0.05", "max_drawdown": "0.25"}
JUST_ABOVE_CAP = {
    "per_trade_risk": "0.0200001",
    "daily_loss_limit": "0.0500001",
    "max_drawdown": "0.2500001",
    "max_open_positions": "9",
}


def risk_table(**values: str) -> str:
    return "[risk]\n" + "".join(f"{name} = {value}\n" for name, value in values.items())


def problems_of(toml_text: str) -> tuple[str, ...]:
    with pytest.raises(RiskConfigError) as raised:
        load_limits(toml_text)
    return raised.value.problems


def test_valid_config_loads_exact_values() -> None:
    """AC-1: yazılan değerler tam ondalık olarak gelir; hiçbiri varsayılandan değildir."""
    loaded = load_limits(
        risk_table(
            per_trade_risk="0.005",
            daily_loss_limit="0.02",
            max_drawdown="0.1",
            max_open_positions="3",
        )
    )

    assert loaded.limits == RiskLimits(Decimal("0.005"), Decimal("0.02"), Decimal("0.1"), 3)
    assert loaded.limits.max_drawdown == Decimal("0.1")  # exactly 0.1, not the float's expansion
    assert isinstance(loaded.limits.max_drawdown, Decimal)
    assert loaded.defaulted == frozenset()


def test_missing_limits_take_defaults_and_are_named() -> None:
    """AC-2 (BR-4, BR-7): eksik limitler BR varsayılanını alır ve tam olarak onlar adlandırılır."""
    loaded = load_limits(risk_table(daily_loss_limit="0.02", max_drawdown="0.1"))

    assert loaded.limits.per_trade_risk == DEFAULT_LIMITS.per_trade_risk == Decimal("0.01")
    assert loaded.limits.max_open_positions == DEFAULT_LIMITS.max_open_positions == 5
    assert loaded.limits.daily_loss_limit == Decimal("0.02")
    assert loaded.defaulted == {"per_trade_risk", "max_open_positions"}


@pytest.mark.parametrize(
    "toml_text", ["[risk]\n", '[exchange]\nname = "binance"\n'], ids=["empty", "no_table"]
)
def test_no_limits_or_no_risk_table_gives_all_defaults(toml_text: str) -> None:
    """AC-2: limit içermeyen veya risk tablosu olmayan config'te dördü de varsayılandır."""
    loaded = load_limits(toml_text)

    assert (
        loaded.limits
        == DEFAULT_LIMITS
        == RiskLimits(Decimal("0.01"), Decimal("0.03"), Decimal("0.15"), 5)
    )
    assert loaded.defaulted == set(LIMIT_NAMES)


@pytest.mark.parametrize("name", LIMIT_NAMES)
def test_value_at_cap_is_accepted(name: str) -> None:
    """AC-3 (BR-4…BR-7): üst sınıra eşit değer geçerlidir."""
    cap = getattr(HARD_CAPS, name)

    loaded = load_limits(risk_table(**{name: str(cap)}))

    assert getattr(loaded.limits, name) == cap


@pytest.mark.parametrize("name", LIMIT_NAMES)
def test_value_just_above_cap_is_rejected_naming_limit_value_cap(name: str) -> None:
    """AC-3: üst sınırın hemen üstü reddedilir; hata limiti, değeri ve üst sınırı adlandırır."""
    value = JUST_ABOVE_CAP[name]

    [problem] = problems_of(risk_table(**{name: value}))

    assert name in problem and value in problem
    # the cap must be named on its own: "0.02" is also a prefix of the value "0.0200001"
    assert str(getattr(HARD_CAPS, name)) in problem.replace(value, "")


def test_hard_caps_are_the_spec_values() -> None:
    """R-2: sabit üst sınırlar %2 / %5 / %25 / 8."""
    expected = RiskLimits(Decimal("0.02"), Decimal("0.05"), Decimal("0.25"), 8)

    assert expected == HARD_CAPS


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("per_trade_risk", '"0.01"'),
        ("per_trade_risk", "nan"),
        ("daily_loss_limit", "inf"),
        ("daily_loss_limit", "-inf"),
        ("max_drawdown", "0"),
        ("max_drawdown", "0.0"),
        ("per_trade_risk", "-0.01"),
        ("per_trade_risk", "true"),
        ("max_open_positions", "0"),
        ("max_open_positions", "-1"),
        ("max_open_positions", "2.5"),
        ("max_open_positions", "5.0"),
        ("max_open_positions", "true"),
        ("max_open_positions", '"5"'),
    ],
    ids=[
        "ratio_string",
        "ratio_nan",
        "ratio_inf",
        "ratio_minus_inf",
        "ratio_zero_int",
        "ratio_zero",
        "ratio_negative",
        "ratio_bool",
        "positions_zero",
        "positions_negative",
        "positions_fraction",
        "positions_float_whole",
        "positions_bool",
        "positions_string",
    ],
)
def test_invalid_value_is_rejected_naming_limit(name: str, value: str) -> None:
    """AC-4: sayı olmayan, NaN, sonsuz, sıfır, negatif, kesirli veya mantıksal değer reddedilir."""
    written = tomllib.loads(f"v = {value}", parse_float=Decimal)["v"]

    [problem] = problems_of(risk_table(**{name: value}))

    assert name in problem and str(written) in problem  # R-5: limit and the given value


@pytest.mark.parametrize("value", ["0.0000001", "1e-2", "2E-2"])
def test_tiny_and_scientific_ratios_are_accepted(value: str) -> None:
    """AC-4: alt sınır yok; bilimsel gösterim tam ondalık olarak okunur."""
    loaded = load_limits(risk_table(per_trade_risk=value))

    assert loaded.limits.per_trade_risk == Decimal(value)


def test_integer_ratio_is_checked_against_cap() -> None:
    """AC-3: tam sayı oran da bir sayıdır; 1 (= %100) "sayı değil" değil, üst sınır aşımıdır."""
    [problem] = problems_of(risk_table(per_trade_risk="1"))

    assert "per_trade_risk" in problem and "üst sınır" in problem


@pytest.mark.parametrize(
    "key",
    ["per_trade_riks", "Per_Trade_Risk", '" per_trade_risk"', "hard_cap_per_trade_risk"],
    ids=["typo", "case", "space", "cap_key"],
)
def test_unknown_limit_name_is_rejected(key: str) -> None:
    """AC-5: adlar birebir eşleşir; üst sınırı ayarlamaya çalışan anahtar da bilinmeyendir."""
    [problem] = problems_of(f"[risk]\n{key} = 0.01\n")

    assert key.strip('"') in problem and "0.01" in problem and "bilinmeyen" in problem


def test_all_problems_reported_together() -> None:
    """AC-5: birden fazla hata tek seferde bildirilir."""
    problems = problems_of(
        risk_table(per_trade_risk="0.03", max_drawdown="nan", max_open_positions="0", typo="1")
    )

    assert len(problems) == 4
    for name in ("per_trade_risk", "max_drawdown", "max_open_positions", "typo"):
        assert any(name in problem for problem in problems)


@pytest.mark.parametrize("toml_text", ["[risk\n", "risk = 0.01\n"], ids=["malformed", "not_table"])
def test_unreadable_risk_config_is_rejected(toml_text: str) -> None:
    """R-5: okunamayan config veya tablo olmayan `risk` limit oluşturmaz."""
    problems_of(toml_text)
