"""İndikatör kalibrasyonunun koşusu (spec 0045 R-2, R-6, R-7, R-11; plan Risk 3, 11, 12).

`load_calibration_config` ayar dosyasının `[calibration]` bölümünü denetler: beş veri yolu
(`data_15m` … `data_1d`), ölçüm maliyetleri (`fee`, `slippage`, `spread`), 1. aşamanın çıktıları
(`report_path`, `settings_path`, `records_path`), son ölçümün çıktıları (`final_report_path`,
`final_records_path`); hiçbirinin varsayılanı yoktur, bilinmeyen anahtar reddedilir, yollar
birbirinden farklıdır. Son ölçümün onayı (`settings_sha256`, `approved_by`, `approved_at`) yalnız
`--final`'da zorunludur. İlk sorun adıyla, ham değer yazılmadan söylenir.

`run_calibration` (1. aşama) ve `run_calibration_final` (son ölçüm) aynı sırayı izler, hiçbir
ölçüm yapılmadan önce:

1. Çıktı dosyaları yok mu (var olanın üzerine yazılmaz).
2. Son ölçümde: ayar seti dosyası var mı, baytlarının SHA-256'sı onaydakine eşit mi, dosya
   bozuk mu, onay anı ayar setinin üretim anından önce ya da şimdiden sonra mı, maliyetler ve veri
   dosyalarının parmak izi ayar setindekiyle aynı mı (R-6, R-7: sonuca bakılarak değişmez).
3. Her veri dosyası (aralık sırasıyla): okunur, aralığı, sürümü (hacim, sürüm 2) ve beş çifti
   denetlenir; her çift x dönemde mum
   var mı (AC-7). Dosyanın dönemi ölçüm dönemlerini kapsamalıdır (indirme 2023-01-01'den; önceki
   mumlar ısınmadır). Boşluklar rapora geçer, doldurulmaz.

Sonra ölçüm (`crytobot.calibration`), gerçek saat bir kez okunur (üretim anı) ve dosyalar yazılır:
1. aşamada ayar seti, rapor, kayıtlar; son ölçümde rapor ve kayıtlar. Parmak izleri konsola yazılır.
Gerçek etkiler `CalibrationParts` ile gelir: `app` dosya açmaz, saat çağırmaz, ağa çıkmaz. Durdurma
isteğine her aralıktan önce bakılır. Ret, durma ve beklenmeyen hata adıyla döner, rapor yazılmaz.
"""

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum

from crytobot.analysis import Candle
from crytobot.app._config import _Bad, _number
from crytobot.app._loop import ForcedStop, StopRequest
from crytobot.app._session import AppError
from crytobot.calibration import (
    INTERVALS,
    PAIRS,
    PERIODS,
    Costs,
    DataFacts,
    GapRow,
    IntervalData,
    Measured,
    PairSeries,
    Periods,
    ReportFacts,
    SettingsProblem,
    SettingsSet,
    final_stage,
    read_settings,
    records_text,
    report_text,
    settings_text,
    stage_one,
)
from crytobot.market_data import (
    CANDLE_INTERVALS,
    HistoryData,
    HistoryRead,
    HistoryReadProblem,
    has_candle,
    period_gaps,
)

SECTION = "calibration"
_EVENT = "kalibrasyon"
_DATA_KEYS = tuple(f"data_{interval}" for interval in INTERVALS)
_COST_KEYS = ("fee", "slippage", "spread")
_OUTPUT_KEYS = (
    "report_path",
    "settings_path",
    "records_path",
    "final_report_path",
    "final_records_path",
)
_APPROVAL_KEYS = ("settings_sha256", "approved_by", "approved_at")
_HEX = frozenset("0123456789abcdef")
_INTERVALS_BY_TEXT = {text: interval for interval, text in CANDLE_INTERVALS.items()}
_READ_REFUSALS = {
    HistoryReadProblem.MISSING: "veri dosyası yok",
    HistoryReadProblem.UNREADABLE: "veri dosyası okunamıyor",
    HistoryReadProblem.CORRUPT: "veri dosyası bozuk",
    HistoryReadProblem.INCOMPLETE: "veri dosyası tamamlanmamış",
    HistoryReadProblem.UNTRUSTED: "güvenilmeyen veri",
}


@dataclass(frozen=True)
class Approval:
    settings_sha256: str
    approved_by: str
    approved_at: datetime


@dataclass(frozen=True)
class CalibrationConfig:
    """`data`: (aralık, yol) `INTERVALS` sırasıyla; `approval` yalnız verildiyse."""

    data: tuple[tuple[str, str], ...]
    costs: Costs
    report_path: str
    settings_path: str
    records_path: str
    final_report_path: str
    final_records_path: str
    approval: Approval | None


