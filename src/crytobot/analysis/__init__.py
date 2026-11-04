"""Teknik analiz ve indikatör hesapları (saf fonksiyonlar).

Her indikatör bir mum serisi (`Candle`, zamana göre artan) ve açıkça verilen parametreler alır;
sonucu girdiyle aynı uzunluktadır, yeterli geçmişi olmayan konum `None` ("değer yok") taşır.
Geçersiz veri ya da parametre adı konmuş hatayla reddedilir, kısmi sonuç dönmez. Yalnız sayı döner:
"al/sat" yorumu `strategy`'nin, varsayılan periyotlar da onundur. Saat, ağ, depo ve global durum
kullanmaz; değerler `float`'tır, `Decimal`'e çevirme `strategy → risk` sınırının işidir.
"""

from crytobot.analysis._candles import (
    AnalysisError,
    Candle,
    CandleProblem,
    InvalidCandleError,
    InvalidParameterError,
    NonFiniteResultError,
    ParameterProblem,
)
from crytobot.analysis._indicators import (
    BollingerSeries,
    MacdSeries,
    atr,
    bollinger,
    ema,
    macd,
    rsi,
    sma,
)

__all__ = [
    "AnalysisError",
    "BollingerSeries",
    "Candle",
    "CandleProblem",
    "InvalidCandleError",
    "InvalidParameterError",
    "MacdSeries",
    "NonFiniteResultError",
    "ParameterProblem",
    "atr",
    "bollinger",
    "ema",
    "macd",
    "rsi",
    "sma",
]
