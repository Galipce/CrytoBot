"""Toplama turu ve döngüsü (spec 0046 R-1, R-2, R-6, R-7, R-9; plan Risk 1, 8, 9, 10, 11).

Kararlar burada, gerçek etkiler (saat, bekleme, durdurma, getirme, bildirim, satır yazıcısı)
`CollectParts` ile gelir. Her kaynaktan önce durdurmaya bakılır; terk edilen kaynak yazılmaz. İlk
görme anı yanıtın tamamı okunduktan sonra saatten alınır (G-2). Kaynak hatası yalnız o kaynağı
etkiler. Kesinti başı başarıdan sonraki ilk hatanın anıdır; `şimdi - başı > source_alert_hours`
olunca, bildirim gitmediyse tek giriş bildirimi; ilk başarıda, giriş bildirimi gittiyse tek çıkış
bildirimi. Bildirim `reporting`'e verilince (kuyruk dahil) kayıt aynı işlemde işaretlenir.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum

from crytobot.news._config import NewsConfig, NewsSource
from crytobot.news._fetch import Fetched
from crytobot.news._items import NewsItem, prepare
from crytobot.news._parse import PARSERS, ParseError
from crytobot.news._store import NewsStore, SourceState, StoreError
from crytobot.reporting import escape_html

POSSIBLE_MISS = "uyarı=olası kaçırma"


@dataclass(frozen=True)
class CollectParts:
    """Toplamanın gerçek etkileri. `notify` yoksa Telegram kapalıdır: bildirim yalnız satırdır.
    `drain` her tur başında `reporting` kuyruğunu iletmeyi dener."""

    clock: Callable[[], datetime]
    wait: Callable[[float], None]
    stopped: Callable[[], bool]
    fetch: Callable[[NewsSource, int], Fetched]
    say: Callable[[str], None]
    notify: Callable[[str], object] | None = None
    drain: Callable[[], object] | None = None


class CollectionExit(Enum):
    STOPPED = "stopped"
    STORE_FAILED = "store_failed"


@dataclass(frozen=True)
class SourceRound:
    """Bir kaynağın tur sonucu (özet satırının içeriği)."""

    name: str
    new: int = 0
    duplicate: int = 0
    invalid: int = 0
    error: str | None = None
    possible_miss: bool = False

    @property
    def line(self) -> str:
        if self.error is not None:
            return f"kaynak={self.name} hata={self.error}"
        text = f"kaynak={self.name} yeni={self.new} tekrar={self.duplicate} geçersiz={self.invalid}"
        return f"{text} {POSSIBLE_MISS}" if self.possible_miss else text


def _stamp(moment: datetime) -> str:
    return moment.isoformat()


def outage_notice(name: str, started: datetime) -> str:
    return (
        "<b>Haber kaynağı kesintisi</b>\n"
        f"Kaynak: {escape_html(name)}\n"
        f"Başlangıç: {escape_html(_stamp(started))} (UTC)"
    )


def recovery_notice(name: str, started: datetime) -> str:
    return (
        "<b>Haber kaynağı yeniden çalışıyor</b>\n"
        f"Kaynak: {escape_html(name)}\n"
        f"Kesinti başlangıcı: {escape_html(_stamp(started))} (UTC)"
    )


def _content(source: NewsSource, fetched: Fetched, first_seen: datetime) -> list[NewsItem | None]:
    if fetched.body is None:
        raise ParseError(fetched.error or "network_error")
    raws = PARSERS[source.kind](fetched.body)
    return [prepare(raw, first_seen) for raw in raws]


class _Round:
    def __init__(self, config: NewsConfig, store: NewsStore, parts: CollectParts) -> None:
        self.config = config
        self.store = store
        self.parts = parts

    def _notify(self, text: str, line: str) -> bool:
        """Satır her zaman; Telegram açıksa `reporting`'e verilir. Verildi mi (ya da kapalı mı)."""
        self.parts.say(line)
        if self.parts.notify is None:
            return True
        try:
            self.parts.notify(text)
        except Exception:  # reporting never stops the collection; the next round retries
            self.parts.say(f"{line.split(' ', 1)[0]} bildirim iletilemedi")
            return False
        return True

    def _failed(self, source: NewsSource, previous: SourceState, error: str, at: datetime) -> None:
        started = previous.outage_started_at or at
        state = replace(previous, last_error=error, last_error_at=at, outage_started_at=started)
        threshold = timedelta(hours=self.config.source_alert_hours)
        if not previous.alert_sent and at - started > threshold:
            sent = self._notify(
                outage_notice(source.name, started),
                f"kaynak={source.name} kesinti: başlangıç={_stamp(started)} bildirim=giriş",
            )
            state = replace(state, alert_sent=sent)
        self.store.write(source.name, [], state)
        self.parts.say(SourceRound(source.name, error=error).line)

    def _succeeded(
        self, source: NewsSource, previous: SourceState, items: list[NewsItem | None], at: datetime
    ) -> None:
        valid = [item for item in items if item is not None]
        state = replace(previous, last_success_at=at, outage_started_at=None, alert_sent=False)
        if previous.outage_started_at is not None and previous.alert_sent:
            self._notify(
                recovery_notice(source.name, previous.outage_started_at),
                f"kaynak={source.name} kesinti bitti: başlangıç="
                f"{_stamp(previous.outage_started_at)} bildirim=çıkış",
            )
        written = self.store.write(source.name, valid, state)
        seen: set[str] = set()
        earlier = 0  # duplicates of records stored before this response (not within it)
        for item, was_written in zip(valid, written, strict=True):
            if not was_written and item.key not in seen:
                earlier += 1
            seen.add(item.key)
        new = sum(written)
        result = SourceRound(
            source.name,
            new=new,
            duplicate=len(valid) - new,
            invalid=len(items) - len(valid),
            possible_miss=source.kind == "binance-duyuru" and bool(valid) and earlier == 0,
        )
        self.parts.say(result.line)

    def source(self, source: NewsSource) -> bool:
        """Kaynağı toplar; durdurma isteğiyle terk edildiyse `False`."""
        fetched = self.parts.fetch(source, self.config.max_response_bytes)
        if fetched.abandoned or self.parts.stopped():
            return False
        at = self.parts.clock()  # the response is fully read: the first-seen time (G-2)
        previous = self.store.state(source.name)
        try:
            items = _content(source, fetched, at)
        except ParseError as error:
            self._failed(source, previous, error.name, at)
            return True
        self._succeeded(source, previous, items, at)
        return True


