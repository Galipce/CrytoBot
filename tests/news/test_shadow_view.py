"""Spec 0052 AC-2, AC-3, AC-4, AC-5 (plan step 3, Risk 3, 6): tur anında coin başına filtre durumu.
Gerçek haber kaydı ve gerçek skor kaydı yazılır, görünüm onları yalnız okur."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crytobot.news import (
    CoinFilter,
    EventRef,
    EventScore,
    FilterState,
    MissingCounts,
    NewsItem,
    NewsStore,
    ResultKind,
    ScoreResult,
    ScoreStore,
    SourceState,
    base_of,
    read_filter_view,
)

T = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
COINS = ("BTC", "ETH")


@dataclass
class Records:
    root: Path
    started: datetime = T - timedelta(days=2)
    count: int = 0
    marked: bool = True
    _score: ScoreStore | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.news = NewsStore.open(self.news_path)

    @property
    def news_path(self) -> str:
        return str(self.root / "news.db")

    @property
    def score_path(self) -> str:
        return str(self.root / "score.db")

    @property
    def score(self) -> ScoreStore:
        if self._score is None:
            self._score = ScoreStore.open(self.score_path, self.started)
            if self.marked:
                self._score.mark_round(T - timedelta(minutes=5), None)
        return self._score

    def add(
        self,
        seen: datetime,
        *events: EventScore,
        kind: ResultKind | None = ResultKind.SCORED,
        scored_at: datetime | None = None,
    ) -> int:
        self.count += 1
        item = NewsItem(f"id:{self.count}", None, f"News {self.count}", "t", False, None, seen)
        self.news.write("binance", [item], SourceState())
        store = self.score
        if kind is not None:
            store.write_result(
                ScoreResult(self.count, kind, scored_at or seen, scores=tuple(events))
            )
        return self.count

    def view(self, at: datetime = T, coins: tuple[str, ...] = COINS) -> dict[str, CoinFilter]:
        self.score  # noqa: B018 - the record exists
        return dict(read_filter_view(self.score_path, self.news_path, at, coins))

    def close(self) -> None:
        self.news.close()
        if self._score is not None:
            self._score.close()


@pytest.fixture
def records(tmp_path: Path) -> Records:
    return Records(tmp_path)


def negative(coin: str = "BTC", severity: int = 2, direction: str = "olumsuz") -> EventScore:
    return EventScore(coin, coin, "listeden çıkarma", direction, severity, "quote")


NONE_MISSING = MissingCounts(0, 0, 0)


@pytest.mark.parametrize("severity", [2, 3])
def test_negative_severity_2_and_3_suppress(records: Records, severity: int) -> None:
    news_id = records.add(T - timedelta(hours=3), negative(severity=severity))
    view = records.view()
    assert view["BTC"] == CoinFilter(
        FilterState.SUPPRESS, "olumsuz olay", (EventRef(news_id, severity),), NONE_MISSING, None
    )
    assert view["ETH"] == CoinFilter(FilterState.PASS, "olumsuz olay yok", (), NONE_MISSING)


@pytest.mark.parametrize(
    ("score", "seen"),
    [
        (negative(severity=1), T - timedelta(hours=1)),
        (negative(direction="olumlu", severity=3), T - timedelta(hours=1)),
        (negative(direction="belirsiz", severity=3), T - timedelta(hours=1)),
        (negative("XRP", 3), T - timedelta(hours=1)),  # outside the whitelist
        (negative("ETH", 3), T - timedelta(hours=1)),  # another coin
        (negative(severity=3), T - timedelta(hours=24, microseconds=1)),  # older than 24 h
    ],
    ids=["severity-1", "positive", "uncertain", "not-whitelisted", "other-coin", "older-24h"],
)
def test_not_suppressing_cases(records: Records, score: EventScore, seen: datetime) -> None:
    records.add(seen, score)
    view = records.view()
    assert set(view) == set(COINS)
    assert view["BTC"].state == FilterState.PASS
    assert view["BTC"].events == ()


def test_exact_24h_counts(records: Records) -> None:
    news_id = records.add(T - timedelta(hours=24), negative())
    assert records.view()["BTC"].events == (EventRef(news_id, 2),)
    assert records.view()["BTC"].state == FilterState.SUPPRESS


@pytest.mark.parametrize("coin", ["btc", "BTCB", "WBTC", "BTC/USDT"])
def test_coin_matches_base_exactly(records: Records, coin: str) -> None:
    records.add(T - timedelta(hours=1), negative(coin, 3))
    assert records.view()["BTC"].state == FilterState.PASS
    assert base_of("BTC/USDT") == "BTC"
    assert base_of("ETH/USDT") == "ETH"


def test_score_after_turn_ignored_equal_counts(records: Records) -> None:
    later = records.add(T - timedelta(hours=1), negative(), scored_at=T + timedelta(seconds=1))
    view = records.view()["BTC"]
    assert view.state == FilterState.PASS_MISSING  # unknown at T: still pending
    assert view.events == ()
    assert view.missing == MissingCounts(1, 0, 0)
    equal = records.add(T - timedelta(hours=1), negative(severity=3), scored_at=T)
    view = records.view()["BTC"]
    assert view.state == FilterState.SUPPRESS
    assert view.events == (EventRef(equal, 3),)
    assert later not in {ref.news_id for ref in view.events}


def test_news_seen_after_turn_outside_window(records: Records) -> None:
    records.add(T + timedelta(seconds=1), negative(severity=3))
    records.add(T + timedelta(minutes=1), kind=None)  # pending, but after T
    view = records.view()["BTC"]
    assert view.state == FilterState.PASS
    assert view.missing == NONE_MISSING


def test_missing_counts_by_kind(records: Records) -> None:
    for _ in range(2):
        records.add(T - timedelta(hours=2), kind=None)
    records.add(T - timedelta(hours=2), kind=ResultKind.SCHEMA)
    records.add(T - timedelta(hours=2), kind=ResultKind.STALE)
    records.add(T - timedelta(hours=2))  # scored, no events
    records.add(T - timedelta(hours=30), kind=None)  # outside the window
    view = records.view()
    for coin in COINS:
        assert view[coin].state == FilterState.PASS_MISSING
        assert view[coin].reason == "eksik bilgi"
        assert view[coin].missing == MissingCounts(2, 1, 1)


def test_missing_with_and_without_negative(records: Records) -> None:
    records.add(T - timedelta(hours=2), kind=None)
    news_id = records.add(T - timedelta(hours=1), negative("ETH", 2))
    view = records.view()
    assert view["BTC"].state == FilterState.PASS_MISSING
    assert view["ETH"].state == FilterState.SUPPRESS  # missing info never lifts a suppression
    assert view["ETH"].events == (EventRef(news_id, 2),)
    assert view["ETH"].missing == MissingCounts(1, 0, 0)  # still written


@pytest.mark.parametrize("held", ["kota beklemesi", "günlük sınır dolu", None])
def test_held_quota_and_daily_limit(records: Records, held: str | None) -> None:
    records.marked = False
    records.score.mark_round(T - timedelta(minutes=10), None)
    records.score.mark_round(T - timedelta(minutes=2), held)
    records.score.mark_round(T + timedelta(minutes=1), "kota beklemesi")  # after T: unseen
    assert records.view()["BTC"].held == held


def garbage(path: str) -> None:
    Path(path).write_bytes(b"not a database at all" * 100)


def remove(path: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(path + suffix).unlink(missing_ok=True)


def no_score(records: Records) -> None:
    records.score.close()
    records._score = None
    remove(records.score_path)


def score_unreadable(records: Records) -> None:
    no_score(records)
    garbage(records.score_path)


def started_after(records: Records) -> None:
    no_score(records)
    records.started = T + timedelta(seconds=1)
    records.score  # noqa: B018 - reopened: the start is written once, on open


def no_news(records: Records) -> None:
    records.news.close()
    remove(records.news_path)


def news_unreadable(records: Records) -> None:
    no_news(records)
    garbage(records.news_path)


def marks_only(*moments: datetime) -> Callable[[Records], None]:
    def arrange(records: Records) -> None:
        no_score(records)
        records.marked = False
        store = records.score  # reopened without the default mark
        for moment in moments:
            store.mark_round(moment, None)

    return arrange


def no_rounds_table(records: Records) -> None:
    """0051'de açılmış kayıt: `rounds` tablosu yok."""
    records.score.close()
    records._score = None
    with sqlite3.connect(records.score_path) as connection:
        connection.execute("DROP TRIGGER rounds_no_update")
        connection.execute("DROP TRIGGER rounds_no_delete")
        connection.execute("DROP TABLE rounds")


