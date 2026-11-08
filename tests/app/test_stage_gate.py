"""Spec 0028 AC-6 (R-4) ve AC-7 (R-5) aşama kapısı testleri (plan Adım 2)."""

from decimal import Decimal

from crytobot.app import (
    BotConfig,
    StageConfig,
    check_stage_gate,
    load_config,
)
from crytobot.backtest import (
    CandidateMetrics,
    ParsedReport,
    ReportRead,
    ReportReadProblem,
)
from tests.app.test_config import BASE, NOW


def make_bot_config() -> BotConfig:
    config = load_config(BASE, NOW).config
    assert config is not None
    return config


def make_stage_config(
    min_trades: int = 10, min_profit_factor: Decimal | None = None
) -> StageConfig:
    return StageConfig(
        report_path="report.txt",
        approved_by="Galip Badem",
        approved_at=NOW,
        min_trades=min_trades,
        min_profit_factor=min_profit_factor,
    )


def make_report(
    net: Decimal = Decimal("100"),
    max_drawdown: Decimal | None = Decimal("0.05"),
    trades: int = 20,
    profit_factor: Decimal | None = Decimal("2.0"),
    pairs: tuple[str, ...] = ("BTC/USDT", "ETH/USDT"),
    candle_interval: str = "1h",
    turn_interval: str = "1h",
    spread: Decimal = Decimal("0.0005"),
    strategy: dict[str, int | Decimal] | None = None,
) -> ParsedReport:
    if strategy is None:
        strategy = {
            "fast_period": 12,
            "slow_period": 26,
            "rsi_period": 14,
            "rsi_threshold": Decimal("70"),
            "atr_period": 14,
            "k": Decimal("2"),
            "r": Decimal("2"),
        }
    candidate = CandidateMetrics(
        net=net,
        return_ratio=Decimal("0.01"),
        max_drawdown=max_drawdown,
        trades=trades,
        profit_factor=profit_factor,
    )
    return ParsedReport(
        candle_interval=candle_interval,
        turn_interval=turn_interval,
        pairs=pairs,
        spread=spread,
        candidate=candidate,
        strategy=strategy,
    )


def test_metric_thresholds_refusal() -> None:
    """AC-6: Örneklem dışı metrik eşiklerinin yetersizliğinde ret (R-4)."""
    bot = make_bot_config()
    stage = make_stage_config(min_trades=10, min_profit_factor=Decimal("1.5"))

    # Mutlu yol: tüm metrikler eşikleri karşılıyor
    happy = check_stage_gate(stage, bot, make_report(), expected_spread=Decimal("0.0005"))
    assert happy.passed is True
    assert "geçerli" in happy.message

    # (a) Net kâr sıfır veya negatif
    res_zero = check_stage_gate(stage, bot, make_report(net=Decimal("0")))
    assert res_zero.passed is False
    assert "net kâr" in res_zero.message

    res_neg = check_stage_gate(stage, bot, make_report(net=Decimal("-50")))
    assert res_neg.passed is False
    assert "net kâr" in res_neg.message

    # (b) En büyük drawdown bot limitini (0.15) aşıyor
    res_dd_high = check_stage_gate(stage, bot, make_report(max_drawdown=Decimal("0.16")))
    assert res_dd_high.passed is False
    assert "max_drawdown" in res_dd_high.message

    # En büyük drawdown BR-6 tavanını (%25) aşıyor
    res_dd_ceiling = check_stage_gate(stage, bot, make_report(max_drawdown=Decimal("0.26")))
    assert res_dd_ceiling.passed is False
    assert "max_drawdown" in res_dd_ceiling.message

    # En büyük drawdown tanımsız (None)
    res_dd_none = check_stage_gate(stage, bot, make_report(max_drawdown=None))
    assert res_dd_none.passed is False
    assert "max_drawdown" in res_dd_none.message

    # (c) İşlem sayısı min_trades eşiğinden az veya sıfır
    res_trades_few = check_stage_gate(stage, bot, make_report(trades=9))
    assert res_trades_few.passed is False
    assert "min_trades" in res_trades_few.message

    res_trades_zero = check_stage_gate(stage, bot, make_report(trades=0))
    assert res_trades_zero.passed is False
    assert "min_trades" in res_trades_zero.message

    # (d) Kâr faktörü min_profit_factor eşiğinden az veya tanımsız
    res_pf_low = check_stage_gate(stage, bot, make_report(profit_factor=Decimal("1.49")))
    assert res_pf_low.passed is False
    assert "min_profit_factor" in res_pf_low.message

    res_pf_none = check_stage_gate(stage, bot, make_report(profit_factor=None))
    assert res_pf_none.passed is False
    assert "min_profit_factor" in res_pf_none.message

    # min_profit_factor ayarlanmamışsa düşük kâr faktörü veya None kabul edilir
    stage_no_pf = make_stage_config(min_trades=10, min_profit_factor=None)
    assert check_stage_gate(stage_no_pf, bot, make_report(profit_factor=Decimal("0.5"))).passed


