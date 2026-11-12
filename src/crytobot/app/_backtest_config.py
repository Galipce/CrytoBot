"""Backtest ayarları (spec 0025 R-2; plan Risk 6, 12).

`load_backtest_config` aynı ayar dosyasından botun ayarlarını (`load_config`) ve `[backtest]`
bölümünü denetler. Sıra: bot ayarları (tur aralığı mum aralığının katı olmalı) → bölüm →
`data_path`, `report_path`, `split_at`, `holdout_at`, `spread` anahtarlarının varlığı → aynı sırayla
değerleri →
bölümdeki bilinmeyen anahtar. İlk sorun adıyla söylenir, ham değer yazılmaz. Hiçbir ayarın
varsayılanı yoktur.

Denetimin anı gerçek saat değildir: sabit `CHECK_MOMENT` (defter ve risk denetimi bir an ister,
koşu kararlarına girmez). Ayrım anı UTC'dir (ofset 0) ve tur aralığı sınırındadır; dönemin içinde
olup olmadığı veri dosyası okununca denetlenir. Spec 0042 R-1 (plan Risk 1, 2): `split_at` örneklem
dışının, zorunlu `holdout_at` saklı dönemin başıdır; aynı kurallar ve `split_at < holdout_at`
(değilse `ayar geçersiz: backtest.holdout_at`); eksik anahtar proje kuralıyla `ayar eksik`.
Spread turun birimindedir (oran): `0 ≤ s < 1` ve turun kendi maliyet denetiminden geçer. Rapor
yolu veri dosyasının, deponun ya da kayıt dosyasının yolu olamaz; burada metinle, giriş noktasında
çözülmüş yolla denetlenir.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from crytobot.app._config import BotConfig, _Bad, _number, load_config
from crytobot.app._inputs import _PROBE_RULES, _costs_valid

SECTION = "backtest"
_KEYS = ("data_path", "report_path", "split_at", "holdout_at", "spread")
CHECK_MOMENT = datetime(2000, 1, 1, tzinfo=UTC)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class BacktestConfig:
    """Koşunun ayarları; `bot` botun bugünkü ayarlarıdır (tur, risk, strateji, aralıklar, kasa)."""

    data_path: str
    report_path: str
    split_at: datetime
    spread: Decimal
    bot: BotConfig
    holdout_at: datetime = field(kw_only=True)  # spec 0042 R-1: the start of the holdout period


@dataclass(frozen=True)
class BacktestConfigResult:
    """`config` yalnız her ayar geçerliyse doludur; değilse `setting` ilk sorunlu ayarın adıdır."""

    config: BacktestConfig | None
    setting: str | None
    message: str


class _Problem(Exception):
    def __init__(self, setting: str, message: str) -> None:
        super().__init__(setting)
        self.setting = setting
        self.message = message


def _missing(name: str) -> _Problem:
    return _Problem(name, f"ayar eksik: {name}")


def _invalid(name: str) -> _Problem:
    return _Problem(name, f"ayar geçersiz: {name}")


def on_boundary(moment: datetime, interval: timedelta) -> bool:
    """`moment` UTC'de `interval`'ın tam katı mı."""
    return (moment - _EPOCH) % interval == timedelta(0)


def _path(value: object, name: str, taken: tuple[str, ...]) -> str:
    if type(value) is not str or not value or value in taken:
        raise _invalid(name)
    return value


def _moment(value: object, bot: BotConfig, key: str) -> datetime:
    name = f"{SECTION}.{key}"
    if type(value) is not datetime or value.utcoffset() != timedelta(0):
        raise _invalid(name)
    moment = value.astimezone(UTC)
    if not on_boundary(moment, bot.turn_interval):
        raise _invalid(name)
    return moment


def _spread(value: object, bot: BotConfig) -> Decimal:
    name = f"{SECTION}.spread"
    try:
        spread = Decimal(_number(value))
    except _Bad:
        raise _invalid(name) from None
    if not (0 <= spread < 1):
        raise _invalid(name)
    if not _costs_valid(bot.turn.limits, _PROBE_RULES, 0, spread, 0, CHECK_MOMENT):
        raise _invalid(name)  # the turn's own check: digits, scale
    return spread


def _backtest(document: Mapping[object, object], bot: BotConfig) -> BacktestConfig:
    if bot.turn_interval % bot.read.candle_interval != timedelta(0):
        raise _invalid("bot.turn_interval")  # plan Risk 6: every turn opens a candle
    table = document.get(SECTION)
    if table is None:
        raise _missing(SECTION)
    if not isinstance(table, Mapping):
        raise _invalid(SECTION)
    for key in _KEYS:
        if key not in table:
            raise _missing(f"{SECTION}.{key}")
    bot_paths = (bot.store_path, bot.log_path)
    data_path = _path(table["data_path"], f"{SECTION}.data_path", bot_paths)
    report_path = _path(table["report_path"], f"{SECTION}.report_path", (data_path, *bot_paths))
    split_at = _moment(table["split_at"], bot, "split_at")
    holdout_at = _moment(table["holdout_at"], bot, "holdout_at")
    if not split_at < holdout_at:
        raise _invalid(f"{SECTION}.holdout_at")
    spread = _spread(table["spread"], bot)
    for key in table:
        if key not in _KEYS:
            raise _Problem(f"{SECTION}.{key}", f"bilinmeyen ayar: {SECTION}.{key}")
    return BacktestConfig(data_path, report_path, split_at, spread, bot, holdout_at=holdout_at)


def load_backtest_config(document: object) -> BacktestConfigResult:
    """R-2: botun ayarları ve `[backtest]` geçerliyse `BacktestConfig`; değilse ilk sorunlu ayarın
    adı. Dokunmaz, okumaz, saat çağırmaz."""
    bot = load_config(document, CHECK_MOMENT)
    if bot.config is None:
        return BacktestConfigResult(None, bot.setting, bot.message)
    assert isinstance(document, Mapping)  # load_config refuses anything else
    try:
        config = _backtest(document, bot.config)
    except _Problem as problem:
        return BacktestConfigResult(None, problem.setting, problem.message)
    return BacktestConfigResult(config, None, "ayarlar geçerli")
