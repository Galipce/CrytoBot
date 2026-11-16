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
| `market_data` | Mum, fiyat, emir defteri verisini borsadan çekmek ve saklamak | OHLCV geçmişi, ticker anlık görüntüleri, geçmiş veri dosyası (backtest girdisi, spec 0023); dönem boşlukları ve dönemde mum denetimi — saf, indirme özetinin `boşluk=` kuralıyla (spec 0044); olay fiyatları (spec 0048): genel piyasa verisinden, vermezse herkese açık geçmiş veri arşivinden (`data.binance.vision`) indirme adımı ve kendi SQLite deposu (borsa bilgisi anlık görüntüsü, 1h mumlar, indirilmiş aralıklar, koşu süresi) |
| `news` | Haber/duyuru kaynaklarını takip edip haber skoru üretmek; spec 0046: ayardaki kaynaklardan (Binance duyuruları, RSS 2.0, Atom) ileriye dönük toplama — tur ve döngü kararları, HTTPS getirme sınırları, ayrıştırma, kesinti bildirimi kararı; spec 0047: geçmiş Binance duyuru arşivi — katalog keşfi, sayfalama, sürdürme, durma kuralı, istek aralığı; spec 0048: duyuru başlığının sabit etiket kuralları (olay türü, beklenen yön, coinler; kural seti parmak izi) ve örnek kütüphanesinin kaynaklarını (arşiv + ileriye dönük `binance-duyuru` kayıtları) yalnız okuyup kimliğe göre birleştirme | Haber kaydı (kendi SQLite deposu: yalnız eklenen haberler — kaynak, kimlik ya da bağlantı, yayın anı, ilk görme anı — ve kaynak durumu), arşiv (ayrı SQLite deposu: yalnız eklenen, "arşivden" işaretli geçmiş duyurular — katalog, kimlik, yayın anı, arşive alınma anı, ilk görme anı yok — ve katalog durumu), haber ayarı (`crytobot-news.toml`), haber skorları |
| `research` | Whitepaper/proje dokümanlarını okuyup kaynak alıntılı araştırma skoru üretmek | Doküman önbelleği, araştırma skorları |
| `llm` | Claude API'ye tek erişim noktası: şema doğrulama, harcama limiti | LLM çağrı günlüğü, günlük harcama |
| `analysis` | Teknik analiz ve indikatör hesapları (saf fonksiyonlar) | — (durumsuz); spec 0045: stochastic, ADX/DI, Supertrend, Donchian |
| `calibration` | İndikatör sinyallerinin isabet ölçümü ve kalibrasyonu (saf): sekiz indikatörün sabit "al"/"sat" kuralları ve ızgaraları, isabet kuralı ve taban oran, olağandışı mumlar, BTC'de ayarlama, çapraz sınama, görülmemiş dönemde hüküm (spec 0045); geçmiş olay örnekleri (spec 0048): duyuru × coin örnekleri, giriş mumu, 0045'in isabet kuralıyla isabet ve taban oran, ölçülemeyen nedenleri, model kesim dönemi, çakışma, betimleyici kalibrasyon tablosu | Ayar seti metni (kanonik JSON, parmak izi), kalibrasyon raporu metni, sinyal kayıtları metni (JSON Lines); olay kalibrasyon tablosu ve örnek kütüphanesi metni (JSON Lines); dosyaları giriş noktası yazar |
| `strategy` | Sinyalleri birleştirip işlem önerisi (yön, giriş, stop, hedef) üretmek; sabit aday kümesi S0…S3, ayarın tipi adayı seçer (spec 0043) | Strateji konfigürasyonu |
| `risk` | Her işlem önerisini BR-3…BR-11'e göre onaylamak/reddetmek, pozisyon boyutlamak | Risk limitleri, sabit üst sınırlar, kill switch durumu |
| `execution` | Onaylı emirleri borsaya (live) / simülatöre (paper, backtest) iletmek, emir durumunu izlemek | Emir kayıtları, clientOrderId'ler |
| `portfolio` | Pozisyonlar, bakiye mutabakatı, kâr/zarar defteri | Defter (append-only), pozisyonlar, kasa geçmişi |
| `backtest` | Geçmiş veri üzerinde strateji+risk+simüle execution koşturmak | Backtest sonuçları: metrikler, rapor metni ve rapor dosyası (spec 0025); değerlendirme kuralı — örneklem içi seçim, sabit eşikli hüküm, paper adayı — ve son değerlendirme raporu (spec 0042); son değerlendirmenin sabit R-3 ızgarası (`app/_grid.py`) ve iki aralığı 1h, 4h (spec 0043); son değerlendirme raporunda aralık başına veri bölümü — dönem, saklı dönemin son mumu, boşluklar (spec 0044; boşlukları `app` `market_data`'dan alıp verir) |
| `control` | CLI ve Telegram komutları, yetkilendirme (chat ID, TOTP, teyit), audit log | Audit log, mod/aşama durumu |
| `reporting` | Günlük rapor, metrikler (günlük hedef dahil), bildirim gönderimi | Rapor kayıtları |
| `persistence` | Defter, emirler ve risk durumunu tek SQLite deposunda korumak; okunamayan depoda durumu reddetmek | Depo dosyası, biçim sürümü, depo modu |
| `dashboard` | Localhost'ta salt-okunur web panosu sunmak (HTML ve /api/status) | Pano şablonu, sunucu yaşam döngüsü, host doğrulama |
| `app` | Bileşim kökü (composition root): modülleri bağlar, ayarları denetler, zamanlayıcı/döngü | — (depo hazırlığı ve başlatma kapıları; gerçek etkiler enjekte edilir) |

**Giriş noktası.** `src/crytobot/__main__.py` (`python -m crytobot prepare|start|download|backtest|calibrate|status|kill-switch|resume|stop|dashboard|news|events`, spec 0022, 0023, 0025, 0030, 0031, 0045, 0046, 0047, 0048) bir modül
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
saatle); `backtest` tur kayıtlarından metrikleri ve raporu üretir. Spec 0042: varsayılan koşu
yalnız örneklem içi turları atar; `backtest --final` `app`'te `run_evaluation` ile adayları aynı
koşullarla örneklem içinde koşar, seçileni tam döneme açar ve `backtest`'in saf kuralıyla
(`select_combination`, `verdict`, `paper_candidate`) tek son değerlendirme raporu yazar.
`calibrate` (spec 0045) aynı ayar dosyasının `[calibration]` bölümüyle koşar: giriş noktası beş veri
dosyasının okumasını (`market_data`), dosya parmak izini, ayar seti baytlarını, üzerine yazmayan
dosya yazıcısını (`backtest`'in rapor yazıcısı), konsolu, durdurma isteğini ve gerçek saati `app`'e
verir. `app` veriyi denetler (aralık, sürüm 2 hacmi, çiftler, dönemlerde mum), `calibration`'ın saf
ölçümünü koşar ve çıktıları yazdırır; `calibrate --final` yalnız onaylı ayar setiyle (parmak izi,
onaylayan, onay anı) koşar. Ağa çıkılmaz, kilit alınmaz, bot deposu, kayıt dosyası ve botun işlem
davranışı değişmez.
`news` (spec 0046) haber toplayıcısıdır ve `app` dışında koşar (işlem döngüsüyle hiçbir şey
paylaşmaz): ayarı ayrı dosyadan (`crytobot-news.toml`) okunur; giriş noktası gerçek saati, ≤1 s'lik
beklemeyi, sinyalleri, haber kaydının mutlak yolunun kilidini (bot kilidinden ayrı), konsol ve haberin
kendi kayıt dosyasını, HTTPS getirmeyi ve `reporting`'in gönderimini `news`'e (`run_collection`)
verir. Bot ayarından yalnız `[bot]` yolları (karşılaştırma için) ve `[reporting.telegram]` okunur;
bot deposu açılmaz. `news status` ağa çıkmaz, kilit almaz.
`news archive` (spec 0047) aynı biçimde `app` dışında koşar: ayarı aynı dosyanın `archive_` anahtarlarıdır;
giriş noktası gerçek ve monoton saati, ≤1 s'lik beklemeyi, sinyalleri, arşiv deposunun mutlak yolunun kilidini
(toplayıcının ve botun kilidinden ayrı), arşivin kendi kayıt dosyasını ve HTTPS getirmeyi `news`'e
(`run_archive`) verir. Telegram bağlanmaz; bot deposu ve ileriye dönük haber kaydı açılmaz. `news archive
status` ağa çıkmaz, kilit almaz, arşivi ve ileriye dönük kaydı yalnız okur (örtüşme sayısı).
`events download` ve `events measure` (spec 0048) ayarı ayrı dosyadan (`crytobot-events.toml`) okur; kaynak
kayıtların yolları haber ayarından, bot yolları bot ayarından yalnız karşılaştırma için okunur. Giriş noktası kaynak
kayıtları `news`'le (`read_library_sources`: okuma ve etiket) okutur ve `calibration`'ın tipine çevirir — `app`
`news`'i import etmez. `app` (`run_events_download`, `run_events_measure`) örnekleri ve fiyat aralıklarını
`calibration`'dan alır, indirmeyi `market_data`'nın adımına (`download_event_prices`; borsa, arşiv, monoton saat,
bekleme ve durdurma giriş noktasından) verir, ölçümde fiyat deposunu ağsız okutur, `calibration`'ın saf ölçümünü
koşar ve üzerine yazmayan yazıcıyla (`backtest`'in rapor yazıcısı) kütüphaneyi ve raporu yazdırır. Fiyat deposunun
mutlak yolu kilitlenir (iki komuta tek). Bot deposu, kayıt dosyası, çalışan ayarlar ve kaynak kayıtlar değişmez.

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
- `calibration` `analysis` dışında hiçbir proje modülünü import etmez; dosya, saat ve ağ kullanmaz. Yalnız `app` onu bağlar (spec 0045, R-3h).
- `dashboard` hiçbir zaman `control` ve `execution`'ı import etmez (ADR 0002, spec 0031).
- `news` ticaret modüllerini (`app`, `persistence`, `execution`, `portfolio`, `risk`, `strategy`, `backtest`,
  `control`, `dashboard`, `market_data`) import etmez: haber toplama `app` dışında koşar, gerçek etkilerini giriş
  noktası verir (spec 0046, R-3i).
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
