"""Paper simülatörü: emirleri gerçek bir borsaya göndermeden sonuçlandırır (spec 0006 R-5)."""

from dataclasses import dataclass
from enum import Enum


class OrderStatus(Enum):
    FILLED = "filled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PaperExchange:
    """Piyasa alımını anında doldurur."""

    def place(self, client_order_id: str) -> OrderStatus:
        return OrderStatus.FILLED
