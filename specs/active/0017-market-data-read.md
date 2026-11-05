# Spec 0017 — `market_data`: gerçek piyasa verisini okuma

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0017-plan.md`
- Self-critique: done

## Intent
Sistemin sahibi, paper turunun testlerdeki sahte veri yerine gerçek borsa verisiyle beslenebilmesini istiyor; bugün `market_data` boş
olduğu için bot borsadan hiçbir şey okuyamıyor. Başarı, istenen her çift için kapanmış mumların, zaman damgalı güncel fiyatın, spread'in ve
borsa kurallarının turun beklediği biçimde gelmesidir. Veri alınamaz ya da güvenilmez olursa bu gizlenmez: alan "eksik" olarak ve adı konmuş
nedenle döner, tur da alımı durdurur (BR-11). Bu iş emir göndermez, API anahtarı kullanmaz, live açmaz, veri saklamaz ve çalıştırılabilir bot
vermez; kârlılık kanıtlamaz, BR-10'un backtest kapısını aşmaz.

## Requirements
Terimler:
- **Okuma:** bir kez çağrılan, verilen çift listesi için tek geçiş. Çift listesi, ayarlar ve saat çağrıyla verilir; listeyi çağıran belirler, okuma depoya bakmaz.
- **Güncel fiyat:** borsanın bildirdiği son işlem fiyatı. Yoksa fiyat eksiktir; alış ya da satış fiyatından türetilmez.
- **Spread oranı:** `(satış − alış) ÷ orta fiyat`; orta fiyat, en iyi alış ile en iyi satışın ortalamasıdır.
- **Ayarlar:** borsa adı, mum aralığı, mum sayısı (1 ile 1000 arası tam sayı), çağrı başına süre, okuma başına toplam süre bütçesi. Hiçbirinin gizli varsayılanı yoktur.
- **Eksik alan:** okunamayan ya da güvenilmeyen alan yok sayılır ve yanında adı konmuş bir neden taşır; yerine eski ya da tahmini değer konmaz.

Davranış:
- R-1: **Sonuç.** Okuma, istenen her çift için istek sırasıyla şu alanları döndürür: kapanmış mum serisi, güncel fiyat, fiyatın zamanı, spread oranı, fiyat adımı (tick) ve çift kuralları (miktar adımı, asgari miktar, asgari tutar).
- R-2: **Kapsam yalnız okuma.** Okuma yalnız herkese açık veriye erişir. API anahtarı yüklenmez, ortamda bulunsa bile kullanılmaz; emir ya da hesap işlemi yapılamaz.
- R-3: **Kısmi hata.** Bir çiftin ya da alanın okunamaması diğerlerini etkilemez. Okuma istisna fırlatmaz (BR-11). Örneğin mumları alınamayan çiftin fiyatı alınabildiyse fiyat döner; böylece o pozisyonun kapanışı 0016 R-4 uyarınca sürer.
- R-4: **Süre.** Tek çağrı kendi süresini, okuma toplam bütçesini aşamaz. Yeniden deneme yalnız geçici hatalarda (ağ, zaman aşımı, istek sınırı, borsanın geçici hatası) ve bütçe içinde yapılır; geçersiz sembol ve bozuk yanıt yeniden denenmez. Borsanın istek sınırına uyulur. Bütçe biterse kalan alanlar "süre bitti" nedeniyle eksik döner.
- R-5: **Kapanmamış mum.** Saate göre kapanışı (`open_time` + mum aralığı) henüz gelmemiş mumlar seriden sessizce çıkarılır; bu bir hata değildir. Kapanışı saate eşit olan mum kapanmıştır.
- R-6: **Boşluk.** Art arda iki mum arasında eksik aralık varsa yalnız son boşluktan sonraki mumlar döner ve boşluk adıyla raporlanır. Kısa seri tur tarafında o çift için "öneri yok" sonucunu verir, diğer çiftleri durdurmaz (0014, 0016).
- R-7: **Fiyat zamanı.** Fiyatın zamanı borsanın verdiği damgadır, UTC ve timezone-aware döner. Damga yoksa fiyat ve zamanı eksiktir; yerel saat damga diye yazılmaz. Damga saatin ilerisindeyse değer değiştirilmez, tolerans uygulanmaz, "saat kayması" adıyla raporlanır; hükmü 0016 R-4 verir.
- R-8: **Fiyat biçimi (B-43).** Çiftin fiyat adımından daha ince fiyat geçersizdir ve eksik döner.
- R-9: **Hassasiyet.** Fiyat, spread, tick ve kural değerleri `Decimal`'dir ve borsanın bildirdiği değerle birebir aynıdır; dönüşüm hatası taşımaz (`docs/conventions.md`).
- R-10: **Tur uyumu.** Okuma sonucu, `app`'in tur girdisine (`PairMarket`) kayıpsız çevrilir; eksik alan orada "eksik veri" olur. Çeviri `app`'tedir, `run_turn` davranışı değişmez.
- R-11: **Sır ve güvenilmeyen girdi.** Borsa yanıtı güvenilmeyen girdidir, sınırda doğrulanır. Neden adları ham yanıt metni taşımaz, sonuçta sır yoktur.
- R-12: **Spread sınırları.** Alış ya da satış yoksa, alış satıştan büyükse ya da oran 1'e eşit veya büyükse spread eksik döner. Alış satışa eşitse spread 0'dır.
- R-13: **Bozuk mum.** Yüksek < düşük, sıfır ya da negatif fiyat, sayı olmayan değer, tekrar eden ya da sırası bozuk zaman veya mum aralığına oturmayan zaman içeren yanıtta o çiftin mum serisinin tamamı adı konmuş nedenle eksik döner; onarım yapılmaz. Bedeli bilerek kabul edilir: tur o çift yüzünden alımı durdurur (BR-11, 0016 R-4).
- R-14: **Çift ve kural.** Borsada olmayan, spot olmayan, işleme kapalı ya da USDT çifti olmayan çiftte tüm alanlar adıyla eksik döner (BR-2). Kuraldaki bir değer bildirilmemişse o çiftin kuralları eksiktir; 0 varsayılmaz.
- R-15: **Geçersiz girdi.** Geçersiz ya da eksik ayar, desteklenmeyen borsa adı, tekrarlı ya da metin olmayan çift adı adıyla reddedilir ve borsaya çağrı gitmez. Boş liste boş sonuç verir, çağrı gitmez.
- R-16: **Mum sayısı.** Okuma çift başına tek mum isteği yapar. Borsa istenenden az mum verirse bu hata değildir, kısa seri döner.

## User experience
none — no user interface

## Constraints & out of scope
- Yeni runtime bağımlılığı: `ccxt` (insan onayı: Galip Badem, 2026-11-05; lisans, bakım ve CVE denetimi planda). `ccxt` import sınırı değişmez (`docs/architecture.md`).
- Borsa adı zorunlu ayardır; bu spec yalnız Binance spot'u destekler (Galip Badem, 2026-11-05). Kayıtlı veriler ve elle doğrulama Binance spot ile yapılır. Aday borsalar Binance ve OKX'tir; bu seçim masa başı karşılaştırmasına dayanır, BR-12'nin istediği efektif maliyet ölçümü değildir. OKX, o ölçüm zamanı geldiğinde eklenir.
- `check` ağa çıkmaz (`docs/testing.md`): testler kayıtlı veri ve sahte borsa ile koşar.
- Sensitive area: yok. Anahtar yüklenmez, emir gönderilmez, `risk` ve `execution` değişmez; `app` yalnız R-10 kadar eklenir. Shipped testlerin assert'leri değişmez.
- 0016'nın "gelecek zamanlı = geçersiz" kuralı değişmez. Bilinen bedel: yerel saat borsanın gerisindeyse alım durur, o çiftlerin pozisyonu o turda kapanmaz. Çözüm saat eşitlemedir, giriş noktası spec'inde başlangıç denetimi olarak ele alınır.
- Backlog: B-43 bu spec'le kapanır, bileşim senaryosu temiz değilse açık kalır ve kaydı güncellenir. B-41 açık kalır, kaydına "giriş noktası spec'inden önce çözülmeli" notu düşülür.
- Boyut: tek spec. Split: proposed 0017 temel okuma; 0018 hata ve süre davranışı; kept as one — Galip Badem, 2026-11-05, yetenek tektir ve hata davranışı olmayan okuma BR-11'i karşılamaz.
- Mum sayısının 1000 üst sınırı Binance'in istek başına sınırına dayanır; plan doğrular. Daha uzun geçmiş saklama spec'inin işidir.
- Coverage: `market_data` hassas alan olmadığı için modüle özel eşik konmaz (`docs/testing.md`).
- Out of scope: beyaz liste ile açık pozisyonları birleştirip çift listesi kurmak (giriş noktası spec'i); OHLCV ve ticker saklama (ayrı spec, backtest'in ön koşulu); emir defteri derinliği; döngü, zamanlayıcı, CLI, giriş noktası; config dosyası okuma; saat eşitleme; borsa seçimi ölçümü (BR-12); live ve testnet; `execution`'ın borsa adaptörü; backtest.

## Acceptance criteria
- [ ] AC-1 — Mutlu yol: kayıtlı borsa yanıtıyla iki çiftlik okuma, istek sırasıyla R-1'in tüm alanlarını doğru değerlerle döndürür; fiyat son işlem fiyatıdır, spread tanımdaki formülle hesaplanır; değerler `Decimal`'dir ve kayıtlı değerle birebir aynıdır, zamanlar UTC ve timezone-aware'dir (R-1, R-9).
- [ ] AC-2 — Yalnız okuma: ortamda anahtar varken bile okuma anahtar kullanmaz; sahte borsa yalnız herkese açık veri çağrıları kaydeder, emir ve hesap çağrısı kaydetmez (R-2).
- [ ] AC-3 — Kısmi hata: bir çiftin mum çağrısı, başka bir çiftin fiyat çağrısı başarısız olunca yalnız o alanlar adı konmuş nedenle eksik döner, kalan alanlar doğrudur; istisna fırlamaz (R-3).
- [ ] AC-4 — Süre: takılan çağrı süresinde kesilir; bütçe bitince kalan alanlar "süre bitti" nedeniyle eksik döner ve okuma bütçeyi aşmaz; geçici hata bütçe içinde yeniden denenip başarılı olunca değer döner; geçersiz sembol ve bozuk yanıt tek çağrıda kalır (R-4).
- [ ] AC-5 — Kapanmamış mum: kapanışı saatten bir birim sonra olan mum çıkarılır, saate eşit olan kalır; bu durum nedeni üretmez (R-5).
- [ ] AC-6 — Boşluk: ortasında boşluk olan seride yalnız son boşluktan sonraki mumlar döner, boşluk raporlanır; iki boşlukta yine sonuncu esas alınır; boşluksuz seride rapor yoktur (R-6).
- [ ] AC-7 — Fiyat zamanı: damgasız fiyat ve zamanı eksik döner, yerel saat kullanılmaz; saatin ilerisindeki damga değişmeden döner ve "saat kayması" raporlanır (R-7).
- [ ] AC-8 — Fiyat biçimi: fiyat adımına tam oturan fiyat döner, adımdan ince olan eksik döner; B-43'ün bileşim senaryosu yeniden denenir, sonucu kayda geçer (R-8).
- [ ] AC-9 — Tur uyumu: kayıtlı veriden gelen sonuç çevrilip `run_turn`'e verilince temiz veride tur tamamlanır; eksik fiyatlı ya da eksik mumlu çiftte alım durur, fiyatı taze pozisyon kapanır (R-3, R-10).
- [ ] AC-10 — Sır ve güvenilmeyen girdi: bozuk yanıt ve içinde sır biçimli metin taşıyan hata, adı konmuş nedenle eksik alan üretir; sonuçta ham metin ve sır yoktur (R-11).
- [ ] AC-11 — Gerçek borsa: kayıtlı verilerin kaynağı ve tarihi yazılıdır; VERIFY'da Binance spot'a karşı `check` dışında yapılan tek gerçek okuma, R-1 alanlarını döndürdüğünü gösteren kanıtla belgelenir (anahtarsız).
- [ ] AC-12 — Spread sınırları: alış satışa eşitse spread 0'dır; alış ya da satış eksikken, alış satıştan büyükken ve oran 1'e eşit veya büyükken spread adıyla eksik döner, fiyat etkilenmez; son işlem fiyatı yoksa fiyat alış ya da satıştan türetilmez (R-12, Güncel fiyat).
- [ ] AC-13 — Bozuk mum: R-13'teki her bozukluk türü o çiftin serisini adıyla eksik yapar, diğer çiftin serisi etkilenmez; onarılmış ya da kısmi seri dönmez (R-13).
- [ ] AC-14 — Çift ve kural: borsada olmayan, spot olmayan, işleme kapalı ve USDT olmayan çiftin her birinde tüm alanlar adıyla eksik döner; bildirilmemiş kural değeri kuralları eksik yapar, 0 dönmez (R-14).
- [ ] AC-15 — Geçersiz girdi ve mum sayısı: her geçersiz ya da eksik ayar, desteklenmeyen borsa adı (OKX dahil), tekrarlı ve metin olmayan çift adı adıyla reddedilir, sahte borsa çağrı kaydetmez; boş liste boş sonuç verir, çağrı yoktur; mum sayısı 1 ve 1000 kabul, 0 ve 1001 ret; borsa az mum verince kısa seri hatasız döner (R-15, R-16).

## Definition of Done
- [ ] Every acceptance criterion mapped to proof (test or reproducible observation)
- [ ] `scripts/check` green
- [ ] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [ ] Docs / ADRs updated if behavior or architecture changed
- [ ] Spec moved to `specs/done/` (it becomes immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | |
| Fix rounds | |
| Review findings: real / noise / deferred | |
| Regressions introduced | |
| Bugs escaped to production | |
