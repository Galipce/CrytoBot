# Kayıtlı Binance yanıtları (spec 0017 AC-11)

Kaynak: Binance spot herkese açık REST API, `https://api.binance.com/api/v3`, anahtarsız.
Kayıt tarihi: 2026-11-05 (UTC). `curl` ile alındı, `check` bunları yalnız dosyadan okur.

| Dosya | İstek | Düzenleme |
|---|---|---|
| `exchange_info.json` | `GET /exchangeInfo` | Yalnız `BTCUSDT`, `ETHUSDT`, `ETHBTC` (USDT değil), `EOSUSDT` (`BREAK`), `BTCUPUSDT` (`isSpotTradingAllowed: false`) bırakıldı; `rateLimits` ve `exchangeFilters` silindi. Kalan alanlar değiştirilmedi. |
| `klines_btcusdt_1h.json`, `klines_ethusdt_1h.json` | `GET /klines?symbol=…&interval=1h&limit=3&endTime=1793879999999` | Yok |
| `ticker_btcusdt.json`, `ticker_ethusdt.json` | `GET /ticker/24hr?symbol=…` | Yok |
| `error_bad_symbol.json` | `GET /ticker/24hr?symbol=NOPEUSDT` (HTTP 400) | Yok |

Son kayıtlı mum `1793880000000` ms'de kapanır, ticker damgaları `1793880256008` ms civarındadır;
testlerin saati (`helpers.NOW`) bu ikisinden sonradır.
