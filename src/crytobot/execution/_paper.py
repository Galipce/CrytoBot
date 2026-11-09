"""Paper simülatörü: emirleri gerçek bir borsaya göndermeden sonuçlandırır (spec 0006 R-5, R-9)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Protocol, runtime_checkable


class OrderStatus(Enum):
    FILLED = "filled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


@runtime_checkable
class Exchange(Protocol):
    """Borsa adaptör arayüzü (paper ve live ortak sözleşmesi)."""

    def place(self, client_order_id: str) -> OrderStatus: ...

    def query(self, client_order_id: str) -> OrderStatus: ...

    def fetch_free_balance(self, asset: str = "USDT") -> Decimal | None: ...


@dataclass(frozen=True)
class PaperExchange:
    """Piyasa alımını anında doldurur. `placements` bir emrin yerleştirme sonucunu, `resolutions`
    durumu bilinmeyen bir emrin sonraki sorgudaki sonucunu `clientOrderId`'ye göre ayarlar; ayarsız
    emir `FILLED` olur, ayarsız sorgu `UNKNOWN` kalır."""

    placements: Mapping[str, OrderStatus] = field(default_factory=lambda: MappingProxyType({}))
    resolutions: Mapping[str, OrderStatus] = field(default_factory=lambda: MappingProxyType({}))
    free_balances: Mapping[str, Decimal] = field(default_factory=lambda: MappingProxyType({}))

    def place(self, client_order_id: str) -> OrderStatus:
        return self.placements.get(client_order_id, OrderStatus.FILLED)

    def query(self, client_order_id: str) -> OrderStatus:
        return self.resolutions.get(client_order_id, OrderStatus.UNKNOWN)

    def fetch_free_balance(self, asset: str = "USDT") -> Decimal | None:
        return self.free_balances.get(asset)
