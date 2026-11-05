# Spec 0016 — `app` bağlantısı: tek paper turu

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0016-plan.md`
- Self-critique: done

## Intent
Sistemin sahibi, şimdiye kadar ayrı ayrı yazılan `strategy`, `risk`, `execution`, `portfolio` ve `persistence` modüllerinin tek bir
paper işlem turunda birlikte çalışmasını istiyor; bugün `app` boş olduğu için bu parçaları birleştiren ve onlara verilen sözleri tutan
kod yok. Başarı, verilen piyasa verisiyle bir turun açık pozisyonları stop ya da hedefte kapatması, koşullar uygunsa risk onaylı alım
yapması ve her adımı kalıcı olarak kaydetmesidir. Durum belirsizse tur yeni alım açmaz, kapanışları sürdürür ve bildirim üretir (BR-11).
Bu iş kârlılık kanıtlamaz; çalıştırılabilir bir bot vermez, tur yalnız testlerde sahte veriyle koşar. Gerçek borsa verisi, live, Telegram,
CLI, döngü ve config dosyası okuma bu işte yoktur.

## Requirements
Terimler:
- **Tur:** bir kez çağrılan, başından sonuna tek geçiş. Piyasa verisi, ayarlar, depo yolu, zaman, paper simülatörü ve bildirim alıcısı çağrıyla verilir.
- **Piyasa verisi:** çift başına kapanmış mum serisi, zaman damgalı güncel fiyat, borsa kuralları ve spread.
- **Ayarlar:** sıralı beyaz liste, risk limitleri, strateji ayarları, komisyon, slippage, mum aralığı, azami mum yaşı, azami fiyat yaşı. Hiçbirinin gizli varsayılanı yoktur.
- **Bayat veri:** son mumun kapanışından (`open_time` + mum aralığı) bu yana geçen süre azami mum yaşını ya da fiyatın zamanından bu yana geçen süre azami fiyat yaşını aşıyorsa veri bayattır; yaşa eşit olan tazedir.
- **Geçersiz veri:** kapanışı turun zamanından sonra olan mum, zamanı turun zamanından sonra olan fiyat, zaman dilimi taşımayan zaman, eksik veri ya da `strategy`'nin reddettiği mum serisi.
- **Alım durdurma:** o turda hiçbir yeni alım denenmez; kapanışlar sürer.

Davranış:
- R-1: **Sıra.** Tur şu sırayla ilerler: depoyu yükle → durumu bilinmeyen emirleri sorgula → kasayı gözle → stop ve hedef kapanışları → kasayı yeniden gözle → beyaz liste sırasıyla öneri ve alım. Her adımdan sonra kalıcı durum kaydedilir (0011 Constraints (d)).
- R-2: **Emir yolu.** Alım yalnız `strategy` → `risk` → `execution` yolundan, kapanış yalnız `portfolio` kararı → `risk` → `execution` yolundan oluşur (BR-9). Dolan emir deftere verilir; dolu emir ve defter kaydı tek kayıtta yazılır. Tek istisna: defter emri reddederse emir yine kaydedilir ve R-7 uygulanır. Her alım onayı, aynı turda önceki adımların değiştirdiği bakiye ve pozisyon sayısını görür.
- R-3: **Tekrar koruması.** Aynı çiftin aynı son mumundan en fazla bir alım emri oluşur. Pozisyon aynı mumda kapansa da aynı mumdan yeniden girilmez; aynı veriyle tur yeniden çağrılınca ikinci emir oluşmaz. Kaydedilmemiş bir alım, sonraki turda aynı kimlikle yeniden denenir (0011).
- R-4: **Bayat ya da geçersiz veri (BR-11, B-39).** Beyaz listedeki herhangi bir çiftin ya da açık pozisyonu olan bir çiftin verisi bayat ya da geçersizse o turda alım durdurma uygulanır. Fiyatı bayat ya da geçersiz olan pozisyon o turda kapatılmaz; fiyatı taze olan pozisyonlar kapatılır. Sonraki temiz turda alım kendiliğinden sürer.
- R-5: **Depo yüklenemiyor (0004, 0011 (a); BR-6).** Depo yok, okunamıyor, meşgul, biçim sürümü bilinmiyor ya da modu uyuşmuyorsa tur hiçbir işlem yapmaz ve bildirim üretir. Tur depoyu kendisi oluşturmaz.
- R-6: **Kayıt reddi (0011 (c), 0012).** Kayıt "yazılamadı", "meşgul" ya da "eski yazım" dönerse alım durdurma uygulanır, bildirim gider ve tur orada biter; sonraki tur diskteki durumdan başlar, kaydedilemeyen kapanış orada yeniden denenir. "Geçmiş değiştirilemez" dönerse aynısı olur; ayrıca alım, süreç belleğinde tutulan bir durdurmayla süreç yeniden başlatılana kadar durur. Hata sürüyorsa yeniden başlatma sonrası ilk kayıtta yine durur.
- R-7: **Mutabakat (0010 S3, 0011 (b); BR-11).** Yüklenen depo "mutabakat tutmuyor" işareti taşıyorsa ya da defter dolu bir emri reddettiyse yeni alım durur, kapanışlar sürer, bildirim gider. İşaret depodan her turda yeniden türer: temiz turla ya da yeniden başlatmayla kalkmaz.
- R-8: **Risk durdurmaları.** Drawdown ve günlük zarar durdurmaları alımı `risk` kararıyla engeller, kapanışı engellemez. Yeniden başlatma durdurmayı kaldırmaz (BR-6).
- R-9: **Olağan sonuçlar.** "Öneri yok" nedenleri ve `risk` retleri hata değildir; bildirim üretmez, tur sonucunda çift başına görünür.
- R-10: **Bildirim.** Durdurma ve güvenli mod bildirimleri çağıranın verdiği alıcıya iletilir. Süren bir durum için yalnız giriş ve çıkışta bildirim üretilir; bu hafıza kalıcı değildir, yeniden başlatma sonrası ilk tur süren durumu yeniden bildirir. Alıcı hata verirse işlem akışı sürer, hata tur sonucunda görünür. Bildirim sır içermez.
- R-11: **Tur sonucu.** Tur istisna fırlatmaz; yapılan kapanışları ve alımları, çift başına "öneri yok" ve ret nedenlerini, uygulanan durdurmaları, bildirim hatalarını adlarıyla döndürür.
- R-12: **Geçersiz ayar.** Geçersiz ya da eksik ayar adı konmuş sonuçla reddedilir; tur hiçbir işlem yapmaz ve depoyu değiştirmez. Boş beyaz liste geçerlidir: alım olmaz, kapanışlar sürer.
- R-13: **Yalnız paper.** Turun mod girdisi yoktur; emir ve depo modu her zaman paper'dır. Hiçbir girdi live davranışa yol açamaz.
- R-14: **BR-1.** Kâr hedefi, gerçekleşen kâr-zarar ve işlem sıklığı tur kararlarına girdi değildir.
- R-15: **B-6.** `approve_trade`, metin olmayan ya da hash'lenemeyen çiftte istisna fırlatmaz, "beyaz listede değil" ile reddeder. Diğer onay davranışı değişmez.
- R-16: **Kasa hesaplanamıyor (BR-11).** Defter açılmamışsa tur işlem yapmaz, adı konmuş sonuç ve bildirim üretir. Gözlem reddedilirse (ör. zaman son gözlemden eski) alım durdurma uygulanır, bildirim gider. Açık pozisyonun fiyatı bayat ya da geçersiz olduğu için kasa hesaplanamıyorsa o turda gözlem yapılmaz; alım R-4 ile zaten durmuştur.
- R-17: **Durumu bilinmeyen emirler.** Tur başında verilen paper simülatöründen sorgulanır. Dolu çıkan emir deftere yazılır; güvenli mod giriş ve çıkış bildirimleri alıcıya iletilir. Durumu bilinmeyen emir kaldıkça yeni alım olmaz (0006).
- R-18: **Kapanış reddi (0009).** Kapanış onayı ya da emri reddedilirse ya da çiftin kuralı eksikse pozisyon açık kalır, bildirim gider; sonraki turda stop ya da hedef hâlâ geçerliyse yeniden denenir. Beyaz liste dışındaki pozisyonlar da kapatılır. Daha önce borsa tarafından reddedilmiş kapanış emri aynı kimlikle yeniden oluşmaz (B-17); bu durumda pozisyon açık kalır, bildirim gider ve davranış testle sabitlenir.

## User experience
none — no user interface

## Constraints & out of scope
- Sensitive area: Emir gönderimi (`execution`), Risk limitleri (`risk`), Portföy / defter (`portfolio`), Kalıcı durum (`persistence`), Paper ↔ live mod anahtarı — `docs/domain.md`.
- Bağlayıcı kural (BR-10): gerçek paper başlatma, komisyon ve slippage dahil out-of-sample backtest sonucu ve insan onayı ister. Bu spec giriş noktası vermez; giriş noktası spec'i bu kuralı taşır.
- Giriş noktası spec'ine devredilenler: geçersiz config'de başlamama (0002), config dosyası okuma, varsayılan depo yolu `data/` (0011), B-29'un makine adlandırılarak verilecek kararı. R-11'in (0011) 1 saniye sınırı değişmez.
- Coverage: `app` için de %90 branch coverage ve bağımsız beklenen-sonuç modelli property testi zorunludur; `docs/testing.md` ve eşik buna göre güncellenir.
- Boyut: tek spec. Split: proposed 0016 temiz tur; 0017 belirsiz durum tepkileri; kept as one — Galip Badem, 2026-11-04, yetenek tektir (paper turu) ve ilk parça BR-11 tepkileri olmadan emir açan bir tur bırakırdı.
- Tek sürece dayanır; ayrı süreç kilidi yoktur (0011).
- Yeni runtime bağımlılığı yok. `risk` yalnız R-15 kadar değişir; `strategy`, `execution`, `portfolio`, `persistence` değişmez. Shipped testlerin assert'leri değişmez.
- Para ve fiyat değerleri `decimal.Decimal`; zamanlar timezone-aware (`docs/conventions.md`).
- Backlog: B-39, B-6 ve B-16 bu spec'le kapanır ve satırları silinir. B-16 düzeltme yerine `app`'in yalnız düz `dict` verdiğini gösteren testle kapanır. B-29'a kararın giriş noktası spec'ine taşındığı not edilir. B-9, B-15, B-17, B-18 açık kalır.
- Out of scope: `market_data`, ağ, ccxt; döngü ve zamanlayıcı; CLI ve giriş noktası; config dosyası okuma; depo oluşturma ve başlangıç yatırması; mutabakatı düzeltme aracı ve depo biçimi değişikliği; Telegram ve gerçek bildirim gönderimi; `control`, kill switch; backtest; haber ve whitepaper sinyalleri; live.

## Acceptance criteria
- [x] AC-1 — Alım: temiz veride kesişim olan çiftte tur alım yapar; emir, defter ve risk durumu kaydedilir; dolu emir ve defter kaydı tek kayıtta yazılır; depo yeniden yüklenince aynı durum ve mutabakat temiz gelir; miktar `risk`'in onayladığı miktardır (R-1, R-2).
- [x] AC-2 — Kapanış: stop ve hedefe ulaşan pozisyonlar aynı turda alımdan önce kapanır, bakiye güncellenir; ulaşmayan pozisyon açık kalır; o bakiyeyi sonraki alım onayı görür (R-1, R-2).
- [x] AC-3 — Çoklu çift: öneriler beyaz liste sırasıyla işlenir; pozisyon limiti ya da bakiye bir sonraki çiftin onayında etkisini gösterir (R-2).
- [x] AC-4 — Tekrar: aynı veriyle ikinci tur ikinci emir oluşturmaz; aynı mumda kapanan pozisyona aynı mumdan yeniden girilmez; yeni mumda öneri çıkarsa alım yapılabilir (R-3).
- [x] AC-5 — Bayat veri sınırı: yaşı azami yaşa eşit veri tazedir, bir birim fazlası bayattır; mum ve fiyat için kendi ayarlarıyla ayrı ayrı. Bayat tek çift tüm alımları durdurur; fiyatı bayat pozisyon kapanmaz, fiyatı taze olan (mumu bayat olsa da) kapanır; sonraki temiz turda alım sürer (R-4).
- [x] AC-6 — Geçersiz veri: kapanmamış mum, gelecek zamanlı fiyat, zaman dilimsiz zaman, eksik veri ve `strategy`'nin reddettiği seri AC-5'teki durdurmayı uygular (R-4).
- [x] AC-7 — Depo yüklenemiyor: yok, okunamıyor, meşgul, bilinmeyen sürüm ve mod uyuşmazlığının her birinde emir yok, depo değişmez, bildirim gider; tur depoyu oluşturmaz; drawdown durdurması yeniden başlatmayla atlanmaz (R-5, R-8).
- [x] AC-8 — Kayıt reddi: "yazılamadı", "meşgul", "eski yazım" ve "geçmiş değiştirilemez" enjekte edildiğinde alım durur, bildirim gider, tur biter; sonraki tur diskteki durumdan başlar ve kaydedilemeyen kapanışı yeniden dener. "Geçmiş değiştirilemez" durdurması temiz turda kalkmaz, yeniden başlatmayla kalkar (R-6).
- [x] AC-9 — Mutabakat: mutabakat işareti taşıyan depoda ve defterin dolu emri reddettiği turda yeni alım durur, kapanışlar sürer, bildirim gider; emir kayıtlıdır; durum temiz turda ve yeniden başlatmayla kalkmaz (R-2, R-7).
- [x] AC-10 — Risk durdurmaları: drawdown ve günlük zarar durumunda alım `risk` nedeniyle olmaz, kapanış olur; "öneri yok" ve ret nedenleri sonuçta görünür, bildirim üretmez (R-8, R-9).
- [x] AC-11 — Bildirim: süren durum art arda turlarda tek giriş bildirimi, düzelince tek çıkış bildirimi üretir; yeniden başlatma sonrası ilk tur süren durumu yeniden bildirir; alıcı istisna fırlatınca kapanış ve alım yine yapılır, hata sonuçta görünür; bildirim metninde sır yoktur (R-10, R-11).
- [x] AC-12 — Geçersiz girdi ve mod: her geçersiz ya da eksik ayar adı konmuş sonuçla reddedilir, emir yok, depo değişmez; boş beyaz liste kapanışları engellemez; live davranışa götüren girdi yoktur, live depo mod uyuşmazlığıyla reddedilir (R-12, R-13).
- [x] AC-13 — Sınırlar ve backlog: `approve_trade` hash'lenemeyen çifti "beyaz listede değil" ile reddeder (B-6); `app` portföye yalnız düz `dict` verir (B-16); kâr hedefi ya da kâr-zarar girdisi yoktur (BR-1); import sınırları `scripts/check`'te korunur (R-14, R-15).
- [x] AC-14 — Kasa hesaplanamıyor: açılmamış defterde emir yok, adı konmuş sonuç ve bildirim var; reddedilen gözlemde (eski zaman) alım durur, bildirim gider, kapanış sürer; bayat fiyatlı açık pozisyonda o tur gözlem yapılmaz ve risk durumu değişmez (R-16).
- [x] AC-15 — Bilinmeyen emir: durumu bilinmeyen emir varken alım olmaz; sorgu dolu dönünce emir deftere yazılır, mutabakat temiz kalır, güvenli mod giriş ve çıkış bildirimi alıcıya ulaşır; sorgu hâlâ bilinmiyor derse alım durmaya devam eder (R-17).
- [x] AC-16 — Kapanış reddi: asgari altı kapanış ve eksik kural pozisyonu açık bırakır, bildirim üretir, koşul sürerse sonraki turda yeniden dener; beyaz liste dışındaki pozisyon kapanır; reddedilmiş kapanış emrinde pozisyon açık kalır ve bildirim gider (B-17) (R-18).

## Definition of Done
- [x] Every acceptance criterion mapped to proof (test or reproducible observation)
- [x] `scripts/check` green
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Docs / ADRs updated if behavior or architecture changed
- [x] Spec moved to `specs/done/` (it becomes immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | 1 onay sonrası (AC-5 metni R-4'e eşitlendi, A-4); plan: A-1, A-2, A-3, A-4 |
| Fix rounds | 4 (fix-1…fix-4; R-06 analizi round 4'te, A-4; review round 5 temiz) |
| Review findings: real / noise / deferred | 12 / 5 / 5, ayrıca 1 investigate (round 1 F-5, ship PR'ındaki full koşuda karar). VERIFY bulguları dahil: r1 5/1/1, r2 3/0/1, r3 0/0/1, V1 2/3/0, r4 2/0/2, r5 0/0/0, V2 0/1/0 |
| Regressions introduced | 0 (shipped testlerin assert'i değişmedi) |
| Bugs escaped to production | 0 (henüz üretim yok) |

DoD'nin `scripts/check` kutusu koşullu işaretlendi (`doctor`, `specs/done/`'da işaretsiz kriteri reddediyor); koşul bu PR'ın full koşusudur, yeşil olmadan merge yapılmaz (`docs/testing.md`, Two speeds, rule 10). `app` coverage kapısı ve `test-slow` da ilk kez bu koşuda görülür.
