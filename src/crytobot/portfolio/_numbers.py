"""Defter girdilerinin sayı kuralı ve ret mesajı yardımcıları (spec 0007 R-11).

`crytobot.execution._numbers`'ın kopyasıdır (o da `crytobot.risk`'inkilerin kopyası): başka
modülün iç alt modülü import edilemez (docs/architecture.md), kural ise üç modülde aynı kalmalıdır
(docs/conventions.md).
"""

from decimal import Context, Decimal, DivisionByZero, Inexact, InvalidOperation, Overflow

# the default context's exponent range, as in risk (spec 0005 R-7)
SCALE = 999_999
# significant digits of a ledger amount or price: every real exchange value fits (spec 0007 R-11)
DIGITS = 28
# significant digits of an exact calculation: realistic values need at most 48 (spec 0010 R-2, R-5)
CALC_DIGITS = 60


def _number(value: object) -> Decimal | None:
    """`Decimal` veya `int` (`bool` hariç) sonlu bir sayı; değilse `None`."""
    if isinstance(value, bool) or not isinstance(value, Decimal | int):
        return None
    number = Decimal(value)
    return number if number.is_finite() else None


def _in_scale(number: Decimal) -> bool:
    """Üssü varsayılan decimal aralığında (±999999) olan sayı."""
    return -SCALE <= number.adjusted() <= SCALE


def _significant(number: Decimal) -> int:
    """Sondaki sıfırlar hariç basamak sayısı; değeri `str`'e ya da `int`'e çevirmeden sayar."""
    digits = number.as_tuple().digits
    return len(bytes(digits).rstrip(b"\0"))


def _brief(number: Decimal) -> str:
    """Mesaj için sayı: en fazla 28 basamaklıysa kendisi, değilse basamak sayısı — ölçek içindeki
    milyon basamaklı bir değer mesajı megabaytlarca uzatmasın (B-11)."""
    length = len(number.as_tuple().digits)
    return str(number) if length <= DIGITS else f"<{length} basamaklı sayı>"


def _show(value: object) -> str:
    """Ret mesajı için `repr`; 3.12'de 4300 basamağı aşan `int` `str`'e çevrilirken `ValueError`
    fırlatır — çıplaksa `Decimal` üzerinden yazılır, `Fraction`/tuple içindeyse yerine tür adı."""
    if isinstance(value, Decimal):
        return repr(value) if len(value.as_tuple().digits) <= DIGITS else _brief(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return _brief(Decimal(value))
    try:
        return repr(value)
    except ValueError:
        return f"<{type(value).__name__}: gösterilemiyor>"


# 60 digits, and a result that does not fit raises instead of rounding (plan 0007 Risk 3): the
# exact answer is kept or the calculation stops, in time independent of how many digits a value has
BOUNDED = Context(
    prec=CALC_DIGITS,
    Emax=SCALE,
    Emin=-SCALE,
    traps=[InvalidOperation, DivisionByZero, Overflow, Inexact],
)
