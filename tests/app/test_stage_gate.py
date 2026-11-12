"""Spec 0028 AC-6 (R-4) ve AC-7 (R-5) aşama kapısı testleri (plan Adım 2); spec 0040 CB-1…CB-4,
CB-6 (G-6 sırası) ve PB-1 (mevcut eşik ve uyuşmazlık testleri, assert'ler aynen).

Spec 0042 AC-8 (plan Risk 7, 8): rapor fixture'ları son değerlendirme biçiminde ve strateji adı
`S0` taşır; ad farklıysa `ayar uyuşmazlığı: strateji`, varsayılan rapor `rapor son değerlendirme
değil`."""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crytobot.app import (
    BotConfig,
    StageConfig,
    StageGateResult,
    check_stage_gate,
    load_config,
    load_stage_config,
)
from crytobot.backtest import (
    CONDITIONS,
    PASSED,
    CandidateMetrics,
    CandidateResult,
    ParsedReport,
    ReportFacts,
    ReportRead,
    ReportReadProblem,
    final_report_text,
    read_report,
    report_fingerprint,
    report_text,
    run_metrics,
)
from tests.app.test_config import BASE, NOW

SHA = "0123456789abcdef" * 4
GENERATED = NOW - timedelta(days=1)
LATER = NOW + timedelta(hours=1)  # "now" of the gate: after the approval (NOW)
SPREAD = "0.0005"
STRATEGY: dict[str, int | Decimal] = {
    "fast_period": 12,
    "slow_period": 26,
    "rsi_period": 14,
    "rsi_threshold": Decimal("70"),
    "atr_period": 14,
    "k": Decimal("2"),
    "r": Decimal("2"),
}
# the BASE config's effective report conditions (tests.app.test_config)
CONDITION_VALUES: dict[str, Decimal] = {
    "fee": Decimal("0.001"),
    "slippage": Decimal("0.001"),
    "per_trade_risk": Decimal("0.01"),
    "daily_loss_limit": Decimal("0.03"),
    "max_drawdown": Decimal("0.15"),
    "max_open_positions": Decimal(5),
    "profit_cost_multiple": Decimal("2"),
    "opening_balance": Decimal("10000"),
}


def make_bot_config() -> BotConfig:
    config = load_config(BASE, NOW).config
    assert config is not None
    return config


def make_stage_config(
    min_trades: int = 10, min_profit_factor: Decimal | None = None
) -> StageConfig:
    return StageConfig(
        report_path="report.txt",
        report_sha256=SHA,
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
    spread: Decimal | None = Decimal("0.0005"),
    strategy: dict[str, int | Decimal] | None = None,
    generated_at: datetime | None = GENERATED,
    conditions: dict[str, Decimal] | None = None,
    sha256: str | None = SHA,
    strategy_name: str | None = "S0",
) -> ReportRead:
    candidate = CandidateMetrics(
        net=net,
        return_ratio=Decimal("0.01"),
        max_drawdown=max_drawdown,
        trades=trades,
        profit_factor=profit_factor,
    )
    data = ParsedReport(
        candle_interval=candle_interval,
        turn_interval=turn_interval,
        pairs=pairs,
        spread=spread,
        candidate=candidate,
        strategy=dict(STRATEGY) if strategy is None else strategy,
        generated_at=generated_at,
        conditions=dict(CONDITION_VALUES) if conditions is None else conditions,
        strategy_name=strategy_name,
    )
    return ReportRead(data, None, sha256=sha256)


def gate(
    stage: StageConfig,
    bot: BotConfig,
    report: ReportRead,
    spread: object = SPREAD,
    now: datetime = LATER,
) -> StageGateResult:
    return check_stage_gate(stage, bot, report, spread, now)


