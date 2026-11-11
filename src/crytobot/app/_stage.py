"""Aşama onayı ve BR-10 başlatma kapısı (spec 0028 R-2, R-4, R-5; plan Adım 2).

`load_stage_config`: ayar dosyasındaki `[stage]` bölümünü denetler (dosya sırasıyla `report_path`,
spec 0040'ın `report_sha256`'sı, `approved_by`, `approved_at`, `min_trades`, `min_profit_factor`;
canlıda ayrıca `live_approved_*` ve spec 0038'in `paper_store_path`, `paper_min_days`,
`paper_min_trades`'i) ve bilinmeyen anahtarları reddeder.
`check_stage_gate`: spec 0040 CB-6/G-6 sırasıyla rapor okunabilirliği → parmak izi (CB-1) → onay
anı (CB-2) → rapor ve ayar eksikleri (CB-4) → metrik eşikleri → ayar uyuşmazlıkları (mevcutlar,
sonra rapor koşulları, CB-3); ilk karşılanmayan denetimin adıyla döner. Hiçbir denetim bilgi
eksikliği yüzünden atlanmaz. Sayılar değerle karşılaştırılır (`"0.001"` = `"0.0010"`, G-3).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, DecimalException

from crytobot.app._config import BotConfig, _Bad, _number
from crytobot.backtest import CONDITIONS, ReportRead
from crytobot.market_data import CANDLE_INTERVALS

_STAGE_SECTION = "stage"
_STAGE_KEYS = (
    "report_path",
    "report_sha256",
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
_HEX = frozenset("0123456789abcdef")
_STRATEGY = (
    "fast_period",
    "slow_period",
    "rsi_period",
    "rsi_threshold",
    "atr_period",
    "k",
    "r",
)


@dataclass(frozen=True, slots=True)
class StageConfig:
    """`[stage]` bölümünün doğrulanmış ayarları."""

    report_path: str
    report_sha256: str
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

    # 1b. report_sha256 (spec 0040 CB-1, G-2: case-insensitive, stored lower-case)
    name_sha = "stage.report_sha256"
    if "report_sha256" not in table:
        return StageConfigResult(None, name_sha, f"ayar eksik: {name_sha}")
    val_sha = table["report_sha256"]
    report_sha256 = val_sha.strip().lower() if type(val_sha) is str else ""
    if len(report_sha256) != 64 or not set(report_sha256) <= _HEX:
        return StageConfigResult(None, name_sha, f"ayar geçersiz: {name_sha}")

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
            report_sha256=report_sha256,
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


def _refused(message: str) -> StageGateResult:
    return StageGateResult(passed=False, message=message)


def bot_conditions(bot: BotConfig) -> dict[str, Decimal]:
    """Spec 0040 CB-3, G-5: çalışan ayarın etkin rapor koşulları, `CONDITIONS` adlarıyla."""
    limits = bot.turn.limits
    return {
        "fee": Decimal(bot.turn.fee),
        "slippage": Decimal(bot.turn.slippage),
        "per_trade_risk": limits.per_trade_risk,
        "daily_loss_limit": limits.daily_loss_limit,
        "max_drawdown": limits.max_drawdown,
        "max_open_positions": Decimal(limits.max_open_positions),
        "profit_cost_multiple": limits.profit_cost_multiple,
        "opening_balance": bot.opening_balance,
    }


def _backtest_spread(value: object) -> Decimal | None:
    """`[backtest] spread`'in değeri (`[backtest]` kuralıyla: tam sayı ya da düz ondalık metin;
    çağıranın verdiği `Decimal` de); geçersizse `None` (plan Risk 6)."""
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    try:
        number = Decimal(_number(value))
    except _Bad:
        return None
    return number if number.is_finite() else None


def check_stage_gate(
    stage: StageConfig,
    bot: BotConfig,
    report: ReportRead,
    backtest_spread: object,
    now: datetime,
) -> StageGateResult:
    """BR-10 aşama kapısı (spec 0028 R-4, R-5; spec 0040 CB-1…CB-4, CB-6).

    `backtest_spread`: çalışan ayarın `[backtest] spread` ham değeri, yoksa `None`. `now`: şimdiki
    an (UTC), onay anı sınırı için.
    """
    # 1. Rapor okunabilirliği (metinler aynı)
    if report.problem is not None:
        return _refused(report.detail or report.problem.value)
    assert report.data is not None
    rep = report.data

    # 2. Parmak izi (CB-1): ham baytlar onaylanan özetle aynı olmalı
    if report.sha256 is None or report.sha256.lower() != stage.report_sha256:
        return _refused("rapor onaylanandan farklı")

    # 3. Onay anı (CB-2): üretim anı ≤ onay ≤ şimdi; tolerans yok
    if rep.generated_at is None:
        return _refused("rapor eksik: üretim anı")
    if stage.approved_at < rep.generated_at:
        return _refused("onay rapordan önce")
    if stage.approved_at > now:
        return _refused("onay gelecekte")

    # 4. Eksik bilgi (CB-4): hiçbir denetim atlanmaz
    if rep.spread is None:
        return _refused("rapor eksik: spread")
    strategy = rep.strategy
    if strategy is None or any(name not in strategy for name in _STRATEGY):
        return _refused("rapor eksik: strateji")
    for name in CONDITIONS:
        if name not in rep.conditions:
            return _refused(f"rapor eksik: {name}")
    if backtest_spread is None:
        return _refused("ayar eksik: backtest.spread")
    expected_spread = _backtest_spread(backtest_spread)
    if expected_spread is None:
        return _refused("ayar geçersiz: backtest.spread")

    # 5. Metrik eşikleri (R-4, AC-6)
    cand = rep.candidate
    # (a) Net kâr sıfırdan büyük olmalı
    if cand.net <= Decimal(0):
        return _refused("eşik karşılanmadı: net kâr sıfırdan büyük olmalı")

    # (b) Drawdown sınırı
    dd_limit = min(bot.turn.limits.max_drawdown, Decimal("0.25"))
    if cand.max_drawdown is None or cand.max_drawdown > dd_limit:
        return _refused("eşik karşılanmadı: max_drawdown")

    # (c) İşlem sayısı
    if cand.trades < stage.min_trades or cand.trades == 0:
        return _refused("eşik karşılanmadı: min_trades")

    # (d) Kâr faktörü
    if stage.min_profit_factor is not None and (
        cand.profit_factor is None or cand.profit_factor < stage.min_profit_factor
    ):
        return _refused("eşik karşılanmadı: min_profit_factor")

    # 6. Ayar ve evren uyumu (R-5, AC-7), sonra rapor koşulları (CB-3)
    if set(rep.pairs) != set(bot.turn.whitelist):
        return _refused("ayar uyuşmazlığı: whitelist")
    if rep.candle_interval != CANDLE_INTERVALS.get(bot.turn.candle_interval):
        return _refused("ayar uyuşmazlığı: candle_interval")
    if rep.turn_interval != CANDLE_INTERVALS.get(bot.turn_interval):
        return _refused("ayar uyuşmazlığı: turn_interval")
    if rep.spread != expected_spread:
        return _refused("ayar uyuşmazlığı: spread")
    strat = bot.turn.strategy
    for name in _STRATEGY:
        if Decimal(str(strategy[name])) != Decimal(str(getattr(strat, name))):
            return _refused(f"ayar uyuşmazlığı: {name}")
    running = bot_conditions(bot)
    for name in CONDITIONS:
        if rep.conditions[name] != running[name]:
            return _refused(f"ayar uyuşmazlığı: {name}")

    return StageGateResult(passed=True, message="aşama onayı ve rapor geçerli")
