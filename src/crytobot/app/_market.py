"""Okuma sonucunu tur girdisine çevirir (spec 0017 R-10; plan Risk 4, 13).

`analysis` mumları `float` ister, okuma `Decimal` verir. Değer `float`'ta birebir geri dönmüyorsa
o çiftin serisi eksik veridir: yuvarlanmış seriyle karar verilmez, tur alımı durdurur (BR-11).
`run_turn`'ün `now`'ı `read.read_at`'tir: okuma sırasında gelen damgalar ondan ileri olamaz.
"""

from decimal import Decimal

from crytobot.analysis import Candle
from crytobot.app._inputs import PairMarket
from crytobot.market_data import MarketCandle, MarketRead, MarketRules, PairRead
from crytobot.risk import PairRules


def _exact_float(value: Decimal) -> float | None:
    number = float(value)
    return number if Decimal(repr(number)) == value else None


def _candle(candle: MarketCandle) -> Candle | None:
    open_ = _exact_float(candle.open)
    high = _exact_float(candle.high)
    low = _exact_float(candle.low)
    close = _exact_float(candle.close)
    if open_ is None or high is None or low is None or close is None:
        return None
    return Candle(candle.open_time, open_, high, low, close)


def _series(candles: tuple[MarketCandle, ...] | None) -> tuple[Candle, ...] | None:
    if candles is None:
        return None
    series: list[Candle] = []
    for candle in candles:
        translated = _candle(candle)
        if translated is None:
            return None
        series.append(translated)
    return tuple(series)


def _rules(rules: MarketRules | None) -> PairRules | None:
    if rules is None:
        return None
    return PairRules(rules.amount_step, rules.min_amount, rules.min_notional)


def _pair_market(pair: PairRead) -> PairMarket:
    return PairMarket(
        _series(pair.candles),
        pair.price,
        pair.price_at,
        _rules(pair.rules),
        pair.tick,
        pair.spread,
    )


def to_turn_market(read: MarketRead) -> dict[str, PairMarket]:
    """Her çift için `PairMarket`; okumadaki eksik alan turda eksik veri olur (R-10).

    Reddedilen okumada sonuç boştur: tur her çifti eksik veri sayar.
    """
    return {pair.pair: _pair_market(pair) for pair in read.pairs}