def test_metric_thresholds_refusal() -> None:
    """AC-6: Örneklem dışı metrik eşiklerinin yetersizliğinde ret (R-4)."""
    bot = make_bot_config()
    stage = make_stage_config(min_trades=10, min_profit_factor=Decimal("1.5"))

    # Mutlu yol: tüm metrikler eşikleri karşılıyor
    happy = gate(stage, bot, make_report(), spread=Decimal("0.0005"))
    assert happy.passed is True
    assert "geçerli" in happy.message

    # (a) Net kâr sıfır veya negatif
    res_zero = gate(stage, bot, make_report(net=Decimal("0")))
    assert res_zero.passed is False
    assert "net kâr" in res_zero.message

    res_neg = gate(stage, bot, make_report(net=Decimal("-50")))
    assert res_neg.passed is False
    assert "net kâr" in res_neg.message

    # (b) En büyük drawdown bot limitini (0.15) aşıyor
    res_dd_high = gate(stage, bot, make_report(max_drawdown=Decimal("0.16")))
    assert res_dd_high.passed is False
    assert "max_drawdown" in res_dd_high.message

    # En büyük drawdown BR-6 tavanını (%25) aşıyor
    res_dd_ceiling = gate(stage, bot, make_report(max_drawdown=Decimal("0.26")))
    assert res_dd_ceiling.passed is False
    assert "max_drawdown" in res_dd_ceiling.message

    # En büyük drawdown tanımsız (None)
    res_dd_none = gate(stage, bot, make_report(max_drawdown=None))
    assert res_dd_none.passed is False
    assert "max_drawdown" in res_dd_none.message

    # (c) İşlem sayısı min_trades eşiğinden az veya sıfır
    res_trades_few = gate(stage, bot, make_report(trades=9))
    assert res_trades_few.passed is False
    assert "min_trades" in res_trades_few.message

    res_trades_zero = gate(stage, bot, make_report(trades=0))
    assert res_trades_zero.passed is False
    assert "min_trades" in res_trades_zero.message

    # (d) Kâr faktörü min_profit_factor eşiğinden az veya tanımsız
    res_pf_low = gate(stage, bot, make_report(profit_factor=Decimal("1.49")))
    assert res_pf_low.passed is False
    assert "min_profit_factor" in res_pf_low.message

    res_pf_none = gate(stage, bot, make_report(profit_factor=None))
    assert res_pf_none.passed is False
    assert "min_profit_factor" in res_pf_none.message

    # min_profit_factor ayarlanmamışsa düşük kâr faktörü veya None kabul edilir
    stage_no_pf = make_stage_config(min_trades=10, min_profit_factor=None)
    assert gate(stage_no_pf, bot, make_report(profit_factor=Decimal("0.5"))).passed


