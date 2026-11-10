"""Spec 0034 AC-5..AC-8: Canlı borsa şartlı stop emri entegrasyonu ve paper izolasyonu."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

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
    BannedError,
    LiveExchange,
    LiveReply,
    OrderStatus,
    PaperExchange,
    stop_client_id,
)
from crytobot.persistence import load_store
from crytobot.portfolio import CloseReason
from tests.app.helpers import BTC, CROSS, ETH, FLAT, NOW, make_settings, pair_market
from tests.app.test_live_loop import FillingLiveExchange
from tests.app.test_live_start import FakeLiveClient

PAIR = BTC


def stop_filled(amount: Decimal, average: str, fee: Decimal | None = None) -> dict[str, Any]:
    """Spec 0036 (plan Risk 3, 6): borsada dolan stopun tam dolum yanıtı; komisyon USDT'den,
    verilmezse ayardaki oranla (0.001), eski yedeğin değeriyle aynı."""
    cost = amount * Decimal(average)
    return {
        "status": "closed",
        "filled": str(amount),
        "average": average,
        "cost": str(cost),
        "fee": {"cost": str(cost * Decimal("0.001") if fee is None else fee), "currency": "USDT"},
    }


def _position_amount(store_path: str) -> Decimal:
    state = load_store(store_path, "live").state
    assert state is not None
    return next(iter(state.ledger.positions.values())).amount


class MockLiveExchange(FillingLiveExchange):
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

    def query_fill(self, client_order_id: str, symbol: str = "") -> LiveReply:
        if client_order_id.startswith("cs-"):  # the stop's fill comes from `fetch_order`
            return LiveExchange.query_fill(self, client_order_id, symbol)
        return super().query_fill(client_order_id, symbol)

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
    # VERIFY round 1 (AC-3, R-4): yedek limitli stopun fiyatı stopun slippage kadar altı
    slippage = make_settings().slippage
    assert ex.placed_stop_calls[0]["limit_price"] == buy_order.stop * (1 - slippage)

    # 2. Stop emri başarısızlığı fail-closed durdurma ve güvenli mod üretmeli
    assert BuyHalt.STOP_ORDER_FAILED in res.halts
    # review round 1 F-3: pozisyona özgü bildirim; aynı turda "düzeldi" çıkışı yok
    stop_notices = [n for n in notices if n.kind is NoticeKind.STOP_ORDER_FAILED]
    assert [(n.subject, n.entering) for n in stop_notices] == [(buy_order.client_order_id, True)]


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
        stop_fetch_order=stop_filled(pos.amount, "8.00", Decimal(fee_cost_str)),
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
        stop_fetch_order=stop_filled(_position_amount(store_path_race), "8.00"),
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


def _opened(tmp_path: Path, name: str) -> tuple[str, str]:
    """Canlı depo, tur 1'de BTC alımı (stop NEW). Dönüş: depo yolu, pozisyon kimliği."""
    store_path = str(tmp_path / name)
    prepare_live_store(
        store_path, NOW, live_client=FakeLiveClient(free_balance=Decimal("10000.00"))
    )
    res = _run(
        store_path=store_path,
        exchange=MockLiveExchange(free_balance=Decimal("10000.00")),
        market={BTC: pair_market(closes=CROSS, price=Decimal(10))},
        now=NOW,
    )
    return store_path, res.buys[0].client_order_id


LATER = datetime(2026, 11, 10, 11, 0, tzinfo=UTC)
LATEST = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def _balance(store_path: str) -> Decimal:
    state = load_store(store_path, "live").state
    assert state is not None and state.ledger.balance is not None
    return state.ledger.balance


