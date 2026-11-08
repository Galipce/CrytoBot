"""Spec 0022 döngü testlerinin sahteleri: saat, bekleme, okuma, yazıcı, durdurma (plan Risk 10).

Gerçek bekleme yoktur: `wait` sahte saati ilerletir. Okuma `MarketRead` döndürür, borsaya çıkmaz.
Yalnız `tests/app`'ten import eder: araç kopyası `tests/market_data`'yı ve `tests/main`'i taşımaz.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from crytobot.app import BotConfig, LoopExit, LoopParts, StopRequest, TurnSettings, run_loop
from crytobot.execution import PaperExchange
from crytobot.market_data import (
    InputProblem,
    MarketCandle,
    MarketRead,
    MarketRules,
    PairRead,
    ReadBan,
    ReadSettings,
)
from tests.app.helpers import BTC, CROSS, DEPOSIT, FLAT, HOUR, NOW, SPREAD, TICK
from tests.app.helpers import make_settings as turn_settings

READ = ReadSettings("binance", HOUR, 4, timedelta(seconds=5), timedelta(seconds=30))
MARKET_RULES = MarketRules(Decimal("0.001"), Decimal("0.001"), Decimal(10))  # helpers.RULES
# a turn-like time inside an interval, so that the start is not on a boundary
START = NOW + timedelta(minutes=20)


def bot_config(
    store: Path, *, turn: TurnSettings | None = None, interval: timedelta = HOUR
) -> BotConfig:
    return BotConfig(
        str(store),
        str(store.with_suffix(".log")),
        interval,
        DEPOSIT,
        READ,
        turn_settings() if turn is None else turn,
    )


def market_candles(closes: Sequence[float], closed_at: datetime) -> tuple[MarketCandle, ...]:
    start = closed_at - len(closes) * HOUR
    rows = []
    for index, close in enumerate(closes):
        value = Decimal(repr(close))
        rows.append(MarketCandle(start + index * HOUR, value, value, value, value))
    return tuple(rows)


def pair_read(pair: str, at: datetime, closes: Sequence[float] = FLAT) -> PairRead:
    """Son mum `at`'in sınırında kapanır; fiyat `at` damgalıdır, son kapanışa eşittir."""
    closed_at = NOW + (at - NOW) // HOUR * HOUR
    price = Decimal(repr(closes[-1]))
    return PairRead(
        pair, market_candles(closes, closed_at), price, at, SPREAD, TICK, MARKET_RULES, ()
    )


@dataclass
class Clock:
    now: datetime = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


Hook = Callable[["Harness"], None]


@dataclass
class Harness:
    """Bir süreç: sahte etkiler ve kayıtları. `stop_after` tur özetinden sonra durdurma ister.

    `read_hooks[n]` n'inci okumada (0'dan), `wait_hooks[n]` n'inci beklemede çağrılır.
    `answers[n]` n'inci okumanın yerine döner: `MarketRead`, okumanın anından onu kuran işlev ya
    da fırlatılacak istisna.
    """

    store: Path
    config: BotConfig
    clock: Clock = field(default_factory=Clock)
    closes: Sequence[float] = FLAT
    stop_after: int | None = 1
    read_seconds: float = 2.0
    answers: dict[int, object] = field(default_factory=dict)
    read_hooks: dict[int, Hook] = field(default_factory=dict)
    wait_hooks: dict[int, Hook] = field(default_factory=dict)
    max_waits: int = 100_000
    stop: StopRequest = field(default_factory=StopRequest)
    lines: list[str] = field(default_factory=list)
    reads: list[tuple[tuple[str, ...], datetime]] = field(default_factory=list)
    waits: list[float] = field(default_factory=list)
    write_error: Exception | None = None

    # --- effects ----------------------------------------------------------------------------
    def read(self, pairs: tuple[str, ...], settings: ReadSettings) -> MarketRead:
        index = len(self.reads)
        self.reads.append((pairs, self.clock.now))
        hook = self.read_hooks.get(index)
        if hook is not None:
            hook(self)
        self.clock.advance(self.read_seconds)
        at = self.clock.now
        answer = self.answers.get(index)
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, MarketRead):
            return answer
        if callable(answer):  # built from the read's own time
            built: MarketRead = answer(at)
            return built
        return MarketRead(tuple(pair_read(pair, at, self.closes) for pair in pairs), at, None)

    def wait(self, seconds: float) -> None:
        index = len(self.waits)
        self.waits.append(seconds)
        hook = self.wait_hooks.get(index)
        if hook is not None:
            hook(self)
        if index >= self.max_waits and not self.stop.requested:
            self.stop.request("test")
        self.clock.advance(seconds)

    def write(self, text: str) -> None:
        self.lines.append(text)
        if self.write_error is not None:
            raise self.write_error
        reached = self.stop_after is not None and len(self.events("tur")) >= self.stop_after
        if reached and not self.stop.requested:
            self.stop.request("test")

    # --- running and reading back -----------------------------------------------------------
    def parts(self) -> LoopParts:
        return LoopParts(self.clock, self.wait, self.read, self.write, self.stop)

    def run(
        self,
        exchange: PaperExchange | None = None,
        *,
        trial: bool = True,
        approved_by: str | None = None,
        report_path: str | None = None,
        reporter: Any | None = None,
    ) -> LoopExit:
        return run_loop(
            self.config,
            self.parts(),
            exchange=exchange,
            trial=trial,
            approved_by=approved_by,
            report_path=report_path,
            reporter=reporter,
        )

    def events(self, event: str) -> list[str]:
        return [text for text in self.lines if text.split(" ", 2)[1] == event]

    def read_times(self) -> list[datetime]:
        return [at for _, at in self.reads]


def harness(store: Path, **kwargs: Any) -> Harness:
    turn = kwargs.pop("turn", None)
    interval = kwargs.pop("interval", HOUR)
    return Harness(store, bot_config(store, turn=turn, interval=interval), **kwargs)


def banned_read(at: datetime, until: datetime | None, pairs: Sequence[str] = (BTC,)) -> MarketRead:
    """Yasakla biten okuma: çiftlerin alanları eksik, `ban` dolu."""
    missing = tuple(PairRead(pair, None, None, None, None, None, None, ()) for pair in pairs)
    return MarketRead(missing, at, None, ReadBan(until))


def refused_read(problem: InputProblem) -> MarketRead:
    return MarketRead((), None, problem)


__all__ = ["CROSS", "FLAT", "START", "Clock", "Harness", "banned_read", "harness", "refused_read"]
