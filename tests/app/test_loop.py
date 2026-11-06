"""Spec 0022 AC-1, AC-8, AC-9, AC-12, AC-13 (R-8…R-10, R-13…R-15): döngünün turları ve çıktısı.

Sahte saatle koşar, gerçek bekleme yoktur (plan Risk 10).
"""

from datetime import timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import TRIAL_MARK, ExitReason, LogWriteError, TurnMemory, _loop
from crytobot.app._turn import run_turn
from crytobot.execution import OrderStatus
from crytobot.market_data import InputProblem, MarketRead
from crytobot.persistence import load_store
from tests.app.helpers import BTC, CROSS, HOUR, NOW, Exchange, opened_store
from tests.app.loop_fakes import START, harness, refused_read

SECRET = "apiKey=AKIAABCDEF0123456789 secret=s3cr3t-T0KEN"


def test_first_turn_runs_at_once_then_on_boundaries(tmp_path: Path) -> None:
    """R-8: ilk tur hemen, sonrakiler UTC saat başlarında."""
    bot = harness(opened_store(tmp_path / "s.db"), stop_after=3)
    exit_ = bot.run()
    assert exit_.reason is ExitReason.STOPPED and exit_.turns == 3
    assert bot.read_times() == [START, NOW + HOUR, NOW + 2 * HOUR]
    summaries = bot.events("tur")
    assert len(summaries) == 3
    assert all("sonuç=completed" in text and "kaçan_sınır=0" in text for text in summaries)


def test_each_turn_uses_its_own_read_and_one_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R-9: turun `now`'ı o turun okumasının saatidir; süreç belleği tek nesnedir."""
    seen: list[tuple[Any, TurnMemory, tuple[str, ...]]] = []

    def spy(**kwargs: Any) -> Any:
        seen.append((kwargs["now"], kwargs["memory"], tuple(kwargs["market"])))
        return run_turn(**kwargs)

    monkeypatch.setattr(_loop, "run_turn", spy)
    bot = harness(opened_store(tmp_path / "s.db"), stop_after=3)
    bot.run()
    read_at = [at + timedelta(seconds=bot.read_seconds) for at in bot.read_times()]
    assert [now for now, _, _ in seen] == read_at
    assert len({id(memory) for _, memory, _ in seen}) == 1
    assert all(pairs == (BTC,) for _, _, pairs in seen)
    for at, text in zip(read_at, bot.events("tur"), strict=True):
        assert f"an={at.isoformat(timespec='seconds')}" in text


def test_open_positions_are_read_with_the_whitelist(tmp_path: Path) -> None:
    """R-9: beyaz liste ve açık pozisyonların çiftleri okunur; pozisyon depodan bilinir."""
    bot = harness(opened_store(tmp_path / "s.db"), closes=CROSS, stop_after=2)
    bot.config = type(bot.config)(
        bot.config.store_path,
        bot.config.log_path,
        bot.config.turn_interval,
        bot.config.opening_balance,
        bot.config.read,
        type(bot.config.turn)(**{**vars(bot.config.turn), "whitelist": ("ETH/USDT",)}),
    )
    bot.run()
    first, second = (pairs for pairs, _ in bot.reads)
    assert first == ("ETH/USDT",)
    assert second == ("ETH/USDT",)  # ETH bought; still read once
    stored = load_store(bot.store, "paper").state
    assert stored is not None and {p.pair for p in stored.ledger.positions.values()} == {"ETH/USDT"}


def test_turns_never_overlap(tmp_path: Path) -> None:
    """R-8: uzun tur bir sonraki sınırı aşar: ikinci tur ilki bitmeden başlamaz, kaçan sayılır."""
    bot = harness(opened_store(tmp_path / "s.db"), stop_after=3, read_seconds=1.5 * 3600)
    bot.run()
    starts = bot.read_times()
    for before, after in pairwise(starts):
        assert after >= before + timedelta(seconds=bot.read_seconds)
    assert starts == [START, NOW + 2 * HOUR, NOW + 4 * HOUR]
    first, second, third = bot.events("tur")
    assert "kaçan_sınır=0" in first
    assert "kaçan_sınır=1" in second and "kaçan_sınır=1" in third


