"""Spec 0030 AC-7, AC-8: Depo kill switch kalıcılığı ve audit log testleri."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from crytobot.execution import EMPTY_EXECUTION
from crytobot.persistence import (
    StoreOutcome,
    append_audit_record,
    create_store,
    load_audit_records,
    load_store,
    save_store,
)
from crytobot.persistence._codec import decode_risk, encode_risk
from crytobot.portfolio import EMPTY_LEDGER
from crytobot.risk import (
    DEFAULT_LIMITS,
    EMPTY_STATE,
    engage_kill_switch,
    observe,
    resume,
)

T0 = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)


def test_kill_switch_persists_across_restarts(tmp_path: Path) -> None:
    """AC-7 (R-6): Kill switch devredeyken kaydedilen durum yüklendiğinde devrededir."""
    db_path = tmp_path / "bot.db"
    res = create_store(db_path, "paper")
    assert res.outcome is StoreOutcome.CREATED
    base = res.state
    assert base is not None

    # Bot runs, observes equity 10000
    observed_state = observe(EMPTY_STATE, T0, Decimal("10000"), DEFAULT_LIMITS).state
    save_res1 = save_store(db_path, base, EMPTY_LEDGER, EMPTY_EXECUTION, observed_state)
    assert save_res1.outcome is StoreOutcome.SAVED
    base1 = save_res1.state
    assert base1 is not None

    # Kill switch is engaged
    ks_state = engage_kill_switch(base1.risk).state
    assert ks_state.kill_switch
    save_res2 = save_store(db_path, base1, EMPTY_LEDGER, EMPTY_EXECUTION, ks_state)
    assert save_res2.outcome is StoreOutcome.SAVED

    # Reopening the store
    loaded = load_store(db_path, "paper")
    assert loaded.outcome is StoreOutcome.LOADED
    assert loaded.state is not None
    assert loaded.state.risk.kill_switch is True
    assert loaded.state.risk.last_equity == Decimal("10000")


def test_decode_risk_backward_compatible_with_6_elements() -> None:
    """Risk 4: 6 elemanlı eski JSON satırları varsayılan kill_switch=False olarak çözülür."""
    # 6-element legacy encoding: [day, day_start, peak, at, last, halted]
    legacy_json = '["2026-11-02","10000","10000","2026-11-02T10:00:00+00:00","10000",false]'
    decoded = decode_risk(legacy_json)
    assert decoded.kill_switch is False
    assert decoded.halted is False
    assert decoded.last_equity == Decimal("10000")

    # 7-element new encoding
    new_json_true = '["2026-11-02","10000","10000","2026-11-02T10:00:00+00:00","10000",false,true]'
    decoded_true = decode_risk(new_json_true)
    assert decoded_true.kill_switch is True
    assert decoded_true.halted is False

    # Round trip
    encoded = encode_risk(decoded_true)
    assert decode_risk(encoded) == decoded_true


def test_audit_records_append_and_load(tmp_path: Path) -> None:
    """AC-8 (R-7): Denetim kayıtları append-only olarak sırayla yazılır ve okunur."""
    db_path = tmp_path / "bot.db"
    create_store(db_path, "paper")

    record1 = '{"time":"2026-11-02T10:00:00Z","action":"kill-switch on","result":"engaged"}'
    record2 = '{"time":"2026-11-02T10:05:00Z","action":"resume","result":"resumed"}'

    res1 = append_audit_record(db_path, record1)
    assert res1.outcome is StoreOutcome.SAVED

    res2 = append_audit_record(db_path, record2)
    assert res2.outcome is StoreOutcome.SAVED

    records = load_audit_records(db_path)
    assert len(records) == 2
    assert records[0] == record1
    assert records[1] == record2


def test_audit_record_missing_store(tmp_path: Path) -> None:
    """Olmayan depoya audit kaydı eklenemez, NOT_FOUND döner."""
    db_path = tmp_path / "missing.db"
    res = append_audit_record(db_path, '{"action":"test"}')
    assert res.outcome is StoreOutcome.NOT_FOUND
    assert load_audit_records(db_path) == []


def test_resume_from_kill_switch_alone_saves_successfully(tmp_path: Path) -> None:
    """Yalnızca kill switch devredeyken resume ile zirve sıfırlansa bile save_store izin verir."""
    db_path = tmp_path / "bot.db"
    base = create_store(db_path, "paper").state
    assert base is not None

    # Observe 10000, then drop to 9000 (drawdown limit 15% not reached, so halted=False)
    state1 = observe(EMPTY_STATE, T0, Decimal("10000"), DEFAULT_LIMITS).state
    state2 = observe(state1, T0, Decimal("9000"), DEFAULT_LIMITS).state
    assert not state2.halted
    assert state2.peak_equity == Decimal("10000")

    # Engage kill switch and save
    state_ks = engage_kill_switch(state2).state
    base1 = save_store(db_path, base, EMPTY_LEDGER, EMPTY_EXECUTION, state_ks).state
    assert base1 is not None

    # Resume clears kill switch, sets peak to 9000 (which is lower than previous 10000 peak)
    resumed = resume(base1.risk, "cli").state
    assert not resumed.kill_switch
    assert resumed.peak_equity == Decimal("9000")

    save_res = save_store(db_path, base1, EMPTY_LEDGER, EMPTY_EXECUTION, resumed)
    assert save_res.outcome is StoreOutcome.SAVED
    assert save_res.state is not None
    assert save_res.state.risk.peak_equity == Decimal("9000")