def test_settings_mismatch_refusal() -> None:
    """AC-7: Ayar ve evren uyuşmazlığında ret (R-5)."""
    bot = make_bot_config()
    stage = make_stage_config()

    # 1. whitelist uyuşmazlığı
    res_wl_missing = check_stage_gate(stage, bot, make_report(pairs=("BTC/USDT",)))
    assert res_wl_missing.passed is False
    assert res_wl_missing.message == "ayar uyuşmazlığı: whitelist"

    res_wl_extra = check_stage_gate(
        stage, bot, make_report(pairs=("BTC/USDT", "ETH/USDT", "SOL/USDT"))
    )
    assert res_wl_extra.passed is False
    assert res_wl_extra.message == "ayar uyuşmazlığı: whitelist"

    # 2. candle_interval uyuşmazlığı
    res_candle = check_stage_gate(stage, bot, make_report(candle_interval="15m"))
    assert res_candle.passed is False
    assert res_candle.message == "ayar uyuşmazlığı: candle_interval"

    # 3. turn_interval uyuşmazlığı
    res_turn = check_stage_gate(stage, bot, make_report(turn_interval="4h"))
    assert res_turn.passed is False
    assert res_turn.message == "ayar uyuşmazlığı: turn_interval"

    # 4. spread uyuşmazlığı
    res_spread = check_stage_gate(
        stage,
        bot,
        make_report(spread=Decimal("0.0010")),
        expected_spread=Decimal("0.0005"),
    )
    assert res_spread.passed is False
    assert res_spread.message == "ayar uyuşmazlığı: spread"

    # 5. Strateji parametreleri uyuşmazlığı
    strategy_cases: list[tuple[str, int | Decimal]] = [
        ("fast_period", 10),
        ("slow_period", 30),
        ("rsi_period", 20),
        ("rsi_threshold", Decimal("80")),
        ("atr_period", 20),
        ("k", Decimal("3")),
        ("r", Decimal("3")),
    ]
    for param_name, different_val in strategy_cases:
        strat: dict[str, int | Decimal] = {
            "fast_period": 12,
            "slow_period": 26,
            "rsi_period": 14,
            "rsi_threshold": Decimal("70"),
            "atr_period": 14,
            "k": Decimal("2"),
            "r": Decimal("2"),
        }
        strat[param_name] = different_val
        res = check_stage_gate(stage, bot, make_report(strategy=strat))
        assert res.passed is False
        assert res.message == f"ayar uyuşmazlığı: {param_name}"


def test_report_read_problem_propagation() -> None:
    """ReportRead içindeki sorunların kapı sonucuna yansıması."""
    bot = make_bot_config()
    stage = make_stage_config()

    read_err = ReportRead(None, ReportReadProblem.MISSING, "rapor dosyası yok")
    res = check_stage_gate(stage, bot, read_err)
    assert res.passed is False
    assert "rapor dosyası yok" in res.message
