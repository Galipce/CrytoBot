"""Spec 0032 AC-2 ve AC-3: Para çekme (fail-closed) ve spot yetki koruması."""

import pytest

from crytobot.execution._credentials import REDACTED, ExchangeCredentials
from crytobot.execution._live_client import (
    PERMISSION_CHECK_FAILED,
    SPOT_TRADING_DISABLED,
    WITHDRAWAL_PERMISSION_FORBIDDEN,
    BinanceLiveClient,
    PermissionCheckFailedError,
    PermissionForbiddenError,
)


class FakeExchange:
    def __init__(self, restrictions: object = None, raise_error: Exception | None = None) -> None:
        self.restrictions = restrictions
        self.raise_error = raise_error

    def sapiGetAccountApiRestrictions(self) -> object:
        if self.raise_error is not None:
            raise self.raise_error
        return self.restrictions


class FakeSnakeCaseExchange:
    def __init__(self, restrictions: object = None) -> None:
        self.restrictions = restrictions

    def sapi_get_account_api_restrictions(self) -> object:
        return self.restrictions


class FakeNoMethodExchange:
    pass


def test_withdrawal_permission_fails_closed() -> None:
    """AC-2: Para çekme yetkisi tespit edilirse veya yetki sorgusu başarısızsa sistem durur."""
    creds = ExchangeCredentials(api_key="k", api_secret="s", testnet=False)

    # 1. enableWithdrawals = True -> WITHDRAWAL_PERMISSION_FORBIDDEN
    fake_dangerous = FakeExchange(
        restrictions={
            "enableWithdrawals": True,
            "enableSpotAndMarginTrading": True,
        }
    )
    client = BinanceLiveClient(credentials=creds, exchange=fake_dangerous)
    with pytest.raises(PermissionForbiddenError) as exc_info:
        client.verify_permissions()
    assert exc_info.value.code == WITHDRAWAL_PERMISSION_FORBIDDEN

    # 2. Yetki sorgusu borsa hatası veya ağ hatası verirse -> PERMISSION_CHECK_FAILED
    fake_failing = FakeExchange(raise_error=RuntimeError("Binance API unreachable"))
    client_failing = BinanceLiveClient(credentials=creds, exchange=fake_failing)
    with pytest.raises(PermissionCheckFailedError) as exc_failed:
        client_failing.verify_permissions()
    assert exc_failed.value.code == PERMISSION_CHECK_FAILED

    # 3. Yanıt dict formatında değilse -> PERMISSION_CHECK_FAILED
    fake_malformed = FakeExchange(restrictions="not a dict")
    client_malformed = BinanceLiveClient(credentials=creds, exchange=fake_malformed)
    with pytest.raises(PermissionCheckFailedError) as exc_malformed:
        client_malformed.verify_permissions()
    assert exc_malformed.value.code == PERMISSION_CHECK_FAILED

    # 4. Hiç yetki metodu olmayan nesne -> PERMISSION_CHECK_FAILED
    client_no_method = BinanceLiveClient(credentials=creds, exchange=FakeNoMethodExchange())
    with pytest.raises(PermissionCheckFailedError) as exc_no_method:
        client_no_method.verify_permissions()
    assert exc_no_method.value.code == PERMISSION_CHECK_FAILED

    # 5. sapi_get_account_api_restrictions (snake_case) desteği
    fake_snake = FakeSnakeCaseExchange(
        restrictions={"enableWithdrawals": False, "enableSpotAndMarginTrading": True}
    )
    client_snake = BinanceLiveClient(credentials=creds, exchange=fake_snake)
    client_snake.verify_permissions()

    # 6. enableWithdrawals alanı eksik veya None ise -> fail-closed (F-4)
    fake_missing_withdraw = FakeExchange(
        restrictions={
            "enableSpotAndMarginTrading": True,
        }
    )
    client_missing_withdraw = BinanceLiveClient(credentials=creds, exchange=fake_missing_withdraw)
    with pytest.raises(PermissionForbiddenError) as exc_missing_withdraw:
        client_missing_withdraw.verify_permissions()
    assert exc_missing_withdraw.value.code == WITHDRAWAL_PERMISSION_FORBIDDEN


def test_spot_trading_disabled_rejected() -> None:
    """AC-3: Spot işlem yetkisi kapalı ise adaptör SPOT_TRADING_DISABLED ile reddeder."""
    creds = ExchangeCredentials(api_key="k", api_secret="s", testnet=False)

    # 1. enableSpotAndMarginTrading = False
    fake_no_spot = FakeExchange(
        restrictions={
            "enableWithdrawals": False,
            "enableSpotAndMarginTrading": False,
        }
    )
    client_no_spot = BinanceLiveClient(credentials=creds, exchange=fake_no_spot)
    with pytest.raises(PermissionForbiddenError) as exc_info:
        client_no_spot.verify_permissions()
    assert exc_info.value.code == SPOT_TRADING_DISABLED

    # 2. enableSpotAndMarginTrading anahtarı hiç yok
    fake_missing_spot = FakeExchange(
        restrictions={
            "enableWithdrawals": False,
        }
    )
    client_missing = BinanceLiveClient(credentials=creds, exchange=fake_missing_spot)
    with pytest.raises(PermissionForbiddenError) as exc_missing:
        client_missing.verify_permissions()
    assert exc_missing.value.code == SPOT_TRADING_DISABLED

    # 3. İzin verilen geçerli durum: enableWithdrawals=False, enableSpotAndMarginTrading=True
    fake_valid = FakeExchange(
        restrictions={
            "enableWithdrawals": False,
            "enableSpotAndMarginTrading": True,
        }
    )
    client_valid = BinanceLiveClient(credentials=creds, exchange=fake_valid)
    client_valid.verify_permissions()
    assert client_valid.credentials == creds


def test_verify_permissions_redacts_secrets_in_error() -> None:
    """AC-2, AC-4: Yetki sorgusu hatasında sırlar maskelenir ve traceback zincirlenmez (F-7)."""
    creds = ExchangeCredentials(
        api_key="leaked_key_999", api_secret="leaked_sec_888", testnet=False
    )
    fake = FakeExchange(
        raise_error=RuntimeError("Auth error for leaked_key_999 with leaked_sec_888")
    )
    client = BinanceLiveClient(credentials=creds, exchange=fake)
    with pytest.raises(PermissionCheckFailedError) as exc_info:
        client.verify_permissions()
    msg = str(exc_info.value)
    assert "leaked_key_999" not in msg
    assert "leaked_sec_888" not in msg
    assert REDACTED in msg
    assert exc_info.value.__cause__ is None
