"""Spec 0025 `tests/app` testlerinin ortak parçaları: veri dosyası, ayarlar, koşu parçaları.

Plan Risk 14 (B-46): `tests/tooling` kopyası yalnız hassas modül testlerini taşır; bu dosya
`tests/market_data`'dan ve `tests/backtest`'ten import etmez. Veri dosyası 0023'ün biçimiyle burada
yazılır. Koşular küçüktür (≤ 50 tur, `candle_count` ≤ 5).

Mumlar: `high = low = open = close = değer`, ya da açıkça dört değer. `tests/app/helpers` stratejisi
(EMA 1/2, RSI 2, ATR 2, `k=r=2`, tick 0.01): 10, 8, 9, 10 kapanmış serisinde öneri giriş 10, stop 8,
hedef 14'tür.

Spec 0042 (plan Risk 8): `config` saklı dönem başı (`holdout_at`) alır, verilmezse ayrım anından bir
saat sonrası; `Run.final` son değerlendirmeyi (`run_evaluation`) aynı parçalarla koşar.
"""

import json
from collections.abc import Callable, Mapping, Sequence
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
    final_configs,
    run_backtest,
    run_evaluation,
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
GENERATED_AT = datetime(2026, 3, 2, 9, 30, tzinfo=UTC)  # spec 0040: the fixed generation clock
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
    holdout_at: datetime | None = None,
    spread: Decimal = SPREAD,
    **bot: Any,
) -> BacktestConfig:
    split = at(2) if split_at is None else split_at
    return BacktestConfig(
        str(root / "history.jsonl"),
        str(root / "rapor.txt"),
        split,
        spread,
        bot_config(root, **bot),
        holdout_at=split + HOUR if holdout_at is None else holdout_at,
    )


OWN: Any = object()  # `Run.final`: each configuration with its own strategy


@dataclass
class Run:
    """Bir koşu: gerçek okuyucu ve rapor yazıcısı, satırlar listede, geçici depo `work`'te; saat
    sabit `GENERATED_AT`, her okuması `clock_reads`'e sayılır (spec 0040)."""

    root: Path
    lines: list[str] = field(default_factory=list)
    stop: StopRequest = field(default_factory=StopRequest)
    reads: list[str] = field(default_factory=list)
    clock_reads: int = 0

    @property
    def work(self) -> Path:
        path = self.root / "work"
        path.mkdir(exist_ok=True)
        return path

    def read(self, path: str) -> HistoryRead:
        self.reads.append(path)
        return read_history(path)

    def clock(self) -> datetime:
        self.clock_reads += 1
        return GENERATED_AT

    def parts(self, **changes: Any) -> BacktestParts:
        parts = BacktestParts(
            self.read,
            report_exists,
            write_report,
            self.lines.append,
            self.stop,
            str(self.work / "backtest.db"),
            self.clock,
        )
        return replace(parts, **changes)

    def __call__(self, config: BacktestConfig, **changes: Any) -> BacktestExit:
        return run_backtest(config, self.parts(**changes))

    def final(
        self, configs: BacktestConfig | Sequence[BacktestConfig], grids: Any = OWN, **changes: Any
    ) -> BacktestExit:
        """`grids`: verilmezse (`OWN`) her yapılandırma kendi stratejisiyle (0042'nin küçük
        fixture'ları; spec 0043 plan Risk 5); `None` R-3 ızgarasıdır."""
        chosen = [configs] if isinstance(configs, BacktestConfig) else list(configs)
        if grids is OWN:
            grids = [[config.bot.turn.strategy] for config in chosen]
        return run_evaluation(chosen, self.parts(**changes), grids)

    @property
    def console(self) -> str:
        return "".join(line + "\n" for line in self.lines)

    def report(self, config: BacktestConfig) -> str:
        return Path(config.report_path).read_text(encoding="utf-8")


def force_pass(monkeypatch: Any) -> None:
    """Spec 0042 (plan Risk 3): küçük fixture'larda örneklem içinde 30 işlem olmaz; tam koşunun
    hesabını sınayan testler seçimi (ilk kombinasyon) ve hükmü ("geçti") sabitler. Kuralın kendisi
    `tests/backtest/test_evaluation.py` ve `tests/app/test_evaluation_run.py`'dedir."""
    from crytobot.app import _evaluation
    from crytobot.backtest import PASSED

    monkeypatch.setattr(_evaluation, "select_combination", lambda parts: 0 if parts else None)
    monkeypatch.setattr(_evaluation, "verdict", lambda _outside, _held: PASSED)


def report_lines(text: str, section: str) -> dict[str, str]:
    """Raporun bir bölümü: satır etiketi → değer."""
    body = text.split(f"== {section}", 1)[1].split("\n\n", 1)[0]
    found: dict[str, str] = {}
    for row in body.splitlines()[1:]:
        label, _, value = row.partition(": ")
        found[label] = value
    return found


# --- spec 0043 R-3…R-5: iki aralıklı son değerlendirme fixture'ı ---

FINAL_WARM = 200  # the R-3 grid's longest indicator (R-4)
FINAL_SPLIT, FINAL_HOLDOUT, FINAL_END = at(8), at(12), at(16)  # on 1h and 4h boundaries


def spaced(
    interval: timedelta, count: int, values: Callable[[int], Row]
) -> tuple[MarketCandle, ...]:
    """Isınma dahil `count` mum, `START - FINAL_WARM * interval`'dan aralıkla; `values(i)`."""
    first = START - FINAL_WARM * interval
    return tuple(candle(first + index * interval, values(index)) for index in range(count))


def final_history(
    interval: timedelta, values: Callable[[int], Row], pairs: Sequence[str] = (BTC,)
) -> HistoryData:
    """Dönem `START`..`FINAL_END`, ısınma 200 mum; her çift aynı seri."""
    periods = (FINAL_END - START) // interval
    rows = spaced(interval, FINAL_WARM + periods, values)
    return HistoryData(
        "binance",
        interval,
        START,
        FINAL_END,
        START - FINAL_WARM * interval,
        DOWNLOADED_AT,
        tuple(HistoryPair(pair, TICK, MARKET_RULES, rows) for pair in pairs),
    )


def final_setup(
    root: Path, values: Callable[[int], Row] = lambda _index: 10, **turn: Any
) -> tuple[BacktestConfig, tuple[BacktestConfig, ...]]:
    """`[backtest] final_data` ile yapılandırma ve `final_configs`'in iki kopyası (1h, 4h); veri
    dosyaları yazılır."""
    paths = {text: root / f"history-{text}.jsonl" for text in ("1h", "4h")}
    for text, hours in (("1h", 1), ("4h", 4)):
        write_history(paths[text], final_history(hours * HOUR, values))
    base = config(
        root,
        turn=settings((BTC,), **turn),
        count=FINAL_WARM,
        split_at=FINAL_SPLIT,
        holdout_at=FINAL_HOLDOUT,
    )
    base = replace(base, final_data=tuple((text, str(path)) for text, path in paths.items()))
    result = final_configs(base)
    assert result.configs is not None, result.message
    return base, result.configs
