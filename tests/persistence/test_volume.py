"""Spec 0011 AC-12 (R-11): 10.000 defter kayıtlı depoda yükleme ve kayıt 1 saniyenin altında.

Süre ayrı süreçte ölçülür: `test-slow` `--cov` ile koşar ve coverage izlemesi ürüne ait olmayan
süre ekler (bu makinede yükleme 0,6 s yerine 1,75 s). Sınır aynıdır, ölçülen ürünün kendisidir.
"""

import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import pytest

from crytobot.execution import (
    EMPTY_EXECUTION,
    CloseOrder,
    Order,
    OrderStatus,
)
from crytobot.persistence import StoreOutcome, load_store
from crytobot.portfolio import (
    CloseReason,
    Closure,
    Entry,
    EntryKind,
    Ledger,
    Position,
)
from crytobot.risk import EMPTY_STATE
from tests.persistence.chain import PAIR, T0, World, bought, created, save, seen

pytestmark = pytest.mark.slow

ROUNDS = 5000
LIMIT_S = 1.0
ROOT = Path(__file__).resolve().parents[2]
CHILD = """
import json, sys
from pathlib import Path
from tests.persistence.test_volume import measure
assert "coverage" not in sys.modules
print(json.dumps(measure(Path(sys.argv[1]))))
"""


def big_world() -> World:
    """5000 alım + 5000 kapanış + açılış: kayıtlar doğrudan, motorun hesabıyla aynı biçimde.
    Her değer tekil: gerçek veride tekrar yok, ölçüm önbellekten yararlanmasın.

    `record_fill` ile kurmak O(n²) olurdu; `ledger_problems` kayıtta aynı hesabı doğrular.
    """
    deposit = Decimal("100000000.12345678")
    entries = [Entry(EntryKind.OPENING, T0, deposit, None)]
    balance, realized = deposit, Decimal(0)
    closures: dict[str, Closure] = {}
    orders: dict[str, Order | CloseOrder] = {}
    for i in range(ROUNDS):
        at = T0 + timedelta(seconds=i + 1)
        amount = Decimal(f"0.0012{i:04d}")
        price = Decimal(f"65432.1{i:04d}678")
        fee = Decimal(f"0.08{i:04d}")
        position = Position(
            f"cb-{i}", PAIR, amount, price, fee, Decimal("60000.1"), Decimal("70000.1"), at
        )
        cost = amount * price + fee
        entries.append(Entry(EntryKind.FILL, at, cost, position))
        balance -= cost
        orders[f"cb-{i}"] = Order(
            f"cb-{i}",
            str(i),
            PAIR,
            "buy",
            price,
            position.stop,
            position.target,
            amount,
            OrderStatus.FILLED,
            price,
            fee,
            at,
        )
        sale = Decimal(f"66000.5{i:04d}")
        close_fee = Decimal(f"0.09{i:04d}")
        proceeds = amount * sale - close_fee
        gain = proceeds - cost
        closure = Closure(
            f"cx-{i}", position, amount, sale, close_fee, CloseReason.TARGET, at, proceeds, gain
        )
        entries.append(Entry(EntryKind.CLOSE, at, proceeds, position, closure))
        closures[closure.client_order_id] = closure
        balance += proceeds
        realized += gain
        orders[f"cx-{i}"] = CloseOrder(
            f"cx-{i}",
            f"cb-{i}",
            PAIR,
            "sell",
            amount,
            "hedef",
            OrderStatus.FILLED,
            sale,
            close_fee,
            at,
        )
    ledger = Ledger(
        tuple(entries),
        balance,
        MappingProxyType({}),
        MappingProxyType(closures),
        realized,
    )
    execution = replace(EMPTY_EXECUTION, orders=MappingProxyType(orders))
    return seen(World(ledger, execution, EMPTY_STATE), "100000000", T0)


def measure(path: Path) -> dict[str, float]:
    """Kayıt, yükleme, sonraki kayıt: saniye."""
    world = big_world()
    assert len(world.ledger.entries) >= 10_000
    state = created(path)

    start = time.perf_counter()
    first = save(path, state, world)
    first_took = time.perf_counter() - start
    assert first.outcome is StoreOutcome.SAVED, first.message
    assert first.reconciled and first.state is not None

    start = time.perf_counter()
    result = load_store(path, "paper")
    load_took = time.perf_counter() - start
    assert result.outcome is StoreOutcome.LOADED and result.state is not None

    grown = bought(world, "yeni", amount="0.5", at=T0 + timedelta(days=1))
    start = time.perf_counter()
    second = save(path, result.state, grown)
    second_took = time.perf_counter() - start
    assert second.outcome is StoreOutcome.SAVED, second.message
    return {"load": load_took, "first": first_took, "second": second_took}


def test_load_and_save_of_ten_thousand_entries_stay_under_a_second(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("COV_", "COVERAGE_"))}
    child = subprocess.run(
        [sys.executable, "-c", CHILD, str(tmp_path / "depo.sqlite")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert child.returncode == 0, child.stderr
    took = json.loads(child.stdout)

    assert took["load"] < LIMIT_S, f"yükleme {took['load']:.3f} s"
    assert took["first"] < LIMIT_S, f"ilk kayıt {took['first']:.3f} s"
    assert took["second"] < LIMIT_S, f"sonraki kayıt {took['second']:.3f} s"
