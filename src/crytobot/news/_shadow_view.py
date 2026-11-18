"""Gölge filtre görünümü: bir paper turu anında coin başına filtre durumu (spec 0052 R-3, R-4,
R-5; plan step 3, Risk 3, 4, 6).

Karar `news`'tedir (skorun anlamı onun): `filter_view` saf, `read_filter_view` skor ve haber
kaydını `mode=ro` okur, hiçbir şey yazmaz; skorlayıcıyı ve toplayıcıyı beklemez. Bot bu görünümü
giriş noktasının verdiği işlevle alır (`app` `news`'i import etmez, R-3k).

Tur anı T için sırayla:
1. `filtre yok: <neden>` — skor kaydı yok ya da okunamıyor; skor kaydının başlangıcı T'den sonra;
   haber kaydı yok ya da okunamıyor; skorlayıcı durmuş (T'den önce ya da eşit son tur izi yok ya da
   T'den 30 dakikadan eski).
2. `bastırılırdı` — coin için bilinen (skor anı ≤ T) bir olumsuz olay: yön olumsuz, şiddet ≥ 2,
   haberinin ilk görme anı [T - 24 s, T] içinde, coin çiftin taban varlığına birebir eşit.
3. `bastırılmazdı — eksik bilgi` — olumsuz olay yok; pencerede T'de bilinen "skorlandı" sonucu
   olmayan haber var (bekleyen, şema dışı, bayat ayrı sayılır).
4. `bastırılmazdı`.
Zamanlar metinle değil ayrıştırılmış anla karşılaştırılır (0051, "the moment decides").
"""

import sqlite3
from collections.abc import Collection, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

from crytobot.news._score_store import ResultKind, ScoreStoreError, _check_format
from crytobot.news._store import ForwardItem, StoreError, read_forward

WINDOW = timedelta(hours=24)  # fixed by 0051 (ADR 0003 Consequences): never configurable
LIVE_FOR = timedelta(minutes=30)
NEGATIVE = "olumsuz"
MIN_SEVERITY = 2

NO_SCORE_RECORD = "skor kaydı yok"
SCORE_UNREADABLE = "skor kaydı okunamıyor"
STARTED_AFTER = "skor kaydı tur anından sonra başladı"
NO_NEWS_RECORD = "haber kaydı yok"
NEWS_UNREADABLE = "haber kaydı okunamıyor"
SCORER_STOPPED = "skorlayıcı durmuş"


class FilterState(StrEnum):
    SUPPRESS = "bastırılırdı"
    PASS = "bastırılmazdı"
    PASS_MISSING = "bastırılmazdı — eksik bilgi"
    NONE = "filtre yok"


@dataclass(frozen=True)
class EventRef:
    news_id: int
    severity: int


@dataclass(frozen=True)
class MissingCounts:
    pending: int
    schema: int
    stale: int

    @property
    def total(self) -> int:
        return self.pending + self.schema + self.stale


@dataclass(frozen=True)
class CoinFilter:
    """Bir coin için tur anındaki filtre durumu. `filtre yok`ta olay, eksik sayı ve engel yoktur."""

    state: FilterState
    reason: str
    events: tuple[EventRef, ...] = ()
    missing: MissingCounts | None = None
    held: str | None = None


@dataclass(frozen=True)
class ScoreReadout:
    """Skor kaydının ham hâli: başlangıç, sonuçlar (haber, tür, an), olay skorları (haber, coin,
    yön, şiddet) ve tur izleri (an, engel)."""

    started_at: datetime
    results: tuple[tuple[int, str, datetime], ...]
    events: tuple[tuple[int, str, str, int], ...]
    rounds: tuple[tuple[datetime, str | None], ...]


def base_of(pair: str) -> str:
    """`BTC/USDT` → `BTC` (G-6)."""
    return pair.split("/", 1)[0]


def _none(reason: str, coins: Collection[str]) -> dict[str, CoinFilter]:
    return {coin: CoinFilter(FilterState.NONE, reason) for coin in coins}