def test_filled_exchange_stop_leaves_no_reconciliation_conflict(tmp_path: Path) -> None:
    """Review round 1 F-1 (AC-5): dolan stop emir durumunda FILLED `cs-` kapanış emri olur; depo
    çelişki taşımaz, tur RECONCILIATION ile durmaz."""
    store_path, position_id = _opened(tmp_path, "f1.db")
    stored = load_store(store_path, "live").state
    assert stored is not None
    pos = stored.ledger.positions[position_id]
    proceeds = pos.amount * Decimal(8) * (Decimal(1) - Decimal("0.001"))
    ex = MockLiveExchange(
        free_balance=_balance(store_path) + proceeds,
        stop_query_status=OrderStatus.FILLED,
        stop_fetch_order=stop_filled(pos.amount, "8", pos.amount * Decimal("0.008")),
    )
    res = _run(
        store_path=store_path,
        exchange=ex,
        market={BTC: pair_market(closes=FLAT, price=Decimal(8), closed_at=LATER)},
        now=LATER,
    )
    loaded = load_store(store_path, "live")
    assert loaded.conflicts == ()
    assert BuyHalt.RECONCILIATION not in res.halts
    assert loaded.state is not None
    stop_id = stop_client_id(position_id)
    assert loaded.state.execution.orders[stop_id].status is OrderStatus.FILLED
    assert [c.client_order_id for c in res.closes] == [stop_id]


def test_stop_filled_during_cancel_leaves_no_conflict(tmp_path: Path) -> None:
    """Review round 1 F-1 (AC-6): iptal sırasında dolmuş stop da çelişkisiz yazılır, satış yok."""
    store_path, _ = _opened(tmp_path, "f1race.db")
    ex = MockLiveExchange(
        free_balance=Decimal("9500.00"),
        stop_cancel_status=OrderStatus.FILLED,
        stop_fetch_order=stop_filled(_position_amount(store_path), "8.00"),
    )
    _run(
        store_path=store_path,
        exchange=ex,
        market={BTC: pair_market(closes=FLAT, price=Decimal(15), closed_at=LATER)},
        now=LATER,
    )
    assert not any(c.startswith("place:cx-") for c in ex.call_order)
    assert load_store(store_path, "live").conflicts == ()


def test_rejected_stop_keeps_halting_on_later_turns(tmp_path: Path) -> None:
    """Review round 1 F-2 (R-5): borsada bu kimlikle reddedilmiş stop durdukça sonraki turlarda da
    alım durur, bildirim sürer (tek giriş, çıkış yok); kimlik dolu olduğundan yeniden verilmez."""
    store_path, position_id = _opened(tmp_path, "f2.db")
    notices: list[TurnNotice] = []
    memory = TurnMemory()
    for at in (LATER, LATEST):
        ex = MockLiveExchange(
            free_balance=_balance(store_path),
            stop_query_status=OrderStatus.REJECTED,
            stop_fetch_order={"status": "rejected"},
        )
        res = _run(
            store_path=store_path,
            exchange=ex,
            market={BTC: pair_market(closes=FLAT, price=Decimal(10), closed_at=at)},
            now=at,
            memory=memory,
            sink=notices.append,
        )
        assert BuyHalt.STOP_ORDER_FAILED in res.halts
        assert ex.placed_stop_calls == []
    stop_notices = [n for n in notices if n.kind is NoticeKind.STOP_ORDER_FAILED]
    assert [(n.subject, n.entering) for n in stop_notices] == [(position_id, True)]


def test_missing_stop_is_placed_again_and_notice_ends(tmp_path: Path) -> None:
    """Review round 1 F-2: borsada hiç olmayan stop (ör. ilk deneme ağda kayboldu) yeniden verilir;
    verilince durdurma kalkar, önceki bildirim çıkışla biter."""
    store_path, position_id = _opened(tmp_path, "f2miss.db")
    notices: list[TurnNotice] = []
    memory = TurnMemory()
    failing = MockLiveExchange(
        free_balance=_balance(store_path),
        stop_query_status=OrderStatus.REJECTED,
        stop_placement_status=OrderStatus.UNKNOWN,
    )
    first = _run(
        store_path=store_path,
        exchange=failing,
        market={BTC: pair_market(closes=FLAT, price=Decimal(10), closed_at=LATER)},
        now=LATER,
        memory=memory,
        sink=notices.append,
    )
    assert BuyHalt.STOP_ORDER_FAILED in first.halts
    assert [c["id"] for c in failing.placed_stop_calls] == [stop_client_id(position_id)]

    placing = MockLiveExchange(
        free_balance=_balance(store_path), stop_query_status=OrderStatus.REJECTED
    )
    second = _run(
        store_path=store_path,
        exchange=placing,
        market={BTC: pair_market(closes=FLAT, price=Decimal(10), closed_at=LATEST)},
        now=LATEST,
        memory=memory,
        sink=notices.append,
    )
    assert BuyHalt.STOP_ORDER_FAILED not in second.halts
    assert len(placing.placed_stop_calls) == 1
    stop_notices = [n for n in notices if n.kind is NoticeKind.STOP_ORDER_FAILED]
    assert [n.entering for n in stop_notices] == [True, False]