@dataclass(frozen=True)
class CalibrationConfigResult:
    config: CalibrationConfig | None
    setting: str | None
    message: str


class _Problem(Exception):
    def __init__(self, setting: str, message: str) -> None:
        super().__init__(setting)
        self.setting = setting
        self.message = message


def _name(key: str) -> str:
    return f"{SECTION}.{key}"


def _missing(key: str) -> _Problem:
    return _Problem(_name(key), f"ayar eksik: {_name(key)}")


def _invalid(key: str) -> _Problem:
    return _Problem(_name(key), f"ayar geçersiz: {_name(key)}")


def _path(table: Mapping[object, object], key: str, taken: list[str]) -> str:
    value = table[key]
    if type(value) is not str or not value.strip() or value in taken:
        raise _invalid(key)
    taken.append(value)
    return value


def _cost(table: Mapping[object, object], key: str) -> Decimal:
    try:
        value = Decimal(_number(table[key]))
    except _Bad:
        raise _invalid(key) from None
    if not (0 <= value < 1):
        raise _invalid(key)
    return value


def _approval(table: Mapping[object, object]) -> Approval | None:
    if not any(key in table for key in _APPROVAL_KEYS):
        return None
    for key in _APPROVAL_KEYS:
        if key not in table:
            raise _missing(key)
    sha = table["settings_sha256"]
    digest = sha.strip().lower() if type(sha) is str else ""
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise _invalid("settings_sha256")
    by = table["approved_by"]
    if type(by) is not str or not by.strip():
        raise _invalid("approved_by")
    moment = table["approved_at"]
    try:
        parsed = datetime.fromisoformat(moment.strip()) if type(moment) is str else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.utcoffset() is None:
        raise _invalid("approved_at")
    return Approval(digest, by.strip(), parsed.astimezone(UTC))


def _section(document: Mapping[object, object]) -> CalibrationConfig:
    table = document.get(SECTION)
    if table is None:
        raise _Problem(SECTION, f"ayar eksik: {SECTION}")
    if not isinstance(table, Mapping):
        raise _Problem(SECTION, f"ayar geçersiz: {SECTION}")
    for key in (*_DATA_KEYS, *_COST_KEYS, *_OUTPUT_KEYS):
        if key not in table:
            raise _missing(key)
    taken: list[str] = []
    data = tuple(
        (interval, _path(table, key, taken))
        for interval, key in zip(INTERVALS, _DATA_KEYS, strict=True)
    )
    fee, slippage, spread = (_cost(table, key) for key in _COST_KEYS)
    if fee + slippage >= 1:
        raise _invalid("slippage")
    report, settings, records, final_report, final_records = (
        _path(table, key, taken) for key in _OUTPUT_KEYS
    )
    approval = _approval(table)
    for key in table:
        if key not in (*_DATA_KEYS, *_COST_KEYS, *_OUTPUT_KEYS, *_APPROVAL_KEYS):
            raise _Problem(_name(str(key)), f"bilinmeyen ayar: {_name(str(key))}")
    return CalibrationConfig(
        data,
        Costs(fee, slippage, spread),
        report,
        settings,
        records,
        final_report,
        final_records,
        approval,
    )


def load_calibration_config(document: object) -> CalibrationConfigResult:
    """`[calibration]` geçerliyse `CalibrationConfig`; değilse ilk sorunlu ayarın adı."""
    if not isinstance(document, Mapping):
        return CalibrationConfigResult(None, SECTION, f"ayar geçersiz: {SECTION}")
    try:
        config = _section(document)
    except _Problem as problem:
        return CalibrationConfigResult(None, problem.setting, problem.message)
    return CalibrationConfigResult(config, None, "ayarlar geçerli")


class CalibrationOutcome(Enum):
    COMPLETED = "completed"
    REFUSED = "refused"
    STOPPED = "stopped"
    NOT_WRITTEN = "not_written"


@dataclass(frozen=True)
class CalibrationExit:
    outcome: CalibrationOutcome
    message: str


@dataclass(frozen=True)
class CalibrationParts:
    """Gerçek etkiler: veri dosyası okuması, dosyanın SHA-256'sı (okunamazsa `None`), ayar seti
    baytları (yoksa `None`), çıktı var mı, çıktı yazıcısı (üzerine yazmaz), konsol, durdurma
    isteği, saat (UTC)."""

    read: Callable[[str], HistoryRead]
    digest: Callable[[str], str | None]
    read_bytes: Callable[[str], bytes | None]
    exists: Callable[[str], bool]
    write_file: Callable[[str, str], bool]
    write: Callable[[str], None]
    stop: StopRequest
    clock: Callable[[], datetime]


class _Halt(AppError):
    def __init__(self, outcome: CalibrationOutcome, message: str) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.message = message


