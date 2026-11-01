# Domain

> Bootstrap: 2026-10-29. Ortak dil — kodda, spec'lerde ve sohbette aynı kelime aynı anlama gelir.

## Ubiquitous language

| Term | Meaning | Notes / not to be confused with |
|---|---|---|
| Kasa (equity) | Hesaptaki toplam değer: USDT bakiyesi + açık pozisyonların piyasa değeri | Serbest bakiye değil |
| Serbest bakiye | Yeni emir için kullanılabilir USDT | Kasa değil |
| Çift (pair) | `BASE/USDT` sembolü, ör. `BTC/USDT` | Yalnızca beyaz listedekiler işlem görür |
| Beyaz liste | Config'teki, işlem yapılabilir likit USDT çiftleri (ilk 20–30) | Değişikliği insan onaylar |
| Sinyal | Bir kaynağın (teknik, haber, whitepaper) ürettiği yön + güç skoru | Emir değil |
| Araştırma skoru | `research`'ün whitepaper/proje için ürettiği, kaynak alıntılı, şemalı skor | Asla doğrudan emir üretmez |
| Haber skoru | `news`'in bir haber için ürettiği etki/yön skoru | Güvenilmeyen girdiden türetilir |
| İşlem önerisi (trade intent) | `strategy`'nin sinyallerden ürettiği "şunu, şu stop ile al/sat" önerisi | Risk onayı olmadan emir değildir |
| Onaylı emir | `risk`'in onayladığı, hassasiyete yuvarlanmış emir | Yalnızca `execution` gönderir |
| Stop-loss | Pozisyonun zararla kapanacağı fiyat | Her pozisyonda zorunlu |
| İşlem riski | Stop'a gelinirse kaybedilecek tutar ÷ kasa | Pozisyon büyüklüğü değil |
| Günlük zarar limiti | Gün içinde (UTC) gerçekleşen + açık zarar ÷ gün başı kasa | Aşılınca o gün yeni işlem yok |
| Drawdown | Kasanın en yüksek değerden düşüşü (%) | Limit aşılınca bot durur, insan açar |
| Efektif maliyet | Komisyon + spread + tahmini slippage | Yalnızca komisyon değil |
| Mod | `backtest` · `paper` · `live` — aynı strateji kodu, farklı `execution` adaptörü | Varsayılan `paper` |
| Aşama (stage) | backtest → paper → live (küçük sermaye) → live; her geçiş insan onaylı | |
| Kill switch | Tüm yeni işlemleri durduran acil anahtar | CLI veya Telegram |
| Günlük hedef | Günlük kâr % (hedef %20–25) — **ölçülen metrik, karar kuralı değil** | Bkz. BR-1 |

## Business rules

- BR-1: Günlük kâr hedefi yalnızca raporlanan bir metriktir. Hedefe ulaşılmaması pozisyon büyüklüğünü, kaldıracı veya işlem sıklığını **asla** artırmaz. Opsiyonel: hedefe ulaşılınca gün kapatılabilir (config).
- BR-2: Yalnızca spot, kaldıraçsız işlem; yalnızca beyaz listedeki USDT çiftleri.
- BR-3: Her pozisyon açılırken bir stop-loss taşır; stop'suz işlem önerisi reddedilir.
- BR-4: İşlem başına risk ≤ %1 kasa (config; kodda sabit üst sınır %2).
- BR-5: Günlük zarar limiti %3 (config; sabit üst sınır %5). Aşılınca o UTC günü yeni pozisyon açılmaz.
- BR-6: Drawdown %15 (config; sabit üst sınır %25). Aşılınca bot tüm yeni işlemleri durdurur; yalnızca insan yeniden başlatır.
- BR-7: Aynı anda en fazla 5 açık pozisyon (config; sabit üst sınır 8).
- BR-8: Beklenen kâr, efektif maliyetin (komisyon + spread + slippage) config'teki katını geçmiyorsa işlem açılmaz (varsayılan kat 2; sabit alt sınır 1).
- BR-9: Her işlem önerisi `risk` onayından geçer; onaysız hiçbir emir borsaya gitmez.
- BR-10: Aşama geçişi (backtest→paper→live) metrik eşiği + insan onayı ister; strateji paper'a ancak komisyon/slippage dahil out-of-sample backtest sonucu ile geçer.
- BR-11: Durum belirsizse (emir durumu bilinmiyor, bakiye mutabakatı tutmuyor, veri bayat) bot yeni işlem açmaz, güvenli tarafa geçer ve bildirim gönderir.
- BR-12: Borsa seçimi efektif maliyet ölçümüyle yapılır; ücretler config'te tutulur, kodda değil.
- BR-13: Risk limitleri Telegram'dan yalnızca sıkılaştırılabilir; gevşetme yalnızca CLI'den yapılır (oran ve pozisyon limitlerinde sıkılaştırmak düşürmek, kâr/maliyet katında yükseltmektir).

## Key domain invariants

- Hiçbir kod yolu kodda sabitlenmiş risk üst sınırlarını aşamaz (config ne derse desin).
- LLM çıktısı (haber/whitepaper) hiçbir zaman doğrudan emir, limit veya mod değişikliği tetiklemez.
- Strateji kodu backtest, paper ve live'da aynıdır; yalnızca `execution` adaptörü değişir.
- Defter (ledger) kayıtları silinmez/değiştirilmez; düzeltme yeni kayıtla yapılır.
- Para çekme (withdrawal) hiçbir kod yolunda yoktur.

## Sensitive areas

- **Emir gönderimi** (`execution`) — yanlış emir = doğrudan para kaybı.
- **Risk limitleri** (`risk`) — limit hatası = kontrolsüz kayıp.
- **API anahtarları / sırlar** — sızıntı = hesap ele geçirme.
- **Paper ↔ live mod anahtarı** — yanlış mod = sanal sanılan gerçek işlem.
- **Telegram komut yetkilendirmesi** (chat ID, TOTP, teyit) — yetkisiz kontrol.
- **Portföy / defter** (`portfolio`) — yanlış bakiye/kâr-zarar = yanlış risk hesabı.
