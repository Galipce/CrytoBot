"""Toplama turu ve döngüsü (spec 0046 R-1, R-2, R-6, R-7, R-9; plan Risk 1, 8, 9, 10, 11).

Kararlar burada, gerçek etkiler (saat, bekleme, durdurma, getirme, bildirim, satır yazıcısı)
`CollectParts` ile gelir. Her kaynaktan önce durdurmaya bakılır; terk edilen kaynak yazılmaz. İlk
görme anı yanıtın tamamı okunduktan sonra saatten alınır (G-2). Kaynak hatası yalnız o kaynağı
etkiler. Kesinti başı başarıdan sonraki ilk hatanın anıdır; `şimdi - başı > source_alert_hours`
olunca, bildirim gitmediyse tek giriş bildirimi; ilk başarıda, giriş bildirimi gittiyse tek çıkış
bildirimi. Bildirim `reporting`'e verilince (kuyruk dahil) kayıt aynı işlemde işaretlenir.

Spec 0056 (plan Risk 5, 6): akış kaynağı (`binance-akış`) sorgulanmaz; tur, akış yöneticisinin
kuyruğunu beklemeden boşaltır (diğer kaynaklar gecikmez). İlk görme anı iletinin alınma anıdır.
Kuyruk boş ve bağlantı kopuksa tur hatası `kopuk`tur: kesinti kuralı aynen işler. Bağlantı durumu
kaynağın durumuyla aynı işlemde yazılır. Akış yöneticisi fazla yetki gördüyse toplama durur
(`KEY_REFUSED`).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum

from crytobot.news._config import STREAM_KIND, NewsConfig, NewsSource
from crytobot.news._fetch import Fetched
from crytobot.news._items import NewsItem, prepare
from crytobot.news._parse import CONTROL, PARSERS, ParseError, parse_stream_message
from crytobot.news._store import NewsStore, SourceState, StoreError, StreamState
from crytobot.news._stream import StreamStatus, StreamView
from crytobot.reporting import escape_html

POSSIBLE_MISS = "uyarı=olası kaçırma"
DISCONNECTED = "kopuk"


@dataclass(frozen=True)
class CollectParts:
    """Toplamanın gerçek etkileri. `notify` yoksa Telegram kapalıdır: bildirim yalnız satırdır.
    `notify` iletilemeyip kuyruğa alınan mesajın hata adını döndürür; `drain` her tur başında
    `reporting` kuyruğunu iletmeyi dener, iletilemeyenlerin hata adlarını döndürür; `dropped`
    kuyruktan atılanların, `disabled_reason` Telegram kalıcı kapandıysa gerekçesinin adını bir kez
    verir (review round 1 F-4)."""

    clock: Callable[[], datetime]
    wait: Callable[[float], None]
    stopped: Callable[[], bool]
    fetch: Callable[[NewsSource, int], Fetched]
    say: Callable[[str], None]
    notify: Callable[[str], str | None] | None = None
    drain: Callable[[], list[str]] | None = None
    dropped: Callable[[], list[str]] | None = None
    disabled_reason: Callable[[], str | None] | None = None
    streams: Mapping[str, StreamView] = field(default_factory=dict)  # spec 0056: by source name


class CollectionExit(Enum):
    STOPPED = "stopped"
    STORE_FAILED = "store_failed"
    KEY_REFUSED = "key_refused"  # spec 0056 AC-2: excess permission seen while running


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
        """Satır her zaman; Telegram açıksa `reporting`'e verilir (kuyruk dahil). Verildi mi (ya da
        kapalı mı). İletim sorunları satıra yazılır (F-4); işaretleme kuralı değişmez."""
        self.parts.say(line)
        if self.parts.notify is None:
            return True
        prefix = line.split(" ", 1)[0]
        try:
            error = self.parts.notify(text)
        except Exception:  # reporting never stops the collection; the next round retries
            self.parts.say(f"{prefix} bildirim iletilemedi")
            return False
        if error is not None:
            self.parts.say(f"{prefix} bildirim kuyrukta ({error})")
        telegram_lines(self.parts)
        return True

    def _failed(
        self,
        source: NewsSource,
        previous: SourceState,
        error: str,
        at: datetime,
        stream: StreamState | None = None,
    ) -> None:
        started = previous.outage_started_at or at
        state = replace(previous, last_error=error, last_error_at=at, outage_started_at=started)
        threshold = timedelta(hours=self.config.source_alert_hours)
        if not previous.alert_sent and at - started > threshold:
            sent = self._notify(
                outage_notice(source.name, started),
                f"kaynak={source.name} kesinti: başlangıç={_stamp(started)} bildirim=giriş",
            )
            state = replace(state, alert_sent=sent)
        self.store.write(source.name, [], state, stream)
        self.parts.say(SourceRound(source.name, error=error).line)

    def _succeeded(
        self,
        source: NewsSource,
        previous: SourceState,
        items: list[NewsItem | None],
        at: datetime,
        stream: StreamState | None = None,
    ) -> None:
        valid = [item for item in items if item is not None]
        state = replace(previous, last_success_at=at, outage_started_at=None, alert_sent=False)
        if previous.outage_started_at is not None and previous.alert_sent:
            self._notify(
                recovery_notice(source.name, previous.outage_started_at),
                f"kaynak={source.name} kesinti bitti: başlangıç="
                f"{_stamp(previous.outage_started_at)} bildirim=çıkış",
            )
        written = self.store.write(source.name, valid, state, stream)
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

    def paused(self, source: NewsSource) -> None:
        """Review round 1 F-3: kapalı kaynak sorgulanmaz, kesinti sayacı ilerlemez (plan Risk 13).
        Süren kesinti kapatılınca sıfırlanır; bildirim gittiyse çıkış bildirimi gitmez, satır
        kalır."""
        previous = self.store.state(source.name)
        if previous.outage_started_at is None:
            return
        self.store.write(
            source.name, [], replace(previous, outage_started_at=None, alert_sent=False)
        )
        self.parts.say(f"kaynak={source.name} kapalı: kesinti sayacı sıfırlandı")

    def stream(self, source: NewsSource) -> None:
        """Spec 0056: kuyruk beklemeden boşaltılır; boş ve kopuksa `kopuk` hatası."""
        runner = self.parts.streams.get(source.name)
        at = self.parts.clock()
        previous = self.store.state(source.name)
        if runner is None:
            self._failed(source, previous, DISCONNECTED, at)
            return
        received = runner.drain()
        status = runner.status()
        stream = stream_state(status)
        if not received and not status.connected:
            self._failed(source, previous, DISCONNECTED, at, stream)
            return
        items: list[NewsItem | None] = []
        for text, seen in received:
            raw = parse_stream_message(text, self.config.max_response_bytes)
            if raw == CONTROL:
                continue
            items.append(None if raw is None or isinstance(raw, str) else prepare(raw, seen))
        self._succeeded(source, previous, items, at, stream)

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


def telegram_lines(parts: CollectParts) -> None:
    """Kuyruktan atılan mesajlar ve Telegram'ın kalıcı kapanması, bot döngüsünün satırlarıyla."""
    for error in [] if parts.dropped is None else parts.dropped():
        parts.say(f"telegram bildirimi iletilemedi ({error})")
    reason = None if parts.disabled_reason is None else parts.disabled_reason()
    if reason:
        parts.say(f"telegram devre dışı ({reason})")


def run_round(config: NewsConfig, store: NewsStore, parts: CollectParts) -> bool:
    """Açık kaynakların her biri bir kez; tur durdurmayla kesildiyse `False` (R-2, AC-8)."""
    if parts.drain is not None:
        for error in parts.drain():
            parts.say(f"telegram bildirimi iletilemedi ({error})")
        telegram_lines(parts)
    current = _Round(config, store, parts)
    for source in config.sources:
        if not source.enabled:
            current.paused(source)
            continue
        if parts.stopped():
            return False
        if source.kind == STREAM_KIND:
            current.stream(source)
        elif not current.source(source):
            return False
    return True


def stream_state(status: StreamStatus) -> StreamState:
    return StreamState(
        status.connected,
        status.last_connected_at,
        status.gap_started_at,
        int(status.gap_total.total_seconds()),
    )


def _refused(parts: CollectParts) -> str | None:
    for runner in parts.streams.values():
        fatal = runner.status().fatal
        if fatal is not None:
            return fatal.message
    return None


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
            refused = _refused(parts)
            if refused is not None:
                parts.say(f"reddedildi: {refused} tur_sayısı={rounds}")
                return CollectionExit.KEY_REFUSED
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