def _refused(message: str) -> _Halt:
    return _Halt(CalibrationOutcome.REFUSED, message)


def _say(parts: CalibrationParts, text: str) -> None:
    parts.write(f"{_EVENT} {text}")


def _outputs_free(paths: tuple[str, ...], parts: CalibrationParts) -> None:
    for path in paths:
        if parts.exists(path):
            raise _refused(f"dosya var: {path}; üzerine yazılmaz")


@dataclass(frozen=True)
class _Inputs:
    data: tuple[IntervalData, ...]
    facts: tuple[DataFacts, ...]
    gaps: tuple[GapRow, ...]


def _series(data: HistoryData, interval: timedelta) -> dict[str, PairSeries]:
    found: dict[str, PairSeries] = {}
    for pair in data.pairs:
        if pair.pair not in PAIRS:
            continue
        assert pair.volumes is not None  # version 2: checked by the caller
        candles = tuple(
            Candle(c.open_time, float(c.open), float(c.high), float(c.low), float(c.close))
            for c in pair.candles
        )
        volumes = tuple(float(volume) for volume in pair.volumes)
        found[pair.pair] = PairSeries(pair.pair, interval, candles, volumes)
    return found


def _read_one(
    interval: str, path: str, parts: CalibrationParts, periods: Periods
) -> tuple[IntervalData, DataFacts, list[GapRow]]:
    read = parts.read(path)
    if read.problem is not None or read.data is None:
        text = _READ_REFUSALS.get(read.problem, "veri dosyası okunamıyor")  # type: ignore[arg-type]
        detail = ", ".join(item for item in (read.pair, read.detail) if item)
        raise _refused(f"{text}{f' ({detail})' if detail else ''}: {path}")
    data = read.data
    step = _INTERVALS_BY_TEXT[interval]
    if data.candle_interval != step:
        raise _refused(f"veri dosyası uyumsuz: mum aralığı {interval} değil: {path}")
    pairs = {pair.pair: pair for pair in data.pairs}
    missing = [pair for pair in PAIRS if pair not in pairs]
    if missing:
        raise _refused(f"veri dosyası uyumsuz: çift yok ({', '.join(missing)}): {path}")
    if any(pairs[pair].volumes is None for pair in PAIRS):
        raise _refused(f"veri dosyası uyumsuz: hacim yok (sürüm 1): {path}")
    first = min(period.start for period in periods)
    last = max(period.end for period in periods)
    if not (data.start <= first and last <= data.end):
        raise _refused(f"veri dosyası uyumsuz: dönemleri kapsamıyor: {path}")
    gaps: list[GapRow] = []
    for period in periods:
        for pair in period.pairs:
            if not has_candle(pairs[pair], period.start, period.end):
                raise _refused(f"veri eksik: {pair} {interval} {period.name}")
            for gap in period_gaps(pairs[pair], step, period.start, period.end):
                gaps.append(GapRow(interval, period.name, pair, gap.first, gap.last, gap.count))
    digest = parts.digest(path)
    if digest is None:
        raise _refused(f"veri dosyası okunamıyor: {path}")
    facts = DataFacts(interval, path, digest, data.downloaded_at)
    return IntervalData(interval, _series(data, step)), facts, gaps


def _inputs(config: CalibrationConfig, parts: CalibrationParts, periods: Periods) -> _Inputs:
    data: list[IntervalData] = []
    facts: list[DataFacts] = []
    gaps: list[GapRow] = []
    for interval, path in config.data:
        item, fact, found = _read_one(interval, path, parts, periods)
        data.append(item)
        facts.append(fact)
        gaps.extend(found)
    return _Inputs(tuple(data), tuple(facts), tuple(gaps))


def _progress(parts: CalibrationParts) -> Callable[[str], None]:
    def progress(text: str) -> None:
        if parts.stop.requested:
            raise _Halt(CalibrationOutcome.STOPPED, "durdurma isteği")
        _say(parts, text)

    return progress


def _write(parts: CalibrationParts, label: str, path: str, text: str) -> None:
    if not parts.write_file(path, text):
        raise _Halt(CalibrationOutcome.NOT_WRITTEN, f"{label} yazılamadı: {path}")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    _say(parts, f"{label} parmak izi: {digest} ({path})")


def _publish(
    parts: CalibrationParts,
    measured: Measured,
    facts: ReportFacts,
    report_path: str,
    records_path: str,
) -> None:
    _write(parts, "rapor", report_path, report_text(measured, facts))
    records = records_text(measured, final=facts.final, generated_at=facts.generated_at)
    _write(parts, "kayıt", records_path, records)


