"""Spec 0046 AC-7: uzun kesintide tek giriş bildirimi, ilk başarıda tek çıkış bildirimi; yeniden
başlatma sayacı sıfırlamaz ve ikinci bildirim üretmez; Telegram kapalıyken yalnız satır."""

from datetime import timedelta
from pathlib import Path

from crytobot.news import Fetched
from tests.news.test_collect import START, Harness, make_config, source_table

HOUR = 3600.0


def failing(tmp_path: Path, *, telegram: bool = True) -> Harness:
    tmp_path.mkdir(parents=True, exist_ok=True)
    harness = Harness(
        tmp_path,
        make_config(tmp_path, source_table("coindesk"), source_alert_hours=6),
        telegram=telegram,
    )
    harness.responses["coindesk"] = Fetched(error="http_503")
    harness.fetch_seconds = 0.0
    return harness


def rounds_at(harness: Harness, *hours: float) -> None:
    for hour in hours:
        harness.clock.now = START + timedelta(hours=hour)
        harness.round()


def test_single_alert_after_threshold(tmp_path: Path) -> None:
    harness = failing(tmp_path)
    rounds_at(harness, 0, 3, 6)  # exactly 6 h: not longer than the threshold
    assert harness.notices == []
    rounds_at(harness, 6.25)
    assert len(harness.notices) == 1


def test_no_repeat_during_outage(tmp_path: Path) -> None:
    harness = failing(tmp_path)
    rounds_at(harness, 0, 7, 8, 24, 48)
    assert len(harness.notices) == 1
    assert sum("bildirim=giriş" in row for row in harness.lines) == 1


def test_restart_keeps_outage_and_sent_flag(tmp_path: Path) -> None:
    """Bildirim gittikten sonra yeniden başlatma ikinci bildirim üretmez; eşiğe yaklaşmış kesinti
    yeniden başlatmayla sıfırlanmaz (G-1)."""
    near = failing(tmp_path / "near")
    rounds_at(near, 0, 5.5)
    restarted = failing(tmp_path / "near")
    rounds_at(restarted, 6.5)
    assert len(restarted.notices) == 1

    sent = failing(tmp_path / "sent")
    rounds_at(sent, 0, 7)
    assert len(sent.notices) == 1
    again = failing(tmp_path / "sent")
    rounds_at(again, 8, 30)
    assert again.notices == []


def test_single_recovery_notice(tmp_path: Path) -> None:
    harness = failing(tmp_path)
    rounds_at(harness, 0, 7)
    del harness.responses["coindesk"]
    rounds_at(harness, 8, 9)
    assert len(harness.notices) == 2
    assert "yeniden çalışıyor" in harness.notices[1]
    assert sum("bildirim=çıkış" in row for row in harness.lines) == 1
    # a short outage afterwards: no entry, so no exit notice either
    harness.responses["coindesk"] = Fetched(error="timeout")
    rounds_at(harness, 10)
    del harness.responses["coindesk"]
    rounds_at(harness, 11)
    assert len(harness.notices) == 2


def test_new_outage_after_recovery_starts_fresh(tmp_path: Path) -> None:
    harness = failing(tmp_path)
    rounds_at(harness, 0, 7)
    del harness.responses["coindesk"]
    rounds_at(harness, 8)
    harness.responses["coindesk"] = Fetched(error="timeout")
    rounds_at(harness, 9, 15)
    assert len(harness.notices) == 2  # 9 → 15 is exactly 6 h
    rounds_at(harness, 15.5)
    assert len(harness.notices) == 3
    assert f"Başlangıç: {(START + timedelta(hours=9)).isoformat()}" in harness.notices[2]


def test_telegram_off_line_only(tmp_path: Path) -> None:
    harness = failing(tmp_path, telegram=False)
    rounds_at(harness, 0, 7, 8)
    assert harness.notices == []
    entry = [row for row in harness.lines if "bildirim=giriş" in row]
    assert entry == [f"kaynak=coindesk kesinti: başlangıç={START.isoformat()} bildirim=giriş"]
    for store in harness.store():
        assert store.state("coindesk").alert_sent  # the record is the same


def test_notice_carries_name_and_start(tmp_path: Path) -> None:
    harness = Harness(
        tmp_path,
        make_config(tmp_path, source_table("a<b>&c"), source_alert_hours=1),
    )
    harness.responses["a<b>&c"] = Fetched(error="timeout")
    harness.fetch_seconds = 0.0
    rounds_at(harness, 0, 2)
    assert harness.notices == [
        "<b>Haber kaynağı kesintisi</b>\n"
        "Kaynak: a&lt;b&gt;&amp;c\n"
        f"Başlangıç: {START.isoformat()} (UTC)"
    ]


def test_failed_hand_over_retried_next_round(tmp_path: Path) -> None:
    harness = failing(tmp_path)
    attempts: list[str] = []

    def broken(text: str) -> None:
        attempts.append(text)
        if len(attempts) == 1:
            raise RuntimeError("telegram down")

    rounds_at(harness, 0)
    original = harness.parts

    def parts():  # type: ignore[no-untyped-def]
        from dataclasses import replace

        return replace(original(), notify=broken)

    harness.parts = parts  # type: ignore[method-assign]
    rounds_at(harness, 7, 8, 9)
    assert len(attempts) == 2
    assert "kaynak=coindesk bildirim iletilemedi" in harness.lines
