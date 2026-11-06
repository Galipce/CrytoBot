"""Spec 0022 AC-10 (R-11, B-48): borsa yasağı sonraki okumalara taşınır; bitişe kadar okuma yok.

Yasak süresince turlar sürer, piyasa verisi verilmez: veri eksiktir, alım durur, fiyatsız kapanış
yapılmaz (BR-11).
"""

from datetime import datetime, timedelta
from pathlib import Path

from crytobot.app import ExitReason
from crytobot.persistence import load_store
from tests.app.helpers import BTC, CROSS, HOUR, NOW, bot_with_position, opened_store
from tests.app.loop_fakes import START, banned_read, harness

DAY = timedelta(days=1)


def ban_for(length: timedelta | None):  # type: ignore[no-untyped-def]
    def build(at: datetime):  # type: ignore[no-untyped-def]
        return banned_read(at, None if length is None else at + length)

    return build


def test_ban_with_retry_after_sends_nothing_until_end(tmp_path: Path) -> None:
    bot = harness(opened_store(tmp_path / "s.db"), stop_after=4, answers={0: ban_for(2.5 * HOUR)})
    exit_ = bot.run()
    assert exit_.turns == 4
    # banned at 12:20 until 14:50: the 13:00 and 14:00 turns send nothing, 15:00 reads again
    assert bot.read_times() == [START, NOW + 3 * HOUR]
    first, during_1, during_2, after = bot.events("tur")
    assert "veri=yasak" in during_1 and "veri=yasak" in during_2
    assert "veri=yasak" not in first and "veri=yasak" not in after


def test_ban_without_retry_after_waits_one_interval(tmp_path: Path) -> None:
    bot = harness(opened_store(tmp_path / "s.db"), stop_after=3, answers={0: ban_for(None)})
    bot.run()
    first, second = bot.read_times()
    banned_at = first + timedelta(seconds=bot.read_seconds)
    assert second >= banned_at + HOUR
    assert second == NOW + 2 * HOUR


def test_days_long_ban_is_not_clipped(tmp_path: Path) -> None:
    """`Retry-After`'ın üst sınırı yoktur: 3 gün olduğu gibi uygulanır."""
    store = opened_store(tmp_path / "s.db")
    bot = harness(store, interval=DAY, stop_after=5, answers={0: ban_for(3 * DAY)})
    bot.run()
    first, second = bot.read_times()
    assert second - first >= 3 * DAY
    assert len(bot.events("tur")) == 5
    assert sum("veri=yasak" in text for text in bot.events("tur")) == 3


def test_ban_start_and_end_are_reported(tmp_path: Path) -> None:
    bot = harness(opened_store(tmp_path / "s.db"), stop_after=4, answers={0: ban_for(2.5 * HOUR)})
    bot.run()
    until = START + timedelta(seconds=bot.read_seconds) + 2.5 * HOUR
    started, ended = bot.events("yasak")
    assert f"borsa yasağı başladı: bitiş {until.isoformat(timespec='seconds')}" in started
    assert f"borsa yasağı bitti: bitiş {until.isoformat(timespec='seconds')}" in ended


def test_open_ban_is_reported_with_its_earliest_read(tmp_path: Path) -> None:
    bot = harness(opened_store(tmp_path / "s.db"), stop_after=1, answers={0: ban_for(None)})
    bot.run()
    earliest = START + timedelta(seconds=bot.read_seconds) + HOUR
    (started,) = bot.events("yasak")
    assert f"bitiş bildirilmedi; sonraki okuma en erken {earliest.isoformat()}" in started


def test_ban_turns_buy_nothing_and_close_nothing(tmp_path: Path) -> None:
    """BR-11: yasak turlarında veri yok: alım yok, fiyatsız kapanış yok, pozisyon açık kalır."""
    bot_before = bot_with_position(tmp_path / "s.db")
    positions = bot_before.stored().ledger.positions
    bot = harness(bot_before.path, closes=CROSS, stop_after=3, answers={0: ban_for(5 * HOUR)})
    exit_ = bot.run()
    assert exit_.reason is ExitReason.STOPPED
    for text in bot.events("tur"):
        assert "alım=0 kapanış=0" in text
    for text in bot.events("tur")[1:]:
        assert "durdurma=invalid_data" in text
    stored = load_store(bot.store, "paper").state
    assert stored is not None and stored.ledger.positions == positions
    assert not stored.ledger.closures
    assert all(BTC in pairs for pairs, _ in bot.reads)
