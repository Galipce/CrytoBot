"""Spec 0035 AC-2, AC-5, AC-6, AC-7, AC-12: kontrol komutları canlı depoda ve mod uyuşmazlığında."""

import dataclasses
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crytobot.app import (
    BotConfig,
    engage_kill_switch,
    query_status,
    request_stop,
    resume_operations,
)
from crytobot.persistence import create_store, load_audit_records, load_store, save_store
from crytobot.portfolio import EMPTY_LEDGER, open_ledger
from tests.app.helpers import DEPOSIT, NOW, opened_store
from tests.app.test_control_commands import make_bot_config

T0 = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def store_in(path: Path, mode: str) -> Path:
    """Defteri açılmış, `mode` modunda bir depo."""
    if mode == "paper":
        return opened_store(path)
    created = create_store(path, mode)
    assert created.state is not None
    ledger = open_ledger(EMPTY_LEDGER, DEPOSIT, NOW).ledger
    saved = save_store(path, created.state, ledger, created.state.execution, created.state.risk)
    assert saved.state is not None
    return path


def config_for(tmp_path: Path, store_mode: str, config_mode: str) -> BotConfig:
    db_path = store_in(tmp_path / "bot.db", store_mode)
    return dataclasses.replace(make_bot_config(db_path, tmp_path / "bot.log"), mode=config_mode)


def kill_switch_of(config: BotConfig, mode: str) -> bool:
    loaded = load_store(config.store_path, mode)
    assert loaded.state is not None
    return loaded.state.risk.kill_switch


def test_resume_and_status_on_live_store(tmp_path: Path) -> None:
    """AC-2 (R-1, R-3): canlı depoda kill switch → resume; status canlı modu gösterir."""
    config = config_for(tmp_path, "live", "live")
    assert engage_kill_switch(config, clock=lambda: T0).success
    assert kill_switch_of(config, "live")

    status = query_status(config, clock=lambda: T0)
    assert status.success
    assert status.message.splitlines()[0] == "CANLI MOD — gerçek para"
    assert "Çalışma Modu: live" in status.message
    assert "Aktif Durdurmalar: kill switch" in status.message
    assert "UYARI" not in status.message

    resumed = resume_operations(config, clock=lambda: T0)
    assert resumed.success, resumed.message
    assert not kill_switch_of(config, "live")


def test_paper_status_has_no_live_banner(tmp_path: Path) -> None:
    """AC-10 (R-3): paper depoda ilk satır bugünkü başlıktır, mod satırı paper."""
    config = config_for(tmp_path, "paper", "paper")
    status = query_status(config, clock=lambda: T0)
    assert status.message.splitlines()[0] == "=== CrytoBot Durum Raporu ==="
    assert "Çalışma Modu: paper" in status.message


@pytest.mark.parametrize(("store_mode", "config_mode"), [("live", "paper"), ("paper", "live")])
def test_resume_refused_on_mode_mismatch(tmp_path: Path, store_mode: str, config_mode: str) -> None:
    """AC-5 (R-2): uyuşmazlıkta resume depoya dokunmaz, iki modu da adıyla söyler."""
    config = config_for(tmp_path, store_mode, config_mode)
    same_mode = dataclasses.replace(config, mode=store_mode)
    assert engage_kill_switch(same_mode, clock=lambda: T0).success
    before = load_store(config.store_path, store_mode)
    assert before.state is not None

    res = resume_operations(config, clock=lambda: T0)

    assert not res.success
    assert f"ayar={config_mode}" in res.message and f"depo={store_mode}" in res.message
    after = load_store(config.store_path, store_mode)
    assert after.state is not None
    assert after.state.revision == before.state.revision
    assert after.state.risk.kill_switch


@pytest.mark.parametrize(("store_mode", "config_mode"), [("live", "paper"), ("paper", "live")])
def test_kill_switch_applies_in_store_mode_on_mismatch(
    tmp_path: Path, store_mode: str, config_mode: str
) -> None:
    """AC-6 (R-2): uyuşmazlıkta kill switch deponun modunda devreye girer, kayıt bunu taşır."""
    config = config_for(tmp_path, store_mode, config_mode)

    res = engage_kill_switch(config, clock=lambda: T0)

    assert res.success
    assert "mod uyuşmazlığı" in res.message
    assert kill_switch_of(config, store_mode)
    rows = load_audit_records(config.store_path)
    assert any(
        '"result":"engaged"' in r and f'"mode":"{store_mode}"' in r and "mod uyuşmazlığı" in r
        for r in rows
    )


def test_status_and_stop_warn_on_mismatch(tmp_path: Path) -> None:
    """AC-7 (R-2): status deponun gerçek modunu ve uyarıyı gösterir; stop çalışan sürece gider."""
    config = config_for(tmp_path, "live", "paper")

    status = query_status(config, clock=lambda: T0)
    assert status.success
    assert status.message.splitlines()[0] == "CANLI MOD — gerçek para"
    assert "Çalışma Modu: live" in status.message
    assert "UYARI: mod uyuşmazlığı: ayar=paper, depo=live" in status.message

    calls: list[str] = []
    stopped = request_stop(
        config, clock=lambda: T0, is_running=True, on_stop_requested=lambda: calls.append("stop")
    )
    assert stopped.success
    assert calls == ["stop"]
    assert "mod uyuşmazlığı" in stopped.message


