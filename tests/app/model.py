"""Spec 0016 Constraints: bağımsız beklenen sonuç modeli (plan Risk 17).

`app`, `portfolio` ve `risk` kullanmaz; tek çift, her tur yeni bir mum ve yeni UTC günü, seri hep
kesişir (giriş 10, stop 8, hedef 14). Limitler `helpers`'ın varsayılanlarıdır.
"""

from dataclasses import dataclass, field
from decimal import Context, Decimal, localcontext

_EXACT = Context(prec=200)
ENTRY, STOP, TARGET = Decimal(10), Decimal(8), Decimal(14)
STEP = Decimal("0.001")
MINIMUM_NOTIONAL = Decimal(10)
RISK_SHARE = Decimal("0.01")
HARD_CAP = Decimal("0.02")


@dataclass
class ModelPosition:
    amount: Decimal


@dataclass
class Model:
    fee: Decimal
    slippage: Decimal
    balance: Decimal
    position: ModelPosition | None = None
    closes: int = 0
    history: list[str] = field(default_factory=list)

    def turn(self, price: Decimal) -> None:
        with localcontext(_EXACT):
            self._close_if_reached(price)
            if self.position is None:
                self._buy(price)

    def _close_if_reached(self, price: Decimal) -> None:
        if self.position is None or STOP < price < TARGET:
            return
        self.balance += self.position.amount * price * (1 - self.slippage) * (1 - self.fee)
        self.position = None
        self.closes += 1
        self.history.append("close")

    def _buy(self, price: Decimal) -> None:
        unit_loss = (ENTRY - STOP) + ENTRY * self.fee + STOP * self.fee
        by_risk = (self.balance * RISK_SHARE) // (STEP * unit_loss)
        by_balance = self.balance // (STEP * ENTRY * (1 + self.fee))
        amount = min(by_risk, by_balance) * STEP
        if amount * ENTRY < MINIMUM_NOTIONAL:
            return
        fill = price * (1 + self.slippage)
        commission = amount * fill * self.fee
        cost = amount * fill + commission
        loss = amount * (fill - STOP) + commission + amount * STOP * self.fee
        if cost > self.balance or loss > self.balance * HARD_CAP:
            return
        self.balance -= cost
        self.position = ModelPosition(amount)
        self.history.append("buy")
