"""Canlı borsa adaptörü: emirleri ve sorguları ccxt istemcisine iletir (spec 0032, 0034)."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crytobot.execution._live_client import (
    BinanceLiveClient,
    LiveExchangeCallError,
)
from crytobot.execution._paper import OrderStatus


def _is_stop_order(client_order_id: str) -> bool:
    from crytobot.execution._orders import STOP_ID_PREFIX

    return client_order_id.startswith(STOP_ID_PREFIX)


def _map_stop_order_status(res: dict[str, Any]) -> OrderStatus:
    raw_status = res.get("status") if isinstance(res, dict) else ""
    if "filled" in res and res["filled"] is not None:
        try:
            filled_qty = Decimal(str(res["filled"]))
            if not filled_qty.is_finite() or filled_qty < 0:
                return OrderStatus.UNKNOWN
            if filled_qty > 0 and raw_status not in ("closed", "filled"):
                return OrderStatus.UNKNOWN
        except Exception:
            return OrderStatus.UNKNOWN
    if raw_status in ("open", "new"):
        return OrderStatus.NEW
    if raw_status in ("closed", "filled"):
        return OrderStatus.FILLED
    if raw_status in ("canceled", "cancelled"):
        return OrderStatus.CANCELED
    if raw_status in ("expired", "rejected"):
        return OrderStatus.REJECTED
    return OrderStatus.UNKNOWN


@dataclass(frozen=True)
class LiveExchange:
    """ccxt Binance canlı spot adaptörü (R-5, R-6, R-7, spec 0034)."""

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
            return OrderStatus.UNKNOWN
        except LiveExchangeCallError as err:
            if err.is_unknown:
                return OrderStatus.UNKNOWN
            return OrderStatus.REJECTED

    def place_stop_order(
        self,
        client_order_id: str,
        symbol: str = "",
        amount: object = None,
        stop_price: object = None,
        limit_price: object = None,
    ) -> OrderStatus:
        """Koşullu stop emrini borsaya iletir (spec 0034 R-3, R-4)."""
        try:
            amt_str = str(amount) if isinstance(amount, (Decimal, float, int, str)) else ""
            stop_str = str(stop_price) if isinstance(stop_price, (Decimal, float, int, str)) else ""
            lim_str = (
                str(limit_price) if isinstance(limit_price, (Decimal, float, int, str)) else None
            )
            res = self.client.place_stop_order(
                symbol=symbol,
                side="sell",
                amount=amt_str,
                stop_price=stop_str,
                client_order_id=client_order_id,
                limit_price=lim_str,
            )
            raw_status = res.get("status") if isinstance(res, dict) else ""
            if raw_status in ("open", "new"):
                return OrderStatus.NEW
            if raw_status in ("closed", "filled"):
                return OrderStatus.FILLED
            if raw_status in ("canceled", "cancelled"):
                return OrderStatus.CANCELED
            if raw_status in ("expired", "rejected"):
                return OrderStatus.REJECTED
            return OrderStatus.UNKNOWN
        except LiveExchangeCallError as err:
            if err.is_unknown:
                return OrderStatus.UNKNOWN
            return OrderStatus.REJECTED

    def cancel_order(self, client_order_id: str, symbol: str = "") -> OrderStatus:
        """origClientOrderId ile açık emri iptal eder (spec 0034 R-7)."""
        try:
            res = self.client.cancel_order(client_order_id, symbol=symbol)
            if res is None:
                return self.query(client_order_id, symbol=symbol)
            if _is_stop_order(client_order_id):
                if not isinstance(res, dict):
                    return OrderStatus.UNKNOWN
                return _map_stop_order_status(res)
            raw_status = res.get("status") if isinstance(res, dict) else ""
            if raw_status in ("canceled", "cancelled"):
                return OrderStatus.CANCELED
            if raw_status in ("closed", "filled"):
                return OrderStatus.FILLED
            if raw_status in ("open", "new"):
                return OrderStatus.NEW
            if raw_status in ("expired", "rejected"):
                return OrderStatus.REJECTED
            return OrderStatus.UNKNOWN
        except LiveExchangeCallError as err:
            if err.is_unknown:
                return OrderStatus.UNKNOWN
            return OrderStatus.REJECTED

    def query(self, client_order_id: str, symbol: str = "") -> OrderStatus:
        """Emir durumunu borsadan origClientOrderId ile sorgular (R-7, spec 0034)."""
        try:
            res = self.client.query_order(client_order_id, symbol=symbol)
            if res is None:
                return OrderStatus.REJECTED
            if _is_stop_order(client_order_id):
                if not isinstance(res, dict):
                    return OrderStatus.UNKNOWN
                return _map_stop_order_status(res)

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

    def fetch_order(self, client_order_id: str, symbol: str = "") -> dict[str, Any] | None:
        """origClientOrderId ile emrin detaylı borsa yanıtını çeker."""
        return self.client.query_order(client_order_id, symbol=symbol)

    def fetch_free_balance(self, asset: str = "USDT") -> Decimal:
        """Borsadaki serbest bakiyeyi çeker."""
        return self.client.fetch_free_balance(asset=asset)
