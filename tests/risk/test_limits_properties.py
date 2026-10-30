"""Spec 0002 AC-10 (R-7): hiçbir girdi üst sınırları aşamaz; Telegram hiçbir limiti yükseltemez."""

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from crytobot.risk import (
    DEFAULT_LIMITS,
    HARD_CAPS,
    LimitChange,
    RiskConfigError,
    RiskLimits,
    decide_change,
    load_limits,
)

LIMIT_NAMES = ["per_trade_risk", "daily_loss_limit", "max_drawdown", "max_open_positions"]

# TOML literals around every boundary: zero, the caps, just above them, specials and wrong types
decimal_literals = st.decimals(
    min_value=Decimal("-0.1"), max_value=Decimal("0.4"), places=7, allow_nan=False
).map(lambda d: f"{d:f}")
toml_literals = st.one_of(
    decimal_literals,
    st.integers(min_value=-3, max_value=12).map(str),
    st.sampled_from(["nan", "inf", "-inf", "true", "false", '"0.01"', "0.02", "0.05", "0.25"]),
)
risk_tables = st.dictionaries(
    st.sampled_from([*LIMIT_NAMES, "Per_Trade_Risk", "hard_cap"]), toml_literals, max_size=6
)

junk_values = st.one_of(
    st.decimals(allow_nan=True, allow_infinity=True),
    st.integers(min_value=-3, max_value=12),
    st.booleans(),
    st.floats(),
    st.sampled_from(["0.01", "", "5"]),  # no st.text: no unicode table built per run
)


def values_near_cap(limit: str) -> st.SearchStrategy[object]:
    """Mostly valid values between zero and just above the cap, where BR-13 decisions happen."""
    if limit == "max_open_positions":
        near: st.SearchStrategy[object] = st.integers(min_value=0, max_value=10)
    else:
        cap = getattr(HARD_CAPS, limit, Decimal("0.25"))
        near = st.decimals(min_value=Decimal(0), max_value=cap + Decimal("0.01"), places=7)
    return st.one_of(near, near, near, junk_values)


changes = st.sampled_from([*LIMIT_NAMES, "bogus"]).flatmap(
    lambda limit: st.builds(
        LimitChange,
        limit=st.just(limit),
        value=values_near_cap(limit),
        channel=st.sampled_from(["cli", "telegram", "cli", "telegram", "TELEGRAM", "sms"]),
    )
)


# any starting point inside the caps, so a raise is judged against the current value, not a default
start_limits = st.builds(
    RiskLimits,
    **{
        name: st.decimals(
            min_value=Decimal("0.0000001"), max_value=getattr(HARD_CAPS, name), places=7
        )
        for name in LIMIT_NAMES[:3]
    },
    max_open_positions=st.integers(min_value=1, max_value=HARD_CAPS.max_open_positions),
)


def within_caps(limits: RiskLimits) -> bool:
    return all(
        getattr(limits, name) <= getattr(HARD_CAPS, name)
        and getattr(limits, name) > 0
        and isinstance(getattr(limits, name), int if name == "max_open_positions" else Decimal)
        for name in LIMIT_NAMES
    )


@given(risk_tables)
def test_loaded_limits_never_exceed_caps(table: dict[str, str]) -> None:
    """AC-10 (BR-4…BR-7): yükleme ya kapsam içinde limit üretir ya da RiskConfigError verir."""
    toml_text = "[risk]\n" + "".join(f"{key} = {value}\n" for key, value in table.items())

    try:
        loaded = load_limits(toml_text)
    except RiskConfigError:
        return

    assert within_caps(loaded.limits)


@given(st.one_of(st.just(DEFAULT_LIMITS), start_limits), st.lists(changes, max_size=20))
def test_change_sequences_never_exceed_caps_or_raise_via_telegram(
    start: RiskLimits, requests: list[LimitChange]
) -> None:
    """AC-10 (BR-13): limitler hep kapsam içinde; Telegram'dan kabul edilen istek yükseltmez."""
    limits = start

    for request in requests:
        decision = decide_change(limits, request)

        assert within_caps(decision.limits)
        if not decision.accepted:
            assert decision.limits == limits
        elif request.channel == "telegram":
            assert all(
                getattr(decision.limits, name) <= getattr(limits, name) for name in LIMIT_NAMES
            )
        limits = decision.limits
