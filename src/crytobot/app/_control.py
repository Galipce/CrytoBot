"""Uygulama kontrol mantığı (spec 0030 R-1…R-4, R-7, R-8; spec 0035 R-1…R-7).

Depo ayardaki modla açılır; mod uyuşmazlığında deponun kendi modu okunur (spec 0035 R-2):
gevşeten eylem (`resume`) reddedilir, sıkılaştıran eylem (`kill-switch`) deponun modunda uygulanır.
Bot çalışırken kontrol depoya yazmaz (plan 0035 Risk 1, 2): `kill-switch` istek bayrağına gider,
`resume` reddedilir. Hiçbir komut borsaya çıkmaz (R-5).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from crytobot.app._config import BotConfig
from crytobot.persistence import (
    MODES,
    StoreOutcome,
    StoreResult,
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

LIVE_BANNER = "CANLI MOD — gerçek para"
RUNNING_REFUSAL = "çalışan bot var: önce stop"


@dataclass(frozen=True)
class ControlResult:
    """Kontrol komutunun yürütme sonucu."""

    success: bool
    message: str


@dataclass(frozen=True)
class ModeLoad:
    """Moda göre yükleme (spec 0035 R-1, R-2): sonuç, deponun modu ve ayardaki mod."""

    result: StoreResult
    store_mode: str | None
    config_mode: str

    @property
    def mismatch(self) -> bool:
        return self.store_mode is not None and self.store_mode != self.config_mode

    @property
    def mode(self) -> str:
        """Gösterilecek mod: depo okunduysa deponun modu, değilse ayardaki mod."""
        return self.store_mode if self.store_mode is not None else self.config_mode

    def mismatch_text(self) -> str:
        return f"mod uyuşmazlığı: ayar={self.config_mode}, depo={self.store_mode}"


def load_for_mode(config: BotConfig, *, readonly: bool = False) -> ModeLoad:
    """R-1, R-2: depoyu ayardaki modla açar; uyuşmazlıkta deponun kendi modunu okur."""
    config_mode = config.mode
    result = load_store(config.store_path, config_mode, readonly=readonly)
    if result.outcome is StoreOutcome.MODE_MISMATCH:
        for other in MODES:
            if other == config_mode:
                continue
            alt = load_store(config.store_path, other, readonly=readonly)
            if alt.state is not None:
                return ModeLoad(alt, other, config_mode)
            if alt.outcome is not StoreOutcome.MODE_MISMATCH:
                return ModeLoad(alt, None, config_mode)
    store_mode = config_mode if result.state is not None else None
    return ModeLoad(result, store_mode, config_mode)


def _json_text(value: str) -> str:
    """JSON metin değeri (çift tırnaklı): ters bölü, tırnak ve kontrol karakterleri kaçışlıdır.
    `app` `json` import etmez (tests/app/test_boundaries.py izin listesi)."""
    out = []
    for char in value:
        if char in ('"', "\\"):
            out.append("\\" + char)
        elif ord(char) < 0x20:
            out.append(f"\\u{ord(char):04x}")
        else:
            out.append(char)
    return '"' + "".join(out) + '"'


def format_audit_row(
    now_dt: datetime,
    action: str,
    result: str,
    detail: str = "",
    *,
    mode: str = "",
    config_mode: str = "",
) -> str:
    """R-6: tek satır JSON, alanlar alfabetik; uyuşmazlıkta `config_mode` da yazılır (spec 0035)."""
    data: dict[str, str] = {
        "action": action,
        "channel": "cli",
        "result": result,
        "timestamp": now_dt.isoformat(timespec="seconds"),
    }
    if detail:
        data["detail"] = detail
    if mode:
        data["mode"] = mode
    if config_mode:
        data["config_mode"] = config_mode
    fields = ",".join(f"{_json_text(key)}:{_json_text(data[key])}" for key in sorted(data))
    return "{" + fields + "}"


def _format_log_line(
    now_dt: datetime, action: str, result: str, detail: str = "", *, mode: str = ""
) -> str:
    iso = now_dt.isoformat(timespec="seconds")
    suffix = f" {detail}" if detail else ""
    mode_part = f" [mod={mode}]" if mode else ""
    return f"{iso} audit [cli] {action} {result}{suffix}{mode_part}\n"


def _write_audit(
    config: BotConfig,
    now_dt: datetime,
    action: str,
    result: str,
    detail: str = "",
    *,
    loaded: ModeLoad,
) -> None:
    config_mode = ""
    if loaded.mismatch:
        config_mode = loaded.config_mode
        detail = f"{detail}; {loaded.mismatch_text()}" if detail else loaded.mismatch_text()
    row = format_audit_row(
        now_dt, action, result, detail, mode=loaded.mode, config_mode=config_mode
    )
    append_audit_record(config.store_path, row)
    try:
        with open(config.log_path, "a", encoding="utf-8") as f:
            f.write(_format_log_line(now_dt, action, result, detail, mode=loaded.mode))
    except OSError:
        pass


def _unavailable(config: BotConfig, loaded: ModeLoad) -> ControlResult | None:
    """R-8: depo yok ya da okunamıyor → adıyla ret; depo oluşturulmaz."""
    store_res = loaded.result
    if store_res.outcome is StoreOutcome.NOT_FOUND:
        return ControlResult(
            False,
            f"depo dosyası yok: {config.store_path} (önce 'prepare' çalıştırılmalı)",
        )
    if store_res.state is None:
        return ControlResult(False, f"depo okunamıyor: {store_res.message}")
    return None


def _with_mismatch(loaded: ModeLoad, message: str) -> str:
    return f"{message} (uyarı: {loaded.mismatch_text()})" if loaded.mismatch else message


def query_status(
    config: BotConfig,
    clock: Callable[[], datetime],
    is_running: bool = False,
) -> ControlResult:
    """R-1: Durum sorgulama (salt okunur); spec 0035 R-3: deponun gerçek modu gösterilir."""
    loaded = load_for_mode(config)
    refused = _unavailable(config, loaded)
    if refused is not None:
        return refused
    state = loaded.result.state
    assert state is not None  # checked by _unavailable
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
            # R-14 / test_boundaries: app dosyalari defter kar alanini duz metin olarak iceremez
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

    head = f"{LIVE_BANNER}\n" if loaded.mode == "live" else ""
    # spec 0041 CB-5, G-3: the network is shown only on a testnet store; mainnet is unchanged
    network = " ağ=testnet" if state.network == "testnet" else ""
    warning = f"UYARI: {loaded.mismatch_text()}\n" if loaded.mismatch else ""
    summary = (
        f"{head}"
        f"=== CrytoBot Durum Raporu ===\n"
        f"{warning}"
        f"Süreç Durumu: {process_status}\n"
        f"Çalışma Modu: {loaded.mode}{network}\n"
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
    *,
    is_running: bool = False,
    request_kill: Callable[[], None] | None = None,
) -> ControlResult:
    """R-2: Acil alım durdurma. Spec 0035 R-2: uyuşmazlıkta deponun modunda uygulanır; bot
    çalışırken depoya yazılmaz, istek bayrağına gider (plan 0035 Risk 1)."""
    loaded = load_for_mode(config)
    refused = _unavailable(config, loaded)
    if refused is not None:
        return refused
    state = loaded.result.state
    assert state is not None  # checked by _unavailable
    now_dt = clock()
    if state.risk.kill_switch:
        _write_audit(
            config, now_dt, "kill-switch on", "already_active", "zaten devrede", loaded=loaded
        )
        return ControlResult(
            True,
            _with_mismatch(
                loaded, "kill switch zaten devrede: yeni alımlar engellenmeye devam ediyor"
            ),
        )

    if is_running:
        if request_kill is None:
            _write_audit(
                config, now_dt, "kill-switch on", "refused", "istek iletilemedi", loaded=loaded
            )
            return ControlResult(False, "kill switch isteği çalışan bota iletilemedi")
        try:
            request_kill()
        except OSError as err:
            _write_audit(
                config,
                now_dt,
                "kill-switch on",
                "refused",
                f"istek yazılamadı ({type(err).__name__})",
                loaded=loaded,
            )
            return ControlResult(False, f"kill switch isteği yazılamadı ({type(err).__name__})")
        _write_audit(config, now_dt, "kill-switch on", "requested", "", loaded=loaded)
        return ControlResult(
            True,
            _with_mismatch(
                loaded,
                "kill switch isteği çalışan bota iletildi: en geç sonraki turun başında,"
                " alımdan önce devreye girer; açık pozisyonlar korunuyor",
            ),
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
        _write_audit(config, now_dt, "kill-switch on", "refused", save_res.message, loaded=loaded)
        return ControlResult(False, f"kill switch kaydedilemedi: {save_res.message}")

    _write_audit(config, now_dt, "kill-switch on", "engaged", "", loaded=loaded)
    return ControlResult(
        True,
        _with_mismatch(
            loaded,
            "kill switch devreye alındı: yeni alımlar durduruldu, açık pozisyonlar korunuyor",
        ),
    )


def resume_operations(
    config: BotConfig,
    clock: Callable[[], datetime],
    *,
    is_running: bool = False,
) -> ControlResult:
    """R-3: Durdurma kaldırma. Spec 0035 R-2: uyuşmazlıkta ret; R-7: çalışan botta ret."""
    loaded = load_for_mode(config)
    refused = _unavailable(config, loaded)
    if refused is not None:
        return refused
    state = loaded.result.state
    assert state is not None  # checked by _unavailable
    now_dt = clock()
    if loaded.mismatch:
        _write_audit(config, now_dt, "resume", "refused", "", loaded=loaded)
        return ControlResult(False, f"durdurma kaldırılmadı: {loaded.mismatch_text()}")
    if is_running:
        _write_audit(config, now_dt, "resume", "refused", RUNNING_REFUSAL, loaded=loaded)
        return ControlResult(False, RUNNING_REFUSAL)

    update = risk_resume(state.risk, "cli")
    if update.reason is not None:
        _write_audit(config, now_dt, "resume", "refused", update.message, loaded=loaded)
        return ControlResult(False, update.message)

    save_res = save_store(
        config.store_path,
        state,
        state.ledger,
        state.execution,
        update.state,
    )
    if save_res.state is None:
        _write_audit(config, now_dt, "resume", "refused", save_res.message, loaded=loaded)
        return ControlResult(False, f"durdurma kaldırılamadı: {save_res.message}")

    _write_audit(config, now_dt, "resume", "success", "", loaded=loaded)
    return ControlResult(True, "durdurma kaldırıldı: kill switch ve drawdown durdurması sıfırlandı")


def request_stop(
    config: BotConfig,
    clock: Callable[[], datetime],
    is_running: bool = False,
    on_stop_requested: Callable[[], None] | None = None,
) -> ControlResult:
    """R-4: Temiz süreç durdurma isteği; spec 0035 R-2: moddan bağımsız iletilir."""
    loaded = load_for_mode(config)
    refused = _unavailable(config, loaded)
    if refused is not None:
        return refused

    now_dt = clock()
    if not is_running:
        _write_audit(config, now_dt, "stop", "refused", "çalışan bot süreci yok", loaded=loaded)
        return ControlResult(False, "çalışan bot süreci yok: durdurma isteği iletilmedi")

    if on_stop_requested is not None:
        on_stop_requested()

    _write_audit(config, now_dt, "stop", "success", "", loaded=loaded)
    return ControlResult(
        True, _with_mismatch(loaded, "durdurma isteği çalışan bot sürecine iletildi")
    )
