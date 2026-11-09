"""Uygulama kontrol mantığı (spec 0030 R-1…R-4, R-7, R-8)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from crytobot.app._config import BotConfig
from crytobot.persistence import (
    StoreOutcome,
    append_audit_record,
    load_store,
    save_store,
)
from crytobot.risk import (
    engage_kill_switch as risk_engage_kill_switch,
)
from crytobot.risk import (
    resume as risk_resume,
)


@dataclass(frozen=True)
class ControlResult:
    """Kontrol komutunun yürütme sonucu."""

    success: bool
    message: str


def _format_audit_row(now_dt: datetime, action: str, result: str, detail: str = "") -> str:
    iso = now_dt.isoformat(timespec="seconds")
    if detail:
        return (
            f'{{"action":"{action}","channel":"cli","detail":"{detail}",'
            f'"result":"{result}","timestamp":"{iso}"}}'
        )
    return f'{{"action":"{action}","channel":"cli","result":"{result}","timestamp":"{iso}"}}'


def _format_log_line(now_dt: datetime, action: str, result: str, detail: str = "") -> str:
    iso = now_dt.isoformat(timespec="seconds")
    suffix = f" {detail}" if detail else ""
    return f"{iso} audit [cli] {action} {result}{suffix}\n"


def _write_audit(
    store_path: str,
    log_path: str,
    now_dt: datetime,
    action: str,
    result: str,
    detail: str = "",
) -> None:
    row = _format_audit_row(now_dt, action, result, detail)
    append_audit_record(store_path, row)
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(_format_log_line(now_dt, action, result, detail))
    except OSError:
        pass


def query_status(
    config: BotConfig,
    clock: Callable[[], datetime],
    is_running: bool = False,
) -> ControlResult:
    """R-1: Durum sorgulama (salt okunur)."""
    store_res = load_store(config.store_path, "paper")
    if store_res.outcome is StoreOutcome.NOT_FOUND:
        return ControlResult(
            False,
            f"depo dosyası yok: {config.store_path} (önce 'prepare' çalıştırılmalı)",
        )
    if store_res.state is None:
        return ControlResult(False, f"depo okunamıyor: {store_res.message}")

    state = store_res.state
    process_status = "çalışıyor" if is_running else "durdu"

    free_balance = state.ledger.balance
    total_equity = state.risk.last_equity if state.risk.last_equity is not None else free_balance
    peak_equity = state.risk.peak_equity if state.risk.peak_equity is not None else total_equity

    drawdown_pct = Decimal("0.00")
    if (
        peak_equity is not None
        and total_equity is not None
        and peak_equity > Decimal("0")
        and peak_equity > total_equity
    ):
        drawdown_pct = ((peak_equity - total_equity) / peak_equity * Decimal("100")).quantize(
            Decimal("0.01")
        )

    active_halts = []
    if state.risk.halted:
        active_halts.append("drawdown durdurması")
    if state.risk.kill_switch:
        active_halts.append("kill switch")
    halts_str = " ve ".join(active_halts) if active_halts else "yok"

    now_dt = clock()
    today = now_dt.date()
    day_realized = Decimal("0")
    for c in state.ledger.closures.values():
        if c.closed_at.date() == today:
            day_realized += getattr(c, "realized")  # noqa: B009

    day_total = Decimal("0")
    if state.risk.day_start_equity is not None and state.risk.last_equity is not None:
        day_total = state.risk.last_equity - state.risk.day_start_equity

    positions = tuple(state.ledger.positions.values())
    pos_lines = []
    if positions:
        for p in positions:
            pos_lines.append(
                f"  {p.pair}: miktar={p.amount}, giriş={p.cost_price}, "
                f"stop={p.stop}, hedef={p.target}"
            )
    else:
        pos_lines.append("  (açık pozisyon yok)")

    last_time_str = (
        state.risk.last_time.isoformat(timespec="seconds") if state.risk.last_time else "-"
    )
    last_summary = f"zaman={last_time_str}, son kasa={state.risk.last_equity}"

    summary = (
        f"=== CrytoBot Durum Raporu ===\n"
        f"Süreç Durumu: {process_status}\n"
        f"Çalışma Modu: paper\n"
        f"Serbest Bakiye: {free_balance} USDT\n"
        f"Toplam Kasa: {total_equity} USDT\n"
        f"Zirve Kasa: {peak_equity} USDT\n"
        f"Drawdown Oranı: %{drawdown_pct}\n"
        f"Aktif Durdurmalar: {halts_str}\n"
        f"Günün Kâr/Zararı (UTC): gerçekleşen={day_realized} USDT, toplam={day_total} USDT\n"
        f"Açık Pozisyonlar ({len(positions)}):\n"
        + "\n".join(pos_lines)
        + f"\nSon Tur / Gözlem: {last_summary}"
    )
    return ControlResult(True, summary)


def engage_kill_switch(
    config: BotConfig,
    clock: Callable[[], datetime],
) -> ControlResult:
    """R-2: Acil alım durdurma (kill switch)."""
    store_res = load_store(config.store_path, "paper")
    if store_res.outcome is StoreOutcome.NOT_FOUND:
        return ControlResult(
            False,
            f"depo dosyası yok: {config.store_path} (önce 'prepare' çalıştırılmalı)",
        )
    if store_res.state is None:
        return ControlResult(False, f"depo okunamıyor: {store_res.message}")

    state = store_res.state
    now_dt = clock()
    if state.risk.kill_switch:
        _write_audit(
            config.store_path,
            config.log_path,
            now_dt,
            "kill-switch on",
            "already_active",
            "zaten devrede",
        )
        return ControlResult(
            True, "kill switch zaten devrede: yeni alımlar engellenmeye devam ediyor"
        )

    updated_risk = risk_engage_kill_switch(state.risk).state
    save_res = save_store(
        config.store_path,
        state,
        state.ledger,
        state.execution,
        updated_risk,
    )
    if save_res.state is None:
        _write_audit(
            config.store_path,
            config.log_path,
            now_dt,
            "kill-switch on",
            "refused",
            save_res.message,
        )
        return ControlResult(False, f"kill switch kaydedilemedi: {save_res.message}")

    _write_audit(config.store_path, config.log_path, now_dt, "kill-switch on", "engaged", "")
    return ControlResult(
        True,
        "kill switch devreye alındı: yeni alımlar durduruldu, açık pozisyonlar korunuyor",
    )


def resume_operations(
    config: BotConfig,
    clock: Callable[[], datetime],
) -> ControlResult:
    """R-3: Durdurma kaldırma (resume)."""
    store_res = load_store(config.store_path, "paper")
    if store_res.outcome is StoreOutcome.NOT_FOUND:
        return ControlResult(
            False,
            f"depo dosyası yok: {config.store_path} (önce 'prepare' çalıştırılmalı)",
        )
    if store_res.state is None:
        return ControlResult(False, f"depo okunamıyor: {store_res.message}")

    state = store_res.state
    now_dt = clock()
    update = risk_resume(state.risk, "cli")
    if update.reason is not None:
        _write_audit(
            config.store_path,
            config.log_path,
            now_dt,
            "resume",
            "refused",
            update.message,
        )
        return ControlResult(False, update.message)

    save_res = save_store(
        config.store_path,
        state,
        state.ledger,
        state.execution,
        update.state,
    )
    if save_res.state is None:
        _write_audit(
            config.store_path,
            config.log_path,
            now_dt,
            "resume",
            "refused",
            save_res.message,
        )
        return ControlResult(False, f"durdurma kaldırılamadı: {save_res.message}")

    _write_audit(config.store_path, config.log_path, now_dt, "resume", "success", "")
    return ControlResult(True, "durdurma kaldırıldı: kill switch ve drawdown durdurması sıfırlandı")


def request_stop(
    config: BotConfig,
    clock: Callable[[], datetime],
    is_running: bool = False,
    on_stop_requested: Callable[[], None] | None = None,
) -> ControlResult:
    """R-4: Temiz süreç durdurma isteği."""
    store_res = load_store(config.store_path, "paper")
    if store_res.outcome is StoreOutcome.NOT_FOUND:
        return ControlResult(
            False,
            f"depo dosyası yok: {config.store_path} (önce 'prepare' çalıştırılmalı)",
        )
    if store_res.state is None:
        return ControlResult(False, f"depo okunamıyor: {store_res.message}")

    now_dt = clock()
    if not is_running:
        _write_audit(
            config.store_path,
            config.log_path,
            now_dt,
            "stop",
            "refused",
            "çalışan bot süreci yok",
        )
        return ControlResult(False, "çalışan bot süreci yok: durdurma isteği iletilmedi")

    if on_stop_requested is not None:
        on_stop_requested()

    _write_audit(config.store_path, config.log_path, now_dt, "stop", "success", "")
    return ControlResult(True, "durdurma isteği çalışan bot sürecine iletildi")
