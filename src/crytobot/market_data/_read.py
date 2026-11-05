"""Tek okuma: girdi reddi, sıra, kısmi hata (spec 0017 R-1, R-3, R-15; plan Risk 4, 10)."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crytobot.market_data._calls import Caller, CallFailed
from crytobot.market_data._candles import parse_series, request_end_ms
from crytobot.market_data._client import PublicExchange, connect_public
from crytobot.market_data._pairs import pair_spec
from crytobot.market_data._quote import parse_quote
from crytobot.market_data._types import (
    CANDLE_INTERVALS,
    InputProblem,
    IssueReason,
    MarketCandle,
    MarketDataError,
    MarketRead,
    MarketRules,
    PairRead,
    ReadField,
    ReadIssue,
    ReadSettings,
    pairs_problem,
    settings_problem,
)

_ALL_FIELDS = tuple(ReadField)
_QUOTE_FIELDS = (ReadField.PRICE, ReadField.PRICE_AT, ReadField.SPREAD)


class _ClockFailed(MarketDataError):
    """Saat çağrılamadı ya da dilimsiz değer verdi."""


class _Clock:
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self.latest: datetime | None = None

    def read(self) -> datetime:
        try:
            value: object = self._clock()
            if not (isinstance(value, datetime) and value.utcoffset() is not None):
                raise _ClockFailed
            self.latest = value.astimezone(UTC)
        except Exception as error:
            raise _ClockFailed from error
        return self.latest


@dataclass(slots=True)
class _Draft:
    """Bir çiftin birikmekte olan sonucu; karara bağlanmamış alan `settled`'da değildir."""

    pair: str
    candles: tuple[MarketCandle, ...] | None = None
    price: Decimal | None = None
    price_at: datetime | None = None
    spread: Decimal | None = None
    tick: Decimal | None = None
    rules: MarketRules | None = None
    issues: list[ReadIssue] = field(default_factory=list)
    settled: set[ReadField] = field(default_factory=set)

    def miss(self, fields: tuple[ReadField, ...], reason: IssueReason) -> None:
        for name in fields:
            if name not in self.settled:
                self.issues.append(ReadIssue(name, reason))
                self.settled.add(name)

    def miss_rest(self, reason: IssueReason) -> None:
        self.miss(_ALL_FIELDS, reason)

    def result(self) -> PairRead:
        return PairRead(
            self.pair,
            self.candles,
            self.price,
            self.price_at,
            self.spread,
            self.tick,
            self.rules,
            tuple(self.issues),
        )


def _read_candles(
    draft: _Draft,
    market_id: str,
    settings: ReadSettings,
    caller: Caller,
    exchange: PublicExchange,
    clock: _Clock,
) -> None:
    interval = settings.candle_interval
    count = settings.candle_count
    before_request = clock.read()
    end_ms = request_end_ms(before_request, interval)
    text = CANDLE_INTERVALS[interval]
    try:
        response = caller.call(lambda t: exchange.klines(market_id, text, count, end_ms, t))
    except CallFailed as failed:
        draft.miss((ReadField.CANDLES,), failed.reason)
        return
    series = parse_series(response, interval, count, before_request)
    draft.candles = series.candles
    draft.settled.add(ReadField.CANDLES)
    if series.issue is not None:
        draft.issues.append(ReadIssue(ReadField.CANDLES, series.issue))


def _read_quote(
    draft: _Draft, market_id: str, caller: Caller, exchange: PublicExchange, clock: _Clock
) -> None:
    try:
        response = caller.call(lambda t: exchange.ticker(market_id, t))
    except CallFailed as failed:
        draft.miss(_QUOTE_FIELDS, failed.reason)
        return
    quote = parse_quote(response, market_id, draft.tick, clock.read())
    draft.price = quote.price
    draft.price_at = quote.price_at
    draft.spread = quote.spread
    draft.issues.extend(quote.issues)
    draft.settled.update(_QUOTE_FIELDS)


def _read_pair(
    draft: _Draft,
    markets: Mapping[str, object],
    settings: ReadSettings,
    caller: Caller,
    exchange: PublicExchange,
    clock: _Clock,
) -> None:
    spec = pair_spec(draft.pair, markets)
    if isinstance(spec, IssueReason):
        draft.miss_rest(spec)
        return
    draft.tick = spec.tick
    draft.rules = spec.rules
    draft.issues.extend(spec.issues)
    draft.settled.update((ReadField.TICK, ReadField.RULES))
    _read_candles(draft, spec.market_id, settings, caller, exchange, clock)
    _read_quote(draft, spec.market_id, caller, exchange, clock)


def _read_all(
    drafts: list[_Draft],
    settings: ReadSettings,
    clock: _Clock,
    connect: Callable[[], PublicExchange],
) -> None:
    caller = Caller(settings.call_timeout.total_seconds(), settings.read_budget.total_seconds())
    try:
        # connect counts too: the first ccxt import alone takes seconds (plan Risk 9)
        exchange = caller.call(lambda _: connect())
        markets = caller.call(exchange.markets)
    except CallFailed as failed:
        for draft in drafts:
            draft.miss_rest(failed.reason)
        return
    if not isinstance(markets, Mapping):
        for draft in drafts:
            draft.miss_rest(IssueReason.MALFORMED_RESPONSE)
        return
    for draft in drafts:
        _read_pair(draft, markets, settings, caller, exchange, clock)


def _input_problem(pairs: object, settings: object) -> InputProblem | None:
    return settings_problem(settings) or pairs_problem(pairs)


def read_market_data(
    pairs: list[str] | tuple[str, ...],
    settings: ReadSettings,
    clock: Callable[[], datetime],
    *,
    connect: Callable[[], PublicExchange] = connect_public,
) -> MarketRead:
    """Verilen çiftler için tek geçiş; yalnız herkese açık veri okur. İstisna fırlatmaz (R-3).

    Geçersiz girdide borsaya çağrı gitmez, `input_problem` döner. Sonuçta ham yanıt metni yoktur.
    """
    problem = _input_problem(pairs, settings)
    reader = _Clock(clock)
    if problem is None:
        try:
            reader.read()
        except _ClockFailed:
            problem = InputProblem.CLOCK
    if problem is not None:
        return MarketRead((), None, problem)
    if not pairs:
        return MarketRead((), reader.latest, None)
    drafts = [_Draft(pair) for pair in pairs]
    try:
        _read_all(drafts, settings, reader, connect)
        reader.read()
    except Exception:
        # Whatever was not settled stays missing by name; the error's text is not kept (R-11)
        for draft in drafts:
            draft.miss_rest(IssueReason.UNEXPECTED)
    return MarketRead(tuple(draft.result() for draft in drafts), reader.latest, None)
