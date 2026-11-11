# Architecture

## System overview
CrytoBot, tek kullanıcılı, tek süreçli bir **Python 3.12 modüler monolit**tir. Piyasa verisi, haberler
ve whitepaper'lardan sinyaller üretir; `strategy` bunları işlem önerisine çevirir; `risk` her öneriyi
iş kurallarına (BR-n, `docs/domain.md`) göre onaylar ya da reddeder; yalnızca `execution` onaylı emri
borsaya gönderir. Aynı strateji kodu backtest, paper ve live modda çalışır — fark yalnızca `execution`
adaptöründedir. Seçim gerekçesi: kişisel bot için mikroservis operasyon yükü gereksiz; Python, ccxt /
pandas / LLM ekosisteminin en olgun olduğu dil. Kalıcı veri SQLite'ta, repository katmanı arkasında.
Kullanıcı arayüzü: CLI + Telegram (bildirim ve yetkili komutlar).

**Borsa şartlı stop emri yaşam döngüsü (live, spec 0034):** Canlı modda bir alım dolunca borsaya tekil kimlikli (`cs-<alım id>`) şartlı piyasa stop emri verilir. Kapanıştan önce borsa stopunun iptali teyit edilir; tur başında bakiye mutabakatı öncesinde borsada dolmuş stop senkronize edilir. Koruma her canlı turda durumdan türer: borsada hiç olmayan stop yeniden verilir; iptal edilmiş, reddedilmiş, durumu belirsiz ya da kısmen dolmuş stop yeni alımı durdurur (fail-closed, `BuyHalt.STOP_ORDER_FAILED`) ve pozisyona özgü `STOP_ORDER_FAILED` bildirimi üretir (güvenli mod `SAFE_MODE` bildiriminden ayrı).

## Modules / components and ownership

| Module | Single responsibility | Owns |
|---|---|---|
| `market_data` | Mum, fiyat, emir defteri verisini borsadan çekmek ve saklamak | OHLCV geçmişi, ticker anlık görüntüleri, geçmiş veri dosyası (backtest girdisi, spec 0023) |
| `news` | Haber/duyuru kaynaklarını takip edip haber skoru üretmek | Haber kayıtları, haber skorları |
| `research` | Whitepaper/proje dokümanlarını okuyup kaynak alıntılı araştırma skoru üretmek | Doküman önbelleği, araştırma skorları |
| `llm` | Claude API'ye tek erişim noktası: şema doğrulama, harcama limiti | LLM çağrı günlüğü, günlük harcama |
| `analysis` | Teknik analiz ve indikatör hesapları (saf fonksiyonlar) | — (durumsuz) |
| `strategy` | Sinyalleri birleştirip işlem önerisi (yön, giriş, stop, hedef) üretmek | Strateji konfigürasyonu |
| `risk` | Her işlem önerisini BR-3…BR-11'e göre onaylamak/reddetmek, pozisyon boyutlamak | Risk limitleri, sabit üst sınırlar, kill switch durumu |
| `execution` | Onaylı emirleri borsaya (live) / simülatöre (paper, backtest) iletmek, emir durumunu izlemek | Emir kayıtları, clientOrderId'ler |
| `portfolio` | Pozisyonlar, bakiye mutabakatı, kâr/zarar defteri | Defter (append-only), pozisyonlar, kasa geçmişi |
| `backtest` | Geçmiş veri üzerinde strateji+risk+simüle execution koşturmak | Backtest sonuçları: metrikler, rapor metni ve rapor dosyası (spec 0025) |
| `control` | CLI ve Telegram komutları, yetkilendirme (chat ID, TOTP, teyit), audit log | Audit log, mod/aşama durumu |
| `reporting` | Günlük rapor, metrikler (günlük hedef dahil), bildirim gönderimi | Rapor kayıtları |
| `persistence` | Defter, emirler ve risk durumunu tek SQLite deposunda korumak; okunamayan depoda durumu reddetmek | Depo dosyası, biçim sürümü, depo modu |
| `dashboard` | Localhost'ta salt-okunur web panosu sunmak (HTML ve /api/status) | Pano şablonu, sunucu yaşam döngüsü, host doğrulama |
| `app` | Bileşim kökü (composition root): modülleri bağlar, ayarları denetler, zamanlayıcı/döngü | — (depo hazırlığı ve başlatma kapıları; gerçek etkiler enjekte edilir) |

