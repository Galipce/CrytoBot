"""Coin başına teknik özet (spec 0059 R-2, AC-2; S-2; plan A-1). Saf: ağa, saate ve dosyaya
dokunmaz.

Girdi yalnız kapanmış mumlardır: açılışı + aralığı turun sınırını aşan mum atılır. Özet: son 48 adet
1h mum (açılış, en yüksek, en düşük, kapanış — okuyucu hacim taşımaz, A-1), son 30 adet 4h mum, EMA
20/50/200, RSI 14, ATR 14 (1h), 24 saatlik ve 7 günlük değişim, son 48 1h mumun en yüksek ve en
düşüğü, son 24 saatin olay skorları. İndikatörler `analysis` ile hesaplanır. Bir coinin son 1h mumu
turun sınırından bir önceki saat değilse, ya da 1h'de en az `MIN_H1`, 4h'de en az `H4` mum yoksa o
coin "veri yok"tur. Fiyatlar borsanın fiyat adımına (yoksa 6 anlamlı basamağa) yuvarlanır.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final

from crytobot.analysis import AnalysisError, Candle, atr, ema, rsi

HOUR: Final = timedelta(hours=1)
H4_SPAN: Final = timedelta(hours=4)
H1_SHOWN: Final = 48
H4: Final = 30
MIN_H1: Final = 200 + 1  # EMA 200 needs 200 closes; the 7-day change needs 168 more hours back
WEEK_H1: Final = 168
NO_DATA: Final = "veri yok"


@dataclass(frozen=True)
class EventNote:
    """Son 24 saatte skorlanmış bir olay (0051 skor kaydından)."""

    at: datetime
    event_type: str
    direction: str
    severity: int


@dataclass(frozen=True)
class CoinData:
    coin: str
    h1: tuple[Candle, ...]
    h4: tuple[Candle, ...]
    tick: Decimal | None
    events: tuple[EventNote, ...] = ()


@dataclass(frozen=True)
class CoinSummary:
    """`text` istemin veri bölümüne girer; `low`/`high`: son 48 1h mumun aralığı (doğrulama)."""

    coin: str
    text: str
    low: float
    high: float
    last_close: float


def closed(candles: Sequence[Candle], span: timedelta, boundary: datetime) -> tuple[Candle, ...]:
    """Kapanışı turun sınırına kadar olan mumlar; zaman sırasıyla."""
    kept = [candle for candle in candles if candle.open_time + span <= boundary]
    return tuple(sorted(kept, key=lambda candle: candle.open_time))


def _digits(tick: Decimal | None) -> int | None:
    if tick is None or tick <= 0:
        return None
    exponent = tick.normalize().as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else None


def price(value: float, tick: Decimal | None) -> str:
    """Fiyat metni: adımın basamağıyla, yoksa 6 anlamlı basamak."""
    digits = _digits(tick)
    if digits is None:
        return f"{value:.6g}"
    quantum = Decimal(1).scaleb(-digits)
    return str(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_EVEN))


def _change(now: float, then: float) -> str:
    return "-" if then == 0 else f"{(now / then - 1) * 100:+.2f}%"


def _last(values: Sequence[float | None]) -> float | None:
    return values[-1] if values else None


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%MZ")


def _rows(candles: Sequence[Candle], tick: Decimal | None) -> list[str]:
    return [
        f"{_stamp(c.open_time)} {price(c.open, tick)} {price(c.high, tick)} "
        f"{price(c.low, tick)} {price(c.close, tick)}"
        for c in candles
    ]


def summarize(data: CoinData, boundary: datetime) -> CoinSummary | None:
    """`None`: veri yok (eksik, bayat ya da hesaplanamıyor)."""
    h1 = closed(data.h1, HOUR, boundary)
    h4 = closed(data.h4, H4_SPAN, boundary)
    if len(h1) < MIN_H1 or len(h4) < H4 or h1[-1].open_time != boundary - HOUR:
        return None
    try:
        ema20, ema50, ema200 = (_last(ema(h1, period=p)) for p in (20, 50, 200))
        rsi14 = _last(rsi(h1, period=14))
        atr14 = _last(atr(h1, period=14))
    except AnalysisError:
        return None
    if None in (ema20, ema50, ema200, rsi14, atr14):
        return None
    shown, h4_shown = h1[-H1_SHOWN:], h4[-H4:]
    low, high = min(c.low for c in shown), max(c.high for c in shown)
    last = h1[-1].close
    week = h1[-1 - WEEK_H1].close if len(h1) > WEEK_H1 else h1[0].close
    tick = data.tick
    assert ema20 is not None and ema50 is not None and ema200 is not None
    assert rsi14 is not None and atr14 is not None
    events = (
        [f"{_stamp(e.at)} {e.event_type} {e.direction}/{e.severity}" for e in data.events]
        if data.events
        else ["yok"]
    )
    lines = [
        f"## {data.coin}",
        f"fiyat_adımı: {'-' if tick is None else str(tick.normalize())}",
        f"son_kapanış: {price(last, tick)} ({_stamp(h1[-1].open_time)} açılışlı 1h mum)",
        f"değişim_24s: {_change(last, h1[-25].close)} değişim_7g: {_change(last, week)}",
        f"ema20: {price(ema20, tick)} ema50: {price(ema50, tick)} ema200: {price(ema200, tick)}",
        f"rsi14: {rsi14:.1f} atr14: {price(atr14, tick)}",
        f"48x1h_en_yüksek: {price(high, tick)} 48x1h_en_düşük: {price(low, tick)}",
        f"1h mumlar (açılış anı, açılış, en yüksek, en düşük, kapanış), son {H1_SHOWN}:",
        *_rows(shown, tick),
        f"4h mumlar (açılış anı, açılış, en yüksek, en düşük, kapanış), son {H4}:",
        *_rows(h4_shown, tick),
        "olay skorları (son 24 saat):",
        *events,
    ]
    return CoinSummary(data.coin, "\n".join(lines), low, high, last)
