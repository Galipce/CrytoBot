"""Spec 0038 CB-2…CB-5 (plan Adım 4): paper kanıtı kapısı, her ret nedeni ve sınır değerleri.

Depo gerçek zincirle kurulur (`tests/persistence/chain.py`): hazırlık (revizyon 1) → kanıtlı
başlatma kaydı → alım/kapanışlar → son tur işareti. Burada kurulan yardımcıları giriş noktası
testleri de kullanır.
"""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import BotConfig, StageConfig, check_paper_proof
from crytobot.app import _paper_proof as paper_proof
from crytobot.persistence import (
    StartRecord,
    StartRecordsResult,
    StoreOutcome,
    append_start_record,
    load_store,
    mark_turn,
    save_store,
)
from tests.app.helpers import limits
from tests.app.helpers import make_settings as turn_settings
from tests.app.loop_fakes import bot_config
from tests.persistence.chain import EMPTY_WORLD, World, bought, opened, seen, sold, stored

OPENED_AT = datetime.fromisoformat("2026-10-01T08:00:00+00:00")
STARTED = OPENED_AT + timedelta(hours=1)
LAST_TURN = STARTED + timedelta(days=14)
APPROVED = LAST_TURN + timedelta(hours=1)
NOW = APPROVED + timedelta(hours=1)
DEPOSIT = Decimal(10000)


def resolve(path: str) -> str:
    return str(Path(path).resolve())


def same_file(first: str, second: str) -> bool:
    return resolve(first) == resolve(second)


def report_of(root: Path) -> str:
    return str(root / "rapor.txt")


def traded(trades: int = 10, *, open_positions: int = 0, wins: bool = True) -> World:
    """`trades` kapanmış işlem (her biri kâr ya da zararla) ve `open_positions` açık alım."""
    world = opened(DEPOSIT, OPENED_AT)
    price = "110" if wins else "90"
    for index in range(trades):
        at = STARTED + timedelta(hours=index + 1)
        world = bought(world, f"t{index}", amount="10", price="100", at=at)
        world = sold(world, f"cb-t{index}", price=price, at=at + timedelta(minutes=30))
    for index in range(open_positions):
        at = STARTED + timedelta(hours=trades + index + 1)
        world = bought(world, f"o{index}", amount="1", price="100", at=at)
    return world


def proof_store(
    path: Path,
    world: World | None = None,
    *,
    records: tuple[StartRecord, ...] | None = None,
    last_turn: datetime | None = LAST_TURN,
    report: str | None = None,
) -> Path:
    """Hazırlık → başlatma kayıtları → `world` → son tur. Varsayılan: geçen bir kanıt."""
    base = stored(path, opened(DEPOSIT, OPENED_AT))
    report = report_of(path.parent) if report is None else report
    for record in (StartRecord(STARTED, False, report),) if records is None else records:
        assert append_start_record(path, record).outcome is StoreOutcome.SAVED
    world = traded() if world is None else world
    world = seen(world, str(DEPOSIT), at=STARTED + timedelta(minutes=5))
    saved = save_store(path, base, world.ledger, world.execution, world.risk)
    assert saved.state is not None, saved.message
    if last_turn is not None:
        assert mark_turn(path, last_turn).message == "tur işaretlendi"
    return path


def stage_for(root: Path, **changes: Any) -> StageConfig:
    values: dict[str, Any] = {
        "report_path": report_of(root),
        "approved_by": "Galip Badem",
        "approved_at": OPENED_AT,
        "live_approved_by": "Galip Badem",
        "live_approved_at": APPROVED,
        "paper_store_path": str(root / "paper.sqlite"),
    }
    return StageConfig(**{**values, **changes})


def bot_for(root: Path, *, max_drawdown: Decimal | None = None) -> BotConfig:
    config = bot_config(root / "canli.sqlite")
    if max_drawdown is None:
        return config
    turn = turn_settings(limits=limits(max_drawdown=max_drawdown))
    return replace(config, turn=turn)


def check(
    root: Path,
    *,
    stage: StageConfig | None = None,
    bot: BotConfig | None = None,
    now: datetime = NOW,
    busy: bool = False,
    live: str | None = None,
) -> paper_proof.PaperProofResult:
    return check_paper_proof(
        stage_for(root) if stage is None else stage,
        bot_for(root) if bot is None else bot,
        str(root / "canli.sqlite") if live is None else live,
        now,
        lambda _path: busy,
        same_file=same_file,
        resolve=resolve,
    )


# --- passing ----------------------------------------------------------------------------------


