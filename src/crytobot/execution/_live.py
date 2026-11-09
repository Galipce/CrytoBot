"""Canlı borsa adaptörü: emirleri ve sorguları ccxt istemcisine iletir (spec 0032 R-5, R-6, R-7)."""

from dataclasses import dataclass
from decimal import Decimal

from crytobot.execution._live_client import (
    BinanceLiveClient,
    LiveExchangeCallError,
)
from crytobot.execution._paper import OrderStatus


@dataclass(frozen=True)
class LiveExchange:
    """ccxt Binance canlı spot adaptörü (R-5, R-6, R-7)."""

    client: BinanceLiveClient

    def place(
        self,
        client_order_id: str,
        symbol: str = "",
        side: str = "",
        amount: object = None,
    ) -> OrderStatus:
        """Piyasa emrini borsaya iletir (R-5, R-6)."""
        try:
            amt_str = str(amount) if isinstance(amount, (Decimal, float, int, str)) else ""
            res = self.client.place_market_order(
                symbol=symbol,
                side=side,
                amount=amt_str,
                client_order_id=client_order_id,
            )
            raw_status = res.get("status") if isinstance(res, dict) else ""
            if raw_status in ("closed", "filled"):
                return OrderStatus.FILLED
            if raw_status in ("canceled", "cancelled", "expired", "rejected"):
                return OrderStatus.REJECTED
            return OrderStatus.FILLED if isinstance(res, dict) else OrderStatus.UNKNOWN
        except LiveExchangeCallError as err:
            if err.is_unknown:
                return OrderStatus.UNKNOWN
            return OrderStatus.REJECTED

    def query(self, client_order_id: str, symbol: str = "") -> OrderStatus:
        """Emir durumunu borsadan origClientOrderId ile sorgular (R-7)."""
        try:
            res = self.client.query_order(client_order_id, symbol=symbol)
            if res is None:
                return OrderStatus.REJECTED
            raw_status = res.get("status") if isinstance(res, dict) else ""
            if raw_status in ("closed", "filled"):
                return OrderStatus.FILLED
            if raw_status in ("canceled", "cancelled", "expired", "rejected"):
                return OrderStatus.REJECTED
            return OrderStatus.UNKNOWN
        except LiveExchangeCallError as err:
            if err.is_unknown:
                return OrderStatus.UNKNOWN
            return OrderStatus.REJECTED
