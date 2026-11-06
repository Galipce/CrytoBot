"""Aralık sınırı hesabı (spec 0022 R-8; plan Risk 7). Saf: saat çağrılmaz, an parametredir.

Sınır, UTC'de tur aralığının tam katıdır. Bir sınır yalnız bekleme sırasında, kendi aralığının
içinde (T ≤ an < T + aralık) görülürse turu alır; tur sürerken geçen sınırlar kaçmış sayılır ve
telafi edilmez (R-8): tur bitince bir sonraki gelecek sınır beklenir. Uyku ya da saat
sıçramasıyla görülmeden geçen sınırlar da kaçmış sayılır. Geri giden saatte kullanılmış bir
sınır yeniden tur almaz.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def boundary_at_or_before(moment: datetime, interval: timedelta) -> datetime:
    """`moment`'in içinde bulunduğu aralığın başlangıç sınırı."""
    return _EPOCH + (moment - _EPOCH) // interval * interval


@dataclass(frozen=True)
class Due:
    """Sıradaki tur: hangi sınır için ve ondan önce görülmeden kaç sınır geçti."""

    boundary: datetime
    missed: int


def after_turn(boundary: datetime, ended_at: datetime, interval: timedelta) -> tuple[datetime, int]:
    """Tur `ended_at`'te bitti: son kullanılmış sınır ve tur sürerken geçen (kaçan) sınır sayısı.

    Saat geri gittiyse turun sınırı kullanılmış kalır, kaçan yoktur.
    """
    reached = boundary_at_or_before(ended_at, interval)
    if reached <= boundary:
        return boundary, 0
    return reached, (reached - boundary) // interval


def due(last: datetime, now: datetime, interval: timedelta) -> Due | None:
    """Beklemedeyken `now` görüldü: tur alan sınır varsa onu ve öncesinde kaçanları döndürür.

    `None`: henüz sınır yok (saat geri gittiyse de); `last + interval` beklenir.
    """
    current = boundary_at_or_before(now, interval)
    if current <= last:
        return None
    return Due(current, (current - last) // interval - 1)


def seconds_until(last: datetime, now: datetime, interval: timedelta) -> float:
    """Sıradaki sınıra kalan süre; geri giden saatte uzar, sınır geçtiyse 0."""
    return max(0.0, (last + interval - now).total_seconds())
