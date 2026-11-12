"""Pano durum verisi kapısı (spec 0031 R-2, R-4, R-6; spec 0035 R-1…R-3).

Depoyu salt-okunur (`mode=ro`) ve ayardaki modla okuyarak /api/status JSON verisini hazırlar;
uyuşmazlıkta deponun gerçek modu ve `mode_mismatch` uyarısı döner (spec 0035 R-2).
Depo yokken veya bozukken hata durumunu adıyla sunar (AC-7).
"""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from crytobot.app._config import BotConfig
from crytobot.app._control import load_for_mode
from crytobot.persistence import StoreOutcome


def get_dashboard_status(
    config: BotConfig,
    clock: Callable[[], datetime],
    is_running: bool = False,
    logs: tuple[str, ...] = (),
) -> tuple[int, dict[str, object]]:
    """Depodan salt-okunur veri okuyarak /api/status yanıtını üretir (R-2, R-4, R-6)."""
    loaded = load_for_mode(config, readonly=True)
    store_res = loaded.result
    mismatch = loaded.mismatch_text() if loaded.mismatch else None
    if store_res.outcome is StoreOutcome.NOT_FOUND:
        return 503, {
            "error": f"Depo bulunamadı: {config.store_path} (önce 'prepare' çalıştırılmalı)",
            "is_running": is_running,
            "mode": loaded.mode,
            "mode_mismatch": None,
        }

    if store_res.state is None:
        return 503, {
            "error": f"Depo okunamıyor: {store_res.message}",
            "is_running": is_running,
            "mode": loaded.mode,
            "mode_mismatch": None,
        }

    state = store_res.state
    free_balance = float(state.ledger.balance) if state.ledger.balance is not None else 0.0
    equity = float(state.risk.last_equity) if state.risk.last_equity is not None else free_balance
    peak_equity = float(state.risk.peak_equity) if state.risk.peak_equity is not None else equity

    drawdown_pct = 0.0
    if peak_equity > 0 and peak_equity > equity:
        drawdown_pct = float(round(((peak_equity - equity) / peak_equity) * 100, 2))

    day_total = 0.0
    daily_pnl_pct = 0.0
    if state.risk.day_start_equity is not None and state.risk.last_equity is not None:
        pnl = state.risk.last_equity - state.risk.day_start_equity
        day_total = float(pnl)
        if state.risk.day_start_equity > Decimal("0"):
            daily_pnl_pct = float(round((pnl / state.risk.day_start_equity) * Decimal("100"), 2))

    positions: list[dict[str, object]] = []
    for p in state.ledger.positions.values():
        cost_f = float(p.cost_price)
        positions.append(
            {
                "pair": p.pair,
                "direction": "ALIM",
                "amount": float(p.amount),
                "entry_price": cost_f,
                "current_price": cost_f,
                "stop_loss": float(p.stop),
                "take_profit": float(p.target),
                "unrealized_pnl": 0.0,
            }
        )

    last_time_str = (
        state.risk.last_time.isoformat(timespec="seconds")
        if state.risk.last_time is not None
        else None
    )
    last_turn = {
        "time": last_time_str,
        "status": "normal" if not state.risk.halted else "halted",
        "message": f"Kasa: {equity:.2f} USDT",
    }

    body: dict[str, object] = {
        "is_running": is_running,
        "mode": loaded.mode,
        "mode_mismatch": mismatch,
        "equity": equity,
        "free_balance": free_balance,
        "peak_equity": peak_equity,
        "drawdown_pct": drawdown_pct,
        "daily_pnl": day_total,
        "daily_pnl_pct": daily_pnl_pct,
        "halted": state.risk.halted,
        "kill_switch": state.risk.kill_switch,
        "positions": positions,
        "last_turn": last_turn,
        "logs": list(logs),
    }
    if state.network == "testnet":  # spec 0041 CB-5, G-3: absent on mainnet, as before
        body["network"] = "testnet"
    return 200, body
