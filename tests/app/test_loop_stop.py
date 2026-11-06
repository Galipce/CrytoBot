"""Spec 0022 AC-11 (R-12): temiz durdurma; ikinci istek anında çıkarır; çıkış kaydı."""

from pathlib import Path

from crytobot.app import ExitReason, ForcedStop, StopRequest
from crytobot.persistence import load_store
from tests.app.helpers import CROSS, opened_store
from tests.app.loop_fakes import Harness, harness


def request(source: str = "SIGINT"):  # type: ignore[no-untyped-def]
    def hook(bot: Harness) -> None:
        bot.stop.request(source)

    return hook


def request_twice(bot: Harness) -> None:
    bot.stop.request("SIGINT")
    bot.stop.request("SIGINT")


def test_stop_request_is_a_flag_then_forced() -> None:
    stop = StopRequest()
    stop.request("SIGBREAK")
    assert stop.requested and stop.source == "SIGBREAK"
    try:
        stop.request("SIGBREAK")
    except ForcedStop:
        pass
    else:  # pragma: no cover - the assertion below names the failure
        raise AssertionError("second request must force the stop")


def test_stop_while_waiting_exits_at_once(tmp_path: Path) -> None:
    bot = harness(opened_store(tmp_path / "s.db"), stop_after=None, wait_hooks={0: request()})
    exit_ = bot.run()
    assert exit_.reason is ExitReason.STOPPED and exit_.turns == 1
    assert len(bot.waits) == 1 and len(bot.reads) == 1


def test_stop_during_turn_finishes_the_turn(tmp_path: Path) -> None:
    """Tur sürerken gelen istek: tur biter ve kaydeder; yeni tur başlamaz."""
    store = opened_store(tmp_path / "s.db")
    bot = harness(store, closes=CROSS, stop_after=None, read_hooks={0: request()})
    exit_ = bot.run()
    assert exit_.reason is ExitReason.STOPPED and exit_.turns == 1
    assert len(bot.reads) == 1 and bot.waits == []
    assert exit_.last is not None and len(exit_.last.buys) == 1
    stored = load_store(store, "paper").state
    assert stored is not None and len(stored.ledger.positions) == 1  # the turn's own save


def test_second_stop_exits_at_once(tmp_path: Path) -> None:
    during_read = harness(opened_store(tmp_path / "a.db"), read_hooks={0: request_twice})
    exit_ = during_read.run()
    assert exit_.reason is ExitReason.FORCED and exit_.turns == 0
    assert during_read.events("tur") == []

    while_waiting = harness(
        opened_store(tmp_path / "b.db"), stop_after=None, wait_hooks={0: request_twice}
    )
    exit_ = while_waiting.run()
    assert exit_.reason is ExitReason.FORCED and exit_.turns == 1


def test_exit_records_reason_and_last_result(tmp_path: Path) -> None:
    clean = harness(opened_store(tmp_path / "a.db"), stop_after=None, wait_hooks={0: request()})
    clean.run()
    (stopped,) = clean.events("durdurma")
    assert "durdu: neden=durdurma isteği (SIGINT) son_tur=completed tur_sayısı=1" in stopped

    forced = harness(opened_store(tmp_path / "b.db"), read_hooks={0: request_twice})
    forced.run()
    (stopped,) = forced.events("durdurma")
    assert "durdu: neden=zorla durdurma son_tur=yok tur_sayısı=0" in stopped