class BannedStopExchange(MockLiveExchange):
    def place_stop_order(self, *args: Any, **kwargs: Any) -> OrderStatus:
        raise BannedError("418")


def test_ban_on_stop_placement_keeps_the_filled_buy(tmp_path: Path) -> None:
    """Review round 1 F-4: stop verilirken ban (418) yutulmaz, döngüye çıkar; dolan alım ondan
    önce kaydedilmiştir (defterde pozisyon, depo çelişkisiz)."""
    store_path = str(tmp_path / "f4.db")
    prepare_live_store(
        store_path, NOW, live_client=FakeLiveClient(free_balance=Decimal("10000.00"))
    )
    with pytest.raises(BannedError):
        _run(
            store_path=store_path,
            exchange=BannedStopExchange(free_balance=Decimal("10000.00")),
            market={BTC: pair_market(closes=CROSS, price=Decimal(10))},
            now=NOW,
        )
    loaded = load_store(store_path, "live")
    assert loaded.state is not None
    assert len(loaded.state.ledger.positions) == 1
    assert loaded.conflicts == ()


class BannedQueryExchange(MockLiveExchange):
    def query(self, client_order_id: str, symbol: str = "") -> OrderStatus:
        raise BannedError("418")


def test_ban_on_stop_query_is_not_swallowed(tmp_path: Path) -> None:
    """Review round 1 F-4: tur başı stop sorgusundaki ban da döngüye çıkar."""
    store_path, _ = _opened(tmp_path, "f4q.db")
    with pytest.raises(BannedError):
        _run(
            store_path=store_path,
            exchange=BannedQueryExchange(free_balance=_balance(store_path)),
            market={BTC: pair_market(closes=FLAT, price=Decimal(10), closed_at=LATER)},
            now=LATER,
        )


@pytest.mark.parametrize(
    ("cancel", "fetched", "sells"),
    [
        (OrderStatus.NEW, {"status": "open"}, False),
        (OrderStatus.UNKNOWN, None, False),
        (OrderStatus.REJECTED, {"status": "open"}, False),
        (OrderStatus.REJECTED, None, True),
        (OrderStatus.CANCELED, None, True),
    ],
)
def test_close_sells_only_after_confirmed_cancel(
    tmp_path: Path, cancel: OrderStatus, fetched: dict[str, Any] | None, sells: bool
) -> None:
    """Review round 1 F-5 (R-7): satış yalnız iptal teyidiyle ya da borsada stop hiç yoksa; aksi
    hâlde kapanış reddedilir ve alım durur."""
    store_path, _ = _opened(tmp_path, "f5.db")
    ex = MockLiveExchange(
        free_balance=Decimal("9500.00"), stop_cancel_status=cancel, stop_fetch_order=fetched
    )
    res = _run(
        store_path=store_path,
        exchange=ex,
        market={BTC: pair_market(closes=FLAT, price=Decimal(15), closed_at=LATER)},
        now=LATER,
    )
    assert any(c.startswith("place:cx-") for c in ex.call_order) is sells
    assert (BuyHalt.STOP_ORDER_FAILED in res.halts) is not sells