def run_round(config: NewsConfig, store: NewsStore, parts: CollectParts) -> bool:
    """Açık kaynakların her biri bir kez; tur durdurmayla kesildiyse `False` (R-2, AC-8)."""
    if parts.drain is not None:
        parts.drain()
    current = _Round(config, store, parts)
    for source in config.sources:
        if not source.enabled:
            continue
        if parts.stopped() or not current.source(source):
            return False
    return True


def run_collection(config: NewsConfig, store: NewsStore, parts: CollectParts) -> CollectionExit:
    """Durdurulana kadar `interval_minutes` aralıkla turlar (R-1)."""
    enabled = sum(source.enabled for source in config.sources)
    parts.say(
        f"başladı: kaynak={enabled}/{len(config.sources)} aralık={config.interval_minutes}dk"
        f" kayıt={config.store_path}"
    )
    interval = timedelta(minutes=config.interval_minutes)
    rounds = 0
    try:
        while not parts.stopped():
            started = parts.clock()
            finished = run_round(config, store, parts)
            if finished:
                rounds += 1
            if not finished or parts.stopped():
                break
            left = (started + interval - parts.clock()).total_seconds()
            if left > 0:
                parts.wait(left)
    except StoreError as error:
        parts.say(f"durdu: {error} tur_sayısı={rounds}")
        return CollectionExit.STORE_FAILED
    parts.say(f"durdu: durdurma isteği tur_sayısı={rounds}")
    return CollectionExit.STOPPED
