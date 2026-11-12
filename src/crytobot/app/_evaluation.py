"""Son değerlendirme (spec 0042 R-1…R-6; plan Adım 5, Risk 10).

`run_evaluation` bir ya da daha çok backtest yapılandırmasını (aday: strateji ve zaman dilimi) aynı
risk ve maliyet koşullarıyla değerlendirir ve tek bir son değerlendirme raporu yazar. Sıra:

1. Koşullar (spec 0040 rapor koşulları ve `[backtest] spread`) bütün yapılandırmalarda eşit mi
   (R-6, AC-7); değilse `ayar uyuşmazlığı: <ad>`, tur atılmaz, rapor yazılmaz.
2. Rapor dosyası (ilk yapılandırmanın yolu) yok mu; sonra her yapılandırmanın veri dosyası ve üç
   dönemi — hiçbir tur atılmadan önce.
3. Her aday için ızgaranın her kombinasyonu yalnız örneklem içi turlarla koşar (sonraki mumlar
   tura verilmez); `select_combination` örneklem içi metriklerle seçer (R-2). Yalnız seçilen
   kombinasyon baştan sona bir kez daha koşar: örneklem dışı ve saklı dönem yalnız onun için
   hesaplanır; `verdict` hükmü verir (R-3).
4. Bütün koşular bitince gerçek saat bir kez okunur (üretim anı); her koşunun rapor koşulları
   ilkininkiyle yeniden karşılaştırılır (fark → rapor yazmadan ret, AC-7). `paper_candidate` (R-4),
   tek rapor (R-5: sınanan kombinasyon sayısı), parmak izi satırı (spec 0040 yolu).

Izgara (`grids`) bu spec'te aday başına tek kombinasyondur: yapılandırmanın kendi `[strategy]`
ayarı (0043 doldurur). Her koşunun geçici deposu `parts.store_path`'ten türetilir (ilki kendisi,
sonrakiler `<yol>-<n>`); hepsi giriş noktasının geçici dizinindedir.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from crytobot.app._backtest import (
    _NOT_WRITTEN,
    BacktestExit,
    BacktestParts,
    _facts,
    _history,
    _in_sample,
    _interval_text,
    _moments,
    _publish,
    _refused,
    _report_free,
    _say,
    _simulate,
    _started,
    guarded,
    strategy_setting,
)
from crytobot.app._backtest_config import BacktestConfig
from crytobot.app._stage import STRATEGY_NAME, bot_conditions
from crytobot.backtest import (
    CONDITIONS,
    NOT_ENOUGH_TRADES,
    Assessed,
    CandidateResult,
    RunMetrics,
    final_report_text,
    paper_candidate,
    run_metrics,
    select_combination,
    verdict,
)
from crytobot.market_data import HistoryData
from crytobot.strategy import StrategySettings


@dataclass(frozen=True)
class _Ran:
    """Bir koşunun yapılandırması ve verisi: koşulların sonda yeniden karşılaştırılması için."""

    config: BacktestConfig
    data: HistoryData


def _conditions(config: BacktestConfig) -> tuple[tuple[str, Decimal], ...]:
    running = bot_conditions(config.bot)
    return (*((name, running[name]) for name in CONDITIONS), ("spread", config.spread))


def _same_conditions(configs: Sequence[BacktestConfig]) -> None:
    """R-6, AC-7: bütün adaylar aynı risk ve maliyet koşullarıyla; ilk farkın adıyla ret."""
    expected = _conditions(configs[0])
    for config in configs[1:]:
        for (name, value), (_, other) in zip(expected, _conditions(config), strict=True):
            if value != other:
                raise _refused(f"ayar uyuşmazlığı: {name}")


def _store(base: str, index: int) -> str:
    return base if index == 0 else f"{base}-{index}"  # `app` builds no path; same directory


def _combination(config: BacktestConfig, setting: StrategySettings) -> BacktestConfig:
    """Izgaranın bir kombinasyonu: yalnız strateji ayarı değişir (R-6: risk ve maliyet aynı)."""
    turn = replace(config.bot.turn, strategy=setting)
    return replace(config, bot=replace(config.bot, turn=turn))


class _Evaluation:
    def __init__(self, configs: Sequence[BacktestConfig], parts: BacktestParts) -> None:
        self.configs = configs
        self.parts = parts
        self.runs: list[_Ran] = []
        self.turns = 0

    def simulate(
        self,
        config: BacktestConfig,
        data: HistoryData,
        moments: Sequence[datetime],
        until: datetime | None,
    ) -> RunMetrics:
        _started(self.parts, data, moments, until)
        store = _store(self.parts.store_path, len(self.runs))
        self.runs.append(_Ran(config, data))
        records = _simulate(config, self.parts, data, moments, store)
        self.turns += len(moments)
        bot = config.bot
        pairs = tuple(bot.turn.whitelist)
        return run_metrics(bot.opening_balance, records, config.split_at, pairs, config.holdout_at)

    def candidate(
        self, config: BacktestConfig, data: HistoryData, grid: Sequence[StrategySettings]
    ) -> tuple[CandidateResult, RunMetrics | None, BacktestConfig]:
        label = f"{STRATEGY_NAME} {_interval_text(config.bot.turn_interval)}"
        _say(self.parts, f"aday: {label} kombinasyon={len(grid)}")
        moments = _moments(data, config.bot.turn_interval)
        inside = _in_sample(moments, config)
        tried = [_combination(config, setting) for setting in grid]
        parts = [self.simulate(each, data, inside, config.split_at).in_sample for each in tried]
        chosen = select_combination(parts)
        interval = _interval_text(config.bot.turn_interval)
        if chosen is None:
            _say(self.parts, f"aday {label}: {NOT_ENOUGH_TRADES}")
            result = CandidateResult(
                STRATEGY_NAME, interval, None, None, None, None, NOT_ENOUGH_TRADES
            )
            return result, None, config
        selected = tried[chosen]
        metrics = self.simulate(selected, data, moments, None)
        assert metrics.holdout is not None
        decision = verdict(metrics.out_of_sample, metrics.holdout)
        _say(self.parts, f"aday {label}: {decision}")
        result = CandidateResult(
            STRATEGY_NAME,
            interval,
            strategy_setting(selected.bot.turn.strategy),
            metrics.in_sample,
            metrics.out_of_sample,
            metrics.holdout,
            decision,
        )
        return result, metrics, selected

    def drifted(self) -> str | None:
        """AC-7: koşulardan birinin rapor koşulları ilkinden farklıysa farkın adı."""
        expected = _conditions(self.configs[0])
        for ran in self.runs:
            for (name, value), (_, other) in zip(expected, _conditions(ran.config), strict=True):
                if value != other:
                    return name
        return None


def _evaluate(
    configs: Sequence[BacktestConfig],
    grids: Sequence[Sequence[StrategySettings]],
    parts: BacktestParts,
) -> BacktestExit:
    if not configs or len(grids) != len(configs) or any(not grid for grid in grids):
        raise _refused("değerlendirilecek aday yok")
    _same_conditions(configs)
    first = configs[0]
    _report_free(first.report_path, parts)
    datas = [_history(config, parts) for config in configs]
    combinations = sum(len(grid) for grid in grids)
    _say(parts, f"son değerlendirme başladı: aday={len(configs)} kombinasyon={combinations}")
    evaluation = _Evaluation(configs, parts)
    results: list[CandidateResult] = []
    full: list[tuple[RunMetrics, BacktestConfig, HistoryData] | None] = []
    for config, data, grid in zip(configs, datas, grids, strict=True):
        result, metrics, selected = evaluation.candidate(config, data, grid)
        results.append(result)
        full.append(None if metrics is None else (metrics, selected, data))
    drift = evaluation.drifted()
    if drift is not None:
        raise _refused(f"ayar uyuşmazlığı: {drift}", _NOT_WRITTEN)
    assessed = [
        Assessed(item[0].in_sample, item[0].out_of_sample, result.verdict)
        for result, item in zip(results, full, strict=True)
        if item is not None
    ]
    positions = [index for index, item in enumerate(full) if item is not None]
    best = paper_candidate(assessed)
    paper = None if best is None else positions[best]
    generated_at = parts.clock()
    if paper is None:
        facts = _facts(first, datas[0], generated_at)
        report = final_report_text(facts, combinations, results, None, None)
    else:
        chosen = full[paper]
        assert chosen is not None
        metrics, selected, data = chosen
        report = final_report_text(
            _facts(selected, data, generated_at), combinations, results, paper, metrics
        )
    return _publish(parts, first.report_path, report, evaluation.turns)


def run_evaluation(
    configs: Sequence[BacktestConfig],
    parts: BacktestParts,
    grids: Sequence[Sequence[StrategySettings]] | None = None,
) -> BacktestExit:
    """Spec 0042: son değerlendirme; `grids` verilmezse her aday yalnız kendi strateji ayarıyla.
    Ret ve durma `run_backtest`'in yoluyla adıyla döner; ikinci durdurma isteği yeniden fırlar."""
    chosen = [[config.bot.turn.strategy] for config in configs] if grids is None else grids
    return guarded(parts, lambda: _evaluate(configs, chosen, parts))
