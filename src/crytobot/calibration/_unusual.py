"""Olağandışı mum kuralları (spec 0045 Q-8, R-8; plan Risk 8). Saf.

Bir aralığın beş çiftinin mumlarından her mum için hangi kuralların (`a`…`d`) işaretlediğini
verir. Mumlar ölçümden çıkarılmaz; işaret yalnız raporlama ve "olağandışısız" küme içindir.

- ATR: mumun kendi boyu ATR'yi şişirmesin diye bir önceki mevcut mumun ATR(14)'üdür (Wilder).
  Önceki mumun ATR'si yoksa (ısınma) (a), (c), (d) işaretlemez.
- (a) `yüksek - düşük > 4·ATR`.
- (b) `hacim > 5 · (önceki 20 mevcut mumun hacim ortalaması)`; 20 önceki mum yoksa işaretlemez.
- (c) `|kapanış - açılış| > 3·ATR` ve sonraki 3 mevcut mumdan birinin kapanışı hareketin en az
  üçte ikisini geri alır (yükselişte `3·(kapanış - sonraki kapanış) ≥ 2·(kapanış - açılış)`).
- (d) aynı açılış anında beş çiftin en az dördünde `yüksek - düşük > 3·ATR`: yalnız eşiği aşan
  çiftlerin mumları işaretlenir; o anda mumu olmayan çift "aşmadı" sayılır.

Eşikler kesin büyüktür: tam eşik değerindeki mum işaretlenmez (AC-4).
"""

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Final

from crytobot.analysis import Candle, atr

ATR_PERIOD: Final = 14
RANGE_MULTIPLE: Final = 4
VOLUME_WINDOW: Final = 20
VOLUME_MULTIPLE: Final = 5
BODY_MULTIPLE: Final = 3
RETRACE_CANDLES: Final = 3
SHARED_MULTIPLE: Final = 3
SHARED_PAIRS: Final = 4

Flags = tuple[str, ...]  # per candle: the rule letters, "" when none


def previous_atr(candles: Sequence[Candle]) -> tuple[float | None, ...]:
    """Konum `t`'de `t-1`'in ATR(14)'ü; ilk mumda yok."""
    values = atr(candles, period=ATR_PERIOD)
    return (None, *values[:-1]) if values else ()


def _volume_spike(volumes: Sequence[float], index: int) -> bool:
    if index < VOLUME_WINDOW:
        return False
    total = math.fsum(volumes[index - VOLUME_WINDOW : index])
    return volumes[index] * VOLUME_WINDOW > VOLUME_MULTIPLE * total


def _reversal(candles: Sequence[Candle], index: int, average: float) -> bool:
    candle = candles[index]
    move = candle.close - candle.open
    if not abs(move) > BODY_MULTIPLE * average:
        return False
    for later in candles[index + 1 : index + 1 + RETRACE_CANDLES]:
        back = candle.close - later.close if move > 0 else later.close - candle.close
        if 3 * back >= 2 * abs(move):
            return True
    return False


def _own_rules(candles: Sequence[Candle], volumes: Sequence[float]) -> list[str]:
    averages = previous_atr(candles)
    flags: list[str] = []
    for index, candle in enumerate(candles):
        letters = ""
        average = averages[index]
        if average is not None and candle.high - candle.low > RANGE_MULTIPLE * average:
            letters += "a"
        if _volume_spike(volumes, index):
            letters += "b"
        if average is not None and _reversal(candles, index, average):
            letters += "c"
        flags.append(letters)
    return flags


def _wide(candles: Sequence[Candle]) -> dict[datetime, int]:
    """Boyu `3·ATR`'yi aşan mumların açılış anı → konum."""
    averages = previous_atr(candles)
    return {
        candle.open_time: index
        for index, (candle, average) in enumerate(zip(candles, averages, strict=True))
        if average is not None and candle.high - candle.low > SHARED_MULTIPLE * average
    }


def unusual_flags(
    candles: Mapping[str, Sequence[Candle]], volumes: Mapping[str, Sequence[float]]
) -> dict[str, Flags]:
    """Çift → mum başına kural harfleri (`"ad"` gibi, alfabe sırasıyla)."""
    flags = {pair: _own_rules(series, volumes[pair]) for pair, series in candles.items()}
    wide = {pair: _wide(series) for pair, series in candles.items()}
    moments: dict[datetime, list[str]] = {}
    for pair, found in wide.items():
        for moment in found:
            moments.setdefault(moment, []).append(pair)
    for moment, pairs in moments.items():
        if len(pairs) >= SHARED_PAIRS:
            for pair in pairs:
                flags[pair][wide[pair][moment]] += "d"
    return {pair: tuple(letters) for pair, letters in flags.items()}
