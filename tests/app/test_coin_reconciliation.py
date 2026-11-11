"""Spec 0037 AC-5 (R-5, G-8; plan Risk 8, Amendment A-1): canlı turda coin mutabakatı — borsadaki
toplam coin, o coindeki açık pozisyonların net toplamından bir adımdan fazla azsa alım durur."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

from crytobot.app import BuyHalt, NoticeKind, TurnMemory, TurnNotice
from crytobot.execution import ExecutionState, LiveExchangeCallError, Order, OrderStatus
from crytobot.persistence import load_store, save_store
from crytobot.portfolio import Fill, record_fill
from tests.app.helpers import BTC, CROSS, ETH, FIRST_AMOUNT, NOW, pair_market
from tests.app.test_live_fills_turn import (
    BUY_MARKET,
    T1,
    T2,
    Venue,
    ledger_balance,
    live_store,
    stored,
    turn,
)

STEP = Decimal("0.001")  # the helpers' BTC amount step
SECOND = Decimal(2)  # a second BTC position, target 12: closes at price 12.5
HELD = FIRST_AMOUNT + SECOND


def two_btc_positions(tmp_path: Path) -> str:
    """Depoda aynı coinde (BTC) iki açık pozisyon: turdan gelen 49.115 (hedef 14) ve elle eklenen
    2 (hedef 12); ikisinin de dolu alım emri var, defter ↔ emir çelişkisi yok."""
    path = live_store(tmp_path)
    turn(path, Venue(), BUY_MARKET)
    loaded = load_store(path, "live")
    assert loaded.state is not None
    state = loaded.state
    at = NOW + timedelta(minutes=1)
    order = Order(
        "cb-second", "second", BTC, "buy", Decimal(10), Decimal(8), Decimal(12), SECOND,
        OrderStatus.FILLED, Decimal(10), Decimal("0.02"), at,
    )  # fmt: skip
    fill = Fill(order.client_order_id, BTC, "buy", SECOND, Decimal(10), Decimal("0.02"),
                Decimal(8), Decimal(12), at)  # fmt: skip
    ledger = record_fill(state.ledger, fill).ledger
    orders = {**state.execution.orders, order.client_order_id: order}
    execution = ExecutionState(MappingProxyType(orders), state.execution.quotes)
    saved = save_store(path, state, ledger, execution, state.risk)
    assert saved.state is not None and saved.conflicts == ()
    return path


def market(price: str = "11") -> dict[str, object]:
    return {
        BTC: pair_market(closes=CROSS, price=Decimal(price), closed_at=T1),
        ETH: pair_market(closes=CROSS, closed_at=T1),
    }


def venue(path: str, btc: Decimal, **kwargs: object) -> Venue:
    return Venue(balance=ledger_balance(path), coins={"BTC": btc}, **kwargs)  # type: ignore[arg-type]


def shortfalls(notices: list[TurnNotice]) -> list[tuple[str, bool]]:
    return [(n.subject, n.entering) for n in notices if n.kind is NoticeKind.COIN_SHORTFALL]


def test_shortfall_halts_buys_closes_continue(tmp_path: Path) -> None:
    """AC-5 (R-5): aynı coinde iki pozisyon (49.115 + 2); borsada toplam bundan bir adımdan fazla
    az (iki adım): yeni alım durur (ETH alınmaz), kapanış sürer (hedefi 12 olan 2'lik pozisyon
    12.5'te satılır), çift adıyla bildirim gider."""
    path = two_btc_positions(tmp_path)
    notices: list[TurnNotice] = []

    result = turn(
        path, venue(path, HELD - 2 * STEP), market("12.5"), T1, notices=notices,
        whitelist=(BTC, ETH),
    )  # fmt: skip

    assert BuyHalt.COIN_SHORTFALL in result.halts
    assert result.buys == ()
    assert [c.position.client_order_id for c in result.closures] == ["cb-second"]
    assert shortfalls(notices) == [(BTC, True)]
    message = next(n.message for n in notices if n.kind is NoticeKind.COIN_SHORTFALL)
    assert BTC in message and str(HELD) in message


def test_one_step_short_does_not_halt(tmp_path: Path) -> None:
    """AC-5 (sınır): tam bir adım eksiklik alımı durdurmaz (ETH alınır)."""
    path = two_btc_positions(tmp_path)
    notices: list[TurnNotice] = []

    result = turn(
        path, venue(path, HELD - STEP), market(), T1, notices=notices, whitelist=(BTC, ETH)
    )

    assert BuyHalt.COIN_SHORTFALL not in result.halts
    assert [o.pair for o in result.buys] == [ETH]
    assert shortfalls(notices) == []


def test_surplus_ignored(tmp_path: Path) -> None:
    """AC-5 (R-5): borsadaki fazla coin (sahibin bottan bağımsız varlığı, toz) yok sayılır."""
    path = two_btc_positions(tmp_path)
    notices: list[TurnNotice] = []

    result = turn(path, venue(path, HELD + 5), market(), T1, notices=notices, whitelist=(BTC, ETH))

    assert BuyHalt.COIN_SHORTFALL not in result.halts
    assert [o.pair for o in result.buys] == [ETH]
    assert shortfalls(notices) == []


def test_recovery_sends_exit_notice(tmp_path: Path) -> None:
    """AC-5 (R-5): eksiklik düzelince alım durdurması kalkar ve çıkış bildirimi gider; sürdükçe
    giriş bildirimi tekrarlanmaz."""
    path = two_btc_positions(tmp_path)
    memory = TurnMemory()
    notices: list[TurnNotice] = []
    short = venue(path, Decimal(1))
    first = turn(path, short, market(), T1, memory=memory, notices=notices, whitelist=(BTC, ETH))
    assert BuyHalt.COIN_SHORTFALL in first.halts
    again = turn(path, venue(path, Decimal(1)), market(), T1 + timedelta(minutes=1),
                 memory=memory, notices=notices, whitelist=(BTC, ETH))  # fmt: skip
    assert BuyHalt.COIN_SHORTFALL in again.halts
    assert shortfalls(notices) == [(BTC, True)]

    later = {
        BTC: pair_market(closes=CROSS, price=Decimal(11), closed_at=T2),
        ETH: pair_market(closes=CROSS, closed_at=T2),
    }
    fixed = turn(path, venue(path, HELD), later, T2, memory=memory, notices=notices,
                 whitelist=(BTC, ETH))  # fmt: skip
    assert BuyHalt.COIN_SHORTFALL not in fixed.halts
    assert [o.pair for o in fixed.buys] == [ETH]
    assert shortfalls(notices) == [(BTC, True), (BTC, False)]


def test_balance_query_failure_safe_mode(tmp_path: Path) -> None:
    """AC-5 (G-8): coin bakiyesi sorgusu başarısızsa güvenli mod devreye girer, alım durur,
    bildirim üretilir; süren coin eksikliği bildirimi değerlendirilmediği için bitmiş sayılmaz."""
    path = two_btc_positions(tmp_path)
    memory = TurnMemory()
    notices: list[TurnNotice] = []
    turn(path, venue(path, Decimal(1)), market(), T1, memory=memory, notices=notices)
    error = LiveExchangeCallError("ağ", is_unknown=True)
    failing = venue(path, HELD, balances_error=error)

    result = turn(path, failing, market(), T1 + timedelta(minutes=1), memory=memory,
                  notices=notices, whitelist=(BTC, ETH))  # fmt: skip

    assert BuyHalt.BALANCE_CHECK_FAILED in result.halts
    assert result.buys == ()
    safe = [n for n in notices if n.kind is NoticeKind.SAFE_MODE and n.entering]
    assert safe and "LiveExchangeCallError" in safe[0].message
    assert shortfalls(notices) == [(BTC, True)]  # no exit while the coins were not evaluated
    assert len(stored(path).ledger.positions) == 2
