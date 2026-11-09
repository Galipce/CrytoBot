"""Uygulama kontrol mantığı (spec 0030 R-1…R-4, R-7, R-8)."""

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from crytobot.app._config import BotConfig
from crytobot.control import AuditEvent
from crytobot.persistence import (
    StoreOutcome,
    append_audit_record,
    load_store,
    save_store,
)
from crytobot.risk import (
    engage_kill_switch as risk_engage_kill_switch,
    resume as risk_resume,
)


@dataclass(frozen=True)
class ControlResult:
    """Kontrol komutunun yürütme sonucu."""

    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)


def stop_flag_path(store_path: str | Path) -> Path:
    """<depo>.stop bayrak dosyasının yolu."""
    p = Path(store_path)
    return p.with_suffix(p.suffix + ".stop")


def is_lock_held(store_path: str | Path) -> bool:
    """<depo>.lock dosyasının çalışan bir süreç tarafından tutulup tutulmadığını yoklar."""
    p = Path(store_path)
    lock_path = p.with_suffix(p.suffix + ".lock")
    if not lock_path.exists():
        return False
    try:
        handle = open(lock_path, "a+b")
    except OSError:
        return True
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                return False
            except OSError:
                return True
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                return False
            except OSError:
                return True
    finally:
        handle.close()


def _append_to_log(log_path: str, text: str) -> None:
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass


def query_status(
    config: BotConfig,
    clock: Callable[[], datetime] | None = None,
) -> ControlResult:
    """R-1: Durum sorgulama (salt okunur)."""
    target = Path(config.store_path)
    if not target.exists():
        return ControlResult(False, f"depo dosyası yok: {config.store_path} (önce 'prepare' çalıştırılmalı)")
    store_res = load_store(config.store_path, "paper")
    if store_res.state is None:
        return ControlResult(False, f"depo okunamıyor: {store_res.message}")

    state = store_res.state
    running = is_lock_held(config.store_path)
    process_status = "çalışıyor" if running else "durdu"

    free_balance = state.ledger.balance
    total_equity = state.risk.last_equity if state.risk.last_equity is not None else free_balance
    peak_equity = state.risk.peak_equity if state.risk.peak_equity is not None else total_equity

    drawdown_pct = Decimal("0.00")
    if peak_equity is not None and total_equity is not None and peak_equity > Decimal("0"):
        if peak_equity > total_equity:
            drawdown_pct = ((peak_equity - total_equity) / peak_equity * Decimal("100")).quantize(
                Decimal("0.01")
            )

    active_halts = []
    if state.risk.halted:
        active_halts.append("drawdown durdurması")
    if state.risk.kill_switch:
        active_halts.append("kill switch")
    halts_str = " ve ".join(active_halts) if active_halts else "yok"

    now_dt = clock() if clock else datetime.now(UTC)
    today = now_dt.astimezone(UTC).date()
    day_realized = Decimal("0")
    for c in state.ledger.closures:
        if c.closed_at.astimezone(UTC).date() == today:
            day_realized += c.realized

    day_total = Decimal("0")
    if state.risk.day_start_equity is not None and state.risk.last_equity is not None:
        day_total = state.risk.last_equity - state.risk.day_start_equity

    positions = tuple(state.ledger.positions.values())
    pos_lines = []
    if positions:
        for p in positions:
            pos_lines.append(
                f"  {p.pair}: miktar={p.amount}, giriş={p.cost_price}, stop={p.stop}, hedef={p.target}"
            )
    else:
        pos_lines.append("  (açık pozisyon yok)")

    last_time_str = (
        state.risk.last_time.astimezone(UTC).isoformat(timespec="seconds")
        if state.risk.last_time
        else "-"
    )
    last_summary = f"zaman={last_time_str}, son kasa={state.risk.last_equity}"

    summary = (
        f"=== CrytoBot Durum Raporu ===\n"
        f"Süreç Durumu: {process_status}\n"
        f"Çalışma Modu: {state.mode}\n"
        f"Serbest Bakiye: {free_balance} USDT\n"
        f"Toplam Kasa: {total_equity} USDT\n"
        f"Zirve Kasa: {peak_equity} USDT\n"
        f"Drawdown Oranı: %{drawdown_pct}\n"
        f"Aktif Durdurmalar: {halts_str}\n"
        f"Günün Kâr/Zararı (UTC): Gerçekleşen={day_realized} USDT, Toplam={day_total} USDT\n"
        f"Açık Pozisyonlar ({len(positions)}):\n"
        + "\n".join(pos_lines)
        + f"\nSon Tur / Gözlem: {last_summary}\n"
        f"============================="
    )
    return ControlResult(
        True,
        summary,
        data={
            "running": running,
            "mode": state.mode,
            "free_balance": free_balance,
            "total_equity": total_equity,
            "peak_equity": peak_equity,
            "drawdown_pct": drawdown_pct,
            "halts": halts_str,
            "day_realized": day_realized,
            "day_total": day_total,
            "positions_count": len(positions),
            "last_time": last_time_str,
        },
    )


