"""Geçmiş olay örnek kütüphanesinin iki koşusu (spec 0048 R-3, R-9, R-10, G-5, G-8; plan Risk 1, 2,
9, 10, A-1).

`load_events_config` `crytobot-events.toml`'un `[events]` bölümünü denetler: üç yol
(`price_store_path`, `report_path`, `library_path`; zorunlu, birbirinden farklı), `request_gap_s`
(tam sayı, varsayılan 1, en az 1), `model_cutoff` (zorunlu, varsayılansız: `YYYY-MM-DD` metni ya da
TOML tarihi; o günün UTC gece yarısı), `fee`/`slippage`/`spread` (0045'in kuralı: düz ondalık metin
ya da tam sayı, `0 ≤ değer < 1`, `fee + slippage < 1`; varsayılanlar 0045 örneğindeki 0.001, 0.001,
0.0005). Bilinmeyen bölüm ya da anahtar reddedilir; ilk sorun adıyla, ham değer yazılmadan söylenir.

`run_events_download`: kaynak kayıtlar (giriş noktası okur ve etiketler) → örnekler → coin başına
birleşik fiyat aralıkları → `market_data`'nın indirme adımı. `run_events_measure`: çıktılar yok mu
(üzerine yazılmaz) → kaynak kayıtlar → fiyat verisi (ağsız) → her gerekli aralık indirilmiş mi
(değilse ret: sessiz boşluk yok) → ölçüm → kütüphane ve rapor. Gerçek etkiler `*Parts` ile gelir:
`app` dosya açmaz, saat çağırmaz, ağa çıkmaz. Ret ve beklenmeyen hata adıyla döner.
"""

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum

from crytobot.analysis import Candle
from crytobot.app._config import _Bad, _number
from crytobot.app._loop import ForcedStop
from crytobot.calibration import (
    DIRECTIONS,
    TOTAL,
    CoinPrices,
    Costs,
    EventAnnouncement,
    EventMeasured,
    EventReportFacts,
    EventSample,
    Span,
    TableRow,
    event_report_text,
    event_samples,
    library_text,
    measure_events,
    price_needs,
    reason_counts,
    table_rows,
)
from crytobot.market_data import (
    DownloadOutcome,
    PriceData,
    PriceNeed,
    StoredCandle,
    missing_spans,
)

SECTION = "events"
EVENT = "events"
_PATH_KEYS = ("price_store_path", "report_path", "library_path")
_COST_DEFAULTS = {
    "fee": Decimal("0.001"),
    "slippage": Decimal("0.001"),
    "spread": Decimal("0.0005"),
}
_KEYS = (*_PATH_KEYS, "request_gap_s", "model_cutoff", *_COST_DEFAULTS)
MIN_GAP_S = 1
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class EventsConfig:
    price_store_path: str
    report_path: str
    library_path: str
    request_gap_s: int
    model_cutoff: datetime
    costs: Costs


@dataclass(frozen=True)
class EventsConfigResult:
    config: EventsConfig | None
    message: str


