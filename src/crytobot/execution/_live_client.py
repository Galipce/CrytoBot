"""ccxt Binance spot canlı işlem istemcisi ve yetki koruması (spec 0032 R-2, R-3, R-7, R-8)."""

import json
import re
import threading
from decimal import Decimal, InvalidOperation
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
_BINANCE_UNKNOWN_ORDER: Final = -2011
# Plan 0036 A-1: Binance order validation codes that ccxt raises as `BadRequest` (`-1121`:
# `BadSymbol`), not `InvalidOrder`: filter failure (NOTIONAL included), bad or missing
# parameter, precision, order type/side/time-in-force. Refused before the order is accepted.
_BINANCE_ORDER_REFUSALS: Final = frozenset(
    {-1013, *range(-1106, -1099), -1111, *range(-1121, -1113)}
)


def is_definite_refusal(err: BaseException, venue_code: object = None) -> bool:
    """R-7: yalnız yetersiz bakiye, geçersiz emir (filtre dahil) ve yetki hatası kesin rettir;
    ağ hatası, zaman aşımı, erişilemezlik, bakım, hız sınırı ve tanınmayan her hata değildir.
    Sınıf `isinstance` ile denetlenir, adla değil. `DuplicateOrderId` ve "emir yok" türleri
    `InvalidOrder` alt sınıfıdır ama emrin var olup olmadığını söylemez. ccxt'nin `BadRequest`
    olarak fırlattığı Binance emir doğrulama reddi yalnız yanıt gövdesindeki kodla
    (`venue_code`) kesin ret sayılır; `BadRequest`'in geri kalanı tanınmayan hatadır."""
    import ccxt  # lazy: paper and backtest never load ccxt for execution

    refusals = (ccxt.InsufficientFunds, ccxt.InvalidOrder, ccxt.AuthenticationError)
    undecided = (ccxt.DuplicateOrderId, ccxt.OrderNotFound, ccxt.OrderNotCached)
    if isinstance(err, ccxt.BadRequest):
        return type(venue_code) is int and venue_code in _BINANCE_ORDER_REFUSALS
    return isinstance(err, refusals) and not isinstance(err, undecided)


def _venue_code(body: object) -> object:
    """Binance hata gövdesindeki `code`; gövde JSON nesnesi değilse `None`."""
    if not isinstance(body, str):
        return None
    try:
        parsed = json.loads(body)
    except (ValueError, RecursionError):
        return None
    return parsed.get("code") if isinstance(parsed, dict) else None


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

        # R-7: by ccxt class, never by name; a 5xx or 429 is unknown whatever the class says
        is_unknown = (
            status in _HTTP_SERVER_ERRORS
            or status == _HTTP_TOO_MANY
            or not is_definite_refusal(err, _venue_code(getattr(self._seen, "body", None)))
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

    def place_stop_order(
        self,
        symbol: str,
        side: str,
        amount: str,
        stop_price: str,
        client_order_id: str,
        limit_price: str | None = None,
    ) -> dict[str, Any]:
        """Koşullu stop emri iletir. Önce STOP_LOSS, desteklenmiyorsa STOP_LOSS_LIMIT."""
        self._reset_seen()
        try:
            params: dict[str, Any] = {
                "stopPrice": stop_price,
                "newClientOrderId": client_order_id,
            }
            res: dict[str, Any] = self._exchange.create_order(
                symbol,
                "STOP_LOSS",
                side,
                amount,
                params=params,
            )
            return res
        except Exception as first_err:
            call_err = self._handle_call_error(first_err)
            if call_err.is_unknown:
                raise call_err from None
            if limit_price is not None:
                try:
                    fallback_params: dict[str, Any] = {
                        "stopPrice": stop_price,
                        "newClientOrderId": client_order_id,
                    }
                    fallback_res: dict[str, Any] = self._exchange.create_order(
                        symbol,
                        "STOP_LOSS_LIMIT",
                        side,
                        amount,
                        price=limit_price,
                        params=fallback_params,
                    )
                    return fallback_res
                except Exception as fallback_err:
                    raise self._handle_call_error(fallback_err) from None
            raise call_err from None

    def cancel_order(self, client_order_id: str, symbol: str) -> dict[str, Any] | None:
        """origClientOrderId ile emri borsada iptal eder. Yoksa veya zaten kapandıysa None döner."""
        self._reset_seen()
        try:
            res: dict[str, Any] = self._exchange.cancel_order(
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
            if code in (_BINANCE_ORDER_NOT_EXIST, _BINANCE_UNKNOWN_ORDER) or any(
                name in type(err).__name__ for name in ("OrderNotFound", "OrderImmediateFill")
            ):
                return None
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

    def fetch_order_trades(self, symbol: str, order_id: str) -> list[dict[str, Any]]:
        """Plan 0036 Risk 2: emrin borsa işlemleri (`myTrades`, `orderId`); emir sorgusu
        komisyonu vermez, işlemler verir."""
        self._reset_seen()
        try:
            res = self._exchange.fetch_my_trades(symbol, params={"orderId": order_id})
        except Exception as err:
            raise self._handle_call_error(err) from None
        if not isinstance(res, list) or not all(isinstance(t, dict) for t in res):
            raise LiveExchangeCallError("Geçersiz işlem listesi", is_unknown=True)
        return res

    def fetch_free_balance(self, asset: str = "USDT") -> Decimal:
        """Borsadan ilgili varlığın serbest (free) bakiyesini çeker."""
        self._reset_seen()
        try:
            if hasattr(self._exchange, "fetch_free_balance"):
                res = self._exchange.fetch_free_balance()
                val = res.get(asset) if isinstance(res, dict) else None
            elif hasattr(self._exchange, "fetch_balance"):
                res = self._exchange.fetch_balance()
                free_map = res.get("free") if isinstance(res, dict) else {}
                val = free_map.get(asset) if isinstance(free_map, dict) else None
                if val is None and isinstance(res, dict) and isinstance(res.get(asset), dict):
                    val = res[asset].get("free")
            else:
                raise LiveExchangeCallError(
                    "fetch_free_balance veya fetch_balance metodu bulunamadı"
                )
            if val is None:
                return Decimal("0")
            return Decimal(str(val))
        except (LiveExchangeCallError, BannedError):
            raise
        except (InvalidOperation, TypeError):
            raise LiveExchangeCallError(f"Geçersiz bakiye formatı: {val}") from None
        except Exception as err:
            raise self._handle_call_error(err) from None