def test_start_line_and_every_summary_carry_the_trial_mark(tmp_path: Path) -> None:
    """R-14, BR-10: başlatma kaydı ve her tur özeti deneme işaretini taşır."""
    bot = harness(opened_store(tmp_path / "s.db"), stop_after=2)
    bot.run()
    (start,) = bot.events("başlatma")
    assert TRIAL_MARK in start and "mod=paper" in start
    assert len(bot.events("tur")) == 2
    assert all(TRIAL_MARK in text for text in bot.events("tur"))


REFUSALS = [*InputProblem]


@pytest.mark.parametrize("problem", REFUSALS, ids=[p.value for p in REFUSALS])
def test_refused_read_starts_no_turn_and_stops(tmp_path: Path, problem: InputProblem) -> None:
    """R-10, B-50: reddedilen okumada tur yok, depo değişmez, ret adıyla yazılır, döngü durur."""
    store = opened_store(tmp_path / "s.db")
    before = load_store(store, "paper").state
    bot = harness(store, stop_after=None, answers={1: refused_read(problem)})
    exit_ = bot.run()
    assert exit_.reason is ExitReason.READ_REFUSED
    assert exit_.turns == 1 and len(bot.reads) == 2
    assert len(bot.events("tur")) == 1
    (refused,) = bot.events("okuma")
    assert f"okuma reddedildi: {problem.value}" in refused
    after = load_store(store, "paper").state
    assert before is not None and after is not None
    assert after.ledger == before.ledger and after.execution == before.execution
    assert "neden=okuma reddi" in bot.events("durdurma")[0]


def test_read_without_a_time_is_refused_as_clock(tmp_path: Path) -> None:
    bot = harness(opened_store(tmp_path / "s.db"), answers={0: MarketRead((), None, None)})
    exit_ = bot.run()
    assert exit_.reason is ExitReason.READ_REFUSED and exit_.turns == 0
    assert "okuma reddedildi: clock" in bot.events("okuma")[0]


def test_loop_error_is_logged_by_type_and_loop_goes_on(tmp_path: Path) -> None:
    """R-15: okuma hatası çökertmez; tip adıyla yazılır, o sınırda tur yok, sonrakinde tur var."""
    bot = harness(opened_store(tmp_path / "s.db"), answers={0: RuntimeError(SECRET)})
    exit_ = bot.run()
    assert exit_.reason is ExitReason.STOPPED and exit_.turns == 1
    (error,) = bot.events("hata")
    assert error.endswith("döngü hatası: okuma RuntimeError")
    assert bot.read_times() == [START, NOW + HOUR]


def test_missed_boundaries_survive_a_failed_turn(tmp_path: Path) -> None:
    """R-8 (review L-1): uykudan sonra okuma hata verirse kaçan sınırlar sonraki özete girer."""

    def sleep(bot: Any) -> None:
        bot.clock.advance(3 * 3600)  # NOW+1h and NOW+2h are never seen

    bot = harness(
        opened_store(tmp_path / "s.db"),
        stop_after=2,
        wait_hooks={0: sleep},
        answers={1: RuntimeError("x")},
    )
    bot.run()
    woke, after = bot.read_times()[1:]
    assert NOW + 3 * HOUR < woke < NOW + 4 * HOUR and after == NOW + 4 * HOUR
    assert len(bot.events("hata")) == 1
    first, second = bot.events("tur")
    assert "kaçan_sınır=0" in first
    assert "kaçan_sınır=2" in second