def test_a_proven_paper_run_passes_with_its_summary(tmp_path: Path) -> None:
    proof_store(tmp_path / "paper.sqlite", traded(open_positions=2))

    result = check(tmp_path)

    assert result.passed, result.message
    assert result.summary is not None
    assert result.summary.path == str(tmp_path / "paper.sqlite")
    assert (result.summary.days, result.summary.trades) == (14, 10)
    assert result.summary.open_positions == 2
    assert result.summary.net > 0


def test_the_check_writes_nothing_to_the_paper_store(tmp_path: Path) -> None:
    path = proof_store(tmp_path / "paper.sqlite")
    before = path.read_bytes()

    check(tmp_path)

    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["paper.sqlite"]


def test_relative_and_absolute_report_spellings_are_the_same_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-5: göreli/mutlak yazım farkı ret nedeni değildir."""
    monkeypatch.chdir(tmp_path)
    proof_store(tmp_path / "paper.sqlite")

    assert check(tmp_path, stage=stage_for(tmp_path, report_path="rapor.txt")).passed
    assert check(tmp_path, stage=stage_for(tmp_path, report_path="./x/../rapor.txt")).passed


# --- CB-2: the store ---------------------------------------------------------------------------


def test_missing_setting_is_named(tmp_path: Path) -> None:
    result = check(tmp_path, stage=stage_for(tmp_path, paper_store_path=None))

    assert (result.passed, result.message) == (False, "ayar eksik: stage.paper_store_path")


def test_the_live_store_itself_is_refused_before_it_is_read(tmp_path: Path) -> None:
    path = proof_store(tmp_path / "paper.sqlite")

    result = check(tmp_path, live=str(path))

    assert result.message == "paper kanıtı: paper deposu canlı deponun kendisi"


def test_missing_paper_store_is_refused_and_not_created(tmp_path: Path) -> None:
    result = check(tmp_path)

    assert result.message == "paper kanıtı: paper deposu yok"
    assert list(tmp_path.iterdir()) == []


def test_a_store_in_use_is_refused(tmp_path: Path) -> None:
    proof_store(tmp_path / "paper.sqlite")

    assert check(tmp_path, busy=True).message == "paper kanıtı: paper deposu kullanımda"


def test_a_live_store_is_not_paper_proof(tmp_path: Path) -> None:
    stored(tmp_path / "paper.sqlite", traded(), mode="live")

    assert check(tmp_path).message == "paper kanıtı: paper deposu live modunda"


def test_an_unreadable_store_is_refused(tmp_path: Path) -> None:
    (tmp_path / "paper.sqlite").write_bytes(b"not a database at all, just bytes" * 10)

    result = check(tmp_path)

    assert not result.passed
    assert result.message.startswith("paper kanıtı: depo okunamıyor")


def test_a_store_whose_reconciliation_fails_is_refused(tmp_path: Path) -> None:
    """Plan A-4."""
    path = tmp_path / "paper.sqlite"
    base = stored(path, opened(DEPOSIT, OPENED_AT))
    append_start_record(path, StartRecord(STARTED, False, report_of(tmp_path)))
    world = traded()
    save_store(path, base, world.ledger, opened().execution, world.risk)  # fills, no orders

    assert check(tmp_path).message == "paper kanıtı: depo bozuk (mutabakat tutmuyor)"


def test_a_store_without_an_opened_ledger_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite"
    stored(path, EMPTY_WORLD)

    assert check(tmp_path).message == "paper kanıtı: defter açılmamış"


# --- CB-3: integrity ---------------------------------------------------------------------------


def test_a_store_without_start_records_is_refused(tmp_path: Path) -> None:
    proof_store(tmp_path / "paper.sqlite", records=())

    assert check(tmp_path).message == "paper kanıtı: başlatma kaydı yok"


def test_any_trial_record_is_refused(tmp_path: Path) -> None:
    report = report_of(tmp_path)
    records = (
        StartRecord(STARTED, False, report),
        StartRecord(STARTED + timedelta(days=1), True, None),
    )
    proof_store(tmp_path / "paper.sqlite", records=records)

    assert check(tmp_path).message == "paper kanıtı: deneme koşusu var"


def test_history_before_the_first_record_is_refused(tmp_path: Path) -> None:
    """G-8, plan Risk 2: ilk kayıttan önce depoda tur ya da emir varsa kayıt eksiktir."""
    path = tmp_path / "paper.sqlite"
    base = stored(path, opened(DEPOSIT, OPENED_AT))
    world = traded()
    later = save_store(path, base, world.ledger, world.execution, world.risk)
    assert later.state is not None
    append_start_record(path, StartRecord(STARTED, False, report_of(tmp_path)))
    mark_turn(path, LAST_TURN)

    assert check(tmp_path).message == "paper kanıtı: başlatma kaydı eksik"


def test_entries_older_than_the_first_record_are_refused(tmp_path: Path) -> None:
    late = StartRecord(STARTED + timedelta(days=1), False, report_of(tmp_path))
    proof_store(tmp_path / "paper.sqlite", records=(late,))

    assert check(tmp_path).message == "paper kanıtı: başlatma kaydı eksik"


def test_a_last_turn_older_than_the_first_record_is_refused(tmp_path: Path) -> None:
    late = StartRecord(STARTED + timedelta(days=20), False, report_of(tmp_path))
    proof_store(tmp_path / "paper.sqlite", world=opened(DEPOSIT, OPENED_AT), records=(late,))

    assert check(tmp_path).message == "paper kanıtı: başlatma kaydı eksik"


def test_records_linked_to_two_reports_are_refused(tmp_path: Path) -> None:
    records = (
        StartRecord(STARTED, False, report_of(tmp_path)),
        StartRecord(STARTED + timedelta(days=1), False, str(tmp_path / "başka.txt")),
    )
    proof_store(tmp_path / "paper.sqlite", records=records)

    assert check(tmp_path).message == "paper kanıtı: rapor uyuşmazlığı"


def test_a_report_other_than_the_live_settings_is_refused(tmp_path: Path) -> None:
    proof_store(tmp_path / "paper.sqlite")

    result = check(tmp_path, stage=stage_for(tmp_path, report_path=str(tmp_path / "yeni.txt")))

    assert result.message == "paper kanıtı: rapor uyuşmazlığı"


def test_an_unreadable_record_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proof_store(tmp_path / "paper.sqlite")
    broken = StartRecordsResult(StoreOutcome.UNREADABLE, (), "depo okunamıyor")
    monkeypatch.setattr(paper_proof, "load_start_records", lambda *_a, **_k: broken)

    assert check(tmp_path).message == "paper kanıtı: depo okunamıyor"


# --- CB-4: thresholds --------------------------------------------------------------------------


def test_exactly_the_minimum_days_passes_one_second_less_does_not(tmp_path: Path) -> None:
    """(a), G-1: 14 x 24 saat, takvim günü değil."""
    proof_store(tmp_path / "a.sqlite", last_turn=STARTED + timedelta(days=14))
    proof_store(tmp_path / "b.sqlite", last_turn=STARTED + timedelta(days=14, seconds=-1))

    passed = check(tmp_path, stage=stage_for(tmp_path, paper_store_path=str(tmp_path / "a.sqlite")))
    failed = check(tmp_path, stage=stage_for(tmp_path, paper_store_path=str(tmp_path / "b.sqlite")))

    assert passed.passed, passed.message
    assert failed.message == "paper eşiği karşılanmadı: paper_min_days"


def test_the_day_threshold_follows_the_setting(tmp_path: Path) -> None:
    proof_store(tmp_path / "paper.sqlite", last_turn=STARTED + timedelta(days=7))

    assert check(tmp_path).message == "paper eşiği karşılanmadı: paper_min_days"
    assert check(tmp_path, stage=stage_for(tmp_path, paper_min_days=7)).passed


def test_a_store_without_any_turn_has_no_days(tmp_path: Path) -> None:
    proof_store(tmp_path / "paper.sqlite", last_turn=None)

    assert check(tmp_path).message == "paper eşiği karşılanmadı: paper_min_days"


def test_exactly_the_minimum_trades_passes_one_less_does_not(tmp_path: Path) -> None:
    """(b), G-2, G-3: açık pozisyon işlem sayılmaz."""
    proof_store(tmp_path / "a.sqlite", traded(10))
    proof_store(tmp_path / "b.sqlite", traded(9, open_positions=3))

    passed = check(tmp_path, stage=stage_for(tmp_path, paper_store_path=str(tmp_path / "a.sqlite")))
    failed = check(tmp_path, stage=stage_for(tmp_path, paper_store_path=str(tmp_path / "b.sqlite")))

    assert passed.passed, passed.message
    assert failed.message == "paper eşiği karşılanmadı: paper_min_trades"
    assert check(
        tmp_path,
        stage=stage_for(tmp_path, paper_store_path=str(tmp_path / "b.sqlite"), paper_min_trades=9),
    ).passed


def test_a_net_loss_is_refused(tmp_path: Path) -> None:
    """(c): komisyon dahil gerçekleşen net."""
    proof_store(tmp_path / "paper.sqlite", traded(wins=False))

    assert check(tmp_path).message == "paper eşiği karşılanmadı: net kâr sıfırdan büyük olmalı"


@pytest.mark.parametrize(
    ("curve", "passed"),
    [
        ((Decimal(100), Decimal(100)), False),  # net = 0
        ((Decimal(100), Decimal("100.00000001")), True),
        ((Decimal(100), Decimal(90)), False),
    ],
)
def test_net_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, curve: tuple[Decimal, ...], passed: bool
) -> None:
    proof_store(tmp_path / "paper.sqlite")
    monkeypatch.setattr(paper_proof, "realized_curve", lambda _ledger: curve)

    result = check(tmp_path)

    assert result.passed is passed, result.message
    if not passed:
        assert result.message == "paper eşiği karşılanmadı: net kâr sıfırdan büyük olmalı"


def test_a_curve_that_cannot_be_computed_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proof_store(tmp_path / "paper.sqlite")
    monkeypatch.setattr(paper_proof, "realized_curve", lambda _ledger: ())

    assert check(tmp_path).message == "paper kanıtı: kasa eğrisi hesaplanamıyor"


@pytest.mark.parametrize(
    ("limit", "trough", "passed"),
    [
        # peak 125: 15 % of it is 18.75 → trough 106.25 is exactly at the limit
        (Decimal("0.15"), Decimal("106.25"), True),
        (Decimal("0.15"), Decimal("106.24"), False),
        # a limit above the 25 % ceiling: the ceiling holds (trough 93.75 = 25 %)
        (Decimal("0.30"), Decimal("93.75"), True),
        (Decimal("0.30"), Decimal("93.74"), False),
    ],
)
def test_drawdown_boundary_and_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit: Decimal,
    trough: Decimal,
    passed: bool,
) -> None:
    """(d): gerçekleşen kasa eğrisinin tepe→dip oranı ≤ min(risk.max_drawdown, %25)."""
    proof_store(tmp_path / "paper.sqlite")
    curve = (Decimal(100), Decimal(125), trough, Decimal(130))
    monkeypatch.setattr(paper_proof, "realized_curve", lambda _ledger: curve)

    result = check(tmp_path, bot=bot_for(tmp_path, max_drawdown=limit))

    assert result.passed is passed, result.message
    if not passed:
        assert result.message == "paper eşiği karşılanmadı: max_drawdown"


def test_thresholds_are_reported_in_order(tmp_path: Path) -> None:
    """İlk karşılanmayan eşik adıyla: gün, işlem ve net birlikte eksikken gün söylenir."""
    proof_store(tmp_path / "paper.sqlite", traded(2, wins=False), last_turn=STARTED)

    assert check(tmp_path).message == "paper eşiği karşılanmadı: paper_min_days"


# --- CB-5: approval order ----------------------------------------------------------------------


def test_approval_at_or_before_the_last_turn_is_refused(tmp_path: Path) -> None:
    proof_store(tmp_path / "paper.sqlite")

    for approved in (LAST_TURN, LAST_TURN - timedelta(seconds=1)):
        result = check(tmp_path, stage=stage_for(tmp_path, live_approved_at=approved))
        assert result.message == "stage.live_approved_at: onay paper sonucundan önce"


def test_approval_in_the_future_is_refused_and_now_is_allowed(tmp_path: Path) -> None:
    proof_store(tmp_path / "paper.sqlite")

    future = check(tmp_path, now=APPROVED - timedelta(seconds=1))
    equal = check(tmp_path, now=APPROVED)

    assert future.message == "stage.live_approved_at: onay gelecekte"
    assert equal.passed, equal.message


def test_missing_approval_is_named(tmp_path: Path) -> None:
    proof_store(tmp_path / "paper.sqlite")

    result = check(tmp_path, stage=stage_for(tmp_path, live_approved_at=None))

    assert result.message == "ayar eksik: stage.live_approved_at"


def test_the_paper_store_is_read_only_once_per_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CB-2: salt okunur açılır."""
    proof_store(tmp_path / "paper.sqlite")
    seen_flags: list[object] = []

    def spy(path: object, mode: object, readonly: bool = False) -> Any:
        seen_flags.append(readonly)
        return load_store(path, mode, readonly=readonly)

    monkeypatch.setattr(paper_proof, "load_store", spy)

    assert check(tmp_path).passed
    assert seen_flags == [True]