def filter_view(
    score: ScoreReadout | str,
    news: tuple[ForwardItem, ...] | str,
    at: datetime,
    coins: Collection[str],
) -> dict[str, CoinFilter]:
    """Saf karar. `score` ve `news` okunamadıysa nedenin metnidir; `coins` taban varlıklardır."""
    if isinstance(score, str):
        return _none(score, coins)
    if score.started_at > at:
        return _none(STARTED_AFTER, coins)
    if isinstance(news, str):
        return _none(news, coins)
    marks = [mark for mark in score.rounds if mark[0] <= at]
    if not marks:
        return _none(SCORER_STOPPED, coins)
    last_at, held = max(marks, key=lambda mark: mark[0])
    if at - last_at > LIVE_FOR:
        return _none(SCORER_STOPPED, coins)
    window = {item.record_id for item in news if at - WINDOW <= item.first_seen <= at}
    known = {news_id: kind for news_id, kind, result_at in score.results if result_at <= at}
    missing = MissingCounts(
        sum(1 for news_id in window if news_id not in known),
        sum(1 for news_id in window if known.get(news_id) == ResultKind.SCHEMA.value),
        sum(1 for news_id in window if known.get(news_id) == ResultKind.STALE.value),
    )
    view: dict[str, CoinFilter] = {}
    for coin in coins:
        refs = tuple(
            EventRef(news_id, severity)
            for news_id, event_coin, direction, severity in score.events
            if news_id in window
            and known.get(news_id) == ResultKind.SCORED.value
            and event_coin == coin
            and direction == NEGATIVE
            and severity >= MIN_SEVERITY
        )
        if refs:
            state, reason = FilterState.SUPPRESS, "olumsuz olay"
        elif missing.total:
            state, reason = FilterState.PASS_MISSING, "eksik bilgi"
        else:
            state, reason = FilterState.PASS, "olumsuz olay yok"
        view[coin] = CoinFilter(state, reason, refs, missing, held)
    return view


def read_score_readout(path: str) -> ScoreReadout | None:
    """Kayıt yoksa `None` (dosya oluşturulmaz); okunamıyorsa `ScoreStoreError`. `mode=ro`, WAL
    (read_score_snapshot'un notu). 0051'de açılmış, `rounds` tablosu olmayan kayıtta iz yoktur."""
    if not Path(path).is_file():
        return None
    uri = f"{Path(path).resolve().as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=0)) as connection:
            _check_format(connection)
            started = connection.execute(
                "SELECT value FROM meta WHERE name = 'started_at'"
            ).fetchone()
            if started is None:
                raise ScoreStoreError(SCORE_UNREADABLE)
            results = tuple(
                (int(news_id), str(kind), datetime.fromisoformat(str(at)))
                for news_id, kind, at in connection.execute("SELECT news_id, kind, at FROM results")
            )
            events = tuple(
                (int(news_id), str(coin), str(direction), int(severity))
                for news_id, coin, direction, severity in connection.execute(
                    "SELECT news_id, coin, direction, severity FROM event_scores"
                )
            )
            has_rounds = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rounds'"
            ).fetchone()
            rounds = (
                ()
                if has_rounds is None
                else tuple(
                    (datetime.fromisoformat(str(at)), None if held is None else str(held))
                    for at, held in connection.execute("SELECT at, held FROM rounds")
                )
            )
            readout = ScoreReadout(datetime.fromisoformat(str(started[0])), results, events, rounds)
    except (sqlite3.Error, ValueError, TypeError):
        raise ScoreStoreError(SCORE_UNREADABLE) from None
    return readout


def read_filter_view(
    score_path: str, news_path: str, at: datetime, coins: Collection[str]
) -> Mapping[str, CoinFilter]:
    """Kayıtları yalnız okur; okunamayan kayıt hata değil, `filtre yok` nedenidir (R-3, R-6)."""
    score: ScoreReadout | str
    try:
        readout = read_score_readout(score_path)
        score = NO_SCORE_RECORD if readout is None else readout
    except ScoreStoreError:
        score = SCORE_UNREADABLE
    news: tuple[ForwardItem, ...] | str
    try:
        items = read_forward(news_path, at - WINDOW)
        news = NO_NEWS_RECORD if items is None else items
    except StoreError:
        news = NEWS_UNREADABLE
    return filter_view(score, news, at, coins)