class _Problem(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _name(key: str) -> str:
    return f"{SECTION}.{key}"


def _invalid(key: str) -> _Problem:
    return _Problem(f"ayar geçersiz: {_name(key)}")


def _path(table: Mapping[object, object], key: str, taken: list[str]) -> str:
    if key not in table:
        raise _Problem(f"ayar eksik: {_name(key)}")
    value = table[key]
    if type(value) is not str or not value.strip() or value in taken:
        raise _invalid(key)
    taken.append(value)
    return value


def _cost(table: Mapping[object, object], key: str) -> Decimal:
    if key not in table:
        return _COST_DEFAULTS[key]
    try:
        value = Decimal(_number(table[key]))
    except _Bad:
        raise _invalid(key) from None
    if not (0 <= value < 1):
        raise _invalid(key)
    return value


def _cutoff(table: Mapping[object, object]) -> datetime:
    if "model_cutoff" not in table:
        raise _Problem(f"ayar eksik: {_name('model_cutoff')}")
    value = table["model_cutoff"]
    day: date | None = None
    if type(value) is date:
        day = value
    elif type(value) is str and len(value) == 10:
        try:
            day = date.fromisoformat(value)
        except ValueError:
            day = None
    if day is None:
        raise _invalid("model_cutoff")
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _gap(table: Mapping[object, object]) -> int:
    value = table.get("request_gap_s", MIN_GAP_S)
    if type(value) is not int or value < MIN_GAP_S:
        raise _invalid("request_gap_s")
    return value


def _section(document: Mapping[object, object]) -> EventsConfig:
    for name in document:
        if name != SECTION:
            raise _Problem(f"bilinmeyen ayar: {name}")
    table = document.get(SECTION)
    if table is None:
        raise _Problem(f"ayar eksik: {SECTION}")
    if not isinstance(table, Mapping):
        raise _Problem(f"ayar geçersiz: {SECTION}")
    for key in table:
        if key not in _KEYS:
            raise _Problem(f"bilinmeyen ayar: {_name(str(key))}")
    taken: list[str] = []
    store, report, library = (_path(table, key, taken) for key in _PATH_KEYS)
    gap = _gap(table)
    cutoff = _cutoff(table)
    fee, slippage, spread = (_cost(table, key) for key in _COST_DEFAULTS)
    if fee + slippage >= 1:
        raise _invalid("slippage")
    return EventsConfig(store, report, library, gap, cutoff, Costs(fee, slippage, spread))


def load_events_config(document: object) -> EventsConfigResult:
    """`[events]` geçerliyse `EventsConfig`; değilse ilk sorunun adını veren mesaj."""
    if not isinstance(document, Mapping):
        return EventsConfigResult(None, f"ayar geçersiz: {SECTION}")
    try:
        config = _section(document)
    except _Problem as problem:
        return EventsConfigResult(None, problem.message)
    return EventsConfigResult(config, "ayarlar geçerli")


@dataclass(frozen=True)
class EventInputs:
    """Giriş noktasının okuyup etiketlediği kaynak kayıtlar (R-2). `forward_records`: ileriye
    dönük kayıt yoksa `None`. `types`: tür listesi (ad, beklenen yön) tablo sırasıyla."""

    announcements: tuple[EventAnnouncement, ...]
    types: tuple[tuple[str, str], ...]
    archive_path: str
    archive_records: int
    forward_path: str
    forward_records: int | None
    rules_fingerprint: str


class EventsOutcome(Enum):
    COMPLETED = "completed"
    REFUSED = "refused"
    FAILED = "failed"
    STOPPED = "stopped"
    NOT_WRITTEN = "not_written"


@dataclass(frozen=True)
class EventsExit:
    outcome: EventsOutcome
    message: str


@dataclass(frozen=True)
class EventDownloadParts:
    """Gerçek etkiler: kaynak kayıtlar (okunamıyorsa nedeni), indirme adımı, konsol."""

    inputs: Callable[[], EventInputs | str]
    download: Callable[[tuple[PriceNeed, ...]], DownloadOutcome]
    write: Callable[[str], None]


@dataclass(frozen=True)
class EventMeasureParts:
    """Gerçek etkiler: kaynak kayıtlar, fiyat verisi (depo yoksa `None`, okunamıyorsa nedeni),
    çıktı var mı, üzerine yazmayan yazıcı, konsol, saat (UTC)."""

    inputs: Callable[[], EventInputs | str]
    prices: Callable[[], PriceData | str | None]
    exists: Callable[[str], bool]
    write_file: Callable[[str, str], bool]
    write: Callable[[str], None]
    clock: Callable[[], datetime]


class _Halt(Exception):
    def __init__(self, outcome: EventsOutcome, message: str) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.message = message


def _refused(message: str) -> _Halt:
    return _Halt(EventsOutcome.REFUSED, message)


def _samples(inputs: EventInputs | str) -> tuple[EventInputs, tuple[EventSample, ...]]:
    if isinstance(inputs, str):
        raise _refused(inputs)
    unknown = {direction for _, direction in inputs.types} - set(DIRECTIONS)
    if unknown or any(a.direction not in DIRECTIONS for a in inputs.announcements):
        raise _refused("bilinmeyen beklenen yön")
    return inputs, event_samples(inputs.announcements)


def _guarded(write: Callable[[str], None], command: str, body: Callable[[], str]) -> EventsExit:
    def say(text: str) -> None:
        write(f"{EVENT} {command}: {text}")

    try:
        message = body()
    except _Halt as halt:
        verb = "reddedildi" if halt.outcome is EventsOutcome.REFUSED else "durdu"
        say(f"{verb}: {halt.message}")
        return EventsExit(halt.outcome, halt.message)
    except ForcedStop:
        say("durdu: zorla durdurma")
        raise
    except Exception as error:  # the type only; the text may carry anything
        message = f"beklenmeyen hata: {type(error).__name__}"
        say(f"durdu: {message}")
        return EventsExit(EventsOutcome.FAILED, message)
    say(message)
    return EventsExit(EventsOutcome.COMPLETED, message)


_DOWNLOAD_OUTCOMES = {
    DownloadOutcome.FAILED: (EventsOutcome.FAILED, "kaynak hatası"),
    DownloadOutcome.STOPPED: (EventsOutcome.STOPPED, "durdurma isteği"),
}


def _download(parts: EventDownloadParts) -> str:
    inputs, samples = _samples(parts.inputs())
    needs = price_needs(samples)
    wanted = tuple(
        PriceNeed(coin, span.start, span.end) for coin, spans in needs.items() for span in spans
    )
    parts.write(
        f"{EVENT} download: başladı: duyuru={len(inputs.announcements)} örnek={len(samples)} "
        f"coin={len(needs)} aralık={len(wanted)}"
    )
    outcome = parts.download(wanted)
    if outcome in _DOWNLOAD_OUTCOMES:
        result, message = _DOWNLOAD_OUTCOMES[outcome]
        raise _Halt(result, message)
    return "tamam: fiyat verisi indirildi"


def run_events_download(config: EventsConfig, parts: EventDownloadParts) -> EventsExit:
    """İndirme koşusu; ayar (`config`) giriş noktasında denetlenmiştir."""
    return _guarded(parts.write, "download", lambda: _download(parts))


def _candles(stored: tuple[StoredCandle, ...]) -> tuple[Candle, ...]:
    return tuple(
        Candle(
            _EPOCH + timedelta(milliseconds=c.open_ms),
            float(c.open),
            float(c.high),
            float(c.low),
            float(c.close),
        )
        for c in stored
    )


def _coin_prices(needs: Mapping[str, tuple[Span, ...]], prices: PriceData) -> dict[str, CoinPrices]:
    """Her coin için çift var mı ve mumlar; gerekli bir aralık indirilmemişse ret."""
    pairs = prices.pairs
    ceiling = prices.ceiling
    if pairs is None or ceiling is None:
        raise _refused("borsa bilgisi indirilmemiş; önce events download")
    found: dict[str, CoinPrices] = {}
    gaps = 0
    for coin, spans in needs.items():
        pair = pairs.get(coin)
        if pair is None:
            found[coin] = CoinPrices(False, ())
            continue
        wanted = [(s.start, min(s.end, ceiling)) for s in spans if s.start < ceiling]
        gaps += len(missing_spans(wanted, prices.spans.get(pair.symbol, ())))
        found[coin] = CoinPrices(True, _candles(prices.candles.get(pair.symbol, ())))
    if gaps:
        raise _refused(f"fiyat verisi eksik: {gaps} aralık indirilmemiş; önce events download")
    return found


def _write(parts: EventMeasureParts, label: str, path: str, text: str) -> str:
    if not parts.write_file(path, text):
        raise _Halt(EventsOutcome.NOT_WRITTEN, f"{label} yazılamadı: {path}")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    parts.write(f"{EVENT} measure: {label} parmak izi: {digest} ({path})")
    return digest


def _points(row: TableRow) -> str:
    difference = row.difference
    return "-" if difference is None else f"{float(difference * 100):+.2f}"


def _summary(parts: EventMeasureParts, measured: EventMeasured) -> None:
    for row in table_rows(measured):
        if row.period != TOTAL or row.main is False:
            continue
        kind = "ana" if row.main else "nötr"
        parts.write(
            f"{EVENT} measure: {row.event_type} {row.move.value} ({kind}): "
            f"ölçülen={row.measured} fark={_points(row)} puan"
        )
    text = " ".join(f"{reason.value}={count}" for reason, count in reason_counts(measured))
    parts.write(f"{EVENT} measure: ölçülemeyen: {text}")


def _measure(config: EventsConfig, parts: EventMeasureParts) -> str:
    for path in (config.report_path, config.library_path):
        if parts.exists(path):
            raise _refused(f"dosya var: {path}; üzerine yazılmaz")
    inputs, samples = _samples(parts.inputs())
    sources_read_at = parts.clock()
    prices = parts.prices()
    prices_read_at = parts.clock()
    if prices is None:
        raise _refused(f"fiyat verisi yok: {config.price_store_path}; önce events download")
    if isinstance(prices, str):
        raise _refused(prices)
    coins = _coin_prices(price_needs(samples), prices)
    measured = measure_events(samples, coins, config.costs, config.model_cutoff, inputs.types)
    library = library_text(measured, inputs.rules_fingerprint)
    digest = _write(parts, "kütüphane", config.library_path, library)
    facts = EventReportFacts(
        parts.clock(),
        sources_read_at,
        prices_read_at,
        inputs.archive_path,
        inputs.archive_records,
        inputs.forward_path,
        inputs.forward_records,
        config.price_store_path,
        prices.exchange_info_at,
        prices.downloaded_first,
        prices.downloaded_last,
        prices.seconds,
        inputs.rules_fingerprint,
        digest,
        price_pairs=len(prices.pairs or {}),
        price_symbols=sum(bool(items) for items in prices.candles.values()),
        price_candles=sum(len(items) for items in prices.candles.values()),
        price_spans=sum(len(items) for items in prices.spans.values()),
        price_empty_spans=sum(not s.found for items in prices.spans.values() for s in items),
    )
    _write(parts, "rapor", config.report_path, event_report_text(measured, facts))
    _summary(parts, measured)
    return f"tamam: rapor dosyası {config.report_path}"


def run_events_measure(config: EventsConfig, parts: EventMeasureParts) -> EventsExit:
    """Ölçüm koşusu: ağa çıkmaz; rapor ve kütüphane yazılır (üzerine yazılmaz)."""
    return _guarded(parts.write, "measure", lambda: _measure(config, parts))
