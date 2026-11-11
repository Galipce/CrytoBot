"""Spec 0037 AC-3, AC-4 (kalıcılık yarısı): kısmi kapanışlı canlı defter ve tahmini ücretli emir
yazılıp aynen okunur, defter ↔ emir çelişkisi oluşmaz; satır biçimi değişmez."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from crytobot.execution import (
    EMPTY_EXECUTION,
    CloseOrder,
    ExecutionState,
    Order,
    OrderStatus,
    close_client_id,
)
from crytobot.persistence import create_store, load_store, save_store
from crytobot.persistence._codec import CodecError, decode_orders, encode_order, encode_orders
from crytobot.portfolio import (
    EMPTY_LEDGER,
    Close,
    CloseReason,
    Fill,
    close_position,
    open_ledger,
    record_fill,
)
from crytobot.risk import EMPTY_STATE

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
PAIR = "BTC/USDT"
BUY = Order(
    "cb-a1", "a1", PAIR, "buy", Decimal(10), Decimal(8), Decimal(14), Decimal(1),
    OrderStatus.FILLED, Decimal(10), Decimal("0.01"), NOW,
    Decimal(1), Decimal(1), Decimal("0.0001"), "BNB", Decimal(0), fee_estimated=True,
)  # fmt: skip


def sell(cid: str, amount: str, filled: str) -> CloseOrder:
    return CloseOrder(
        cid, "cb-a1", PAIR, "sell", Decimal(amount), "hedef", OrderStatus.FILLED,
        Decimal(14), Decimal("0.004"), NOW + timedelta(hours=1),
        Decimal(filled), Decimal(filled), Decimal("0.004"), "USDT", Decimal(0),
    )  # fmt: skip


def close(order: CloseOrder, hours: int) -> Close:
    return Close(
        order.client_order_id,
        order.position_id,
        order.position_amount,
        order.fill_price,
        order.fee,
        CloseReason.TARGET,
        NOW + timedelta(hours=hours),
    )


def opened_live(tmp_path: Path) -> tuple[Path, Any]:
    path = tmp_path / "live.db"
    created = create_store(path, "live")
    assert created.state is not None
    ledger = open_ledger(EMPTY_LEDGER, Decimal(1000), NOW).ledger
    saved = save_store(path, created.state, ledger, EMPTY_EXECUTION, EMPTY_STATE)
    assert saved.state is not None
    return path, saved.state


def test_partial_close_round_trip_no_conflict(tmp_path: Path) -> None:
    """AC-3 (R-3; plan Risk 5): 1 BTC'lik pozisyon önce 0.4 (`cx-`), sonra kalan 0.6'nın 0.25'i
    (`cx2-`) kısmen kapanır. Depo kaydı kabul eder; yeniden yüklenen defter aynıdır (kalan 0.35,
    orantılı kalan ücret), mutabakat alım emrini alım kaydındaki pozisyonla eşler: çelişki yok."""
    path, base = opened_live(tmp_path)
    fill = Fill("cb-a1", PAIR, "buy", Decimal(1), Decimal(10), Decimal("0.01"),
                Decimal(8), Decimal(14), NOW)  # fmt: skip
    ledger = record_fill(base.ledger, fill).ledger
    first = sell(close_client_id("cb-a1"), "1", "0.4")
    ledger = close_position(ledger, close(first, 1), partial=True).ledger
    second = sell(close_client_id("cb-a1", 1), "0.6", "0.25")
    ledger = close_position(ledger, close(second, 2), partial=True).ledger
    rest = ledger.positions["cb-a1"]
    assert (rest.amount, rest.fee) == (Decimal("0.35"), Decimal("0.0035"))
    orders = {o.client_order_id: o for o in (BUY, first, second)}
    execution = ExecutionState(MappingProxyType(orders), MappingProxyType({}))

    saved = save_store(path, base, ledger, execution, base.risk)
    assert saved.state is not None, saved.message
    assert saved.conflicts == ()

    loaded = load_store(path, "live")
    assert loaded.state is not None and loaded.conflicts == ()
    assert loaded.state.ledger == ledger
    assert loaded.state.ledger.positions["cb-a1"] == rest
    assert loaded.state.execution.orders == orders
    assert loaded.state.execution.orders["cb-a1"].fee_estimated is True


def test_partial_close_conflict_is_still_found(tmp_path: Path) -> None:
    """Mutabakat kısmi kapanışta da çalışır: emir kaydının dolanı defterdeki kısımdan farklıysa
    çelişkidir."""
    path, base = opened_live(tmp_path)
    fill = Fill("cb-a1", PAIR, "buy", Decimal(1), Decimal(10), Decimal("0.01"),
                Decimal(8), Decimal(14), NOW)  # fmt: skip
    ledger = record_fill(base.ledger, fill).ledger
    first = sell("cx-a1", "1", "0.4")
    ledger = close_position(ledger, close(first, 1), partial=True).ledger
    other = replace(first, filled=Decimal("0.5"), net=Decimal("0.5"))
    orders = {o.client_order_id: o for o in (BUY, other)}

    saved = save_store(
        path, base, ledger, ExecutionState(MappingProxyType(orders), MappingProxyType({})),
        base.risk,
    )  # fmt: skip
    assert saved.state is not None
    assert saved.conflicts == ("cx-a1",)


def test_estimated_fee_row_and_old_rows_unchanged() -> None:
    """AC-4, AC-7 (R-4, R-7): tahmini ücret yalnız `true` ise canlı dolum dizisinin sonuna eklenir;
    tahmini olmayan canlı satır 0036'daki gibidir, paper satırı canlı dolum dizisi taşımaz. Bozuk
    işaret satırı okunamaz yapar."""
    estimated = encode_order(BUY, None)
    plain = encode_order(replace(BUY, fee_estimated=False), None)
    assert estimated.endswith('"BNB","0",true]]')
    assert plain.endswith('"BNB","0"]]')
    paper = replace(
        BUY, filled=None, net=None, commission=None, commission_asset=None, dust=None,
        fee_estimated=False,
    )  # fmt: skip
    assert not encode_order(paper, None).endswith("]]")
    state = ExecutionState(MappingProxyType({"cb-a1": BUY}), MappingProxyType({}))
    assert decode_orders(encode_orders(state)).orders["cb-a1"] == BUY
    for bad in ('"BNB","0",false]]', '"BNB","0","true"]]', '"BNB","0",true,true]]'):
        with pytest.raises(CodecError):
            decode_orders([estimated.replace('"BNB","0",true]]', bad)])