def test_settings_mismatch_refusal() -> None:
    """AC-7: Ayar ve evren uyuşmazlığında ret (R-5)."""
    bot = make_bot_config()
    stage = make_stage_config()

    # 1. whitelist uyuşmazlığı
    res_wl_missing = gate(stage, bot, make_report(pairs=("BTC/USDT",)))
    assert res_wl_missing.passed is False
    assert res_wl_missing.message == "ayar uyuşmazlığı: whitelist"

    res_wl_extra = gate(stage, bot, make_report(pairs=("BTC/USDT", "ETH/USDT", "SOL/USDT")))
    assert res_wl_extra.passed is False
    assert res_wl_extra.message == "ayar uyuşmazlığı: whitelist"

    # 2. candle_interval uyuşmazlığı
    res_candle = gate(stage, bot, make_report(candle_interval="15m"))
    assert res_candle.passed is False
    assert res_candle.message == "ayar uyuşmazlığı: candle_interval"

    # 3. turn_interval uyuşmazlığı
    res_turn = gate(stage, bot, make_report(turn_interval="4h"))
    assert res_turn.passed is False
    assert res_turn.message == "ayar uyuşmazlığı: turn_interval"

    # 4. spread uyuşmazlığı
    res_spread = gate(
        stage,
        bot,
        make_report(spread=Decimal("0.0010")),
        spread=Decimal("0.0005"),
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
        res = gate(stage, bot, make_report(strategy=strat))
        assert res.passed is False
        assert res.message == f"ayar uyuşmazlığı: {param_name}"


def test_report_read_problem_propagation() -> None:
    """ReportRead içindeki sorunların kapı sonucuna yansıması."""
    bot = make_bot_config()
    stage = make_stage_config()

    read_err = ReportRead(None, ReportReadProblem.MISSING, "rapor dosyası yok")
    res = gate(stage, bot, read_err)
    assert res.passed is False
    assert "rapor dosyası yok" in res.message


# --- spec 0040 -------------------------------------------------------------------------------


def _refusal(report: ReportRead, **changes: Any) -> str:
    stage = replace(make_stage_config(), **changes.pop("stage", {}))
    result = gate(stage, make_bot_config(), report, **changes)
    assert result.passed is False
    return result.message


def test_happy_gate_with_every_fact() -> None:
    assert gate(make_stage_config(), make_bot_config(), make_report()).passed is True


def _facts() -> ReportFacts:
    return ReportFacts(
        NOW - timedelta(days=10),
        NOW - timedelta(days=2),
        "1h",
        "1h",
        NOW - timedelta(days=5),
        ("BTC/USDT", "ETH/USDT"),
        NOW - timedelta(days=2),
        200,
        Decimal(SPREAD),
        STRATEGY,
        generated_at=GENERATED,
        **{name: value for name, value in CONDITION_VALUES.items()},  # type: ignore[arg-type]
        strategy_name="S0",
        holdout_at=NOW - timedelta(days=3),
    )


def _real_report(path: Path) -> str:
    """Diskte gerçek bir son değerlendirme raporu (ayrışır); eşiklere bakılmaz, parmak izi önce
    gelir."""
    facts = _facts()
    metrics = run_metrics(Decimal(10000), (), facts.split_at, facts.pairs, facts.holdout_at)
    assert facts.strategy is not None
    result = CandidateResult(
        "S0",
        "1h",
        facts.strategy,
        metrics.in_sample,
        metrics.out_of_sample,
        metrics.holdout,
        PASSED,
    )
    text = final_report_text(facts, 1, [result], 0, metrics, data=())
    path.write_bytes(text.encode("utf-8"))
    return text


def test_changed_report_byte_refused(tmp_path: Path) -> None:
    """CB-1: onaydan sonra tek bayt değişen ya da yeniden üretilen rapor geçmez."""
    path = tmp_path / "rapor.txt"
    text = _real_report(path)
    stage = replace(make_stage_config(), report_sha256=report_fingerprint(text))
    bot = make_bot_config()
    original = gate(stage, bot, read_report(path))
    assert original.message != "rapor onaylanandan farklı"  # it passes the fingerprint step

    raw = bytearray(path.read_bytes())
    raw[-2] = ord("X") if raw[-2] != ord("X") else ord("Y")
    path.write_bytes(bytes(raw))
    assert gate(stage, bot, read_report(path)).message == "rapor onaylanandan farklı"

    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))  # same text, other line ends
    assert gate(stage, bot, read_report(path)).message == "rapor onaylanandan farklı"

    assert _refusal(make_report(sha256=None)) == "rapor onaylanandan farklı"
    assert _refusal(make_report(sha256="f" * 64)) == "rapor onaylanandan farklı"


def test_fingerprint_case_insensitive(tmp_path: Path) -> None:
    """CB-1, G-2: ayardaki parmak izi büyük harfle de aynı rapora bağlanır."""
    path = tmp_path / "rapor.txt"
    text = _real_report(path)
    document = {
        "stage": {
            "report_path": str(path),
            "report_sha256": report_fingerprint(text).upper(),
            "approved_by": "Galip Badem",
            "approved_at": NOW.isoformat(),
        }
    }
    stage = load_stage_config(document).config
    assert stage is not None
    result = gate(stage, make_bot_config(), read_report(path))
    assert result.message != "rapor onaylanandan farklı"
    upper = replace(make_report(), sha256=SHA.upper())
    assert gate(make_stage_config(), make_bot_config(), upper).passed is True


