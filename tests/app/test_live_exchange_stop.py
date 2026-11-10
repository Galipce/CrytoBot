"""Spec 0034 AC-5..AC-8: Canlı borsa şartlı stop emri entegrasyonu ve paper izolasyonu."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from crytobot.app import (
    BuyHalt,
    NoticeKind,
    TurnMemory,
    TurnNotice,
    prepare_live_store,
    prepare_store,
    run_turn,
)
from crytobot.execution import (
    LiveExchange,
    OrderStatus,
    PaperExchange,
    stop_client_id,
)
from crytobot.persistence import load_store
from crytobot.portfolio import CloseReason
from tests.app.helpers import BTC, CROSS, FLAT, NOW, make_settings, pair_market
from tests.app.test_live_start import FakeLiveClient

PAIR = BTC


class MockLiveExchange(LiveExchange):
    def __init__(
        self,
        free_balance: Decimal = Decimal("1000.00"),
        stop_placement_status: OrderStatus = OrderStatus.NEW,
        stop_cancel_status: OrderStatus = OrderStatus.CANCELED,
        stop_query_status: OrderStatus = OrderStatus.NEW,
        stop_fetch_order: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(client=FakeLiveClient(free_balance=free_balance))
        self._free_balance = free_balance
        self.stop_placement_status = stop_placement_status
        self.stop_cancel_status = stop_cancel_status
        self.stop_query_status = stop_query_status
        self.stop_fetch_order = stop_fetch_order
        self.placed_market_calls: list[dict[str, Any]] = []
        self.placed_stop_calls: list[dict[str, Any]] = []
        self.canceled_calls: list[dict[str, Any]] = []
        self.call_order: list[str] = []

    def fetch_free_balance(self, asset: str = "USDT") -> Decimal:
        return self._free_balance

    def place(
        self,
        client_order_id: str,
        symbol: str = "",
        side: str = "",
        amount: object = None,
    ) -> OrderStatus:
        self.call_order.append(f"place:{client_order_id}")
        self.placed_market_calls.append(
            {"id": client_order_id, "symbol": symbol, "side": side, "amount": amount}
        )
        return OrderStatus.FILLED

    def place_stop_order(
        self,
        client_order_id: str,
        symbol: str = "",
        amount: object = None,
        stop_price: object = None,
        limit_price: object = None,
    ) -> OrderStatus:
        self.call_order.append(f"place_stop:{client_order_id}")
        self.placed_stop_calls.append(
            {
                "id": client_order_id,
                "symbol": symbol,
                "amount": amount,
                "stop_price": stop_price,
                "limit_price": limit_price,
            }
        )
        return self.stop_placement_status

    def cancel_order(self, client_order_id: str, symbol: str = "") -> OrderStatus:
        self.call_order.append(f"cancel:{client_order_id}")
        self.canceled_calls.append({"id": client_order_id, "symbol": symbol})
        return self.stop_cancel_status

    def query(self, client_order_id: str, symbol: str = "") -> OrderStatus:
        if client_order_id.startswith("cs-"):
            return self.stop_query_status
        return OrderStatus.FILLED

    def fetch_order(self, client_order_id: str, symbol: str = "") -> dict[str, Any] | None:
        return self.stop_fetch_order


def _run(
    store_path: str,
    exchange: Any,
    market: Any,
    now: datetime = NOW,
    memory: TurnMemory | None = None,
    sink: Any = None,
) -> Any:
    return run_turn(
        market=market,
        settings=make_settings(),
        store_path=store_path,
        now=now,
        exchange=exchange,
        sink=sink or (lambda n: None),
        memory=memory or TurnMemory(),
    )


def test_stop_order_failure_enters_safe_mode_and_halts_buys(tmp_path: Path) -> None:
    """Spec 0034 AC-3, AC-7: Canlı alım dolumu sonrası borsa stop başarısızsa güvenli mod."""
    store_path = str(tmp_path / "live_fail.db")
    prepare_live_store(store_path, NOW, live_client=FakeLiveClient(free_balance=Decimal("1000.00")))

    # Borsa stop emri REJECTED dönen adaptör
    ex = MockLiveExchange(
        free_balance=Decimal("1000.00"),
        stop_placement_status=OrderStatus.REJECTED,
    )
    notices: list[TurnNotice] = []
    market = {BTC: pair_market(closes=CROSS, price=Decimal(10))}

    res = _run(
        store_path=store_path,
        exchange=ex,
        market=market,
        now=NOW,
        sink=notices.append,
    )

    # 1. Alım piyasa emri dolmuş ve borsaya stop emri iletilmiş olmalı
    assert len(res.buys) == 1
    buy_order = res.buys[0]
    expected_stop_id = stop_client_id(buy_order.client_order_id)
    assert len(ex.placed_stop_calls) == 1
    assert ex.placed_stop_calls[0]["id"] == expected_stop_id
    assert ex.placed_stop_calls[0]["symbol"] == PAIR
    assert ex.placed_stop_calls[0]["amount"] == buy_order.amount
    assert ex.placed_stop_calls[0]["stop_price"] == buy_order.stop

    # 2. Stop emri başarısızlığı fail-closed durdurma ve güvenli mod üretmeli
    assert BuyHalt.STOP_ORDER_FAILED in res.halts
    assert any(n.kind is NoticeKind.SAFE_MODE for n in notices)


def test_pre_reconciliation_syncs_filled_exchange_stop(tmp_path: Path) -> None:
    """Spec 0034 AC-5: Tur başında dolmuş borsa stop emri mutabakat öncesi eşitlenir."""
    store_path = str(tmp_path / "live_sync.db")
    prepare_live_store(
        store_path, NOW, live_client=FakeLiveClient(free_balance=Decimal("10000.00"))
    )

    # 1. Tur: Pozisyon açılır
    ex_turn1 = MockLiveExchange(
        free_balance=Decimal("10000.00"),
        stop_placement_status=OrderStatus.NEW,
    )
    res1 = _run(
        store_path=store_path,
        exchange=ex_turn1,
        market={BTC: pair_market(closes=CROSS, price=Decimal(10))},
        now=NOW,
    )
    assert len(res1.buys) == 1

    stored1 = load_store(store_path, "live").state
    assert stored1 is not None
    assert stored1.ledger.balance is not None
    assert len(stored1.ledger.positions) == 1
    pos = next(iter(stored1.ledger.positions.values()))

    # Stop dolumu hesabı: miktar * 8 * (1 - fee) USDT kasaya girer
    fee_rate = Decimal("0.001")
    stop_proceeds = pos.amount * Decimal(8) * (Decimal(1) - fee_rate)
    expected_synced_balance = stored1.ledger.balance + stop_proceeds

    # 2. Tur: Borsa stop emri borsada dolmuş; borsa serbest bakiyesi stop gelirini içerir
    later_time = datetime(2026, 11, 10, 11, 0, tzinfo=UTC)
    fee_cost_str = str(pos.amount * Decimal(8) * fee_rate)
    ex_turn2 = MockLiveExchange(
        free_balance=expected_synced_balance,
        stop_query_status=OrderStatus.FILLED,
        stop_fetch_order={"average": "8.00", "fee": {"cost": fee_cost_str}},
    )
    notices2: list[TurnNotice] = []
    res2 = _run(
        store_path=store_path,
        exchange=ex_turn2,
        market={BTC: pair_market(closes=FLAT, price=Decimal(8), closed_at=later_time)},
        now=later_time,
        sink=notices2.append,
    )

    # Dolan stop emri mutabakat öncesi CloseReason.STOP olarak işlenmeli
    stored2 = load_store(store_path, "live").state
    assert stored2 is not None
    assert len(stored2.ledger.positions) == 0
    assert len(stored2.ledger.closures) == 1
    closure = next(iter(stored2.ledger.closures.values()))
    assert closure.reason is CloseReason.STOP
    assert closure.price == Decimal("8.00")

    # Mutabakat tolerans hatası vermemeli (0 fark)
    assert BuyHalt.RECONCILIATION_HALT not in res2.halts
    assert BuyHalt.STOP_ORDER_FAILED not in res2.halts


def test_close_cancels_pending_exchange_stop_before_market_sell(tmp_path: Path) -> None:
    """Spec 0034 AC-6: Hedefte kapanış öncesi borsa stop'u iptal edilir; yarış koşulu önlenir."""
    store_path = str(tmp_path / "live_close.db")
    prepare_live_store(
        store_path, NOW, live_client=FakeLiveClient(free_balance=Decimal("10000.00"))
    )

    # 1. Tur: Pozisyon açılır
    ex_turn1 = MockLiveExchange(
        free_balance=Decimal("10000.00"),
        stop_placement_status=OrderStatus.NEW,
    )
    res1 = _run(
        store_path=store_path,
        exchange=ex_turn1,
        market={BTC: pair_market(closes=CROSS, price=Decimal(10))},
        now=NOW,
    )
    buy_order = res1.buys[0]
    expected_stop_id = stop_client_id(buy_order.client_order_id)

    # 2. Tur: Fiyat hedefe (15 >= 14) ulaşır: önce iptal, sonra piyasa satışı
    later_time = datetime(2026, 11, 10, 11, 0, tzinfo=UTC)
    ex_turn2 = MockLiveExchange(
        free_balance=Decimal("9500.00"),
        stop_cancel_status=OrderStatus.CANCELED,
    )
    _run(
        store_path=store_path,
        exchange=ex_turn2,
        market={BTC: pair_market(closes=FLAT, price=Decimal(15), closed_at=later_time)},
        now=later_time,
    )

    # İptal çağrısı piyasa satışından (place) ÖNCE yapılmış olmalı
    assert len(ex_turn2.canceled_calls) == 1
    assert ex_turn2.canceled_calls[0]["id"] == expected_stop_id
    cancel_idx = ex_turn2.call_order.index(f"cancel:{expected_stop_id}")
    market_sell_calls = [c for c in ex_turn2.call_order if c.startswith("place:cx-")]
    assert len(market_sell_calls) == 1
    place_idx = ex_turn2.call_order.index(market_sell_calls[0])
    assert cancel_idx < place_idx

    # 3. Yarış koşulu senaryosu: İptal sırasında stop emrinin zaten FILLED olduğu anlaşılır
    store_path_race = str(tmp_path / "live_race.db")
    prepare_live_store(
        store_path_race, NOW, live_client=FakeLiveClient(free_balance=Decimal("10000.00"))
    )
    _run(
        store_path=store_path_race,
        exchange=MockLiveExchange(free_balance=Decimal("10000.00")),
        market={BTC: pair_market(closes=CROSS, price=Decimal(10))},
        now=NOW,
    )

    ex_race = MockLiveExchange(
        free_balance=Decimal("9500.00"),
        stop_cancel_status=OrderStatus.FILLED,
        stop_fetch_order={"average": "8.00"},
    )
    _run(
        store_path=store_path_race,
        exchange=ex_race,
        market={BTC: pair_market(closes=FLAT, price=Decimal(15), closed_at=later_time)},
        now=later_time,
    )

    # Stop emri zaten dolduğu için piyasa satış emri (cx-) iletilmemeli (mükerrer satış engellendi)
    assert not any(c.startswith("place:cx-") for c in ex_race.call_order)
    # Deftere stop dolumu olarak kaydedilmiş olmalı
    stored_race = load_store(store_path_race, "live").state
    assert stored_race is not None
    assert len(stored_race.ledger.positions) == 0
    assert len(stored_race.ledger.closures) == 1
    assert next(iter(stored_race.ledger.closures.values())).reason is CloseReason.STOP


