"""İleriye dönük ölçümün iki koşusu (spec 0053 R-1, R-8, R-9, R-10, G-7, G-8; plan step 6, Risk 2,
6, 7, 8, 9).

`load_forward_config` `crytobot-forward.toml`'un `[forward]` bölümünü denetler: üç yol
(`price_store_path`, `report_path`, `samples_path`; zorunlu, birbirinden farklı), `request_gap_s`
(tam sayı, varsayılan 1, en az 1), `fee`/`slippage`/`spread` (0048'in kuralı ve varsayılanları).
Bilinmeyen bölüm ya da anahtar reddedilir; ilk sorun adıyla, ham değer yazılmadan.

`run_forward_download`: kaynaklar (giriş noktası okur) → bütün örneklerin ve teknik "al"ların fiyat
aralıkları → `market_data`'nın indirme adımı. `run_forward_report`: rapor anı (verilmezse şimdi;
gelecekte ise ret) → kaynaklar → fiyat verisi (ağsız; örnek ya da teknik "al" yoksa okunmaz) →
ölçülecek her aralık indirilmiş mi (değilse ret: sessiz boşluk yok) → ölçüm → örnek dosyası ve
rapor (giriş noktası atomik üzerine yazar). Gerçek etkiler `*Parts` ile gelir: `app` dosya açmaz,
saat çağırmaz, ağa çıkmaz, `news`'i import etmez (R-3k). Hüküm hiçbir aksiyonu tetiklemez (R-9).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from crytobot.app._config import _Bad, _number
from crytobot.app._event_samples import _candles
from crytobot.app._loop import ForcedStop
from crytobot.calibration import (
    CoinPrices,
    Costs,
    ForwardInputs,
    ForwardReportFacts,
    download_needs,
    forward_report_text,
    forward_samples,
    measure_forward,
    price_coins,
    report_needs,
    samples_text,
    shadow_buys,
)
from crytobot.market_data import DownloadOutcome, PriceData, PriceNeed, missing_spans

SECTION = "forward"
EVENT = "forward"
_PATH_KEYS = ("price_store_path", "report_path", "samples_path")
_COST_DEFAULTS = {
    "fee": Decimal("0.001"),
    "slippage": Decimal("0.001"),
    "spread": Decimal("0.0005"),
}
_KEYS = (*_PATH_KEYS, "request_gap_s", *_COST_DEFAULTS)
MIN_GAP_S = 1
DOWNLOAD_FIRST = "önce forward download"


@dataclass(frozen=True)
class ForwardConfig:
    price_store_path: str
    report_path: str
    samples_path: str
    request_gap_s: int
    costs: Costs


@dataclass(frozen=True)
class ForwardConfigResult:
    config: ForwardConfig | None
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


def _section(document: Mapping[object, object]) -> ForwardConfig:
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
    store, report, samples = (_path(table, key, taken) for key in _PATH_KEYS)
    gap = table.get("request_gap_s", MIN_GAP_S)
    if type(gap) is not int or gap < MIN_GAP_S:
        raise _invalid("request_gap_s")
    fee, slippage, spread = (_cost(table, key) for key in _COST_DEFAULTS)
    if fee + slippage >= 1:
        raise _invalid("slippage")
    return ForwardConfig(store, report, samples, gap, Costs(fee, slippage, spread))


def load_forward_config(document: object) -> ForwardConfigResult:
    """`[forward]` geçerliyse `ForwardConfig`; değilse ilk sorunun adını veren mesaj."""
    if not isinstance(document, Mapping):
        return ForwardConfigResult(None, f"ayar geçersiz: {SECTION}")
    try:
        config = _section(document)
    except _Problem as problem:
        return ForwardConfigResult(None, problem.message)
    return ForwardConfigResult(config, "ayarlar geçerli")


@dataclass(frozen=True)
class ForwardSources:
    """Giriş noktasının okuduğu kayıtlar (`calibration`'ın tipinde) ve rapor başlığının bilgileri.
    `shadow_path` `None`: bot ayarında `[shadow]` yok."""

    inputs: ForwardInputs
    score_path: str
    score_skipped: int
    news_path: str
    shadow_path: str | None
    shadow_broken: int


class ForwardOutcome(Enum):
    COMPLETED = "completed"
    REFUSED = "refused"
    FAILED = "failed"
    STOPPED = "stopped"
    NOT_WRITTEN = "not_written"


@dataclass(frozen=True)
class ForwardExit:
    outcome: ForwardOutcome
    message: str


@dataclass(frozen=True)
class ForwardDownloadParts:
    """Gerçek etkiler: kaynaklar (okunamıyorsa nedeni), indirme adımı, konsol, saat (UTC)."""

    sources: Callable[[], ForwardSources | str]
    download: Callable[[tuple[PriceNeed, ...]], DownloadOutcome]
    write: Callable[[str], None]
    clock: Callable[[], datetime]


@dataclass(frozen=True)
class ForwardReportParts:
    """Gerçek etkiler: kaynaklar, fiyat verisi (depo yoksa `None`, okunamıyorsa nedeni), atomik
    üzerine yazan yazıcı (yazamazsa `False`), konsol, saat (UTC)."""

    sources: Callable[[], ForwardSources | str]
    prices: Callable[[], PriceData | str | None]
    write_file: Callable[[str, str], bool]
    write: Callable[[str], None]
    clock: Callable[[], datetime]


class _Halt(Exception):
    def __init__(self, outcome: ForwardOutcome, message: str) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.message = message


def _refused(message: str) -> _Halt:
    return _Halt(ForwardOutcome.REFUSED, message)


def _sources(parts: ForwardDownloadParts | ForwardReportParts) -> ForwardSources:
    found = parts.sources()
    if isinstance(found, str):
        raise _refused(found)
    return found


def _guarded(write: Callable[[str], None], command: str, body: Callable[[], str]) -> ForwardExit:
    def say(text: str) -> None:
        write(f"{EVENT} {command}: {text}")

    try:
        message = body()
    except _Halt as halt:
        verb = "reddedildi" if halt.outcome is ForwardOutcome.REFUSED else "durdu"
        say(f"{verb}: {halt.message}")
        return ForwardExit(halt.outcome, halt.message)
    except ForcedStop:
        say("durdu: zorla durdurma")
        raise
    except Exception as error:  # the type only; the text may carry anything
        message = f"beklenmeyen hata: {type(error).__name__}"
        say(f"durdu: {message}")
        return ForwardExit(ForwardOutcome.FAILED, message)
    say(message)
    return ForwardExit(ForwardOutcome.COMPLETED, message)


_DOWNLOAD_OUTCOMES = {
    DownloadOutcome.FAILED: (ForwardOutcome.FAILED, "kaynak hatası"),
    DownloadOutcome.STOPPED: (ForwardOutcome.STOPPED, "durdurma isteği"),
}


def _download(parts: ForwardDownloadParts) -> str:
    inputs = _sources(parts).inputs
    now = parts.clock()
    needs = download_needs(inputs, now)
    wanted = tuple(
        PriceNeed(coin, span.start, span.end) for coin, spans in needs.items() for span in spans
    )
    parts.write(
        f"{EVENT} download: başladı: örnek={len(forward_samples(inputs, now))} "
        f'teknik "al"={len(shadow_buys(inputs, now))} coin={len(needs)} aralık={len(wanted)}'
    )
    if not wanted:
        return "tamam: indirilecek aralık yok"
    outcome = parts.download(wanted)
    if outcome in _DOWNLOAD_OUTCOMES:
        result, message = _DOWNLOAD_OUTCOMES[outcome]
        raise _Halt(result, message)
    return "tamam: fiyat verisi indirildi"


def run_forward_download(config: ForwardConfig, parts: ForwardDownloadParts) -> ForwardExit:
    """İndirme koşusu (G-8); ayar (`config`) giriş noktasında denetlenmiştir."""
    return _guarded(parts.write, "download", lambda: _download(parts))


def _coin_prices(
    inputs: ForwardInputs, report_at: datetime, prices: PriceData
) -> dict[str, CoinPrices]:
    """Plan Risk 2: ölçülecek bir aralık indirilmemişse ret; çift yoksa `çift yok` ölçülür."""
    pairs = prices.pairs
    if pairs is None:
        raise _refused(f"borsa bilgisi indirilmemiş; {DOWNLOAD_FIRST}")
    gaps = 0
    for coin, spans in report_needs(inputs, report_at, pairs).items():
        symbol = pairs[coin].symbol
        wanted = [(span.start, span.end) for span in spans]
        gaps += len(missing_spans(wanted, prices.spans.get(symbol, ())))
    if gaps:
        raise _refused(f"fiyat verisi eksik: {gaps} aralık indirilmemiş; {DOWNLOAD_FIRST}")
    found: dict[str, CoinPrices] = {}
    for coin in price_coins(inputs, report_at):
        pair = pairs.get(coin)
        if pair is None:
            found[coin] = CoinPrices(False, ())
        else:
            found[coin] = CoinPrices(True, _candles(prices.candles.get(pair.symbol, ())))
    return found


def _report(config: ForwardConfig, parts: ForwardReportParts, at: datetime | None) -> str:
    now = parts.clock()
    if at is not None and at > now:
        raise _refused("rapor anı gelecekte")
    report_at = now if at is None else at
    sources = _sources(parts)
    inputs = sources.inputs
    data: PriceData | None = None
    coins: dict[str, CoinPrices] = {}
    if price_coins(inputs, report_at):
        prices = parts.prices()
        if prices is None:
            raise _refused(f"fiyat verisi yok: {config.price_store_path}; {DOWNLOAD_FIRST}")
        if isinstance(prices, str):
            raise _refused(prices)
        data = prices
        coins = _coin_prices(inputs, report_at, prices)
    measured = measure_forward(inputs, report_at, coins, config.costs)
    facts = ForwardReportFacts(
        parts.clock(),
        sources.score_path,
        sources.score_skipped,
        sources.news_path,
        sources.shadow_path,
        sources.shadow_broken,
        config.price_store_path,
        None if data is None else data.exchange_info_at,
        None if data is None else data.downloaded_last,
    )
    if not parts.write_file(config.samples_path, samples_text(measured)):
        raise _Halt(ForwardOutcome.NOT_WRITTEN, f"örnek dosyası yazılamadı: {config.samples_path}")
    if not parts.write_file(config.report_path, forward_report_text(measured, facts)):
        raise _Halt(ForwardOutcome.NOT_WRITTEN, f"rapor yazılamadı: {config.report_path}")
    parts.write(f"{EVENT} report: hüküm: {measured.verdict.line}")
    return f"tamam: rapor dosyası {config.report_path}"


def run_forward_report(
    config: ForwardConfig, parts: ForwardReportParts, at: datetime | None = None
) -> ForwardExit:
    """Rapor koşusu (R-1): ağa çıkmaz, kilit almaz; rapor ve örnek dosyası her koşuda yeniden
    yazılır. `at`: rapor anı (`--at`), verilmezse saatin şimdisi."""
    return _guarded(parts.write, "report", lambda: _report(config, parts, at))
