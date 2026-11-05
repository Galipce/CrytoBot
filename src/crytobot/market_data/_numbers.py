"""Borsa metninden katı değer: `Decimal` ve UTC zaman (spec 0017 R-9, R-11; plan Risk 11)."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_MILLISECOND: Final = timedelta(milliseconds=1)
# `Decimal` alone accepts "1_000", " 1 ", "1e400" and "NaN"; none of them is an exchange value
_PLAIN_NUMBER: Final = re.compile(r"[0-9]+(?:\.([0-9]+))?")
_MAX_LENGTH: Final = 40
_MAX_DECIMALS: Final = 18


def exact_decimal(value: object) -> Decimal | None:
    """Düz ondalık metni birebir `Decimal`'e çevirir; başka her şey `None`."""
    if type(value) is not str or len(value) > _MAX_LENGTH:
        return None
    match = _PLAIN_NUMBER.fullmatch(value)
    if match is None or len(match.group(1) or "") > _MAX_DECIMALS:
        return None
    return Decimal(value)


def utc_from_ms(value: object) -> datetime | None:
    """Epoch milisaniyesini timezone-aware UTC zamana çevirir; `float` geçmez."""
    if type(value) is not int or value < 0:
        return None
    try:
        return _EPOCH + timedelta(milliseconds=value)
    except OverflowError:
        return None


def ms_from_utc(moment: datetime) -> int:
    return (moment - _EPOCH) // _MILLISECOND
