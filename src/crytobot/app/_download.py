"""Geçmiş veri indirme: ayarlar ve koşu (spec 0023 R-2, R-3, R-7, R-8; plan Risk 9, 10).

`load_download_config` aynı ayar dosyasından botun ayarlarını (`load_config`) ve `[history]`
bölümünü denetler. Sıra: bot ayarları → `history.data_path` → `history.start` → `history.end` →
bölümdeki bilinmeyen anahtar; ilk sorun adıyla söylenir, ham değer yazılmaz. Hiçbir ayarın
varsayılanı yoktur. Dönem UTC'dir: ofsetsiz ya da sıfır olmayan ofsetli zaman geçersizdir. İki uç da
tur aralığının sınırına denk gelir, bitiş başlangıçtan sonradır ve indirme anından sonra olamaz.

`run_download` indirmeyi `DownloadParts` ile verilen işlevle yapar: `app` borsaya ve diske kendi
başına çıkmaz, saat çağırmaz. Paper deposuna, kilide ve kayıt dosyasına dokunulmaz (R-1). Çıktı
Türkçedir; istisna metni hiçbir satıra girmez, yalnız tip adı (R-8).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from crytobot.app._config import BotConfig, load_config
from crytobot.app._events import line, stamp
from crytobot.app._loop import ForcedStop, StopRequest
from crytobot.market_data import (
    CANDLE_INTERVALS,
    HistoryRequest,
    HistoryResult,
    HistoryStop,
    HistoryStopReason,
    PairSummary,
)

SECTION = "history"
_KEYS = ("data_path", "start", "end")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_EVENT = "indirme"
_NOT_WRITTEN = "tamamlanmış veri dosyası yazılmadı"

Download = Callable[[HistoryRequest, Callable[[], datetime], Callable[[], bool]], HistoryResult]


@dataclass(frozen=True)
class DownloadConfig:
    """İndirmenin ayarları; `bot` botun bugünkü ayarlarıdır (beyaz liste, aralıklar, süre)."""

    data_path: str
    start: datetime
    end: datetime
    bot: BotConfig

    def request(self) -> HistoryRequest:
        return HistoryRequest(
            self.data_path,
            tuple(self.bot.turn.whitelist),
            self.bot.read,
            self.start,
            self.end,
        )


@dataclass(frozen=True)
class DownloadConfigResult:
    """`config` yalnız her ayar geçerliyse doludur; değilse `setting` ilk sorunlu ayarın adıdır."""

    config: DownloadConfig | None
    setting: str | None
    message: str


@dataclass(frozen=True)
class DownloadParts:
    """İndirmenin gerçek etkileri: saat, indirme işlevi, çıktı, durdurma isteği."""

    clock: Callable[[], datetime]
    download: Download
    write: Callable[[str], None]
    stop: StopRequest


@dataclass(frozen=True)
class DownloadExit:
    """`completed`: veri dosyası tamamlandı. `result`: indirmenin sonucu, döndüyse."""

    completed: bool
    result: HistoryResult | None


class _Problem(Exception):
    def __init__(self, setting: str, message: str) -> None:
        super().__init__(setting)
        self.setting = setting
        self.message = message


def _missing(name: str) -> _Problem:
    return _Problem(name, f"ayar eksik: {name}")


def _invalid(name: str) -> _Problem:
    return _Problem(name, f"ayar geçersiz: {name}")


def _utc(value: object, name: str) -> datetime:
    """TOML tarihli zaman, ofseti 0; dilimsiz zaman, tarih ve metin geçersizdir (plan Risk 10)."""
    if type(value) is not datetime or value.utcoffset() != timedelta(0):
        raise _invalid(name)
    return value.astimezone(UTC)


def _on_boundary(moment: datetime, interval: timedelta) -> bool:
    return (moment - _EPOCH) % interval == timedelta(0)


def _history(document: Mapping[object, object], bot: BotConfig, now: datetime) -> DownloadConfig:
    table = document.get(SECTION)
    if table is None:
        raise _missing(SECTION)
    if not isinstance(table, Mapping):
        raise _invalid(SECTION)
    for key in _KEYS:
        if key not in table:
            raise _missing(f"{SECTION}.{key}")
    data_path = table["data_path"]
    if type(data_path) is not str or not data_path or data_path in (bot.store_path, bot.log_path):
        raise _invalid(f"{SECTION}.data_path")  # R-1: never the store or the bot's log
    start = _utc(table["start"], f"{SECTION}.start")
    if not _on_boundary(start, bot.turn_interval):
        raise _invalid(f"{SECTION}.start")
    end = _utc(table["end"], f"{SECTION}.end")
    if not (start < end and _on_boundary(end, bot.turn_interval) and end <= now):
        raise _invalid(f"{SECTION}.end")
    for key in table:
        if key not in _KEYS:
            raise _Problem(f"{SECTION}.{key}", f"bilinmeyen ayar: {SECTION}.{key}")
    return DownloadConfig(data_path, start, end, bot)


def load_download_config(document: object, now: datetime) -> DownloadConfigResult:
    """R-2: botun ayarları ve `[history]` geçerliyse `DownloadConfig`; değilse ilk sorunlu ayarın
    adı. Dokunmaz, okumaz; `now` indirme anıdır (bitiş ondan sonra olamaz)."""
    bot = load_config(document, now)
    if bot.config is None:
        return DownloadConfigResult(None, bot.setting, bot.message)
    assert isinstance(document, Mapping)  # load_config refuses anything else
    try:
        config = _history(document, bot.config, now)
    except _Problem as problem:
        return DownloadConfigResult(None, problem.setting, problem.message)
    return DownloadConfigResult(config, None, "ayarlar geçerli")


# --- texts ----------------------------------------------------------------------------------


def start_text(config: DownloadConfig) -> str:
    every = CANDLE_INTERVALS.get(config.bot.read.candle_interval, "?")
    pairs = ",".join(config.bot.turn.whitelist)
    return (
        f"başladı: çiftler={pairs} aralık={every} dönem={stamp(config.start)}..{stamp(config.end)}"
        f" ısınma={config.bot.read.candle_count} dosya={config.data_path}"
    )


def summary_text(summary: PairSummary) -> str:
    return (
        f"{summary.pair} ilk={stamp(summary.first_open)} son={stamp(summary.last_open)}"
        f" mum={summary.candles} boşluk={summary.gaps}"
    )


def _ban_text(stop: HistoryStop) -> str:
    end = "bildirilmedi" if stop.ban_until is None else stamp(stop.ban_until)
    return f"borsa yasağı (HTTP 418), bitiş {end}; yeniden istek atılmadı"


def stop_text(stop: HistoryStop, data_path: str) -> str:
    """Durma nedeni adıyla; istisna metni yoktur, yalnız tip adı (R-8)."""
    pair, detail = stop.pair or "-", stop.detail or "-"
    texts: dict[HistoryStopReason, Callable[[], str]] = {
        HistoryStopReason.INPUT: lambda: f"indirme girdisi geçersiz ({detail})",
        HistoryStopReason.DATA_FILE_EXISTS: lambda: (
            f"veri dosyası zaten var: {data_path}; üzerine yazılmaz"
        ),
        HistoryStopReason.PART_FILE_EXISTS: lambda: (
            f"yarım kalmış indirme dosyası var: {data_path}.part; silinmeden indirme yapılmaz"
        ),
        HistoryStopReason.WRITE_FAILED: lambda: f"veri dosyası yazılamıyor: {data_path}",
        HistoryStopReason.NETWORK: lambda: "ağ hatası",
        HistoryStopReason.CALL_TIMED_OUT: lambda: "çağrı süresi aşıldı",
        HistoryStopReason.RATE_LIMITED: lambda: (
            "istek sınırı uyarısı (HTTP 429); yeniden istek atılmadı"
        ),
        HistoryStopReason.BANNED: lambda: _ban_text(stop),
        HistoryStopReason.EXCHANGE_ERROR: lambda: f"borsa hatası ({detail})",
        HistoryStopReason.PAIR_UNAVAILABLE: lambda: (
            f"çift borsada yok ya da kullanılamaz: {pair} ({detail})"
        ),
        HistoryStopReason.MISSING_RULES: lambda: f"çiftin kuralları eksik: {pair} ({detail})",
        HistoryStopReason.UNTRUSTED_DATA: lambda: f"güvenilmeyen veri: {pair} ({detail})",
        HistoryStopReason.NO_CANDLES: lambda: f"dönemde hiç mum yok: {pair}",
        HistoryStopReason.STOP_REQUESTED: lambda: "durdurma isteği",
        HistoryStopReason.UNEXPECTED: lambda: f"beklenmeyen hata: {stop.error_type or '-'}",
    }
    return f"durdu: {texts[stop.reason]()}; {_NOT_WRITTEN}"


def done_text(config: DownloadConfig, result: HistoryResult) -> str:
    return f"tamam: dosya={config.data_path} çift={len(result.summaries)}"


# --- the run --------------------------------------------------------------------------------


def _moment(parts: DownloadParts) -> datetime | None:
    try:
        return parts.clock()
    except Exception:
        return None  # the line still goes out, stamped `-`


def run_download(config: DownloadConfig, parts: DownloadParts) -> DownloadExit:
    """Tek indirme: başlangıç satırı, indirme, özet ya da durma satırı. İkinci durdurma isteği
    (`ForcedStop`) satırı yazılıp yeniden fırlatılır; indirme `.part`'ı kendisi siler."""
    parts.write(line(_moment(parts), _EVENT, start_text(config)))
    try:
        result = parts.download(config.request(), parts.clock, lambda: parts.stop.requested)
    except ForcedStop:
        parts.write(line(_moment(parts), _EVENT, f"durdu: zorla durdurma; {_NOT_WRITTEN}"))
        raise
    except Exception as error:
        stop = HistoryStop(HistoryStopReason.UNEXPECTED, error_type=type(error).__name__)
        parts.write(line(_moment(parts), _EVENT, stop_text(stop, config.data_path)))
        return DownloadExit(False, None)
    if result.stop is not None:
        parts.write(line(_moment(parts), _EVENT, stop_text(result.stop, config.data_path)))
        return DownloadExit(False, result)
    for summary in result.summaries:
        parts.write(line(_moment(parts), "özet", summary_text(summary)))
    parts.write(line(_moment(parts), _EVENT, done_text(config, result)))
    return DownloadExit(True, result)
