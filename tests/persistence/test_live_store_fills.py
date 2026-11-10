"""Spec 0036 AC-9, AC-12 (R-9, R-10, R-13, R-14): canlı deponun gerçek dolum kaydı, eski canlı
deponun reddi ve paper satırlarının değişmezliği."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from crytobot.execution import (
    EMPTY_EXECUTION,
    BinanceLiveClient,
    ExchangeCredentials,
    LiveExchange,
    LiveReply,
    Order,
    OrderRequest,
    OrderStatus,
    QueryOutcome,
    place_order,
    query_order,
)
from crytobot.persistence import StoreOutcome, create_store, load_store, save_store
from crytobot.persistence._codec import decode_orders, encode_order
from crytobot.portfolio import EMPTY_LEDGER, Fill, open_ledger, record_fill
from crytobot.risk import EMPTY_STATE, PairRules, TradeApproval, TradeIntent

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
PAIR = "BTC/USDT"
RULES = PairRules(Decimal("0.001"), Decimal("0.001"), Decimal(5))
INTENT = TradeIntent(PAIR, "buy", Decimal(10), Decimal(8), Decimal(14))
APPROVAL = TradeApproval(Decimal(1), None, False, "onay", INTENT)


class _Ccxt:
    on_rest_response = None


class ScriptedExchange(LiveExchange):
    """Alım ve sorgu yanıtı verilen `LiveReply`'dir."""

    def __init__(self, placed: LiveReply, queried: LiveReply | None = None) -> None:
        creds = ExchangeCredentials(api_key="k", api_secret="s", testnet=False)
        super().__init__(client=BinanceLiveClient(creds, exchange=_Ccxt()))
        self.placed = placed
        self.queried = queried

    def place_market(self, *args: Any, **kwargs: Any) -> LiveReply:
        return self.placed

    def query_fill(self, client_order_id: str, symbol: str = "") -> LiveReply:
        assert self.queried is not None
        return self.queried


def full_fill(average: str, fee: str) -> LiveReply:
    cost = Decimal(average)
    return LiveReply(
        OrderStatus.FILLED,
        {
            "status": "closed",
            "id": "7",
            "filled": "1",
            "average": average,
            "cost": str(cost),
            "fee": {"cost": fee, "currency": "BTC"},
        },
    )


def request(mode: str = "live") -> OrderRequest:
    return OrderRequest(
        "a1", INTENT, APPROVAL, RULES, Decimal(10), Decimal("0.001"), Decimal("0.001"), mode
    )


def opened_live(tmp_path: Path) -> Any:
    path = tmp_path / "live.db"
    created = create_store(path, "live")
    assert created.state is not None
    ledger = open_ledger(EMPTY_LEDGER, Decimal(1000), NOW).ledger
    saved = save_store(path, created.state, ledger, EMPTY_EXECUTION, EMPTY_STATE)
    assert saved.state is not None
    return path, saved.state


def buy_fill(order: Order) -> Fill:
    return Fill(
        order.client_order_id,
        order.pair,
        order.side,
        order.position_amount,
        order.fill_price,
        order.fee,
        order.stop,
        order.target,
        NOW + timedelta(hours=1),
    )


def test_live_resolution_may_differ_from_quote(tmp_path: Path) -> None:
    """AC-9 (R-9, D-1, R-10): `UNKNOWN` kalan canlı alım sonradan dolunca deftere ve emir kaydına
    borsanın gerçek dolumu yazılır (tahmin 10.01, borsa 10.05, coinden komisyon); depo kaydı kabul
    eder, yeniden yüklenen emir aynıdır ve defter ↔ emir çelişki taşımaz (net miktarla)."""
    path, base = opened_live(tmp_path)
    placed = place_order(
        EMPTY_EXECUTION, request(), ScriptedExchange(LiveReply(OrderStatus.UNKNOWN)), NOW
    )
    assert placed.order is not None and placed.order.status is OrderStatus.UNKNOWN
    unknown = save_store(path, base, base.ledger, placed.state, base.risk)
    assert unknown.state is not None

    exchange = ScriptedExchange(LiveReply(OrderStatus.UNKNOWN), full_fill("10.05", "0.001"))
    later = NOW + timedelta(hours=1)
    queried = query_order(placed.state, "cb-a1", exchange, later, step=Decimal("0.001"))
    assert queried.outcome is QueryOutcome.UPDATED
    order = queried.order
    assert isinstance(order, Order)
    assert order.fill_price == Decimal("10.05")
    assert placed.state.quotes["cb-a1"][0] != order.fill_price
    assert (order.filled, order.net, order.commission_asset) == (
        Decimal(1),
        Decimal("0.999"),
        "BTC",
    )

    ledger = record_fill(unknown.state.ledger, buy_fill(order)).ledger
    saved = save_store(path, unknown.state, ledger, queried.state, unknown.state.risk)
    assert saved.outcome is StoreOutcome.SAVED
    assert saved.conflicts == ()
    loaded = load_store(path, "live")
    assert loaded.state is not None and loaded.conflicts == ()
    assert loaded.state.execution.orders["cb-a1"] == order
    position = loaded.state.ledger.positions["cb-a1"]
    assert position.amount == Decimal("0.999")
    assert position.amount * position.cost_price + position.fee == Decimal("10.05")