class BanAt(MockLiveExchange):
    """Review round 2 L-3: ban yalnız seçilen çağrıda (`cancel`, `fetch`)."""

    def __init__(self, where: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.where = where

    def cancel_order(self, client_order_id: str, symbol: str = "") -> OrderStatus:
        if self.where == "cancel":
            raise BannedError("418")
        return super().cancel_order(client_order_id, symbol)

    def fetch_order(self, client_order_id: str, symbol: str = "") -> dict[str, Any] | None:
        if self.where == "fetch":
            raise BannedError("418")
        return super().fetch_order(client_order_id, symbol)


@pytest.mark.parametrize(
    ("where", "query", "price"),
    [
        ("cancel", OrderStatus.NEW, Decimal(15)),  # _stop_cancelled: closing at the target
        ("fetch", OrderStatus.REJECTED, Decimal(10)),  # _stop_missing: is the stop there at all
        ("fetch", OrderStatus.FILLED, Decimal(8)),  # _stop_fill_terms: the filled stop's terms
    ],
)
def test_ban_in_every_stop_call_is_not_swallowed(
    tmp_path: Path, where: str, query: OrderStatus, price: Decimal
) -> None:
    """Review round 2 L-3 (F-4): iptal, varlık sorgusu ve dolum ayrıntısı çağrısındaki ban da
    döngüye çıkar; hiçbir stop çağrısı banı yutmaz."""
    store_path, _ = _opened(tmp_path, "ban.db")
    ex = BanAt(where, free_balance=_balance(store_path), stop_query_status=query)
    with pytest.raises(BannedError):
        _run(
            store_path=store_path,
            exchange=ex,
            market={BTC: pair_market(closes=FLAT, price=price, closed_at=LATER)},
            now=LATER,
        )


def test_unknown_stop_status_halts_without_replacing(tmp_path: Path) -> None:
    """Review round 2 L-3 (F-2): durumu belirsiz stop alımı durdurur, bildirim girer; stop yeniden
    verilmez (çift stop riski)."""
    store_path, position_id = _opened(tmp_path, "unknown.db")
    notices: list[TurnNotice] = []
    ex = MockLiveExchange(free_balance=_balance(store_path), stop_query_status=OrderStatus.UNKNOWN)
    res = _run(
        store_path=store_path,
        exchange=ex,
        market={BTC: pair_market(closes=FLAT, price=Decimal(10), closed_at=LATER)},
        now=LATER,
        sink=notices.append,
    )
    assert BuyHalt.STOP_ORDER_FAILED in res.halts
    assert ex.placed_stop_calls == []
    assert [(n.kind, n.subject, n.entering) for n in notices if n.subject == position_id] == [
        (NoticeKind.STOP_ORDER_FAILED, position_id, True)
    ]


@pytest.mark.parametrize("stop_status", [OrderStatus.NEW, OrderStatus.REJECTED])
def test_unprotected_position_actually_stops_new_buys(
    tmp_path: Path, stop_status: OrderStatus
) -> None:
    """Spec 0034 AC-7 (R-5), VERIFY round 1: BTC'nin borsa stopu reddedilmişken alım sinyali olan
    ETH'de emir verilmez. Pozitif kontrol: stop sağlamken (NEW) aynı turda ETH alınır."""
    store_path, _ = _opened(tmp_path, f"ac7-{stop_status.value}.db")
    ex = MockLiveExchange(
        free_balance=_balance(store_path),
        stop_query_status=stop_status,
        stop_fetch_order={"status": "rejected"},  # the id is taken: not re-placed
    )
    res = run_turn(
        market={
            BTC: pair_market(closes=FLAT, price=Decimal(10), closed_at=LATER),
            ETH: pair_market(closes=CROSS, price=Decimal(10), closed_at=LATER),
        },
        settings=make_settings(whitelist=(BTC, ETH)),
        store_path=store_path,
        now=LATER,
        exchange=ex,
        sink=lambda n: None,
        memory=TurnMemory(),
    )
    if stop_status is OrderStatus.NEW:
        assert [o.pair for o in res.buys] == [ETH]
    else:
        assert BuyHalt.STOP_ORDER_FAILED in res.halts
        assert res.buys == ()
        assert not any(c.startswith("place:cb-") for c in ex.call_order)
