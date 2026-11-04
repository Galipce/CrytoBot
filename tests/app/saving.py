"""Spec 0016: kayıt reddi enjeksiyonu (plan Risk 15). Yükleme hataları gerçek dosyayla kurulur."""

from collections.abc import Callable
from typing import Any

import pytest

from crytobot.app import _session
from crytobot.persistence import StoreOutcome, StoreResult, save_store

Writes = Callable[[Any, Any, Any], bool]


def refuse_saves(
    monkeypatch: pytest.MonkeyPatch,
    outcome: StoreOutcome,
    when: Writes = lambda *_: True,
    times: int = 1,
) -> list[StoreOutcome]:
    """`when(ledger, execution, risk)` doğruysa kayıt `outcome` ile reddedilir, `times` kez."""
    refused: list[StoreOutcome] = []

    def fake(path: object, base: object, ledger: Any, execution: Any, risk: Any) -> StoreResult:
        if len(refused) < times and when(ledger, execution, risk):
            refused.append(outcome)
            return StoreResult(outcome, None, (), outcome.value)
        return save_store(path, base, ledger, execution, risk)

    monkeypatch.setattr(_session, "save_store", fake)
    return refused


def writes_closure(ledger: Any, _execution: Any, _risk: Any) -> bool:
    return bool(ledger.closures)


def writes_order(_ledger: Any, execution: Any, _risk: Any) -> bool:
    return bool(execution.orders)
