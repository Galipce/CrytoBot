"""Spec 0025 `tests/app` testlerinin ortak parçaları: veri dosyası, ayarlar, koşu parçaları.

Plan Risk 14 (B-46): `tests/tooling` kopyası yalnız hassas modül testlerini taşır; bu dosya
`tests/market_data`'dan ve `tests/backtest`'ten import etmez. Veri dosyası 0023'ün biçimiyle burada
yazılır. Koşular küçüktür (≤ 50 tur, `candle_count` ≤ 5).

Mumlar: `high = low = open = close = değer`, ya da açıkça dört değer. `tests/app/helpers` stratejisi
(EMA 1/2, RSI 2, ATR 2, `k=r=2`, tick 0.01): 10, 8, 9, 10 kapanmış serisinde öneri giriş 10, stop 8,
hedef 14'tür.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from crytobot.app import (
    BacktestConfig,
    BacktestExit,
    BacktestParts,
    BotConfig,
    StopRequest,
    TurnSettings,
    run_backtest,
)
from crytobot.backtest import report_exists, write_report
from crytobot.market_data import (
    HistoryData,
    HistoryPair,
    HistoryRead,
    MarketCandle,
    MarketRules,
    ReadSettings,
    read_history,
)
from tests.app.helpers import BTC, DEPOSIT, ETH, HOUR, SPREAD, TICK
from tests.app.helpers import make_settings as turn_settings

START = datetime(2026, 1, 1, tzinfo=UTC)
COUNT = 4
MARKET_RULES = MarketRules(Decimal("0.001"), Decimal("0.001"), Decimal(10))  # helpers.RULES
DOWNLOADED_AT = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
CROSS_BEFORE = (10, 8, 9, 10)  # the closed series that proposes a buy at entry 10
Price = int | float | str | Decimal
Row = Price | tuple[Price, Price, Price, Price] | None


def at(hours: int) -> datetime:
    """Dönem başından `hours` saat sonra (negatif: önce)."""
    return START + hours * HOUR


def candle(open_time: datetime, value: Row) -> MarketCandle:
    assert value is not None
    if isinstance(value, tuple):
        open_, high, low, close = (Decimal(str(part)) for part in value)
    else:
        open_ = high = low = close = Decimal(str(value))
    return MarketCandle(open_time, open_, high, low, close)


def candles(first_hour: int, values: Sequence[Row]) -> tuple[MarketCandle, ...]:
    """`first_hour`'dan başlayarak saatte bir mum; `None` o saatte mum yok (boşluk)."""
    return tuple(
        candle(at(first_hour + index), value)
        for index, value in enumerate(values)
        if value is not None
    )


def history(
    series: Mapping[str, Sequence[MarketCandle]],
    *,
    hours: int,
    count: int = COUNT,
    interval: timedelta = HOUR,
) -> HistoryData:
    """Dönem `START`..`START + hours`; ısınma `count` mum önce başlar."""
    return HistoryData(
        "binance",
        interval,
        START,
        at(hours),
        START - count * interval,
        DOWNLOADED_AT,
        tuple(HistoryPair(pair, TICK, MARKET_RULES, tuple(rows)) for pair, rows in series.items()),
    )


def _text(value: Decimal) -> str:
    return format(value, "f")


def write_history(path: Path, data: HistoryData) -> Path:
    """0023'ün dosya biçimi: başlık, çift başına mum satırları, tamamlanma satırı."""
    interval = {HOUR: "1h", 2 * HOUR: "2h", 4 * HOUR: "4h"}[data.candle_interval]
    header = {
        "format": "crytobot-history",
        "version": 1,
        "exchange": data.exchange,
        "candle_interval": interval,
        "start": data.start.isoformat(),
        "end": data.end.isoformat(),
        "warmup_start": data.warmup_start.isoformat(),
        "downloaded_at": data.downloaded_at.isoformat(),
        "pairs": [
            {
                "pair": pair.pair,
                "market_id": pair.pair.replace("/", ""),
                "tick": _text(pair.tick),
                "amount_step": _text(pair.rules.amount_step),
                "min_amount": _text(pair.rules.min_amount),
                "min_notional": _text(pair.rules.min_notional),
            }
            for pair in data.pairs
        ],
    }
    rows: list[object] = [header]
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    for pair in data.pairs:
        for item in pair.candles:
            open_ms = (item.open_time - epoch) // timedelta(milliseconds=1)
            prices = (item.open, item.high, item.low, item.close)
            rows.append([pair.pair, open_ms, *(_text(price) for price in prices)])
    rows.append({"complete": True, "counts": {pair.pair: len(pair.candles) for pair in data.pairs}})
    text = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows
    )
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def settings(whitelist: Sequence[str] = (BTC, ETH), **overrides: Any) -> TurnSettings:
    return turn_settings(tuple(whitelist), **overrides)


def bot_config(
    root: Path,
    *,
    turn: TurnSettings | None = None,
    turn_interval: timedelta = HOUR,
    count: int = COUNT,
    balance: Decimal = DEPOSIT,
) -> BotConfig:
    turn = settings() if turn is None else turn
    read = ReadSettings(
        "binance", turn.candle_interval, count, timedelta(seconds=5), timedelta(seconds=30)
    )
    return BotConfig(
        str(root / "bot.db"), str(root / "bot.log"), turn_interval, balance, read, turn
    )


def config(
    root: Path,
    *,
    split_at: datetime | None = None,
    spread: Decimal = SPREAD,
    **bot: Any,
) -> BacktestConfig:
    return BacktestConfig(
        str(root / "history.jsonl"),
        str(root / "rapor.txt"),
        at(2) if split_at is None else split_at,
        spread,
        bot_config(root, **bot),
    )


@dataclass
class Run:
    """Bir koşu: gerçek okuyucu ve rapor yazıcısı, satırlar listede, geçici depo `work`'te."""

    root: Path
    lines: list[str] = field(default_factory=list)
    stop: StopRequest = field(default_factory=StopRequest)
    reads: list[str] = field(default_factory=list)

    @property
    def work(self) -> Path:
        path = self.root / "work"
        path.mkdir(exist_ok=True)
        return path

    def read(self, path: str) -> HistoryRead:
        self.reads.append(path)
        return read_history(path)

    def parts(self, **changes: Any) -> BacktestParts:
        parts = BacktestParts(
            self.read,
            report_exists,
            write_report,
            self.lines.append,
            self.stop,
            str(self.work / "backtest.db"),
        )
        return replace(parts, **changes)

    def __call__(self, config: BacktestConfig, **changes: Any) -> BacktestExit:
        return run_backtest(config, self.parts(**changes))

    @property
    def console(self) -> str:
        return "".join(line + "\n" for line in self.lines)

    def report(self, config: BacktestConfig) -> str:
        return Path(config.report_path).read_text(encoding="utf-8")


def report_lines(text: str, section: str) -> dict[str, str]:
    """Raporun bir bölümü: satır etiketi → değer."""
    body = text.split(f"== {section}", 1)[1].split("\n\n", 1)[0]
    found: dict[str, str] = {}
    for row in body.splitlines()[1:]:
        label, _, value = row.partition(": ")
        found[label] = value
    return found
