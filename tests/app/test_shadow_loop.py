"""Spec 0052 AC-1, AC-5, AC-7, AC-8, AC-9 (plan step 4, Risk 1, 7, 8): paper döngüsünün gölge
adımı. Aynı girdilerle gölge ayarlı ve ayarsız döngü aynı alımları, kapanışları, risk kararlarını,
bildirimleri, tur sonucunu ve bot deposunu üretir; gölge adımın hatası turu etkilemez."""

import itertools
import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.__main__ import shadow_append, shadow_view
from crytobot.app import (
    LoopExit,
    LoopParts,
    PairFilter,
    ShadowConfig,
    ShadowParts,
    TurnOutcome,
    prepare_live_store,
)
from crytobot.market_data import MarketRead
from crytobot.news import (
    EventScore,
    NewsItem,
    NewsStore,
    ResultKind,
    ScoreResult,
    ScoreStore,
    SourceState,
)
from crytobot.persistence import create_store
from crytobot.reporting import ReportingService, TelegramConfig
from tests.app.helpers import BTC, CROSS, ETH, make_settings, opened_store
from tests.app.loop_fakes import START, Harness, harness, pair_read
from tests.app.test_live_loop import MockLiveExchange
from tests.app.test_live_start import FakeLiveClient

TELEGRAM = TelegramConfig(enabled=True, bot_token="token-123", chat_id="chat-456")
SECRET = "gizli-yol-ve-anahtar"
PAIRS = (BTC, ETH)
FIELDS = {
    "version",
    "turn_at",
    "pair",
    "whitelist",
    "state",
    "reason",
    "events",
    "missing",
    "held",
    "technical_buy",
    "technical_reason",
    "risk",
    "order",
}


@dataclass
class Record:
    """Sahte gölge parçaları: görünüm hep `state` verir; `fail_*` n'inci çağrıda fırlatır."""

    state: str = "bastırılırdı"
    views: list[tuple[datetime, tuple[str, ...]]] = field(default_factory=list)
    turns: list[list[Mapping[str, object]]] = field(default_factory=list)
    appends: int = 0
    fail_views: frozenset[int] = frozenset()
    fail_appends: frozenset[int] = frozenset()

    def view(self, at: datetime, pairs: tuple[str, ...]) -> dict[str, PairFilter]:
        self.views.append((at, pairs))
        if len(self.views) - 1 in self.fail_views:
            raise RuntimeError(SECRET)
        missing = None if self.state == "filtre yok" else (0, 0, 0)
        return {pair: PairFilter(self.state, "neden", ((1, 3),), missing) for pair in pairs}

    def append(self, rows: Sequence[Mapping[str, object]]) -> None:
        index = self.appends
        self.appends += 1
        if index in self.fail_appends:
            raise OSError(SECRET)
        self.turns.append(list(rows))

    @property
    def parts(self) -> ShadowParts:
        return ShadowParts(self.view, self.append)


@dataclass
class ShadowHarness(Harness):
    shadow: ShadowParts | None = None

    def parts(self) -> LoopParts:
        return replace(super().parts(), shadow=self.shadow)


def closing_read(at: datetime) -> MarketRead:
    """İkinci tur: BTC fiyatı stop'un altına iner, açık pozisyon kapanır."""
    return MarketRead(
        (pair_read(BTC, at, (10.0, 8.0, 9.0, 7.0)), pair_read(ETH, at, CROSS)), at, None
    )


@dataclass
class Run:
    exit: LoopExit
    lines: list[str]
    sent: list[str]
    store: list[str]
    reads: list[datetime]


def dump(path: Path) -> list[str]:
    with sqlite3.connect(path) as connection:
        return list(connection.iterdump())


def run_bot(root: Path, shadow: ShadowParts | None, stop_after: int = 3) -> Run:
    root.mkdir(parents=True, exist_ok=True)
    store = opened_store(root / "s.db")
    sent: list[str] = []

    def transport(url: str, payload: dict[str, Any]) -> tuple[int, str]:
        sent.append(str(payload.get("text")))
        return 200, '{"ok":true}'

    base = harness(store, turn=make_settings(PAIRS), closes=CROSS, stop_after=stop_after)
    bot = ShadowHarness(
        base.store,
        base.config,
        closes=CROSS,
        stop_after=stop_after,
        answers={1: closing_read},
        shadow=shadow,
    )
    exit_ = bot.run(reporter=ReportingService(TELEGRAM, transport=transport))
    lines = [text.replace(str(store), "<depo>") for text in bot.lines]
    return Run(exit_, lines, sent, dump(store), bot.read_times())


