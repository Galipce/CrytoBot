"""Spec 0016 testlerinin ortak parçaları: senaryo kurucuları ve `Bot` (süreç + depo).

Seri `10, 8, 9, 10`, EMA 1/2, RSI 2, ATR 2, `k=r=2`, tick `0.01`: giriş 10, stop 8, hedef 14.
"""

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.analysis import Candle
from crytobot.app import (
    PairMarket,
    TurnMemory,
    TurnNotice,
    TurnResult,
    TurnSettings,
    _session,
    run_turn,
)
from crytobot.execution import OrderStatus, PaperExchange
from crytobot.persistence import (
    StoredState,
    StoreOutcome,
    StoreResult,
    create_store,
    load_store,
    save_store,
)
from crytobot.portfolio import EMPTY_LEDGER, open_ledger
from crytobot.risk import DEFAULT_LIMITS, PairRules
from crytobot.strategy import StrategySettings

BTC = "BTC/USDT"
ETH = "ETH/USDT"
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)
MINUTE = timedelta(minutes=1)
LATER = NOW + 5 * MINUTE
NEXT_CANDLE = NOW + HOUR
CROSS = (10.0, 8.0, 9.0, 10.0)
FLAT = (10.0, 10.0, 10.0, 10.0)
RULES = PairRules(Decimal("0.001"), Decimal("0.001"), Decimal(10))
TICK = Decimal("0.01")
FEE = Decimal("0.001")
SLIPPAGE = Decimal("0.001")
SPREAD = Decimal("0.0005")
DEPOSIT = Decimal(10000)
MAX_CANDLE_AGE = 30 * MINUTE
MAX_PRICE_AGE = 5 * MINUTE
STRATEGY = StrategySettings(1, 2, 2, Decimal(70), 2, Decimal(2), Decimal(2))
# spec 0020 R-1: risk bütçesi 100 USDT, slippage'lı giriş 10.01, birim kayıp
# (10.01 - 8) + 10.01 * 0.001 + 8 * 0.001 = 2.02801: amount = 100 // (0.001 * 2.02801) * 0.001
FIRST_AMOUNT = Decimal("49.309")


def series(closes: Sequence[float], closed_at: datetime = NOW) -> list[Candle]:
    """Son mum `closed_at`'te kapanır; `high = low = open = close`."""
    start = closed_at - len(closes) * HOUR
    return [Candle(start + i * HOUR, c, c, c, c) for i, c in enumerate(closes)]


def pair_market(
    closes: Sequence[float] = CROSS,
    *,
    closed_at: datetime = NOW,
    price: Any = Decimal(10),
    price_at: Any = None,
    **overrides: Any,
) -> PairMarket:
    values: dict[str, Any] = {
        "candles": series(closes, closed_at),
        "price": price,
        "price_at": closed_at if price_at is None else price_at,
        "rules": RULES,
        "tick": TICK,
        "spread": SPREAD,
    }
    return PairMarket(**{**values, **overrides})


def make_settings(whitelist: Sequence[str] = (BTC,), **overrides: Any) -> TurnSettings:
    values: dict[str, Any] = {
        "whitelist": whitelist,
        "limits": DEFAULT_LIMITS,
        "strategy": STRATEGY,
        "fee": FEE,
        "slippage": SLIPPAGE,
        "candle_interval": HOUR,
        "max_candle_age": MAX_CANDLE_AGE,
        "max_price_age": MAX_PRICE_AGE,
    }
    return TurnSettings(**{**values, **overrides})


def limits(**overrides: Any) -> Any:
    return replace(DEFAULT_LIMITS, **overrides)


class Exchange(PaperExchange):
    """Önek başına sabit sonuç: `cb-` alım, `cx-` kapanış; ayarsız emir dolar, sorgu bilinmez."""

    def __init__(
        self,
        place: dict[str, OrderStatus] | None = None,
        query: dict[str, OrderStatus] | None = None,
    ) -> None:
        super().__init__()
        object.__setattr__(self, "_place", place or {})
        object.__setattr__(self, "_query", query or {})

    def place(self, client_order_id: str) -> OrderStatus:
        rules: dict[str, OrderStatus] = object.__getattribute__(self, "_place")
        return rules.get(client_order_id[:3], OrderStatus.FILLED)

    def query(self, client_order_id: str) -> OrderStatus:
        rules: dict[str, OrderStatus] = object.__getattribute__(self, "_query")
        return rules.get(client_order_id[:3], OrderStatus.UNKNOWN)


def opened_store(path: Path, deposit: Decimal = DEPOSIT, at: datetime = NOW - HOUR) -> Path:
    created = create_store(path, "paper")
    assert created.state is not None
    ledger = open_ledger(EMPTY_LEDGER, deposit, at).ledger
    saved = save_store(path, created.state, ledger, created.state.execution, created.state.risk)
    assert saved.state is not None
    return path


class Bot:
    """Bir süreç: aynı `TurnMemory` ve bildirim listesi. `restart` yeni belleğe geçer."""

    def __init__(self, path: Path, *, settings: TurnSettings | None = None) -> None:
        self.path = path
        self.settings = make_settings() if settings is None else settings
        self.memory = TurnMemory()
        self.notices: list[TurnNotice] = []

    def turn(
        self,
        market: dict[str, Any] | None = None,
        *,
        now: Any = NOW,
        settings: TurnSettings | None = None,
        exchange: PaperExchange | None = None,
        sink: Any = None,
    ) -> TurnResult:
        return run_turn(
            market={BTC: pair_market()} if market is None else market,
            settings=self.settings if settings is None else settings,
            store_path=self.path,
            now=now,
            exchange=PaperExchange() if exchange is None else exchange,
            sink=self.notices.append if sink is None else sink,
            memory=self.memory,
        )

    def restart(self) -> None:
        self.memory = TurnMemory()

    def stored(self) -> StoredState:
        loaded = load_store(self.path, "paper")
        assert loaded.state is not None, loaded.message
        return loaded.state

    def conflicts(self) -> tuple[str, ...]:
        return load_store(self.path, "paper").conflicts

    def kinds(self, *, entering: bool = True) -> list[Any]:
        return [n.kind for n in self.notices if n.entering is entering]


def bot_with_position(path: Path, **kwargs: Any) -> Bot:
    """Depoda BTC'de stop 8, hedef 14, miktar `FIRST_AMOUNT` açık pozisyon."""
    bot = Bot(opened_store(path), **kwargs)
    bought = bot.turn({BTC: pair_market()})
    assert len(bought.buys) == 1, bought
    return bot


Writes = Callable[[Any, Any, Any], bool]


def refuse_saves(
    monkeypatch: pytest.MonkeyPatch,
    outcome: StoreOutcome,
    when: Writes = lambda *_: True,
    times: int = 1,
) -> list[StoreOutcome]:
    """`when(ledger, execution, risk)` doğruysa kayıt `outcome` ile reddedilir, `times` kez."""
    refused: list[StoreOutcome] = []

    def fake(path: object, base: object, ledger: Any, execution: Any, risk: Any) -> StoreResult:
        if len(refused) < times and when(ledger, execution, risk):
            refused.append(outcome)
            return StoreResult(outcome, None, (), outcome.value)
        return save_store(path, base, ledger, execution, risk)

    monkeypatch.setattr(_session, "save_store", fake)
    return refused


def writes_closure(ledger: Any, _execution: Any, _risk: Any) -> bool:
    return bool(ledger.closures)


def writes_order(_ledger: Any, execution: Any, _risk: Any) -> bool:
    return bool(execution.orders)