def _stage_one(config: CalibrationConfig, parts: CalibrationParts, periods: Periods) -> str:
    _outputs_free((config.settings_path, config.report_path, config.records_path), parts)
    inputs = _inputs(config, parts, periods)
    _say(parts, "başladı: 1. aşama (ayarlama ve çapraz sınama)")
    measured = stage_one(inputs.data, config.costs, _progress(parts), periods_of=periods)
    generated_at = parts.clock()
    digests = tuple((fact.interval, fact.sha256) for fact in inputs.facts)
    settings = settings_text(measured.choices, generated_at, config.costs, digests)
    _write(parts, "ayar seti", config.settings_path, settings)
    sha = hashlib.sha256(settings.encode("utf-8")).hexdigest()
    facts = ReportFacts(False, generated_at, config.costs, inputs.facts, inputs.gaps, sha)
    _publish(parts, measured, facts, config.report_path, config.records_path)
    return f"tamam: ayar seti {config.settings_path}"


def _approved_settings(
    config: CalibrationConfig, parts: CalibrationParts, now: datetime
) -> SettingsSet:
    approval = config.approval
    if approval is None:
        raise _refused(f"ayar eksik: {_name('settings_sha256')}")
    raw = parts.read_bytes(config.settings_path)
    if raw is None:
        raise _refused(f"ayar seti dosyası yok: {config.settings_path}")
    if hashlib.sha256(raw).hexdigest() != approval.settings_sha256:
        raise _refused("ayar seti parmak izi onayla tutmuyor (calibration.settings_sha256)")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    parsed = read_settings(text)
    if isinstance(parsed, SettingsProblem):
        raise _refused(f"ayar seti dosyası bozuk ({parsed.detail}): {config.settings_path}")
    if not (parsed.generated_at <= approval.approved_at <= now):
        raise _refused(
            "onay anı geçersiz: ayar setinin üretim anından önce ya da şimdiden sonra "
            "(calibration.approved_at)"
        )
    if parsed.costs != config.costs:
        raise _refused("maliyet ayar setinden farklı (calibration.fee/slippage/spread)")
    return parsed


def _final(config: CalibrationConfig, parts: CalibrationParts, periods: Periods) -> str:
    _outputs_free((config.final_report_path, config.final_records_path), parts)
    approval = config.approval
    settings = _approved_settings(config, parts, parts.clock())
    assert approval is not None  # checked above
    inputs = _inputs(config, parts, periods)
    expected = dict(settings.data)
    for fact in inputs.facts:
        if expected.get(fact.interval) != fact.sha256:
            raise _refused(f"veri dosyası ayar setinden farklı: {fact.interval} {fact.path}")
    _say(parts, "başladı: son ölçüm (üç dönem, hüküm)")
    measured = final_stage(
        inputs.data, config.costs, settings.choices, _progress(parts), periods_of=periods
    )
    facts = ReportFacts(
        True,
        parts.clock(),
        config.costs,
        inputs.facts,
        inputs.gaps,
        approval.settings_sha256,
        approval.approved_by,
        approval.approved_at,
    )
    _publish(parts, measured, facts, config.final_report_path, config.final_records_path)
    usable = sum(item.usable for _, _, item in measured.verdicts)
    _say(parts, f"hüküm: {usable}/{len(measured.verdicts)} indikatör x aralık kullanılabilir")
    return f"tamam: rapor dosyası {config.final_report_path}"


def _guarded(parts: CalibrationParts, body: Callable[[], str]) -> CalibrationExit:
    try:
        message = body()
    except _Halt as halt:
        verb = "reddedildi" if halt.outcome is CalibrationOutcome.REFUSED else "durdu"
        _say(parts, f"{verb}: {halt.message}")
        return CalibrationExit(halt.outcome, halt.message)
    except ForcedStop:
        _say(parts, "durdu: zorla durdurma")
        raise
    except Exception as error:  # the type only; the text may carry anything
        message = f"beklenmeyen hata: {type(error).__name__}"
        _say(parts, f"durdu: {message}")
        return CalibrationExit(CalibrationOutcome.STOPPED, message)
    _say(parts, message)
    return CalibrationExit(CalibrationOutcome.COMPLETED, message)


def run_calibration(
    config: CalibrationConfig, parts: CalibrationParts, *, periods: Periods = PERIODS
) -> CalibrationExit:
    """1. aşama; `periods` yalnız testlerde verilir (spec'in dönemleri varsayılandır)."""
    return _guarded(parts, lambda: _stage_one(config, parts, periods))


def run_calibration_final(
    config: CalibrationConfig, parts: CalibrationParts, *, periods: Periods = PERIODS
) -> CalibrationExit:
    """Son ölçüm: onaylı ayar setiyle, bir kez; `periods` yalnız testlerde verilir."""
    return _guarded(parts, lambda: _final(config, parts, periods))