def test_approval_before_report_refused() -> None:
    """CB-2: onay üretim anından önce."""
    early = make_report(generated_at=NOW + timedelta(microseconds=1))
    assert _refusal(early) == "onay rapordan önce"
    assert _refusal(make_report(generated_at=None)) == "rapor eksik: üretim anı"


def test_approval_in_future_refused() -> None:
    """CB-2: onay şimdiki andan sonra; tolerans yok."""
    assert _refusal(make_report(), now=NOW - timedelta(microseconds=1)) == "onay gelecekte"


def test_approval_equal_to_generation_accepted() -> None:
    """CB-2: eşitlik kabul (üretim anı = onay = şimdi)."""
    report = make_report(generated_at=NOW)
    assert gate(make_stage_config(), make_bot_config(), report, now=NOW).passed is True


def test_missing_report_fact_named() -> None:
    """CB-4: eksik rapor bilgisi adıyla; hiçbir denetim atlanmaz."""
    assert _refusal(make_report(spread=None)) == "rapor eksik: spread"
    assert _refusal(make_report(strategy={})) == "rapor eksik: strateji"
    for name in STRATEGY:
        partial = {key: value for key, value in STRATEGY.items() if key != name}
        assert _refusal(make_report(strategy=partial)) == "rapor eksik: strateji"
    for name in CONDITIONS:
        conditions = {key: v for key, v in CONDITION_VALUES.items() if key != name}
        assert _refusal(make_report(conditions=conditions)) == f"rapor eksik: {name}"
    data = make_report().data
    assert data is not None
    missing_strategy = ReportRead(
        replace(data, strategy=None),
        None,
        sha256=SHA,
    )
    assert _refusal(missing_strategy) == "rapor eksik: strateji"


@pytest.mark.parametrize("bad", ["", "abc", "0.0005 ", "1e-3", "NaN", 0.0005, True, [1]])
def test_backtest_spread_invalid_refused(bad: object) -> None:
    """Plan Risk 6: geçersiz `[backtest] spread` sessizce atlanmaz."""
    assert _refusal(make_report(), spread=bad) == "ayar geçersiz: backtest.spread"


def test_backtest_spread_missing_refused() -> None:
    """CB-4: çalışan ayarda `[backtest] spread` yoksa ret; rapor eksikleri önce gelir."""
    assert _refusal(make_report(), spread=None) == "ayar eksik: backtest.spread"
    assert _refusal(make_report(spread=None), spread=None) == "rapor eksik: spread"
    assert gate(make_stage_config(), make_bot_config(), make_report(), spread=0).message == (
        "ayar uyuşmazlığı: spread"  # an integer is a valid value: 0 ≠ 0.0005
    )
    assert _refusal(make_report(), spread=Decimal("NaN")) == "ayar geçersiz: backtest.spread"


def test_condition_mismatch_named() -> None:
    """CB-3: her rapor koşulu çalışan ayarla karşılaştırılır; ilk fark adıyla."""
    for name in CONDITIONS:
        conditions = dict(CONDITION_VALUES)
        conditions[name] = conditions[name] + Decimal("0.0001")
        assert _refusal(make_report(conditions=conditions)) == f"ayar uyuşmazlığı: {name}"
    both = dict(CONDITION_VALUES, fee=Decimal("0.002"), opening_balance=Decimal(1))
    assert _refusal(make_report(conditions=both)) == "ayar uyuşmazlığı: fee"


