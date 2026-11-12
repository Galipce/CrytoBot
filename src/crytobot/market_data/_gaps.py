"""Dönem boşlukları (spec 0044 R-2, R-3; plan Adım 4, Risk 1, 3).

Saftır: bir çiftin veri dosyasındaki mumlarından hesaplar, dosya ve borsa okumaz.

`period_gaps` boşluğu indirmenin özetindeki `boşluk=` sayımıyla (`_history._Download.keep`, 0023
R-6) aynı kuralla bulur; özetle eşitlik testle kanıtlanır (AC-1):

- Ardışık eksik mumlar tek boşluktur; satır ilk ve son eksik mumun açılışını ve eksik mum sayısını
  taşır.
- Çiftin ilk mumundan önceki eksiklik boşluk değildir (geç listelenen çift).
- Isınmadaki eksikler sayılmaz; ısınmadan döneme taşan boşluğun ilk eksik mumu dönemin ilk beklenen
  açılışıdır (dönem başı mum sınırında değilse, başlangıcın kestiği mum — indirmeyle aynı), sayı
  yalnız dönem içi eksik mumlardır.
- Dönem sonundaki eksiklik bir boşluktur; son eksik mum bitişten önce kapanan son mumdur.

`has_candle`: açılışı `[start, end)` içinde mum var mı (R-3 "dönemde kapanmış mum"; dosyada yalnız
kapanmış mumlar vardır).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

from crytobot.market_data._history_read import HistoryPair


@dataclass(frozen=True, slots=True)
class CandleGap:
    """Bir boşluk: çift, ilk ve son eksik mumun açılışı, eksik mum sayısı."""

    pair: str
    first: datetime
    last: datetime
    count: int


def _slot(moment: datetime, interval: timedelta, origin: datetime) -> datetime:
    """`moment`'i içeren mumun açılışı (açılışlar `origin`'den aralık adımlarıyla)."""
    return origin + (moment - origin) // interval * interval


def period_gaps(
    pair: HistoryPair, interval: timedelta, start: datetime, end: datetime
) -> tuple[CandleGap, ...]:
    """Çiftin dönemdeki (`start` dahil, `end` hariç) boşlukları, zaman sırasıyla."""
    candles = pair.candles
    if not candles:
        return ()
    origin = candles[0].open_time
    period_first = _slot(start, interval, origin)  # the candle `start` falls in (0023 R-6)
    gaps: list[CandleGap] = []
    for earlier, later in pairwise(candles):
        missing_first = earlier.open_time + interval
        if later.open_time > missing_first and later.open_time > start:
            first = max(missing_first, period_first)
            last = later.open_time - interval
            gaps.append(CandleGap(pair.pair, first, last, (last - first) // interval + 1))
    last_slot = _slot(end, interval, origin) - interval  # the last candle closed by `end`
    newest = candles[-1].open_time
    if newest < last_slot:
        first = max(newest + interval, period_first)
        gaps.append(CandleGap(pair.pair, first, last_slot, (last_slot - first) // interval + 1))
    return tuple(gaps)


def has_candle(pair: HistoryPair, start: datetime, end: datetime) -> bool:
    """R-3: çiftin açılışı `[start, end)` içinde en az bir mumu var mı."""
    return any(start <= candle.open_time < end for candle in pair.candles)
