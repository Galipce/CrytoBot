"""Spec 0023 testlerinin ortak parçaları: `FakeHistoryExchange`, istek ve dosya okuyucu.

`FakeHistoryExchange` Binance `klines`'ın `endTime` + `limit` davranışını taklit eder: `end_ms`'e
kadar açılan son `limit` mum, eskiden yeniye. Çağrılar `calls`'a, mum istekleri `kline_requests`'e
yazılır. `fail`: genel çağrı sırası (1'den) → fırlatılacak hata; `tamper`: mum çağrısı sırası →
yanıtı değiştiren işlev. Paylaşılan `helpers.py` değişmez (plan, Files).
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from crytobot.market_data import (
    HistoryRequest,
    HistoryResult,
    ReadSettings,
    download_history,
)
from crytobot.market_data._client import PublicExchange
from tests.market_data.helpers import BTC, ETH, HOUR, HOUR_MS, market, market_id

START = datetime(2026, 1, 1, tzinfo=UTC)
START_MS = 1_767_225_600_000
DAY_MS = 24 * HOUR_MS
# After the end of every period the tests use: the end is never after the download moment
DOWNLOADED_AT = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
WARMUP = 3


def at(ms: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=ms)


def price_row(open_ms: int, index: int) -> list[object]:
    """Her mumun fiyatı ayrıdır; metinler borsanın 8 ondalıklı biçimindedir."""
    base = 100 + index % 50
    return [
        open_ms,
        f"{base}.10000000",
        f"{base + 1}.00000000",
        f"{base - 1}.00000010",
        f"{base}.50000000",
        "12.5",
        open_ms + HOUR_MS - 1,
        "1250.0",
        7,
        "1",
        "1",
        "0",
    ]


def rows_between(first_ms: int, end_ms: int, step_ms: int = HOUR_MS) -> list[list[object]]:
    """`first_ms`'ten `end_ms`'e (hariç) her aralıkta bir mum."""
    return [price_row(ms, i) for i, ms in enumerate(range(first_ms, end_ms, step_ms))]


def make_settings(**overrides: Any) -> ReadSettings:
    values: dict[str, Any] = {
        "exchange": "binance",
        "candle_interval": HOUR,
        "candle_count": WARMUP,
        "call_timeout": timedelta(seconds=5),
        "read_budget": timedelta(seconds=30),
    }
    return ReadSettings(**{**values, **overrides})


def make_request(
    data_path: Path,
    *,
    pairs: Sequence[str] = (BTC, ETH),
    start: datetime = START,
    days: int = 2,
    end: datetime | None = None,
    **settings: Any,
) -> HistoryRequest:
    return HistoryRequest(
        str(data_path),
        tuple(pairs),
        make_settings(**settings),
        start,
        start + timedelta(days=days) if end is None else end,
    )


@dataclass
class FakeHistoryExchange:
    """`history`: çift → eskiden yeniye bütün mum satırları (borsanın elindeki geçmiş)."""

    history: dict[str, list[list[object]]]
    markets_answer: object = None
    fail: dict[int, BaseException] = field(default_factory=dict)
    tamper: dict[int, Callable[[list[list[object]]], object]] = field(default_factory=dict)
    on_call: Callable[[int], None] | None = None
    calls: list[str] = field(default_factory=list)
    kline_requests: list[dict[str, Any]] = field(default_factory=list)

    def _called(self, name: str) -> None:
        self.calls.append(name)
        if self.on_call is not None:
            self.on_call(len(self.calls))
        planned = self.fail.get(len(self.calls))
        if planned is not None:
            raise planned

    def markets(self, timeout: float) -> object:
        self._called("markets")
        if self.markets_answer is not None:
            return self.markets_answer
        return {pair: market(pair) for pair in self.history}

    def klines(
        self, market_id_: str, interval: str, limit: int, end_ms: int, timeout: float
    ) -> object:
        self._called(f"klines {market_id_}")
        self.kline_requests.append(
            {"symbol": market_id_, "interval": interval, "limit": limit, "end_ms": end_ms}
        )
        rows = next(
            (rows for pair, rows in self.history.items() if market_id(pair) == market_id_), []
        )
        answer = [row for row in rows if isinstance(row[0], int) and row[0] <= end_ms][-limit:]
        change = self.tamper.get(len(self.kline_requests))
        return answer if change is None else change(answer)

    def ticker(self, market_id_: str, timeout: float) -> object:  # pragma: no cover - never used
        self._called(f"ticker {market_id_}")
        raise AssertionError("the download never reads a ticker")


def full_history(
    pairs: Sequence[str] = (BTC, ETH), days: int = 2, before: int = 10, after: int = 5
) -> dict[str, list[list[object]]]:
    """Dönemden `before` mum önce başlayıp bitişten `after` mum sonraya uzanan geçmiş."""
    first = START_MS - before * HOUR_MS
    end = START_MS + days * DAY_MS + after * HOUR_MS
    return {pair: rows_between(first, end) for pair in pairs}


def run_download(
    request: HistoryRequest,
    exchange: FakeHistoryExchange,
    *,
    clock: Callable[[], datetime] = lambda: DOWNLOADED_AT,
    stop_requested: Callable[[], bool] = lambda: False,
) -> HistoryResult:
    def connect() -> PublicExchange:
        return exchange

    return download_history(request, clock, stop_requested, connect=connect)


@dataclass(frozen=True)
class DataFile:
    header: dict[str, Any]
    candles: list[list[Any]]
    complete: dict[str, Any]


def read_file(path: Path) -> DataFile:
    lines = path.read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(line) for line in lines]
    return DataFile(parsed[0], parsed[1:-1], parsed[-1])


def leftovers(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())
