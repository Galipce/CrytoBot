"""Çağrı süresi, okuma bütçesi ve yeniden deneme (spec 0017 R-4; plan Risk 6, 7).

Her çağrı daemon iş parçacığında koşar: `ccxt`'nin `timeout`'u soket süresidir, yavaş akan yanıt onu
aşar. Geride kalan iş parçacığı kendiliğinden biter; `ThreadPoolExecutor` çıkışta onu beklerdi.
"""

import threading
import time
from collections.abc import Callable
from typing import Final

from crytobot.market_data._client import CallFailure, ExchangeCallError
from crytobot.market_data._types import IssueReason, MarketDataError

_RETRY_DELAYS: Final = (0.25, 0.5)
_RETRYABLE: Final = {
    CallFailure.TRANSIENT: IssueReason.NETWORK,
    CallFailure.RATE_LIMITED: IssueReason.RATE_LIMITED,
}
_FINAL: Final = {
    CallFailure.BANNED: IssueReason.RATE_LIMITED,
    CallFailure.BAD_SYMBOL: IssueReason.BAD_SYMBOL,
    CallFailure.BAD_RESPONSE: IssueReason.MALFORMED_RESPONSE,
    CallFailure.OTHER: IssueReason.EXCHANGE_ERROR,
}


class CallFailed(MarketDataError):
    """Çağrıdan değer alınamadı; alan bu nedenle eksik döner."""

    def __init__(self, reason: IssueReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


class _CallTimedOut(MarketDataError):
    """Çağrı kendi süresini aştı; zaman aşımı geçici hatadır (R-4)."""


def _run_limited[T](request: Callable[[float], T], limit: float) -> T:
    """`limit` saniye bekler; iş bitmediyse `_CallTimedOut`. İşin hatası burada yükselir."""
    values: list[T] = []
    errors: list[Exception] = []

    def work() -> None:
        try:
            values.append(request(limit))
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=work, daemon=True, name="crytobot-market-call")
    thread.start()
    thread.join(min(limit, threading.TIMEOUT_MAX))
    if thread.is_alive():
        raise _CallTimedOut
    if errors:
        raise errors[0]
    return values[0]


class Caller:
    """Bir okumanın çağrıları: bütçe okuma başına, yasak (HTTP 418) okuma boyunca geçerlidir."""

    def __init__(self, call_timeout: float, read_budget: float) -> None:
        self._call_timeout = call_timeout
        self._deadline = time.monotonic() + read_budget
        self._banned = False

    def _remaining(self) -> float:
        return self._deadline - time.monotonic()

    def _attempt[T](self, request: Callable[[float], T]) -> T:
        if self._banned:
            raise CallFailed(IssueReason.RATE_LIMITED)
        remaining = self._remaining()
        if remaining <= 0:
            raise CallFailed(IssueReason.BUDGET_ENDED)
        limit = min(self._call_timeout, remaining)
        try:
            return _run_limited(request, limit)
        except _CallTimedOut:
            if limit < self._call_timeout:
                raise CallFailed(IssueReason.BUDGET_ENDED) from None
            raise

    def _retry_reason(self, error: ExchangeCallError) -> IssueReason:
        """Yeniden denenecek hatanın nedeni; denenmeyecek hata burada `CallFailed` olur."""
        if error.failure is CallFailure.BANNED:
            # Requests during a ban extend it: nothing else is sent in this read (plan Risk 7)
            self._banned = True
        final = _FINAL.get(error.failure)
        if final is not None:
            raise CallFailed(final) from None
        return _RETRYABLE[error.failure]

    def call[T](self, request: Callable[[float], T]) -> T:
        """Geçici hatada bütçe içinde en çok 3 deneme; bekleme bütçeyi aşacaksa `BUDGET_ENDED`."""
        for delay in (*_RETRY_DELAYS, None):
            retry_after = None
            try:
                return self._attempt(request)
            except CallFailed:
                raise
            except _CallTimedOut:
                reason = IssueReason.CALL_TIMED_OUT
            except ExchangeCallError as error:
                reason = self._retry_reason(error)
                retry_after = error.retry_after
            except Exception:
                raise CallFailed(IssueReason.UNEXPECTED) from None
            if delay is None:
                raise CallFailed(reason)
            wait = max(delay, retry_after or 0.0)
            if wait >= self._remaining():
                raise CallFailed(IssueReason.BUDGET_ENDED)
            time.sleep(wait)
        raise AssertionError("the last delay raises")  # pragma: no cover
