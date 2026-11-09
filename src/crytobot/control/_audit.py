"""Denetim günlüğü modeli ve formatlayıcılar (spec 0030 R-7, AC-8)."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class AuditEvent:
    """Kontrol komutlarının değiştirilemez olay kaydı (spec 0030 R-7)."""

    timestamp: datetime
    channel: str
    action: str
    result: str
    detail: str = ""

    def to_json(self) -> str:
        data: dict[str, str] = {
            "timestamp": self.timestamp.astimezone(UTC).isoformat(timespec="seconds"),
            "channel": self.channel,
            "action": self.action,
            "result": self.result,
        }
        if self.detail:
            data["detail"] = self.detail
        return json.dumps(data, separators=(",", ":"))

    def to_log_line(self) -> str:
        suffix = f" {self.detail}" if self.detail else ""
        return (
            f"{self.timestamp.astimezone(UTC).isoformat(timespec='seconds')} "
            f"audit [{self.channel}] {self.action} {self.result}{suffix}"
        )


def decode_audit_event(text: str) -> AuditEvent:
    data = json.loads(text)
    ts = datetime.fromisoformat(data["timestamp"])
    if ts.utcoffset() is None:
        ts = ts.replace(tzinfo=UTC)
    return AuditEvent(
        timestamp=ts,
        channel=str(data["channel"]),
        action=str(data["action"]),
        result=str(data["result"]),
        detail=str(data.get("detail", "")),
    )