def assert_same(plain: Run, shadowed: Run) -> None:
    assert shadowed.exit == plain.exit
    assert shadowed.lines == plain.lines
    assert shadowed.sent == plain.sent
    assert shadowed.store == plain.store
    assert shadowed.reads == plain.reads


def test_completed_turn_writes_row_per_whitelist_pair(tmp_path: Path) -> None:
    record = Record()
    run = run_bot(tmp_path, record.parts)
    assert run.exit.turns == 3
    assert len(record.turns) == 3  # one append per completed turn
    for rows, (at, pairs), read_at in zip(record.turns, record.views, run.reads, strict=True):
        assert pairs == PAIRS
        assert at == read_at + timedelta(seconds=2)  # the turn's time is the read's time
        assert [row["pair"] for row in rows] == [BTC, ETH]
        for row in rows:
            assert set(row) == FIELDS
            assert row["turn_at"] == at.isoformat()
            assert row["whitelist"] == [BTC, ETH]
            assert row["state"] == "bastırılırdı"
            assert row["events"] == [{"news_id": 1, "severity": 3}]
        json.dumps(rows, ensure_ascii=False)  # plain data, JSON-ready


def test_risk_result_on_technical_buy(tmp_path: Path) -> None:
    record = Record()
    run_bot(tmp_path, record.parts)
    first = {row["pair"]: row for row in record.turns[0]}
    assert (first[BTC]["technical_buy"], first[BTC]["risk"]) == ("var", "onay")  # bought
    assert first[ETH]["technical_buy"] == "var"
    assert first[ETH]["risk"] == "onay"  # approved and bought as well


def test_no_section_no_rows_same_turn(tmp_path: Path) -> None:
    plain = run_bot(tmp_path / "plain", None)
    record = Record()
    assert record.views == [] and record.turns == []
    assert plain.exit.turns == 3
    assert all(" gölge" not in text for text in plain.lines)
    assert_same(plain, run_bot(tmp_path / "shadow", record.parts))


@pytest.mark.parametrize("state", ["bastırılırdı", "bastırılmazdı — eksik bilgi"])
def test_parity_with_and_without_shadow(tmp_path: Path, state: str) -> None:
    """AC-7: `bastırılırdı`'da da alım olur; kapanış, risk, bildirim, sonuç ve depo aynı."""
    plain = run_bot(tmp_path / "plain", None)
    record = Record(state)
    shadowed = run_bot(tmp_path / "shadow", record.parts)
    assert_same(plain, shadowed)
    assert any("İŞLEM DOLUMU" in text for text in plain.sent)
    assert any("POZİSYON KAPANDI" in text for text in plain.sent)
    assert all(row["state"] == state for rows in record.turns for row in rows)


def test_no_filter_same_decisions(tmp_path: Path) -> None:
    plain = run_bot(tmp_path / "plain", None)
    record = Record("filtre yok")
    assert_same(plain, run_bot(tmp_path / "shadow", record.parts))
    assert all(row["missing"] is None for rows in record.turns for row in rows)


def test_refused_turn_no_rows(tmp_path: Path) -> None:
    store = tmp_path / "s.db"
    assert create_store(store, "paper").state is not None  # the ledger is never opened
    record = Record()
    base = harness(store, stop_after=2)
    bot = ShadowHarness(base.store, base.config, stop_after=2, shadow=record.parts)
    exit_ = bot.run()
    assert exit_.last is not None
    assert exit_.last.outcome is TurnOutcome.LEDGER_NOT_OPENED
    assert record.views == [] and record.turns == []


@pytest.mark.parametrize(
    ("record", "error"),
    [
        (Record(fail_appends=frozenset({0})), "OSError"),
        (Record(fail_views=frozenset({0})), "RuntimeError"),  # plan Risk 8
    ],
    ids=["write", "view"],
)
def test_write_failure_logged_turn_unchanged_retry_next(
    tmp_path: Path, record: Record, error: str
) -> None:
    plain = run_bot(tmp_path / "plain", None)
    shadowed = run_bot(tmp_path / "shadow", record.parts)
    failure = f" hata döngü hatası: gölge kayıt {error}"
    assert [text for text in shadowed.lines if failure in text] == [
        f"{plain.lines[1].split(' ', 1)[0]}{failure}"
    ]
    assert all(SECRET not in text for text in shadowed.lines)
    kept = [text for text in shadowed.lines if failure not in text]
    assert kept == plain.lines  # the turn's lines, result and store are unchanged
    assert_same(plain, replace(shadowed, lines=kept))
    assert len(record.turns) == 2  # the failed turn stays a gap; the next turns write


