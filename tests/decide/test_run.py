"""Spec 0059 AC-3, AC-6, AC-8: tur zamanı, tek çağrı, günlük sınır, kota, bildirim, durdurma."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from crytobot.decide import (
    ADR_0005_COINS,
    CoinData,
    DecideConfig,
    DecideExit,
    DecideParts,
    DecideReply,
    DecideStore,
    load_decide_config,
    read_decide_snapshot,
    run_decide,
)
from tests.decide.helpers import BOUNDARY, HOUR, all_data, buy_entry, reply, wait_entry
from tests.decide.test_config import document


def config(**changes: object) -> DecideConfig:
    loaded = load_decide_config(document(**changes)).config
    assert loaded is not None
    return loaded


def wait_reply(coins: tuple[str, ...]) -> str:
    return reply(*(wait_entry(coin) for coin in coins))


@dataclass
class Fake:
    now: datetime
    turns: int = 1  # stop at the first wait after this many market reads
    replies: list[DecideReply] = field(default_factory=list)
    data: Mapping[str, CoinData | None] | None = None
    calls: list[str] = field(default_factory=list)
    reads: list[datetime] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    waits: list[float] = field(default_factory=list)
    stop: bool = False

    def wait(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += timedelta(seconds=seconds)
        if len(self.reads) >= self.turns:
            self.stop = True

    def read(self, coins: tuple[str, ...], boundary: datetime) -> Mapping[str, CoinData | None]:
        self.reads.append(boundary)
        return all_data(boundary) if self.data is None else self.data

    def call(self, model: str, system: str, prompt: str, timeout_s: float) -> DecideReply:
        self.calls.append(prompt)
        self.now += timedelta(seconds=30)
        if self.replies:
            return self.replies.pop(0)
        return DecideReply("ok", wait_reply(ADR_0005_COINS))

    def parts(self) -> DecideParts:
        return DecideParts(
            lambda: self.now,
            self.wait,
            lambda: self.stop,
            self.read,
            self.call,
            self.lines.append,
            lambda text: self.notices.append(text) or None,  # type: ignore[func-returns-value]
        )


def run(tmp_path: Path, fake: Fake, cfg: DecideConfig | None = None) -> DecideExit:
    store = DecideStore.open(str(tmp_path / "decide.db"))
    try:
        return run_decide(cfg or config(), store, fake.parts())
    finally:
        store.close()


def test_turn_minute_after_close(tmp_path: Path) -> None:
    fake = Fake(BOUNDARY + timedelta(minutes=1), turns=2)
    assert run(tmp_path, fake) is DecideExit.STOPPED
    assert fake.waits[0] == 4 * 60  # waits until hh:05
    assert fake.reads == [BOUNDARY, BOUNDARY + HOUR]
    snapshot = read_decide_snapshot(str(tmp_path / "decide.db"), BOUNDARY.date())
    assert snapshot is not None and [t.at for t in snapshot.turns] == [BOUNDARY + HOUR, BOUNDARY]
    assert any(line.startswith("tur: an=2026-11-20T10:00:00+00:00 sonuç=ok") for line in fake.lines)
    assert fake.lines[-1] == "durdu: durdurma isteği tur_sayısı=2"


def test_one_call_per_turn(tmp_path: Path) -> None:
    fake = Fake(BOUNDARY + timedelta(minutes=5), replies=[DecideReply("ok", "bozuk")])
    run(tmp_path, fake)
    assert len(fake.calls) == 1  # no retry after a schema violation (G-6)
    assert any("sonuç=şema dışı" in line and "şema_dışı=10" in line for line in fake.lines)


def test_restart_same_hour_no_second_turn(tmp_path: Path) -> None:
    run(tmp_path, Fake(BOUNDARY + timedelta(minutes=5)))
    fake = Fake(BOUNDARY + timedelta(minutes=7), turns=0)
    run(tmp_path, fake)
    assert fake.calls == [] and fake.reads == []


def test_late_start_skips_turn(tmp_path: Path) -> None:
    fake = Fake(BOUNDARY + timedelta(minutes=40), turns=0)
    run(tmp_path, fake)
    assert fake.calls == []
    assert "tur atlandı: an=2026-11-20T10:00:00+00:00 geç kalındı" in fake.lines


def test_daily_limit_no_call(tmp_path: Path) -> None:
    fake = Fake(BOUNDARY + timedelta(minutes=5), turns=3)
    run(tmp_path, fake, config(daily_call_limit=2))
    assert len(fake.calls) == 2
    assert any(
        line.startswith("tur: an=2026-11-20T12:00:00+00:00 sonuç=sınır çağrı=yok")
        for line in fake.lines
    )


def test_quota_waits_without_calls(tmp_path: Path) -> None:
    fake = Fake(BOUNDARY + timedelta(minutes=5), turns=2, replies=[DecideReply("quota", None)])
    run(tmp_path, fake, config(quota_wait_minutes=90))
    assert len(fake.calls) == 1
    assert any("sonuç=quota çağrı=var" in line for line in fake.lines)
    assert any("sonuç=kota bekleniyor çağrı=yok" in line for line in fake.lines)


def test_missing_coin_not_asked(tmp_path: Path) -> None:
    data = dict(all_data())
    data["TON"] = None
    asked = tuple(coin for coin in ADR_0005_COINS if coin != "TON")
    fake = Fake(BOUNDARY + timedelta(minutes=5), data=data,
                replies=[DecideReply("ok", wait_reply(asked))])  # fmt: skip
    run(tmp_path, fake)
    assert "Coinler: " + ", ".join(asked) in fake.calls[0]
    assert "## TON" not in fake.calls[0]
    assert any("sonuç=ok" in line and "veri_yok=1" in line for line in fake.lines)


def test_no_data_at_all_no_call(tmp_path: Path) -> None:
    fake = Fake(BOUNDARY + timedelta(minutes=5), data={})
    run(tmp_path, fake)
    assert fake.calls == []
    assert any("sonuç=veri yok çağrı=yok" in line for line in fake.lines)


def test_notice_per_valid_buy(tmp_path: Path) -> None:
    summary_low = {"BTC": 10.0, "ETH": 20.0}
    entries = [
        buy_entry("BTC", summary_low["BTC"] * 1.1, summary_low["BTC"] * 1.12),
        buy_entry("ETH", 20.0 * 1.1, 20.0 * 1.12, stop=99.0),  # inconsistent: not notified
        *(wait_entry(coin) for coin in ADR_0005_COINS[2:]),
    ]
    fake = Fake(BOUNDARY + timedelta(minutes=5), replies=[DecideReply("ok", reply(*entries))])
    run(tmp_path, fake)
    assert len(fake.notices) == 1 and "BTC al" in fake.notices[0]
    assert "bildirim: BTC al" in fake.lines
    assert any("al=1" in line and "tutarsız=1" in line for line in fake.lines)


def test_notify_failure_does_not_stop(tmp_path: Path) -> None:
    entries = [buy_entry("BTC", 11.0, 11.2), *(wait_entry(c) for c in ADR_0005_COINS[1:])]
    fake = Fake(BOUNDARY + timedelta(minutes=5), replies=[DecideReply("ok", reply(*entries))])
    parts = fake.parts()

    def broken(text: str) -> str | None:
        raise RuntimeError("telegram")

    store = DecideStore.open(str(tmp_path / "decide.db"))
    from dataclasses import replace

    assert run_decide(config(), store, replace(parts, notify=broken)) is DecideExit.STOPPED
    store.close()
    assert "bildirim iletilemedi" in fake.lines


def test_stopped_call_writes_no_turn(tmp_path: Path) -> None:
    fake = Fake(BOUNDARY + timedelta(minutes=5))

    def stopped_call(model: str, system: str, prompt: str, timeout_s: float) -> DecideReply:
        fake.stop = True
        return DecideReply("stopped", None)

    from dataclasses import replace

    store = DecideStore.open(str(tmp_path / "decide.db"))
    assert (
        run_decide(config(), store, replace(fake.parts(), call=stopped_call)) is DecideExit.STOPPED
    )
    assert not store.has_turn(BOUNDARY)
    store.close()


@pytest.mark.parametrize("minute", [0, 30])
def test_minute_setting_honoured(tmp_path: Path, minute: int) -> None:
    fake = Fake(BOUNDARY, turns=1)
    run(tmp_path, fake, config(minute_after_close=minute))
    assert fake.reads == [BOUNDARY]
    assert fake.waits[0] == (minute * 60 if minute else 3600 - 30)  # the call took 30 s
