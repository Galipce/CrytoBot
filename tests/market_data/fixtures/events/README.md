# Kayıtlı herkese açık geçmiş veri arşivi yanıtları (spec 0048 AC-9)

Kaynak: Binance'in herkese açık geçmiş veri arşivi, `https://data.binance.vision/data/spot/monthly/klines`,
anahtarsız. Kayıt tarihi: 2026-11-15 (UTC). `curl` ile genel bir istemci adıyla alındı; `check` bunları
yalnız dosyadan okur, ağa çıkmaz.

| Dosya | İstek | Düzenleme |
|---|---|---|
| `vision_bnxusdt_1h_2023-01.zip` | `GET …/BNXUSDT/1h/BNXUSDT-1h-2023-01.zip` (HTTP 200, `application/zip`) | Yalnız ilk 48 satır bırakıldı (kısaltılmış), aynı adlı tek CSV ile yeniden sıkıştırıldı. Açılış damgaları **milisaniye**. Satırlar değiştirilmedi. |
| `vision_btcusdt_1h_2025-02.zip` | `GET …/BTCUSDT/1h/BTCUSDT-1h-2025-02.zip` (HTTP 200, `application/zip`) | Aynı biçimde ilk 48 satır. Açılış damgaları **mikrosaniye** (arşiv 2025'ten beri). |
| `vision_404.xml` | `GET …/NOPEUSDT/1h/NOPEUSDT-1h-2023-01.zip` (HTTP 404, `application/xml`) | Yok |

Genel piyasa verisinin kayıtlı yanıtları (borsa bilgisi `TRADING`, `BREAK` ve USDT dışı çiftlerle,
mum sayfası, -1121 "Invalid symbol") 0017'nin kayıtlarıdır: `../README.md`.