def test_append_only_prefix_preserved(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    path.write_bytes(b'{"version": "1", "turn_at": "2026-11-0')  # a torn line from a crash
    append = shadow_append(str(path))
    seen: list[bytes] = [path.read_bytes()]

    def recording(rows: Sequence[Mapping[str, object]]) -> None:
        append(rows)
        seen.append(path.read_bytes())

    record = Record()
    run_bot(tmp_path / "bot", ShadowParts(record.view, recording))
    assert len(seen) == 4
    for before, after in itertools.pairwise(seen):
        assert after.startswith(before)  # nothing rewritten, only appended
    lines = path.read_bytes().split(b"\n")
    assert lines[0] == seen[0]  # the torn line stays apart
    assert lines[-1] == b""
    rows = [json.loads(raw) for raw in lines[1:-1]]
    assert len(rows) == 6 and {row["pair"] for row in rows} == {BTC, ETH}


def test_score_and_news_unchanged_after_turn(tmp_path: Path) -> None:
    """Gerçek görünüm: skor ve haber kaydı yalnız okunur, turdan sonra baytları aynıdır."""
    news_path, score_path = tmp_path / "news.db", tmp_path / "score.db"
    news = NewsStore.open(str(news_path))
    news.write(
        "binance",
        [NewsItem("id:1", None, "BTC delist", "t", False, None, START - timedelta(hours=1))],
        SourceState(),
    )
    news.close()
    score = ScoreStore.open(str(score_path), START - timedelta(days=1))
    score.write_result(
        ScoreResult(
            1,
            ResultKind.SCORED,
            START - timedelta(minutes=50),
            scores=(EventScore("BTC", "Bitcoin", "listeden çıkarma", "olumsuz", 3, "q"),),
        )
    )
    score.mark_round(START - timedelta(minutes=1), None)
    score.close()
    before = {path.name: path.read_bytes() for path in (news_path, score_path)}
    rows: list[Mapping[str, object]] = []
    view = shadow_view(ShadowConfig(str(tmp_path / "x.jsonl"), str(score_path), str(news_path)))
    run_bot(tmp_path / "bot", ShadowParts(view, rows.extend), stop_after=1)
    assert {path.name: path.read_bytes() for path in (news_path, score_path)} == before
    first = {row["pair"]: row for row in rows}
    assert first[BTC]["state"] == "bastırılırdı"
    assert first[BTC]["events"] == [{"news_id": 1, "severity": 3}]
    assert first[ETH]["state"] == "bastırılmazdı"
    assert first[BTC]["technical_buy"] == "var" and first[BTC]["risk"] == "onay"  # still bought


def run_live(root: Path, shadow: ShadowParts | None) -> tuple[LoopExit, list[str], list[str]]:
    """Live modda iki tur (sahte canlı borsa): çıkış, satırlar, depo dökümü."""
    root.mkdir(parents=True, exist_ok=True)
    store = root / "bot.db"
    prepare_live_store(str(store), START, live_client=FakeLiveClient(free_balance=Decimal(1000)))
    base = harness(store, turn=make_settings(PAIRS), closes=CROSS, stop_after=2)
    bot = ShadowHarness(
        base.store,
        replace(base.config, mode="live"),
        closes=CROSS,
        stop_after=2,
        shadow=shadow,
    )
    exit_ = bot.run(exchange=MockLiveExchange())  # type: ignore[arg-type]
    lines = [text.replace(str(store), "<depo>") for text in bot.lines]
    return exit_, lines, dump(store)


def test_live_loop_never_calls_shadow(tmp_path: Path) -> None:
    """AC-7 (fix-1, M-1): live döngüde parçalar verilse de görünüm ve yazma hiç çağrılmaz; tur
    sonucu, satırlar ve depo gölgesiz koşuyla aynı (`_loop.py` mod koruması)."""
    plain = run_live(tmp_path / "plain", None)
    record = Record()
    shadowed = run_live(tmp_path / "shadow", record.parts)
    assert plain[0].turns == 2
    assert record.views == [] and record.appends == 0
    assert shadowed == plain
