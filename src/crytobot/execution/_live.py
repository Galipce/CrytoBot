"""Canlı borsa adaptörü: emirleri ve sorguları ccxt istemcisine iletir (spec 0032, 0034, 0036)."""

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from crytobot.execution._fills import LiveReply, fee_entries
from crytobot.execution._live_client import (
    BinanceLiveClient,
    LiveExchangeCallError,
)
from crytobot.execution._paper import OrderStatus

_FILLED_STATUSES = ("closed", "filled")
_ENDED_STATUSES = ("canceled", "cancelled", "expired", "rejected")


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
        """Piyasa emrini borsaya iletir (R-5, R-6); yalnız ham durum. Emir yolu `place_market`'i
        kullanır: dolum bilgisi olmadan durum deftere yazılamaz (spec 0036 R-1)."""
        return self.place_market(client_order_id, symbol=symbol, side=side, amount=amount).status

    def place_market(
        self,
        client_order_id: str,
        symbol: str = "",
        side: str = "",
        amount: object = None,
    ) -> LiveReply:
        """Spec 0036 R-1, R-7: piyasa emri ve borsanın dolum yanıtı. Yalnız kesin ret `REJECTED`;
        ağ hatası, zaman aşımı ve tanınmayan her hata `UNKNOWN`."""
        amt_str = str(amount) if isinstance(amount, (Decimal, float, int, str)) else ""
        try:
            res = self.client.place_market_order(
                symbol=symbol,
                side=side,
                amount=amt_str,
                client_order_id=client_order_id,
            )
        except LiveExchangeCallError as err:
            return LiveReply(OrderStatus.UNKNOWN if err.is_unknown else OrderStatus.REJECTED)
        return self._reply(res, symbol)

    def query_fill(self, client_order_id: str, symbol: str = "") -> LiveReply:
        """Spec 0036 R-8, R-9: durumu bilinmeyen alım ya da kapanış emrinin yanıtı. Borsa "emir
        yok" derse `missing`; sorgu hatası emir hakkında bir şey söylemez, `UNKNOWN` kalır."""
        try:
            res = self.fetch_order(client_order_id, symbol=symbol)
        except LiveExchangeCallError:
            return LiveReply(OrderStatus.UNKNOWN)
        if res is None:
            return LiveReply(OrderStatus.UNKNOWN, missing=True)
        return self._reply(res, symbol)

    def _reply(self, res: object, symbol: str) -> LiveReply:
        """Ham yanıt → `LiveReply`. Yanıtta komisyon yoksa emrin işlemleri sorulur (plan 0036
        Risk 2); dolan emir kayda geçmeden önce bu çağrının hiçbir hatası dışarı çıkmaz
        (spec 0034 F-4)."""
        if not isinstance(res, dict):
            return LiveReply(OrderStatus.UNKNOWN)
        raw_status = res.get("status")
        if raw_status in _FILLED_STATUSES:
            status = OrderStatus.FILLED
        elif raw_status in _ENDED_STATUSES:
            status = OrderStatus.REJECTED
        else:
            return LiveReply(OrderStatus.UNKNOWN, MappingProxyType(dict(res)))
        trades: tuple[dict[str, Any], ...] | None = None
        order_id = res.get("id")
        wanted = status is OrderStatus.FILLED and fee_entries(res) is None
        if wanted and isinstance(order_id, str) and order_id:
            try:
                trades = tuple(self.client.fetch_order_trades(symbol, order_id))
            except Exception:  # the fill must reach the store first (spec 0034 F-4)
                trades = None
        return LiveReply(status, MappingProxyType(dict(res)), trades)

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
