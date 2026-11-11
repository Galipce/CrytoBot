"""Aşama onayı ve BR-10 başlatma kapısı (spec 0028 R-2, R-4, R-5; plan Adım 2).

`load_stage_config`: ayar dosyasındaki `[stage]` bölümünü denetler (dosya sırasıyla `report_path`,
`approved_by`, `approved_at`, `min_trades`, `min_profit_factor`; canlıda ayrıca `live_approved_*` ve
spec 0038'in `paper_store_path`, `paper_min_days`, `paper_min_trades`'i) ve bilinmeyen anahtarları
reddeder.
`check_stage_gate`: metrik eşiklerini ve ayar uyumunu denetler.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, DecimalException

from crytobot.app._config import BotConfig
from crytobot.backtest import ParsedReport, ReportRead
from crytobot.market_data import CANDLE_INTERVALS

_STAGE_SECTION = "stage"
_STAGE_KEYS = (
    "report_path",
    "approved_by",
    "approved_at",
    "min_trades",
    "min_profit_factor",
    "live_approved_by",
    "live_approved_at",
    "paper_store_path",
    "paper_min_days",
    "paper_min_trades",
)
# spec 0038 CB-4: defaults and the floors below which a value is a setting error
PAPER_MIN_DAYS, PAPER_DAYS_FLOOR = 14, 7
PAPER_MIN_TRADES, PAPER_TRADES_FLOOR = 10, 5


@dataclass(frozen=True, slots=True)
class StageConfig:
    """`[stage]` bölümünün doğrulanmış ayarları."""

    report_path: str
    approved_by: str
    approved_at: datetime
    min_trades: int = 10
    min_profit_factor: Decimal | None = None
    live_approved_by: str | None = None
    live_approved_at: datetime | None = None
    paper_store_path: str | None = None
    paper_min_days: int = PAPER_MIN_DAYS
    paper_min_trades: int = PAPER_MIN_TRADES


@dataclass(frozen=True, slots=True)
class StageConfigResult:
    """`config` yalnız `[stage]` geçerliyse doludur; değilse `setting` ilk sorunlu ayardır."""

    config: StageConfig | None
    setting: str | None
    message: str


@dataclass(frozen=True, slots=True)
class StageGateResult:
    """Aşama kapısı denetim sonucu."""

    passed: bool
    message: str


def load_stage_config(document: object, mode: str = "paper") -> StageConfigResult:
    """Ayar dosyasından `[stage]` bölümünü yükler ve doğrular (R-2, AC-4, Spec 0033 R-4)."""
    if not isinstance(document, Mapping):
        return StageConfigResult(None, _STAGE_SECTION, f"ayar geçersiz: {_STAGE_SECTION}")
    table = document.get(_STAGE_SECTION)
    if table is None:
        return StageConfigResult(None, _STAGE_SECTION, f"ayar eksik: {_STAGE_SECTION}")
    if not isinstance(table, Mapping):
        return StageConfigResult(None, _STAGE_SECTION, f"ayar geçersiz: {_STAGE_SECTION}")

    # 1. report_path
    if "report_path" not in table:
        return StageConfigResult(None, "stage.report_path", "ayar eksik: stage.report_path")
    val_rp = table["report_path"]
    if type(val_rp) is not str or not val_rp.strip():
        return StageConfigResult(None, "stage.report_path", "ayar geçersiz: stage.report_path")
    report_path = val_rp.strip()

    # 2. approved_by
    if "approved_by" not in table:
        return StageConfigResult(None, "stage.approved_by", "ayar eksik: stage.approved_by")
    val_ab = table["approved_by"]
    if type(val_ab) is not str or not val_ab.strip():
        return StageConfigResult(None, "stage.approved_by", "ayar geçersiz: stage.approved_by")
    approved_by = val_ab.strip()

    # 3. approved_at
    if "approved_at" not in table:
        return StageConfigResult(None, "stage.approved_at", "ayar eksik: stage.approved_at")
    val_at = table["approved_at"]
    if type(val_at) is not str or not val_at.strip():
        return StageConfigResult(None, "stage.approved_at", "ayar geçersiz: stage.approved_at")
    try:
        dt = datetime.fromisoformat(val_at.strip())
    except (ValueError, TypeError):
        return StageConfigResult(None, "stage.approved_at", "ayar geçersiz: stage.approved_at")
    if dt.tzinfo is None:
        return StageConfigResult(None, "stage.approved_at", "ayar geçersiz: stage.approved_at")
    approved_at = dt.astimezone(UTC)

    # 4. min_trades (isteğe bağlı, varsayılan 10)
    min_trades = 10
    if "min_trades" in table:
        val_mt = table["min_trades"]
        if isinstance(val_mt, bool) or type(val_mt) is not int or val_mt <= 0:
            return StageConfigResult(None, "stage.min_trades", "ayar geçersiz: stage.min_trades")
        min_trades = val_mt

    # 5. min_profit_factor (isteğe bağlı)
    min_profit_factor: Decimal | None = None
    if "min_profit_factor" in table:
        val_pf = table["min_profit_factor"]
        if isinstance(val_pf, bool) or type(val_pf) not in (str, int, Decimal):
            return StageConfigResult(
                None, "stage.min_profit_factor", "ayar geçersiz: stage.min_profit_factor"
            )
        try:
            pf = Decimal(str(val_pf))
        except (DecimalException, ValueError):
            return StageConfigResult(
                None, "stage.min_profit_factor", "ayar geçersiz: stage.min_profit_factor"
            )
        if not pf.is_finite() or pf < 1:
            return StageConfigResult(
                None, "stage.min_profit_factor", "ayar geçersiz: stage.min_profit_factor"
            )
        min_profit_factor = pf

    # 6. live_approved_by (canlı modda zorunlu, paper modda isteğe bağlı)
    live_approved_by: str | None = None
    if mode == "live":
        if "live_approved_by" not in table:
            return StageConfigResult(
                None, "stage.live_approved_by", "ayar eksik: stage.live_approved_by"
            )
        val_lab = table["live_approved_by"]
        if type(val_lab) is not str or not val_lab.strip():
            return StageConfigResult(
                None, "stage.live_approved_by", "ayar geçersiz: stage.live_approved_by"
            )
        live_approved_by = val_lab.strip()
    elif "live_approved_by" in table:
        val_lab = table["live_approved_by"]
        if type(val_lab) is not str or not val_lab.strip():
            return StageConfigResult(
                None, "stage.live_approved_by", "ayar geçersiz: stage.live_approved_by"
            )
        live_approved_by = val_lab.strip()

    # 7. live_approved_at (canlı modda zorunlu, paper modda isteğe bağlı)
    live_approved_at: datetime | None = None
    if mode == "live":
        if "live_approved_at" not in table:
            return StageConfigResult(
                None, "stage.live_approved_at", "ayar eksik: stage.live_approved_at"
            )
        val_lat = table["live_approved_at"]
        if type(val_lat) is not str or not val_lat.strip():
            return StageConfigResult(
                None, "stage.live_approved_at", "ayar geçersiz: stage.live_approved_at"
            )
        try:
            dt_lat = datetime.fromisoformat(val_lat.strip())
        except (ValueError, TypeError):
            return StageConfigResult(
                None, "stage.live_approved_at", "ayar geçersiz: stage.live_approved_at"
            )
        if dt_lat.tzinfo is None:
            return StageConfigResult(
                None, "stage.live_approved_at", "ayar geçersiz: stage.live_approved_at"
            )
        live_approved_at = dt_lat.astimezone(UTC)
    elif "live_approved_at" in table:
        val_lat = table["live_approved_at"]
        if type(val_lat) is not str or not val_lat.strip():
            return StageConfigResult(
                None, "stage.live_approved_at", "ayar geçersiz: stage.live_approved_at"
            )
        try:
            dt_lat = datetime.fromisoformat(val_lat.strip())
        except (ValueError, TypeError):
            return StageConfigResult(
                None, "stage.live_approved_at", "ayar geçersiz: stage.live_approved_at"
            )
        if dt_lat.tzinfo is None:
            return StageConfigResult(
                None, "stage.live_approved_at", "ayar geçersiz: stage.live_approved_at"
            )
        live_approved_at = dt_lat.astimezone(UTC)

    # 8-10. Spec 0038: paper kanıtı ayarları yalnız canlıda aranır ve denetlenir (PB-1)
    paper_store_path: str | None = None
    paper_min_days, paper_min_trades = PAPER_MIN_DAYS, PAPER_MIN_TRADES
    if mode == "live":
        name = "stage.paper_store_path"
        if "paper_store_path" not in table:
            return StageConfigResult(None, name, f"ayar eksik: {name}")
        val_psp = table["paper_store_path"]
        if type(val_psp) is not str or not val_psp.strip():
            return StageConfigResult(None, name, f"ayar geçersiz: {name}")
        paper_store_path = val_psp.strip()
        for key, floor in (
            ("paper_min_days", PAPER_DAYS_FLOOR),
            ("paper_min_trades", PAPER_TRADES_FLOOR),
        ):
            if key not in table:
                continue
            value = table[key]
            if isinstance(value, bool) or type(value) is not int or value < floor:
                return StageConfigResult(None, f"stage.{key}", f"ayar geçersiz: stage.{key}")
            if key == "paper_min_days":
                paper_min_days = value
            else:
                paper_min_trades = value

    # Bilinmeyen anahtarlar
    for key in table:
        if key not in _STAGE_KEYS:
            return StageConfigResult(None, f"stage.{key}", f"bilinmeyen ayar: stage.{key}")

    return StageConfigResult(
        StageConfig(
            report_path=report_path,
            approved_by=approved_by,
            approved_at=approved_at,
            min_trades=min_trades,
            min_profit_factor=min_profit_factor,
            live_approved_by=live_approved_by,
            live_approved_at=live_approved_at,
            paper_store_path=paper_store_path,
            paper_min_days=paper_min_days,
            paper_min_trades=paper_min_trades,
        ),
        None,
        "ayarlar geçerli",
    )


def check_stage_gate(
    stage: StageConfig,
    bot: BotConfig,
    report: ParsedReport | ReportRead,
    expected_spread: Decimal | str | None = None,
) -> StageGateResult:
    """BR-10 aşama kapısı: metrik eşiklerini ve ayar uyumunu doğrular (R-4, R-5, AC-6, AC-7)."""
    if isinstance(report, ReportRead):
        if report.problem is not None:
            return StageGateResult(passed=False, message=report.detail or report.problem.value)
        assert report.data is not None
        rep = report.data
    else:
        rep = report

    # 1. Metrik eşikleri (R-4, AC-6)
    cand = rep.candidate
    # (a) Net kâr sıfırdan büyük olmalı
    if cand.net <= Decimal(0):
        return StageGateResult(
            passed=False, message="eşik karşılanmadı: net kâr sıfırdan büyük olmalı"
        )

    # (b) Drawdown sınırı
    dd_limit = min(bot.turn.limits.max_drawdown, Decimal("0.25"))
    if cand.max_drawdown is None or cand.max_drawdown > dd_limit:
        return StageGateResult(passed=False, message="eşik karşılanmadı: max_drawdown")

    # (c) İşlem sayısı
    if cand.trades < stage.min_trades or cand.trades == 0:
        return StageGateResult(passed=False, message="eşik karşılanmadı: min_trades")

    # (d) Kâr faktörü
    if stage.min_profit_factor is not None and (
        cand.profit_factor is None or cand.profit_factor < stage.min_profit_factor
    ):
        return StageGateResult(passed=False, message="eşik karşılanmadı: min_profit_factor")

    # 2. Ayar ve evren uyumu (R-5, AC-7)
    # whitelist
    if set(rep.pairs) != set(bot.turn.whitelist):
        return StageGateResult(passed=False, message="ayar uyuşmazlığı: whitelist")

    # candle_interval
    bot_candle_text = CANDLE_INTERVALS.get(bot.turn.candle_interval)
    if rep.candle_interval != bot_candle_text:
        return StageGateResult(passed=False, message="ayar uyuşmazlığı: candle_interval")

    # turn_interval
    bot_turn_text = CANDLE_INTERVALS.get(bot.turn_interval)
    if rep.turn_interval != bot_turn_text:
        return StageGateResult(passed=False, message="ayar uyuşmazlığı: turn_interval")

    # spread
    if expected_spread is not None:
        exp_spread = Decimal(str(expected_spread))
        if rep.spread != exp_spread:
            return StageGateResult(passed=False, message="ayar uyuşmazlığı: spread")

    # Strateji parametreleri
    if rep.strategy is not None:
        strat = bot.turn.strategy
        if "fast_period" in rep.strategy and rep.strategy["fast_period"] != strat.fast_period:
            return StageGateResult(passed=False, message="ayar uyuşmazlığı: fast_period")
        if "slow_period" in rep.strategy and rep.strategy["slow_period"] != strat.slow_period:
            return StageGateResult(passed=False, message="ayar uyuşmazlığı: slow_period")
        if "rsi_period" in rep.strategy and rep.strategy["rsi_period"] != strat.rsi_period:
            return StageGateResult(passed=False, message="ayar uyuşmazlığı: rsi_period")
        if "rsi_threshold" in rep.strategy and Decimal(
            str(rep.strategy["rsi_threshold"])
        ) != Decimal(str(strat.rsi_threshold)):
            return StageGateResult(passed=False, message="ayar uyuşmazlığı: rsi_threshold")
        if "atr_period" in rep.strategy and rep.strategy["atr_period"] != strat.atr_period:
            return StageGateResult(passed=False, message="ayar uyuşmazlığı: atr_period")
        if "k" in rep.strategy and Decimal(str(rep.strategy["k"])) != Decimal(str(strat.k)):
            return StageGateResult(passed=False, message="ayar uyuşmazlığı: k")
        if "r" in rep.strategy and Decimal(str(rep.strategy["r"])) != Decimal(str(strat.r)):
            return StageGateResult(passed=False, message="ayar uyuşmazlığı: r")

    return StageGateResult(passed=True, message="aşama onayı ve rapor geçerli")
