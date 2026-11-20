"""Spec 0059 AC-2: özet yalnız kapanmış mumlardan; alanlar; eksik ya da bayat coin `veri yok`."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from crytobot.analysis import Candle
from crytobot.decide import EventNote, summarize
from tests.decide.helpers import BOUNDARY, HOUR, coin_data


def test_summary_fields() -> None:
    event = EventNote(BOUNDARY - timedelta(hours=3), "listeye alma", "olumlu", 2)
    summary = summarize(coin_data("SOL", events=(event,)), BOUNDARY)
    assert summary is not None
    text = summary.text
    for field in (
        "## SOL",
        "son_kapanış:",
        "değişim_24s:",
        "değişim_7g:",
        "ema20:",
        "ema50:",
        "ema200:",
        "rsi14:",
        "atr14:",
        "48x1h_en_yüksek:",
        "48x1h_en_düşük:",
        "son 48:",
        "son 30:",
        "2026-11-20T07:00Z listeye alma olumlu/2",
    ):
        assert field in text, field
    rows = text.split("\n")
    h1_start = rows.index(next(r for r in rows if r.startswith("1h mumlar")))
    h4_start = rows.index(next(r for r in rows if r.startswith("4h mumlar")))
    assert h4_start - h1_start - 1 == 48
    assert rows[h4_start - 1].startswith("2026-11-20T09:00Z")  # last closed 1h candle
    assert summary.low < summary.last_close < summary.high


def test_only_closed_candles() -> None:
    data = coin_data("ETH")
    open_candle = Candle(BOUNDARY, 1e9, 1e9, 1e9, 1e9)  # opened at the boundary: not closed
    with_open = replace(data, h1=(*data.h1, open_candle), h4=(*data.h4, open_candle))
    assert summarize(with_open, BOUNDARY) == summarize(data, BOUNDARY)
    summary = summarize(with_open, BOUNDARY)
    assert summary is not None and "1000000000" not in summary.text


def test_missing_or_stale_coin_no_data() -> None:
    assert summarize(coin_data("ADA", h1=150), BOUNDARY) is None  # too few for EMA 200
    assert summarize(coin_data("ADA", h4=20), BOUNDARY) is None
    stale = coin_data("ADA", boundary=BOUNDARY - HOUR)  # last 1h candle is an hour old
    assert summarize(stale, BOUNDARY) is None


def test_no_events_said() -> None:
    summary = summarize(coin_data("BTC"), BOUNDARY)
    assert summary is not None
    assert summary.text.endswith("olay skorları (son 24 saat):\nyok")


def test_prices_rounded_to_tick() -> None:
    summary = summarize(coin_data("DOGE", base=0.123456789, tick=Decimal("0.00001")), BOUNDARY)
    assert summary is not None
    close = next(r for r in summary.text.split("\n") if r.startswith("son_kapanış"))
    assert len(close.split()[1].split(".")[1]) == 5
    untick = summarize(coin_data("DOGE", base=0.123456789, tick=None), BOUNDARY)
    assert untick is not None and "fiyat_adımı: -" in untick.text
