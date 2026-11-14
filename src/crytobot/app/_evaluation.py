"""Son değerlendirme (spec 0042 R-1…R-6; plan Adım 5, Risk 10).

`run_evaluation` bir ya da daha çok backtest yapılandırmasını (aday: strateji ve zaman dilimi) aynı
risk ve maliyet koşullarıyla değerlendirir ve tek bir son değerlendirme raporu yazar. Sıra:

1. Koşullar (spec 0040 rapor koşulları ve `[backtest] spread`) bütün yapılandırmalarda eşit mi
   (R-6, AC-7); değilse `ayar uyuşmazlığı: <ad>`, tur atılmaz, rapor yazılmaz. Spec 0043 R-4:
   sonra mum sayısı her kombinasyonun `required_candles`'ına yeter mi; değilse
   `ayar geçersiz: market.candle_count`, tur atılmaz, rapor yazılmaz.
2. Rapor dosyası (ilk yapılandırmanın yolu) yok mu; sonra her yapılandırmanın veri dosyası ve üç
   dönemi — hiçbir tur atılmadan önce. Spec 0044 (plan Adım 6, Risk 3, 4): sonra her yapılandırma
   (sırasıyla), çift (dosya sırası) ve dönem (örneklem içi, örneklem dışı, saklı dönem) için dönemde
   kapanmış mum var mı; ilk eksik `veri eksik: <çift> <aralık> <dönem>` (R-3). Sonra veri
   dosyalarının bitişi aynı mı; değilse `veri dosyası uyumsuz: aralıkların bitişi farklı`.
   Her aralığın boşlukları (`period_gaps`, dosyanın dönemi) rapora geçer (R-2); boşluk koşuyu
   durdurmaz, mum eklenmez.
3. Her aday için ızgaranın her kombinasyonu yalnız örneklem içi turlarla koşar (sonraki mumlar
   tura verilmez); `select_combination` örneklem içi metriklerle seçer (R-2). Yalnız seçilen
   kombinasyon baştan sona bir kez daha koşar: örneklem dışı ve saklı dönem yalnız onun için
   hesaplanır; `verdict` hükmü verir (R-3).
4. Bütün koşular bitince gerçek saat bir kez okunur (üretim anı); her koşunun rapor koşulları
   ilkininkiyle yeniden karşılaştırılır (fark → rapor yazmadan ret, AC-7). `paper_candidate` (R-4),
   tek rapor (R-5: sınanan kombinasyon sayısı), parmak izi satırı (spec 0040 yolu).

Spec 0043 R-3, R-5: `grids` verilmezse her yapılandırma (aralık) için S0…S3'ün sabit ızgarası
(`CANDIDATE_GRIDS`) sınanır; aday "<ad> <aralık>"dır, yapılandırma sırasıyla, içinde S0…S3.
Ayardaki strateji ızgarayı değiştirmez (AC-7). `grids` verilirse (testler) her yapılandırma kendi
tek ızgarasıyla eşlenir (0042'deki gibi). Adayın adı ızgaranın ayar tipindendir. "örneklem içi
işlem yetersiz" satırı ızgaranın en yüksek işlem sayısını yazar (R-6). Her koşunun geçici deposu
`parts.store_path`'ten türetilir (ilki kendisi, sonrakiler `<yol>-<n>`); hepsi giriş noktasının
geçici dizinindedir.
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
from crytobot.app._grid import CANDIDATE_GRIDS
from crytobot.app._stage import bot_conditions
from crytobot.backtest import (
    CONDITIONS,
    Assessed,
    CandidateResult,
    DataGap,
    IntervalData,
    RunMetrics,
    final_report_text,
    not_enough_trades,
    paper_candidate,
    run_metrics,
    select_combination,
    verdict,
)
from crytobot.market_data import HistoryData, has_candle, period_gaps
from crytobot.strategy import Settings, required_candles


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


def _warm_enough(
    pairs: Sequence[tuple[int, Sequence[Settings]]], configs: Sequence[BacktestConfig]
) -> None:
    """R-4: her kombinasyon, koştuğu yapılandırmanın mum sayısıyla ısınır; değilse ret."""
    for index, grid in pairs:
        count = configs[index].bot.read.candle_count
        if any(count < required_candles(setting) for setting in grid):
            raise _refused("ayar geçersiz: market.candle_count")


def _periods(
    config: BacktestConfig, data: HistoryData
) -> tuple[tuple[str, datetime, datetime], ...]:
    return (
        ("örneklem içi", data.start, config.split_at),
        ("örneklem dışı", config.split_at, config.holdout_at),
        ("saklı dönem", config.holdout_at, data.end),
    )


def _every_period_has_candles(
    configs: Sequence[BacktestConfig], datas: Sequence[HistoryData]
) -> None:
    """Spec 0044 R-3, AC-2: bir çiftin bir aralıkta bir dönemde hiç kapanmış mumu yoksa ret."""
    for config, data in zip(configs, datas, strict=True):
        interval = _interval_text(data.candle_interval)
        for pair in data.pairs:
            for name, start, end in _periods(config, data):
                if not has_candle(pair, start, end):
                    raise _refused(f"veri eksik: {pair.pair} {interval} {name}")


def _same_end(datas: Sequence[HistoryData]) -> None:
    """Plan Risk 4 (R-1): saklı dönem iki aralıkta aynı anda biter."""
    if any(data.end != datas[0].end for data in datas):
        raise _refused("veri dosyası uyumsuz: aralıkların bitişi farklı")


def _data_section(data: HistoryData) -> IntervalData:
    """R-2: aralığın dönemi, saklı dönemin son mumu ve her çiftin boşlukları (dosya sırası)."""
    interval = data.candle_interval
    gaps = tuple(
        DataGap(gap.pair, gap.first, gap.last, gap.count)
        for pair in data.pairs
        for gap in period_gaps(pair, interval, data.start, data.end)
    )
    return IntervalData(_interval_text(interval), data.start, data.end, data.end - interval, gaps)


def _store(base: str, index: int) -> str:
    return base if index == 0 else f"{base}-{index}"  # `app` builds no path; same directory


def _combination(config: BacktestConfig, setting: Settings) -> BacktestConfig:
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
        self, config: BacktestConfig, data: HistoryData, grid: Sequence[Settings]
    ) -> tuple[CandidateResult, RunMetrics | None, BacktestConfig]:
        name = grid[0].name
        label = f"{name} {_interval_text(config.bot.turn_interval)}"
        _say(self.parts, f"aday: {label} kombinasyon={len(grid)}")
        moments = _moments(data, config.bot.turn_interval)
        inside = _in_sample(moments, config)
        tried = [_combination(config, setting) for setting in grid]
        parts = [self.simulate(each, data, inside, config.split_at).in_sample for each in tried]
        chosen = select_combination(parts)
        interval = _interval_text(config.bot.turn_interval)
        if chosen is None:
            decision = not_enough_trades(parts)
            _say(self.parts, f"aday {label}: {decision}")
            result = CandidateResult(name, interval, None, None, None, None, decision)
            return result, None, config
        selected = tried[chosen]
        metrics = self.simulate(selected, data, moments, None)
        assert metrics.holdout is not None
        decision = verdict(metrics.out_of_sample, metrics.holdout)
        _say(self.parts, f"aday {label}: {decision}")
        result = CandidateResult(
            name,
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
    pairs: Sequence[tuple[int, Sequence[Settings]]],
    parts: BacktestParts,
) -> BacktestExit:
    """`pairs`: (yapılandırmanın sırası, ızgara), değerlendirme sırasıyla."""
    if not configs or not pairs or any(not grid for _, grid in pairs):
        raise _refused("değerlendirilecek aday yok")
    _same_conditions(configs)
    _warm_enough(pairs, configs)
    first = configs[0]
    _report_free(first.report_path, parts)
    datas = [_history(config, parts) for config in configs]
    _every_period_has_candles(configs, datas)
    _same_end(datas)
    data_sections = [_data_section(data) for data in datas]
    combinations = sum(len(grid) for _, grid in pairs)
    _say(parts, f"son değerlendirme başladı: aday={len(pairs)} kombinasyon={combinations}")
    evaluation = _Evaluation(configs, parts)
    results: list[CandidateResult] = []
    full: list[tuple[RunMetrics, BacktestConfig, HistoryData] | None] = []
    for index, grid in pairs:
        config, data = configs[index], datas[index]
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
        report = final_report_text(facts, combinations, results, None, None, data=data_sections)
    else:
        chosen = full[paper]
        assert chosen is not None
        metrics, selected, data = chosen
        report = final_report_text(
            _facts(selected, data, generated_at),
            combinations,
            results,
            paper,
            metrics,
            data=data_sections,
        )
    return _publish(parts, first.report_path, report, evaluation.turns)


def _pairs(
    configs: Sequence[BacktestConfig], grids: Sequence[Sequence[Settings]] | None
) -> list[tuple[int, Sequence[Settings]]]:
    """R-3: verilmezse her yapılandırmaya S0…S3'ün ızgarası; verilirse sırayla birer ızgara."""
    if grids is None:
        return [(index, grid) for index in range(len(configs)) for grid in CANDIDATE_GRIDS]
    if len(grids) != len(configs):
        return []
    return list(enumerate(grids))


def run_evaluation(
    configs: Sequence[BacktestConfig],
    parts: BacktestParts,
    grids: Sequence[Sequence[Settings]] | None = None,
) -> BacktestExit:
    """Spec 0042, 0043: son değerlendirme; `grids` verilmezse her aralıkta R-3 ızgarası. Ret ve
    durma `run_backtest`'in yoluyla adıyla döner; ikinci durdurma isteği yeniden fırlar."""
    return guarded(parts, lambda: _evaluate(configs, _pairs(configs, grids), parts))