def test_paper_resolution_keeps_the_quote(tmp_path: Path) -> None:
    """AC-9 (D-1): paper'da netleşen dolum kayıtlı tahmindir; başka bir dolum geçmişi değiştirir."""
    path = tmp_path / "paper.db"
    created = create_store(path, "paper")
    assert created.state is not None
    unknown_order = Order(
        "cb-a1", "a1", PAIR, "buy", Decimal(10), Decimal(8), Decimal(14), Decimal(1),
        OrderStatus.UNKNOWN, None, None, NOW,
    )  # fmt: skip
    from types import MappingProxyType

    from crytobot.execution import ExecutionState

    quote = (Decimal("10.01"), Decimal("0.01001"))
    state = ExecutionState(
        MappingProxyType({"cb-a1": unknown_order}), MappingProxyType({"cb-a1": quote})
    )
    ledger = open_ledger(EMPTY_LEDGER, Decimal(1000), NOW).ledger
    base = save_store(path, created.state, ledger, state, EMPTY_STATE).state
    assert base is not None
    other = Order(
        "cb-a1", "a1", PAIR, "buy", Decimal(10), Decimal(8), Decimal(14), Decimal(1),
        OrderStatus.FILLED, Decimal("10.05"), Decimal("0.01005"), NOW,
    )  # fmt: skip
    empty_quotes: MappingProxyType[str, tuple[Decimal, Decimal]] = MappingProxyType({})
    refused = save_store(
        path, base, base.ledger, ExecutionState(MappingProxyType({"cb-a1": other}), empty_quotes),
        base.risk,
    )  # fmt: skip
    assert refused.outcome is StoreOutcome.HISTORY_IMMUTABLE


def test_old_live_store_refused_by_name(tmp_path: Path) -> None:
    """AC-12 (R-13): gerçek dolum bilgisi taşımayan (bu spec'ten önce açılmış) canlı depo adıyla
    reddedilir ve `prepare --live` istenir; aynı biçimdeki paper deposu etkilenmez."""
    path, _ = opened_live(tmp_path)
    with closing(sqlite3.connect(path)) as database:
        database.execute("DELETE FROM meta WHERE key = 'fills'")
        database.commit()
    loaded = load_store(path, "live")
    assert loaded.outcome is StoreOutcome.LIVE_STORE_OUTDATED
    assert loaded.state is None
    assert "eski canlı depo" in loaded.message and "prepare --live" in loaded.message

    paper = tmp_path / "paper.db"
    assert create_store(paper, "paper").state is not None
    with closing(sqlite3.connect(paper)) as database:
        keys = {k for (k,) in database.execute("SELECT key FROM meta")}
    assert "fills" not in keys
    assert load_store(paper, "paper").outcome is StoreOutcome.LOADED


def test_paper_rows_byte_identical() -> None:
    """AC-12 (R-14): paper emir satırı bayt bayt eski biçimdedir; canlı dolumun alanları yalnız
    doluysa sondaki diziye yazılır ve geri okunur."""
    paper = Order(
        "cb-a1", "a1", PAIR, "buy", Decimal(10), Decimal(8), Decimal(14), Decimal(1),
        OrderStatus.FILLED, Decimal("10.01"), Decimal("0.01001"), NOW,
    )  # fmt: skip
    assert encode_order(paper, None) == (
        '["b","cb-a1","a1","BTC/USDT","10","8","14","1","filled","10.01","0.01001",'
        '"2026-11-10T12:00:00+00:00",null,null]'
    )
    from dataclasses import replace

    live = replace(
        paper,
        filled=Decimal(1),
        net=Decimal("0.99"),
        commission=Decimal("0.001"),
        commission_asset="BTC",
        dust=Decimal("0.009"),
    )
    row = encode_order(live, None)
    assert row.endswith(',null,null,["1","0.99","0.001","BTC","0.009"]]')
    assert decode_orders([row]).orders["cb-a1"] == live
    assert decode_orders([encode_order(paper, None)]).orders["cb-a1"] == paper