class SpyPaperExchange(PaperExchange):
    def __init__(self) -> None:
        super().__init__()
        self.stop_calls: list[Any] = []
        self.cancel_calls: list[Any] = []

    def place_stop_order(self, *args: Any, **kwargs: Any) -> OrderStatus:
        self.stop_calls.append((args, kwargs))
        return super().place_stop_order(*args, **kwargs)

    def cancel_order(self, *args: Any, **kwargs: Any) -> OrderStatus:
        self.cancel_calls.append((args, kwargs))
        return super().cancel_order(*args, **kwargs)


def test_paper_and_backtest_modes_do_not_call_exchange_stop_api(tmp_path: Path) -> None:
    """Spec 0034 AC-8: Paper ve backtest modlarında borsa şartlı stop/iptal API çağrılmaz."""
    store_path = str(tmp_path / "paper_iso.db")
    prepare_store(store_path, Decimal("10000"), NOW)

    spy_exchange = SpyPaperExchange()

    # 1. Tur: Paper modda alım yapılır
    res1 = _run(
        store_path=store_path,
        exchange=spy_exchange,
        market={BTC: pair_market(closes=CROSS, price=Decimal(10))},
        now=NOW,
    )
    assert len(res1.buys) == 1
    # Borsa stop iletimi çağrılmamış olmalı
    assert len(spy_exchange.stop_calls) == 0

    # 2. Tur: Fiyat hedefe (15 >= 14) ulaşır ve kapanır
    later_time = datetime(2026, 11, 10, 11, 0, tzinfo=UTC)
    res2 = _run(
        store_path=store_path,
        exchange=spy_exchange,
        market={BTC: pair_market(closes=FLAT, price=Decimal(15), closed_at=later_time)},
        now=later_time,
    )
    assert len(res2.closures) == 1
    # Borsa stop iptali çağrılmamış olmalı
    assert len(spy_exchange.cancel_calls) == 0
