"""ccxt Binance spot canlı işlem istemcisi ve yetki koruması (spec 0032 R-2, R-3, R-7, R-8)."""

import json
import re
import threading
from typing import Any, Final

from crytobot.execution._credentials import (
    ExchangeCredentials,
    ExecutionError,
    redact_secrets,
)

WITHDRAWAL_PERMISSION_FORBIDDEN: Final = "WITHDRAWAL_PERMISSION_FORBIDDEN"
PERMISSION_CHECK_FAILED: Final = "PERMISSION_CHECK_FAILED"
SPOT_TRADING_DISABLED: Final = "SPOT_TRADING_DISABLED"

_HTTP_BANNED: Final = 418
_HTTP_TOO_MANY: Final = 429
_HTTP_SERVER_ERRORS: Final = range(500, 600)
_RETRY_AFTER: Final = re.compile(r"[0-9]{1,6}")
_BINANCE_ORDER_NOT_EXIST: Final = -2013


class PermissionForbiddenError(ExecutionError):
    """Para çekme yetkisi gibi yasaklı veya eksik bir yetki tespit edildiğinde fırlatılır."""

    def __init__(
        self,
        message: str = WITHDRAWAL_PERMISSION_FORBIDDEN,
        code: str = WITHDRAWAL_PERMISSION_FORBIDDEN,
    ) -> None:
        super().__init__(message)
        self.code = code


class PermissionCheckFailedError(ExecutionError):
    """Yetki doğrulama borsa çağrısı başarısız olduğunda fırlatılır."""

    def __init__(
        self,
        message: str = PERMISSION_CHECK_FAILED,
        code: str = PERMISSION_CHECK_FAILED,
    ) -> None:
        super().__init__(message)
        self.code = code


class BannedError(ExecutionError):
    """Borsa tarafından IP veya hesap banlandığında (418) fail-closed durdurulur."""