@given(
    name=st.sampled_from(CONDITIONS),
    zeros=st.integers(min_value=0, max_value=12),
    delta=st.decimals(
        min_value=Decimal("-1"), max_value=Decimal("1"), allow_nan=False, places=6
    ).filter(lambda d: d != 0),
)
def test_condition_equal_by_value(name: str, zeros: int, delta: Decimal) -> None:
    """CB-3, G-3: ölçek değişimi (`0.001` = `0.0010`) geçer; farklı değer reddedilir."""
    value = CONDITION_VALUES[name]
    exponent = value.as_tuple().exponent
    assert isinstance(exponent, int)
    rescaled = dict(CONDITION_VALUES)
    rescaled[name] = value.quantize(Decimal(1).scaleb(min(exponent, 0) - zeros))
    assert rescaled[name] == value and (zeros == 0 or str(rescaled[name]) != str(value))
    bot = make_bot_config()
    assert gate(make_stage_config(), bot, make_report(conditions=rescaled)).passed is True
    changed = dict(CONDITION_VALUES)
    changed[name] = changed[name] + delta
    result = gate(make_stage_config(), bot, make_report(conditions=changed))
    assert result.message == f"ayar uyuşmazlığı: {name}"


def test_check_order_first_failure_only() -> None:
    """CB-6, G-6: ret satırı yalnız ilk karşılanmayan denetimi adlandırır; sıra sabittir."""
    unreadable = ReportRead(None, ReportReadProblem.CORRUPT, "başlık bilgileri eksik", SHA)
    assert _refusal(unreadable) == "başlık bilgileri eksik"

    failures: dict[str, Any] = {
        "sha256": "f" * 64,
        "generated_at": NOW + timedelta(hours=1),
        "spread": None,
        "net": Decimal(0),
        "pairs": ("BTC/USDT",),
        "conditions": dict(CONDITION_VALUES, fee=Decimal("0.5")),
    }
    expected = [
        "rapor onaylanandan farklı",
        "onay rapordan önce",
        "rapor eksik: spread",
        "eşik karşılanmadı: net kâr sıfırdan büyük olmalı",
        "ayar uyuşmazlığı: whitelist",
        "ayar uyuşmazlığı: fee",
    ]
    for step, message in enumerate(expected):
        remaining = dict(list(failures.items())[step:])
        assert _refusal(make_report(**remaining)) == message
    # without the report gaps the setting gap comes before the thresholds
    assert _refusal(make_report(net=Decimal(0)), spread=None) == "ayar eksik: backtest.spread"
    # the strategy mismatch comes after the existing ones and before the conditions
    strategy = dict(STRATEGY, k=Decimal(3))
    conditions = dict(CONDITION_VALUES, fee=Decimal("0.5"))
    report = make_report(strategy=strategy, conditions=conditions)
    assert _refusal(report) == "ayar uyuşmazlığı: k"
    assert _refusal(make_report(conditions=conditions, candle_interval="4h")) == (
        "ayar uyuşmazlığı: candle_interval"
    )


# --- spec 0042 AC-8 (R-7; plan Risk 7) ---


def test_strategy_name_mismatch_refused() -> None:
    """Ad farklıysa `ayar uyuşmazlığı: strateji`, parametrelerden önce; adsız rapor da farklıdır."""
    assert _refusal(make_report(strategy_name="S1")) == "ayar uyuşmazlığı: strateji"
    assert _refusal(make_report(strategy_name=None)) == "ayar uyuşmazlığı: strateji"
    strategy = dict(STRATEGY, k=Decimal(3))
    assert _refusal(make_report(strategy_name="S1", strategy=strategy)) == (
        "ayar uyuşmazlığı: strateji"
    )
    # a parameter difference keeps its own name (plan Risk 7)
    assert _refusal(make_report(strategy=strategy)) == "ayar uyuşmazlığı: k"
    # the existing setting mismatches still come first; the conditions after
    assert _refusal(make_report(strategy_name="S1", candle_interval="4h")) == (
        "ayar uyuşmazlığı: candle_interval"
    )
    conditions = dict(CONDITION_VALUES, fee=Decimal("0.5"))
    assert _refusal(make_report(strategy_name="S1", conditions=conditions)) == (
        "ayar uyuşmazlığı: strateji"
    )


