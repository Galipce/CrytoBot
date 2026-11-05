"""Tek `ccxt` dosyası: üç herkese açık Binance çağrısı, anahtarsız (spec 0017 R-2, R-4, R-11).

Mum ve fiyat ham uçtan okunur: birleşik `fetch_ohlcv` yanıtı sıralayıp R-13'ü gizler (plan Risk 3).
Hata metni bu dosyadan çıkmaz; çağrı yalnız `CallFailure` ile başarısız olur. `ccxt`'nin ilk
importu saniyeler sürer, bu yüzden import fonksiyonun içindedir ve okumanın süresine sayılır
(plan Risk 9).
"""

import json
import math
import re
import threading
from collections.abc import Callable
from enum import Enum
from typing import Any, Final, Protocol

from crytobot.market_data._types import MarketDataError

_RETRY_AFTER: Final = re.compile(r"[0-9]{1,6}")
_HTTP_BANNED: Final = 418
_HTTP_TOO_MANY: Final = 429
_HTTP_SERVER_ERRORS: Final = range(500, 600)
# Binance: "too many requests queued, try again"; ccxt does not know the code (plan A-2)
_BINANCE_TRY_AGAIN: Final = -1008


class CallFailure(Enum):
    TRANSIENT = "transient"
    RATE_LIMITED = "rate_limited"
    BANNED = "banned"
    BAD_SYMBOL = "bad_symbol"
    BAD_RESPONSE = "bad_response"
    OTHER = "other"


class ExchangeCallError(MarketDataError):
    """Borsa çağrısı başarısız; borsanın metnini taşımaz (R-11)."""

    def __init__(self, failure: CallFailure, retry_after: float | None = None) -> None:
        super().__init__(failure.value)
        self.failure = failure
        self.retry_after = retry_after


def _error_code(body: object) -> object:
    """Binance hata gövdesindeki `code`; okunamayan gövdede `None`. Metin dışarı çıkmaz (R-11)."""
    if not isinstance(body, str):
        return None
    try:
        parsed: object = json.loads(body)
    except (ValueError, RecursionError):
        return None
    return parsed.get("code") if isinstance(parsed, dict) else None


class PublicExchange(Protocol):
    """Okumanın borsadan görebildiği her şey: emir ve hesap çağrısı yoktur (R-2)."""

    def markets(self, timeout: float) -> object: ...

    def klines(
        self, market_id: str, interval: str, limit: int, end_ms: int, timeout: float
    ) -> object: ...

    def ticker(self, market_id: str, timeout: float) -> object: ...


class _BinancePublic:
    def __init__(self, library: Any) -> None:
        self._library = library
        self._seen = threading.local()
        # No credential is given; ccxt reads none from the environment (plan Risk 14)
        self._exchange: Any = library.binance(
            {
                "enableRateLimit": True,
                "options": {
                    "defaultType": "spot",
                    "fetchMarkets": {"types": ["spot"]},
                    "fetchCurrencies": False,
                },
            }
        )
        # Exact text instead of float (plan Risk 3)
        self._exchange.number = str
        forward = self._exchange.on_rest_response

        def remember_response(
            code: int, reason: str, url: str, method: str, headers: Any, body: Any, *rest: Any
        ) -> Any:
            # binance raises DDoSProtection for 429 and 418 alike; only the status tells a limit
            # to wait out from a ban that retries would extend (plan Risk 7)
            self._seen.status = code
            self._seen.retry_after = headers.get("Retry-After")
            self._seen.body = body
            return forward(code, reason, url, method, headers, body, *rest)

        self._exchange.on_rest_response = remember_response

    def _failure(self, error: Exception) -> CallFailure:
        library = self._library
        status = getattr(self._seen, "status", None)
        if status == _HTTP_BANNED:
            return CallFailure.BANNED
        if status == _HTTP_TOO_MANY or isinstance(error, library.RateLimitExceeded):
            return CallFailure.RATE_LIMITED
        if status in _HTTP_SERVER_ERRORS:
            # The server's own fault, whatever its body says: -1016 and -1121 included (plan A-2)
            return CallFailure.TRANSIENT
        if isinstance(error, library.BadSymbol):
            return CallFailure.BAD_SYMBOL
        if isinstance(error, library.BadResponse):
            return CallFailure.BAD_RESPONSE
        # OperationFailed, not NetworkError: binance -1000/-1001/-1006 are outside NetworkError
        if isinstance(error, library.OperationFailed):
            return CallFailure.TRANSIENT
        if _error_code(getattr(self._seen, "body", None)) == _BINANCE_TRY_AGAIN:
            return CallFailure.TRANSIENT
        return CallFailure.OTHER

    def _retry_after(self) -> float | None:
        text = getattr(self._seen, "retry_after", None)
        if isinstance(text, str) and _RETRY_AFTER.fullmatch(text):
            return float(text)
        return None

    def _request(self, timeout: float, request: Callable[[], object]) -> object:
        self._seen.status = None
        self._seen.retry_after = None
        self._seen.body = None
        self._exchange.timeout = max(1, math.ceil(timeout * 1000))
        try:
            return request()
        except self._library.BaseError as error:
            raise ExchangeCallError(self._failure(error), self._retry_after()) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            # ccxt's market parser met a shape it does not expect
            raise ExchangeCallError(CallFailure.BAD_RESPONSE) from None

    def markets(self, timeout: float) -> object:
        markets = self._request(timeout, self._exchange.load_markets)
        if not markets:
            # ccxt turns an unreadable exchangeInfo into no markets; that is not "pair not listed"
            raise ExchangeCallError(CallFailure.BAD_RESPONSE)
        return markets

    def klines(
        self, market_id: str, interval: str, limit: int, end_ms: int, timeout: float
    ) -> object:
        params = {"symbol": market_id, "interval": interval, "limit": limit, "endTime": end_ms}
        return self._request(timeout, lambda: self._exchange.publicGetKlines(params))

    def ticker(self, market_id: str, timeout: float) -> object:
        params = {"symbol": market_id}
        return self._request(timeout, lambda: self._exchange.publicGetTicker24hr(params))


def connect_public() -> PublicExchange:
    """Anahtarsız Binance istemcisi; soket açmaz, ilk çağrıya kadar ağa çıkmaz."""
    import ccxt

    return _BinancePublic(ccxt)