class LiveExchangeCallError(ExecutionError):
    """Canlı borsa çağrısı hatası."""

    def __init__(
        self,
        message: str,
        is_unknown: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.is_unknown = is_unknown
        self.retry_after = retry_after


def check_api_restrictions(data: Any) -> None:
    """Binance sapiGetAccountApiRestrictions yanıtını doğrular (R-2, R-3)."""
    if not isinstance(data, dict):
        raise PermissionCheckFailedError("Yetki yanıtı geçersiz formatta")

    if data.get("enableWithdrawals") is not False:
        raise PermissionForbiddenError(
            "API anahtarında para çekme yetkisi açık veya belirsiz; fail-closed durduruldu",
            code=WITHDRAWAL_PERMISSION_FORBIDDEN,
        )

    if data.get("enableSpotAndMarginTrading") is not True:
        raise PermissionForbiddenError(
            "API anahtarında spot işlem yetkisi kapalı",
            code=SPOT_TRADING_DISABLED,
        )


def verify_permissions(
    exchange: Any,
    credentials: ExchangeCredentials | None = None,
) -> None:
    """API yetkilerini borsadan sorgular ve doğrular (R-2, R-3)."""
    try:
        if hasattr(exchange, "sapiGetAccountApiRestrictions"):
            data = exchange.sapiGetAccountApiRestrictions()
        elif hasattr(exchange, "sapi_get_account_api_restrictions"):
            data = exchange.sapi_get_account_api_restrictions()
        else:
            raise PermissionCheckFailedError("sapiGetAccountApiRestrictions metodu bulunamadı")
    except PermissionForbiddenError:
        raise
    except Exception as err:
        safe_msg = redact_secrets(str(err), credentials)
        raise PermissionCheckFailedError(f"Yetki sorgusu başarısız: {safe_msg}") from None

    check_api_restrictions(data)


class BinanceLiveClient:
    """ccxt Binance canlı spot istemcisi ve yetki bekçisi."""

    def __init__(
        self,
        credentials: ExchangeCredentials,
        exchange: Any | None = None,
    ) -> None:
        self._credentials = credentials
        self._seen = threading.local()
        self._retry_after_until: float = 0.0

        if exchange is not None:
            self._exchange = exchange
        else:
            import ccxt

            self._exchange = ccxt.binance(
                {
                    "apiKey": credentials.api_key,
                    "secret": credentials.api_secret,
                    "enableRateLimit": True,
                    "options": {
                        "defaultType": "spot",
                        "fetchCurrencies": False,
                    },
                }
            )
            self._exchange.number = str
            if credentials.testnet:
                self._exchange.set_sandbox_mode(True)

        forward = getattr(self._exchange, "on_rest_response", None)

        def remember_response(
            code: int,
            reason: str,
            url: str,
            method: str,
            headers: Any,
            body: Any,
            *rest: Any,
        ) -> Any:
            self._seen.status = code
            self._seen.retry_after = (
                headers.get("Retry-After") if isinstance(headers, dict) else None
            )
            self._seen.body = body
            if forward is not None and callable(forward):
                return forward(code, reason, url, method, headers, body, *rest)
            return body.strip() if hasattr(body, "strip") else body

        self._exchange.on_rest_response = remember_response

    @property
    def credentials(self) -> ExchangeCredentials:
        return self._credentials

    def verify_permissions(self) -> None:
        """Borsa anahtar yetkilerini kontrol eder (R-2, R-3)."""
        verify_permissions(self._exchange, self._credentials)

    def _reset_seen(self) -> None:
        self._seen.status = None
        self._seen.retry_after = None
        self._seen.body = None

    def _extract_retry_after(self) -> float | None:
        text = getattr(self._seen, "retry_after", None)
        if isinstance(text, str) and _RETRY_AFTER.fullmatch(text):
            return float(text)
        return None

    def _handle_call_error(self, err: Exception) -> LiveExchangeCallError:
        status = getattr(self._seen, "status", None)
        retry_after = self._extract_retry_after()

        if status == _HTTP_BANNED:
            raise BannedError("Borsa IP/hesap banı (HTTP 418); fail-closed durduruldu") from None

        is_rate_limited = status == _HTTP_TOO_MANY or "RateLimitExceeded" in type(err).__name__
        is_unknown = (
            status in _HTTP_SERVER_ERRORS
            or is_rate_limited
            or any(
                name in type(err).__name__
                for name in ("NetworkError", "RequestTimeout", "OperationFailed")
            )
        )
        safe_msg = redact_secrets(str(err), self._credentials)
        return LiveExchangeCallError(
            f"Borsa çağrısı hatası: {safe_msg}",
            is_unknown=is_unknown,
            retry_after=retry_after,
        )

    def place_market_order(
        self,
        symbol: str,
        side: str,
        amount: str,
        client_order_id: str,
    ) -> dict[str, Any]:
        """Piyasa emri iletir. Ağ hatasında UNKNOWN, rette REJECTED."""
        self._reset_seen()
        try:
            res: dict[str, Any] = self._exchange.create_order(
                symbol,
                "market",
                side,
                amount,
                params={"newClientOrderId": client_order_id},
            )
            return res
        except Exception as err:
            raise self._handle_call_error(err) from None

    def query_order(self, client_order_id: str, symbol: str) -> dict[str, Any] | None:
        """origClientOrderId ile emri borsadan sorgular. Yoksa None döner."""
        self._reset_seen()
        try:
            res: dict[str, Any] = self._exchange.fetch_order(
                None,
                symbol=symbol,
                params={"origClientOrderId": client_order_id},
            )
            return res
        except Exception as err:
            body = getattr(self._seen, "body", None)
            code = None
            if isinstance(body, str):
                try:
                    code = json.loads(body).get("code")
                except (ValueError, RecursionError):
                    code = None
            if code == _BINANCE_ORDER_NOT_EXIST or "OrderNotFound" in type(err).__name__:
                return None
            raise self._handle_call_error(err) from None