**Giriş noktası.** `src/crytobot/__main__.py` (`python -m crytobot prepare|start|download|backtest|status|kill-switch|resume|stop|dashboard`, spec 0022, 0023, 0025, 0030, 0031) bir modül
değildir, paket olmadığı için tabloda yer almaz. Karar içermez: ayar dosyasını (`crytobot.toml`) okur,
gerçek saati, ≤1 s'lik beklemeyi, sinyalleri, tek süreç kilidini (`<depo>.lock`), konsol ve kayıt
dosyası yazıcısını ve piyasa okumasını `app`'e verir. Kararların, zamanlamanın ve depo kapılarının
hepsi `app`'tedir; `app` saat çağırmaz ve okuma işlevini import etmez, yalnız kendisine verileni çağırır.
`download` (spec 0023) aynı ayar dosyasının `[history]` bölümüyle geçmiş veriyi indirir: giriş noktası
`market_data`'nın indirme işlevini ve gerçek saati `app`'e verir; kilit alınmaz, depo ve kayıt dosyası
açılmaz, çıktı yalnız konsoladır.
`backtest` (spec 0025) aynı ayar dosyasının `[backtest]` bölümüyle koşar: giriş noktası veri
dosyası okumasını (`market_data`), rapor dosyası yazıcısını (`backtest`), konsolu, durdurma
isteğini, geçici bir dizindeki depo yolunu ve gerçek saati `app`'e verir; saat yalnız rapor
başlığındaki üretim anı için okunur (spec 0040), turlar simüle saatle; ağa çıkılmaz, kilit
alınmaz, bot deposu ve kayıt dosyası açılmaz. Turları `app` atar (paper turunun aynısı, simüle
saatle); `backtest` tur kayıtlarından metrikleri ve raporu üretir.

## Communication rules
- Modüller birbirini yalnızca **public arayüz** (`<module>/__init__.py` ile dışa açılanlar) üzerinden çağırır.
- Emir akışı tek yönlüdür: `strategy → risk → execution`. Başka hiçbir yol emir oluşturamaz.
- Sinyal üreticileri (`analysis`, `news`, `research`) yalnızca veri/skor döndürür; yan etkileri kendi depolarıyla sınırlıdır.
- Bildirimler `reporting` üzerinden gider; modüller doğrudan Telegram'a yazmaz.
- Bağımlılıkları yalnızca `app` bağlar (dependency injection); modüller global durum kullanmaz.

## Forbidden dependencies (make them testable)
`import-linter` sözleşmeleri olarak `scripts/check` içinde doğrulanır:
- `ccxt` yalnızca `execution` ve `market_data` tarafından import edilir.
- `anthropic` SDK yalnızca `llm` tarafından import edilir; `news`/`research` LLM'e yalnızca `llm` üzerinden erişir.
- `strategy`, `analysis`, `news`, `research`, `llm` hiçbir zaman `execution`'ı import etmez.
- `execution`'ı yalnızca `risk`, `app`, `backtest` ve `persistence` import eder.
- `persistence`'ı yalnızca `app` import eder; `persistence` diğer modüllerin yalnız public arayüzünü kullanır (ADR 0001).
- Giriş noktası (`crytobot.__main__`) `execution`'ı ve `persistence`'ı import etmez: paper simülatörü ve depo yalnız `app`'in kapılarından geçer (spec 0022).
- `analysis` hiçbir proje modülünü ve hiçbir I/O kütüphanesini import etmez (saf hesap).
- `dashboard` hiçbir zaman `control` ve `execution`'ı import etmez (ADR 0002, spec 0031).
- `backtest` `app`'i ve `market_data`'yı import etmez: koşuyu `app` yapar, veri dosyasını giriş noktası okutur; `backtest` yalnız tur kayıtlarından metrik ve rapor üretir (spec 0025). `ccxt` kuralı onu da kapsar.
- Hiçbir modül başka bir modülün iç alt modülünü (`<module>._*` / `<module>.internal`) import etmez.
- Telegram kütüphanesi yalnızca `control` ve `reporting` tarafından import edilir.

## Deliberately out of scope
- Vadeli işlem, kaldıraç, short, margin.
- Para çekme / transfer.
- Çok kullanıcı, SaaS, başkalarının fonunu yönetme.
- Kontrol komutlu ya da localhost dışından açılan web arayüzü. Salt okunur, localhost pano Faz 2'dedir (ADR 0002).
- Scalping / yüksek frekanslı işlem.
- Günlük kâr hedefini zorlayan herhangi bir mekanizma (BR-1).