def engage_kill_switch(
    config: BotConfig,
    clock: Callable[[], datetime] | None = None,
) -> ControlResult:
    """R-2: Acil durdurma anahtarını devreye alır."""
    target = Path(config.store_path)
    if not target.exists():
        return ControlResult(False, f"depo dosyası yok: {config.store_path} (önce 'prepare' çalıştırılmalı)")
    store_res = load_store(config.store_path, "paper")
    if store_res.state is None:
        return ControlResult(False, f"depo okunamıyor: {store_res.message}")

    now_dt = clock() if clock else datetime.now(UTC)
    was_engaged = store_res.state.risk.kill_switch
    update = risk_engage_kill_switch(store_res.state.risk)

    if not was_engaged:
        save_res = save_store(
            config.store_path,
            store_res.state,
            store_res.state.ledger,
            store_res.state.execution,
            update.state,
        )
        if save_res.outcome is not StoreOutcome.SAVED:
            return ControlResult(False, f"kayıt başarısız: {save_res.message}")

    event = AuditEvent(
        timestamp=now_dt,
        channel="cli",
        action="kill-switch on",
        result="already_active" if was_engaged else "engaged",
        detail=update.message,
    )
    append_audit_record(config.store_path, event.to_json())
    _append_to_log(config.log_path, event.to_log_line())

    return ControlResult(True, update.message)


def resume_operations(
    config: BotConfig,
    clock: Callable[[], datetime] | None = None,
) -> ControlResult:
    """R-3: Durdurmaları (kill switch ve drawdown) kaldırır."""
    target = Path(config.store_path)
    if not target.exists():
        return ControlResult(False, f"depo dosyası yok: {config.store_path} (önce 'prepare' çalıştırılmalı)")
    store_res = load_store(config.store_path, "paper")
    if store_res.state is None:
        return ControlResult(False, f"depo okunamıyor: {store_res.message}")

    now_dt = clock() if clock else datetime.now(UTC)
    update = risk_resume(store_res.state.risk, "cli")

    if not update.accepted:
        event = AuditEvent(
            timestamp=now_dt,
            channel="cli",
            action="resume",
            result="refused",
            detail=update.message,
        )
        append_audit_record(config.store_path, event.to_json())
        _append_to_log(config.log_path, event.to_log_line())
        return ControlResult(False, f"durdurma kaldırma reddedildi: {update.message}")

    save_res = save_store(
        config.store_path,
        store_res.state,
        store_res.state.ledger,
        store_res.state.execution,
        update.state,
    )
    if save_res.outcome is not StoreOutcome.SAVED:
        return ControlResult(False, f"kayıt başarısız: {save_res.message}")

    event = AuditEvent(
        timestamp=now_dt,
        channel="cli",
        action="resume",
        result="success",
        detail=update.message,
    )
    append_audit_record(config.store_path, event.to_json())
    _append_to_log(config.log_path, event.to_log_line())

    return ControlResult(True, update.message)


def request_stop(
    config: BotConfig,
    clock: Callable[[], datetime] | None = None,
) -> ControlResult:
    """R-4: Çalışan bot sürecine durdurma isteği iletir."""
    target = Path(config.store_path)
    if not target.exists():
        return ControlResult(False, f"depo dosyası yok: {config.store_path} (önce 'prepare' çalıştırılmalı)")

    now_dt = clock() if clock else datetime.now(UTC)
    running = is_lock_held(config.store_path)

    if not running:
        event = AuditEvent(
            timestamp=now_dt,
            channel="cli",
            action="stop",
            result="refused",
            detail="çalışan bot süreci yok",
        )
        append_audit_record(config.store_path, event.to_json())
        _append_to_log(config.log_path, event.to_log_line())
        return ControlResult(False, "durdurma isteği reddedildi: çalışan bot süreci yok")

    flag = stop_flag_path(config.store_path)
    try:
        flag.write_text("stop", encoding="utf-8")
    except OSError as err:
        return ControlResult(False, f"durdurma bayrağı yazılamadı: {err}")

    event = AuditEvent(
        timestamp=now_dt,
        channel="cli",
        action="stop",
        result="requested",
        detail="durdurma bayrağı iletildi",
    )
    append_audit_record(config.store_path, event.to_json())
    _append_to_log(config.log_path, event.to_log_line())

    return ControlResult(True, "durdurma isteği çalışan bot sürecine iletildi")
