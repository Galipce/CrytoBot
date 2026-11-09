"""Spec 0030 AC-8: Denetim günlüğü (audit log) testleri."""

from datetime import UTC, datetime
from pathlib import Path

from crytobot.control import AuditEvent, decode_audit_event
from crytobot.persistence import append_audit_record, create_store, load_audit_records

T0 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=UTC)


def test_audit_event_json_roundtrip() -> None:
    """AuditEvent nesnesi JSON satırına serileştirilip geri çözülebilir."""
    event = AuditEvent(
        timestamp=T0,
        channel="cli",
        action="kill-switch on",
        result="engaged",
        detail="manuel acil durdurma",
    )
    json_line = event.to_json()
    assert '"channel":"cli"' in json_line
    assert '"action":"kill-switch on"' in json_line
    assert '"result":"engaged"' in json_line

    decoded = decode_audit_event(json_line)
    assert decoded.timestamp == event.timestamp
    assert decoded.channel == event.channel
    assert decoded.action == event.action
    assert decoded.result == event.result
    assert decoded.detail == event.detail


def test_audit_event_log_line_format() -> None:
    """AuditEvent log dosyasına yazılacak metin satırını standart biçimde üretir."""
    event = AuditEvent(
        timestamp=T0,
        channel="cli",
        action="resume",
        result="success",
        detail="durdurma kaldirildi",
    )
    line = event.to_log_line()
    assert line.startswith("2026-11-02T10:00:00+00:00 audit [cli] resume success")
    assert "durdurma kaldirildi" in line


def test_audit_log_written_to_store_and_file(tmp_path: Path) -> None:
    """AC-8 (R-7): Denetim kaydı hem kalıcı depoya (audit tablosu) hem de log dosyasına yazılır."""
    db_path = tmp_path / "bot.db"
    log_path = tmp_path / "crytobot.log"
    create_store(db_path, "paper")

    event = AuditEvent(
        timestamp=T0,
        channel="cli",
        action="kill-switch on",
        result="engaged",
        detail="onaylandi",
    )

    # 1. Depoya append-only yazım
    save_res = append_audit_record(db_path, event.to_json())
    assert save_res.reconciled
    records = load_audit_records(db_path)
    assert len(records) == 1
    decoded = decode_audit_event(records[0])
    assert decoded.action == "kill-switch on"
    assert decoded.result == "engaged"

    # 2. Log dosyasına yazım
    with log_path.open("a", encoding="utf-8") as f:
        f.write(event.to_log_line() + "\n")

    log_content = log_path.read_text(encoding="utf-8")
    assert "audit [cli] kill-switch on engaged" in log_content
