"""Spec 0016 AC-12: geçersiz ayar adı konmuş sonuçla reddedilir; yalnız paper (R-12, R-13)."""

import dataclasses
import inspect
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import NoticeKind, PairMarket, TurnMemory, TurnOutcome, TurnSettings, run_turn
from crytobot.execution import PaperExchange
from crytobot.persistence import create_store
from crytobot.risk import HARD_CAPS
from tests.app.helpers import (
    BTC,
    LATER,
    NOW,
    STRATEGY,
    Bot,
    bot_with_position,
    limits,
    make_settings,
    opened_store,
    pair_market,
)

INVALID: dict[str, tuple[str, dict[str, Any]]] = {
    "whitelist_text": ("whitelist", {"whitelist": BTC}),
    "whitelist_none": ("whitelist", {"whitelist": None}),
    "whitelist_repeat": ("whitelist", {"whitelist": (BTC, BTC)}),
    "whitelist_empty_name": ("whitelist", {"whitelist": ("",)}),
    "whitelist_not_text": ("whitelist", {"whitelist": (1,)}),
    "limits_none": ("limits", {"limits": None}),
    "limits_over_cap": ("limits", {"limits": limits(per_trade_risk=HARD_CAPS.per_trade_risk * 2)}),
    "strategy_none": ("strategy", {"strategy": None}),
    "strategy_periods": ("fast_period", {"strategy": replace(STRATEGY, fast_period=9)}),
    "fee_none": ("fee", {"fee": None}),
    "fee_float": ("fee", {"fee": 0.001}),
    "fee_one": ("fee", {"fee": Decimal(1)}),
    "slippage_none": ("slippage", {"slippage": None}),
    "slippage_negative": ("slippage", {"slippage": Decimal(-1)}),
    "interval_none": ("candle_interval", {"candle_interval": None}),
    "interval_zero": ("candle_interval", {"candle_interval": timedelta(0)}),
    "candle_age_none": ("max_candle_age", {"max_candle_age": None}),
    "candle_age_negative": ("max_candle_age", {"max_candle_age": timedelta(seconds=-1)}),
    "price_age_none": ("max_price_age", {"max_price_age": None}),
    "price_age_negative": ("max_price_age", {"max_price_age": timedelta(seconds=-1)}),
}


@pytest.mark.parametrize("case", INVALID)
def test_invalid_setting_is_named(tmp_path: Path, case: str) -> None:
    name, overrides = INVALID[case]
    bot = Bot(opened_store(tmp_path / "s.db"))

    result = bot.turn(settings=make_settings(**overrides))

    assert result.outcome is TurnOutcome.INVALID_SETTINGS
    assert name in result.message


def test_invalid_setting_changes_nothing(tmp_path: Path) -> None:
    path = opened_store(tmp_path / "s.db")
    before = path.read_bytes()
    bot = Bot(path)

    result = bot.turn(settings=make_settings(fee=Decimal(1)))

    assert result.buys == () and result.closes == ()
    assert path.read_bytes() == before


def test_settings_object_is_required(tmp_path: Path) -> None:
    bad: Any = "settings"
    bot = Bot(opened_store(tmp_path / "s.db"))

    assert bot.turn(settings=bad).outcome is TurnOutcome.INVALID_SETTINGS


@pytest.mark.parametrize(
    ("name", "overrides"),
    [
        ("memory", {"memory": "memory"}),
        ("exchange", {"exchange": "exchange"}),
        ("sink", {"sink": "sink"}),
    ],
)
def test_collaborators_are_named(tmp_path: Path, name: str, overrides: dict[str, Any]) -> None:
    path = opened_store(tmp_path / "s.db")
    before = path.read_bytes()
    arguments: dict[str, Any] = {
        "market": {BTC: pair_market()},
        "settings": make_settings(),
        "store_path": path,
        "now": NOW,
        "exchange": PaperExchange(),
        "sink": lambda _notice: None,
        "memory": TurnMemory(),
    }

    result = run_turn(**{**arguments, **overrides})

    assert result.outcome is TurnOutcome.INVALID_SETTINGS and name in result.message
    assert path.read_bytes() == before


@pytest.mark.parametrize("kind", [TurnSettings, PairMarket])
def test_settings_have_no_defaults(kind: Any) -> None:
    for field in dataclasses.fields(kind):
        assert field.default is dataclasses.MISSING, field.name
        assert field.default_factory is dataclasses.MISSING, field.name


def test_empty_whitelist_still_closes(tmp_path: Path) -> None:
    bot = bot_with_position(tmp_path / "s.db")

    result = bot.turn(
        {BTC: pair_market(price=Decimal(7), price_at=LATER)},
        now=LATER,
        settings=make_settings(()),
    )

    assert result.outcome is TurnOutcome.COMPLETED
    assert [o.pair for o in result.closes] == [BTC] and result.buys == ()


def test_run_turn_has_no_mode_input() -> None:
    """R-13: hiçbir girdi live davranışa götüremez."""
    names = set(inspect.signature(run_turn).parameters)
    names |= {field.name for field in dataclasses.fields(TurnSettings)}
    names |= {field.name for field in dataclasses.fields(PairMarket)}
    assert not {name for name in names if "mode" in name or "live" in name}


def test_live_store_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "s.db"
    create_store(path, "live")
    before = path.read_bytes()
    bot = Bot(path)

    result = bot.turn()

    assert result.outcome is TurnOutcome.STORE_UNAVAILABLE and result.buys == ()
    assert path.read_bytes() == before


@pytest.mark.parametrize("now", [NOW.replace(tzinfo=None), None, "2026"], ids=str)
def test_invalid_now_does_nothing(tmp_path: Path, now: Any) -> None:
    path = opened_store(tmp_path / "s.db")
    before = path.read_bytes()
    bot = Bot(path)

    result = bot.turn(now=now)

    assert result.outcome is TurnOutcome.INVALID_TIME
    assert path.read_bytes() == before
    assert bot.kinds() == [NoticeKind.INVALID_TIME]