@pytest.mark.parametrize(
    ("arrange", "reason"),
    [
        (no_score, "skor kaydı yok"),
        (score_unreadable, "skor kaydı okunamıyor"),
        (started_after, "skor kaydı tur anından sonra başladı"),
        (no_news, "haber kaydı yok"),
        (news_unreadable, "haber kaydı okunamıyor"),
        (marks_only(), "skorlayıcı durmuş"),
        (no_rounds_table, "skorlayıcı durmuş"),
        (marks_only(T - timedelta(minutes=30, microseconds=1)), "skorlayıcı durmuş"),
        (marks_only(T + timedelta(seconds=1)), "skorlayıcı durmuş"),  # only a mark after T
    ],
    ids=[
        "no-score",
        "score-unreadable",
        "started-after",
        "no-news",
        "news-unreadable",
        "no-mark",
        "no-rounds-table",
        "mark-older-30m",
        "mark-after-turn",
    ],
)
def test_no_filter_reasons(
    records: Records, arrange: Callable[[Records], None], reason: str
) -> None:
    records.add(T - timedelta(hours=1), negative(severity=3))
    arrange(records)
    view = dict(read_filter_view(records.score_path, records.news_path, T, COINS))
    for coin in COINS:
        assert view[coin] == CoinFilter(FilterState.NONE, reason), coin


def test_exactly_30_minutes_is_live(records: Records) -> None:
    records.marked = False
    records.score.mark_round(T - timedelta(minutes=30), None)
    assert records.view()["BTC"].state == FilterState.PASS


def test_reading_never_writes_nor_waits(records: Records) -> None:
    """Okuma yazmaz; yazarın açık işlemi okumayı bekletmez (R-6)."""
    records.add(T - timedelta(hours=1), negative())
    before = {name: Path(records.root / name).read_bytes() for name in ("news.db", "score.db")}
    writer = sqlite3.connect(records.score_path, timeout=0, isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")
    try:
        assert records.view()["BTC"].state == FilterState.SUPPRESS
    finally:
        writer.execute("ROLLBACK")
        writer.close()
    after = {name: Path(records.root / name).read_bytes() for name in ("news.db", "score.db")}
    assert before == after
    missing = records.root / "absent"
    view = read_filter_view(str(missing / "score.db"), str(missing / "news.db"), T, COINS)
    assert view["BTC"].reason == "skor kaydı yok"
    assert not missing.exists()
