"""Spec 0036 AC-8 (R-8): "böyle emir yok" yanıtı alım ve kapanışı yalnız verilişten 5 dakika sonra
ve önceki turda da aynı yanıt alındıysa reddeder; sınırlar 4 dk 59 s ve 5 dk."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

import pytest

from crytobot.execution import (
    EMPTY_EXECUTION,
    NOT_FOUND_GRACE,
    BinanceLiveClient,
    CloseOrder,
    ExchangeCredentials,
    ExecutionState,
    LiveExchange,
    LiveReply,
    Order,
    OrderStatus,
    QueryOutcome,
    query_order,
)

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


class _Ccxt:
    on_rest_response = None


class NotFoundExchange(LiveExchange):
    """Her sorguda "emir yok"; sorgu sayılır."""

    def __init__(self) -> None:
        creds = ExchangeCredentials(api_key="k", api_secret="s", testnet=False)
        super().__init__(client=BinanceLiveClient(creds, exchange=_Ccxt()))
        self.queries: list[str] = []

    def query_fill(self, client_order_id: str, symbol: str = "") -> LiveReply:
        self.queries.append(client_order_id)
        return LiveReply(OrderStatus.UNKNOWN, missing=True)


def unknown_state(kind: str) -> tuple[ExecutionState, str]:
    if kind == "buy":
        order: Order | CloseOrder = Order(
            "cb-a1", "a1", "BTC/USDT", "buy", Decimal(10), Decimal(8), Decimal(14),
            Decimal(1), OrderStatus.UNKNOWN, None, None, NOW,
        )  # fmt: skip
    else:
        order = CloseOrder(
            "cx-a1", "cb-a1", "BTC/USDT", "sell", Decimal(1), "stop",
            OrderStatus.UNKNOWN, None, None, NOW,
        )  # fmt: skip
    quote = (Decimal("10.01"), Decimal("0.01001"))
    state = ExecutionState(
        MappingProxyType({**EMPTY_EXECUTION.orders, order.client_order_id: order}),
        MappingProxyType({order.client_order_id: quote}),
    )
    return state, order.client_order_id


@pytest.mark.parametrize("kind", ["buy", "close"])
@pytest.mark.parametrize(
    ("elapsed", "seen", "refused"),
    [
        (timedelta(minutes=4, seconds=59), True, False),
        (timedelta(minutes=5), False, False),
        (timedelta(minutes=5), True, True),
        (timedelta(hours=3), False, False),
        (timedelta(0), True, False),
    ],
)
def test_not_found_boundaries(kind: str, elapsed: timedelta, seen: bool, refused: bool) -> None:
    """AC-8: 5 dakikadan az ya da yalnız bir sorguda gelen "emir yok" `UNKNOWN` bırakır; 5 dakika
    geçmiş ve önceki turda da gelmişse `REJECTED`. Her çağrı borsaya tek sorgudur."""
    state, cid = unknown_state(kind)
    exchange = NotFoundExchange()
    result = query_order(
        state, cid, exchange, NOW + elapsed, step=Decimal("0.001"), missing_seen=seen
    )
    assert exchange.queries == [cid]
    assert result.order is not None
    if refused:
        assert result.outcome is QueryOutcome.UPDATED
        assert result.order.status is OrderStatus.REJECTED
        assert result.order.fill_price is None
        assert not result.state.unknown
    else:
        assert result.outcome is QueryOutcome.UNCHANGED
        assert result.not_found
        assert result.order.status is OrderStatus.UNKNOWN
        assert result.state is state


def test_grace_is_fixed_at_five_minutes() -> None:
    """R-8: süre ayarla değiştirilemez."""
    assert timedelta(minutes=5) == NOT_FOUND_GRACE