def test_resume_refused_while_bot_running(tmp_path: Path) -> None:
    """AC-12 (R-7): bot çalışırken resume reddedilir, depo değişmez; bot durunca kaldırır."""
    config = config_for(tmp_path, "live", "live")
    assert engage_kill_switch(config, clock=lambda: T0).success
    before = load_store(config.store_path, "live")
    assert before.state is not None

    res = resume_operations(config, clock=lambda: T0, is_running=True)

    assert not res.success
    assert res.message == "çalışan bot var: önce stop"
    after = load_store(config.store_path, "live")
    assert after.state is not None and after.state.revision == before.state.revision
    rows = load_audit_records(config.store_path)
    assert any('"action":"resume"' in r and "önce stop" in r for r in rows)

    assert resume_operations(config, clock=lambda: T0, is_running=False).success
    assert not kill_switch_of(config, "live")


def test_kill_switch_while_running_goes_to_request(tmp_path: Path) -> None:
    """Plan 0035 Risk 1: bot çalışırken kill switch depoya yazılmaz, istek iletilir."""
    config = config_for(tmp_path, "live", "live")
    before = load_store(config.store_path, "live")
    assert before.state is not None
    requests: list[str] = []

    res = engage_kill_switch(
        config, clock=lambda: T0, is_running=True, request_kill=lambda: requests.append("kill")
    )

    assert res.success
    assert requests == ["kill"]
    after = load_store(config.store_path, "live")
    assert after.state is not None and after.state.revision == before.state.revision
    rows = load_audit_records(config.store_path)
    assert any('"result":"requested"' in r for r in rows)


def test_kill_switch_while_running_without_channel_is_refused(tmp_path: Path) -> None:
    """Plan 0035 Risk 1: istek yolu yoksa çalışan bota doğrudan yazılmaz, adıyla reddedilir."""
    config = config_for(tmp_path, "live", "live")
    res = engage_kill_switch(config, clock=lambda: T0, is_running=True)
    assert not res.success
    assert not kill_switch_of(config, "live")


def test_audit_row_is_valid_json_with_escapes() -> None:
    """R-6: elle üretilen denetim satırı geçerli JSON'dur; tırnak, ters bölü, satır sonu kaçışlı."""
    import json

    from crytobot.app._control import format_audit_row

    detail = 'hata: "salt-okunur" \\ yol\nikinci satır\tsekme — ç'
    row = format_audit_row(T0, "resume", "refused", detail, mode="live", config_mode="paper")
    assert json.loads(row) == {
        "action": "resume",
        "channel": "cli",
        "config_mode": "paper",
        "detail": detail,
        "mode": "live",
        "result": "refused",
        "timestamp": "2026-11-10T12:00:00+00:00",
    }
    assert "\n" not in row


# --- spec 0041 CB-4 (G-2), CB-5: control shows the store's network and never checks it ----------


def store_on_testnet(path: Path) -> Path:
    """Defteri açılmış, testnet'e bağlı canlı depo."""
    created = create_store(path, "live", "testnet")
    assert created.state is not None
    ledger = open_ledger(EMPTY_LEDGER, DEPOSIT, NOW).ledger
    saved = save_store(path, created.state, ledger, created.state.execution, created.state.risk)
    assert saved.state is not None
    return path


def _testnet_config(tmp_path: Path) -> BotConfig:
    tmp_path.mkdir(parents=True, exist_ok=True)
    db_path = store_on_testnet(tmp_path / "bot.db")
    return dataclasses.replace(make_bot_config(db_path, tmp_path / "bot.log"), mode="live")


def network_of(config: BotConfig) -> str:
    loaded = load_store(config.store_path, "live")
    assert loaded.state is not None
    return loaded.state.network


def test_status_shows_testnet(tmp_path: Path) -> None:
    """CB-5: testnet deposunda mod satırı ağı taşır; mainnet deposunda satır bugünküyle aynı."""
    status = query_status(_testnet_config(tmp_path / "tn"), clock=lambda: T0)
    assert status.success
    assert "Çalışma Modu: live ağ=testnet" in status.message.splitlines()

    (tmp_path / "mn").mkdir()
    mainnet = config_for(tmp_path / "mn", "live", "live")
    lines = query_status(mainnet, clock=lambda: T0).message.splitlines()
    assert "Çalışma Modu: live" in lines
    assert "ağ=" not in "\n".join(lines)


def test_control_commands_ignore_network(tmp_path: Path) -> None:
    """G-2: kill-switch, resume, stop ve status ağ denetimi yapmaz; ayar hangi ağı söylerse
    söylesin (kontrol ağı okumaz) testnet deposunda çalışır, deponun ağı değişmez."""
    config = _testnet_config(tmp_path)

    assert engage_kill_switch(config, clock=lambda: T0).success
    assert kill_switch_of(config, "live")
    assert resume_operations(config, clock=lambda: T0).success
    assert not kill_switch_of(config, "live")
    stopped: list[bool] = []
    result = request_stop(
        config, clock=lambda: T0, is_running=True, on_stop_requested=lambda: stopped.append(True)
    )
    assert result.success and stopped == [True]
    assert query_status(config, clock=lambda: T0).success
    assert network_of(config) == "testnet"