def test_non_final_report_refused(tmp_path: Path) -> None:
    """Varsayılan (son değerlendirme olmayan) rapor, parmak izi doğru olsa da kapıdan geçmez."""
    path = tmp_path / "rapor.txt"
    facts = _facts()
    text = report_text(facts, run_metrics(Decimal(10000), (), facts.split_at, facts.pairs))
    path.write_bytes(text.encode("utf-8"))
    stage = replace(make_stage_config(), report_sha256=report_fingerprint(text))
    result = gate(stage, make_bot_config(), read_report(path))
    assert (result.passed, result.message) == (False, "rapor son değerlendirme değil")
    not_final = ReportRead(None, ReportReadProblem.NOT_FINAL, "rapor son değerlendirme değil", SHA)
    assert _refusal(not_final) == "rapor son değerlendirme değil"


def test_final_report_without_candidate_refused(tmp_path: Path) -> None:
    path = tmp_path / "rapor.txt"
    facts = _facts()
    text = final_report_text(facts, 1, [], None, None, data=())
    path.write_bytes(text.encode("utf-8"))
    stage = replace(make_stage_config(), report_sha256=report_fingerprint(text))
    result = gate(stage, make_bot_config(), read_report(path))
    assert (result.passed, result.message) == (False, "rapor aday işareti taşımıyor")


def test_real_final_report_passes_to_the_thresholds(tmp_path: Path) -> None:
    """Gerçek bir son değerlendirme raporu adı ve okunabilirliğiyle geçer; ret eşiktedir."""
    path = tmp_path / "rapor.txt"
    text = _real_report(path)
    stage = replace(make_stage_config(), report_sha256=report_fingerprint(text))
    result = gate(stage, make_bot_config(), read_report(path))
    assert result.message == "eşik karşılanmadı: net kâr sıfırdan büyük olmalı"


# --- spec 0043 AC-9 (R-1, R-5; plan Risk 7, A-1) ---

CANDIDATE_STRATEGIES: dict[str, dict[str, Any]] = {
    "S1": {**BASE["strategy"], "trend_period": 150},
    "S2": {"breakout_period": 55, "atr_period": 14, "k": "3", "r": "2"},
    "S3": {"rsi_period": 14, "rsi_threshold": "35", "atr_period": 14, "k": "1.5", "r": "2"},
}


def candidate_bot(name: str, interval: str = "1h") -> BotConfig:
    document: dict[str, Any] = {section: dict(values) for section, values in BASE.items()}
    document["strategy"] = {"name": name, **CANDIDATE_STRATEGIES[name]}
    for section, key in (("bot", "turn_interval"), ("market", "candle_interval")):
        document[section][key] = interval
    config = load_config(document, NOW).config
    assert config is not None
    return config


def candidate_report(name: str, interval: str = "1h", **changes: Any) -> ReportRead:
    """Çalışan adayın parametreleriyle rapor; `changes` parametreleri değiştirir."""
    values = {
        key: int(value) if isinstance(value, int) else Decimal(value)
        for key, value in CANDIDATE_STRATEGIES[name].items()
    }
    return make_report(
        strategy={**values, **changes},
        strategy_name=name,
        candle_interval=interval,
        turn_interval=interval,
    )


def candidate_refusal(bot: BotConfig, report: ReportRead) -> str:
    result = gate(make_stage_config(), bot, report)
    assert not result.passed
    return result.message