def test_error_text_and_secrets_never_logged(tmp_path: Path) -> None:
    """R-15: saat, bekleme ve okuma hatalarının metni hiçbir satırda yoktur."""
    bot = harness(opened_store(tmp_path / "s.db"), stop_after=2, answers={0: ValueError(SECRET)})
    real_clock = bot.clock
    calls = {"clock": 0, "wait": 0}

    def flaky_clock() -> Any:
        calls["clock"] += 1
        if calls["clock"] == 3:
            raise OSError(SECRET)
        return real_clock()

    def flaky_wait(seconds: float) -> None:
        calls["wait"] += 1
        if calls["wait"] == 1:
            raise KeyError(SECRET)
        bot.wait(seconds)

    parts = bot.parts()
    exit_ = _loop.run_loop(
        bot.config, type(parts)(flaky_clock, flaky_wait, bot.read, bot.write, bot.stop)
    )
    assert exit_.turns == 2
    errors = bot.events("hata")
    assert {text.rsplit(" ", 2)[-2:][0] for text in errors} >= {"okuma", "saat"}
    assert any(text.endswith("bekleme KeyError") for text in errors)
    for text in bot.lines:
        assert "s3cr3t" not in text and "AKIA" not in text and "apiKey" not in text


def test_a_failing_step_is_logged_once_while_it_keeps_failing(tmp_path: Path) -> None:
    bot = harness(opened_store(tmp_path / "s.db"), stop_after=1)
    failures = {"left": 5}

    def wait(seconds: float) -> None:
        if failures["left"]:
            failures["left"] -= 1
            raise OSError("x")
        bot.wait(seconds)

    bot.answers = {0: RuntimeError("x")}
    parts = bot.parts()
    _loop.run_loop(bot.config, type(parts)(bot.clock, wait, bot.read, bot.write, bot.stop))
    assert [text.split(" ", 2)[2] for text in bot.events("hata")] == [
        "döngü hatası: okuma RuntimeError",
        "döngü hatası: bekleme OSError",
    ]


def test_clock_without_time_zone_is_a_loop_error(tmp_path: Path) -> None:
    bot = harness(opened_store(tmp_path / "s.db"))
    values = iter([NOW.replace(tzinfo=None)])

    def clock() -> Any:
        return next(values, None) or bot.clock()

    parts = bot.parts()
    exit_ = _loop.run_loop(bot.config, type(parts)(clock, bot.wait, bot.read, bot.write, bot.stop))
    assert exit_.turns == 1
    assert bot.events("hata")[0].endswith("döngü hatası: saat TypeError")


def test_restart_reannounces_ongoing_states(tmp_path: Path) -> None:
    """R-13: süreç belleği kalıcı değildir; yeni süreç süren durumu yeniden "başladı" bildirir."""
    store = opened_store(tmp_path / "s.db")
    unknown = Exchange(place={"cb-": OrderStatus.UNKNOWN})
    first = harness(store, closes=CROSS)
    first.run(exchange=unknown)
    second = harness(store, closes=CROSS)
    second.run(exchange=unknown)
    for bot in (first, second):
        entered = [t for t in bot.events("durum") if "durum başladı: safe_mode" in t]
        assert len(entered) == 1


def test_unwritable_log_stops_the_loop_before_a_turn(tmp_path: Path) -> None:
    """R-15: kayıt dosyası yazılamıyor: bot durur; satır konsola gitmiştir (yazıcının işi)."""
    bot = harness(opened_store(tmp_path / "s.db"), write_error=LogWriteError())
    exit_ = bot.run()
    assert exit_.reason is ExitReason.LOG_FAILED and exit_.turns == 0
    assert bot.reads == []


def test_log_failing_during_a_turn_stops_after_that_turn(tmp_path: Path) -> None:
    bot = harness(opened_store(tmp_path / "s.db"), stop_after=None)

    def fail_from_now(_: Any) -> None:
        bot.write_error = LogWriteError()

    bot.read_hooks = {1: fail_from_now}
    exit_ = bot.run()
    assert exit_.reason is ExitReason.LOG_FAILED and exit_.turns == 2
    assert len(bot.reads) == 2