@pytest.mark.parametrize("name", sorted(CANDIDATE_STRATEGIES))
def test_candidate_matching_report_passes(name: str) -> None:
    for interval in ("1h", "4h"):
        result = gate(
            make_stage_config(), candidate_bot(name, interval), candidate_report(name, interval)
        )
        assert (result.passed, result.message) == (True, "aşama onayı ve rapor geçerli")


@pytest.mark.parametrize(
    ("name", "parameter", "value"),
    [
        ("S1", "trend_period", 100),  # L
        ("S1", "fast_period", 9),
        ("S2", "breakout_period", 20),  # N
        ("S2", "k", Decimal(2)),
        ("S3", "rsi_threshold", Decimal(30)),  # oversold threshold
        ("S3", "k", Decimal(2)),
        ("S3", "atr_period", 13),
    ],
)
def test_candidate_parameter_mismatch(name: str, parameter: str, value: object) -> None:
    """AC-9: rapordaki adayın herhangi bir parametresi çalışan ayardan farklıysa adıyla ret."""
    report = candidate_report(name, "1h", **{parameter: value})
    assert candidate_refusal(candidate_bot(name), report) == f"ayar uyuşmazlığı: {parameter}"


def test_candidate_parameters_compared_in_definition_order() -> None:
    report = candidate_report("S1", k=Decimal(3), trend_period=200)
    assert candidate_refusal(candidate_bot("S1"), report) == "ayar uyuşmazlığı: k"


def test_candidate_interval_mismatch() -> None:
    """AC-9, R-5: adayın aralığı (rapordaki mum aralığı) çalışan mum aralığından farklıysa ret;
    çift listesi bugünkü gibi önce."""
    bot = candidate_bot("S2", "1h")
    assert (
        candidate_refusal(bot, candidate_report("S2", "4h")) == "ayar uyuşmazlığı: candle_interval"
    )
    other_pairs = replace(candidate_report("S2", "4h").data, pairs=("BTC/USDT",))  # type: ignore[type-var]
    assert candidate_refusal(bot, ReportRead(other_pairs, None, sha256=SHA)) == (
        "ayar uyuşmazlığı: whitelist"
    )


def test_candidate_name_and_missing_parameters() -> None:
    """Plan A-1: rapor çalışan adayın adını taşıyıp parametresini eksik bırakırsa `rapor eksik:
    strateji`; başka adayın raporu `ayar uyuşmazlığı: strateji`."""
    s1 = candidate_bot("S1")
    incomplete = make_report(strategy=dict(STRATEGY), strategy_name="S1")  # no trend_period
    assert candidate_refusal(s1, incomplete) == "rapor eksik: strateji"
    assert candidate_refusal(s1, candidate_report("S3")) == "ayar uyuşmazlığı: strateji"
    assert candidate_refusal(s1, make_report()) == "ayar uyuşmazlığı: strateji"  # an S0 report
    assert candidate_refusal(make_bot_config(), candidate_report("S1")) == (
        "ayar uyuşmazlığı: strateji"
    )
    assert candidate_refusal(s1, make_report(strategy=None, strategy_name="S9")) == (
        "ayar uyuşmazlığı: strateji"
    )


def test_whitelist_different_pair_refused() -> None:
    """Spec 0044 AC-3 (R-4): aynı sayıda ama farklı çift → ret (eksik ve fazla: yukarıda)."""
    result = gate(
        make_stage_config(), make_bot_config(), make_report(pairs=("BTC/USDT", "SOL/USDT"))
    )
    assert result.passed is False
    assert result.message == "ayar uyuşmazlığı: whitelist"


def test_whitelist_same_set_any_order_passes() -> None:
    """Spec 0044 AC-3 (R-4): aynı liste, sıra farkı dahil, geçer."""
    bot = make_bot_config()
    assert tuple(bot.turn.whitelist) == ("BTC/USDT", "ETH/USDT")
    result = gate(make_stage_config(), bot, make_report(pairs=("ETH/USDT", "BTC/USDT")))
    assert result.passed is True, result.message
