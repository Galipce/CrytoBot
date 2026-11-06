# Spec 0023 — Backtest için geçmiş veri indirme

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0023-plan.md`
- Self-critique: done

## Intent
Botun sahibi, teknik stratejinin maliyetler düştükten sonra kâr edip etmediğini paper'a "kanıtlı" geçmeden önce geçmiş veride görmek istiyor (BR-10, ADR 0002 Faz 1). Bu iş üç spec'e bölündü; bu ilk parça, backtest'in üzerinde koşacağı geçmiş veriyi hazırlar. Sahibi tek komutla, beyaz listedeki çiftlerin seçtiği dönemdeki kapanmış mumlarını Binance spot'un herkese açık verisinden anahtarsız bir kez indirir. Mumlar, çift kuralları ve indirme tarihiyle birlikte tarihli bir veri dosyasına yazılır. Sonraki koşular bu dosyadan ağsız yapılacağı için aynı dosyayla aynı sonuç çıkar ve borsa yasağı riski tek indirmeyle sınırlı kalır. Başarı şöyle görünür: indirme ya tamamlanmış, eksiksiz bir dosya ve çift başına kısa bir özet bırakır ya da nedeni adıyla söyleyip tamamlanmış görünen hiçbir dosya bırakmaz. Bilerek yapılmayanlar: backtest koşusu ve raporu (0025), BR-10 kapısı (0026), dosyayı güncelleme ya da eklemeli indirme, Binance dışı borsa, live. İndirme paper deposuna ve botun kayıt dosyasına dokunmaz.

## Requirements
Terimler:
- **İndirme:** beyaz liste çiftlerinin geçmiş kapanmış mumlarını herkese açık veriden çekip veri dosyasına yazan, açık ve tek seferlik adım.
- **Veri dosyası:** indirmenin ürettiği dosya. Tek bir mum aralığı ve çift listesi için mumları, indirme anındaki çift kurallarını ve fiyat adımını, mum aralığını, istenen dönemi ve indirme anını taşır.
- **Dönem:** backtest'in başlangıç ve bitiş anı (UTC, tur aralığının sınırına denk). Bitiş hariçtir.
- **Isınma mumları:** dönemin ilk turunun ihtiyaç duyduğu, başlangıçtan önceki kapanmış mumlar. Sayıları okuma ayarındaki mum sayısı kadardır.
- **İndirme özeti:** indirme bitince çift başına ilk ve son mumun anını, mum sayısını ve dönem içindeki mum boşluklarının sayısını gösteren çıktı.

Davranış:
- R-1: **Yalnız herkese açık veri.** İndirme API anahtarı okumaz ve kullanmaz; ortamda anahtar olsa da davranış değişmez. Yalnız mum ve çift kuralı okuması yapılır; hiçbir emir ya da hesap çağrısı yapılmaz. Paper deposuna ve botun kayıt dosyasına dokunulmaz, çalışan bir paper botu etkilenmez.
- R-2: **Ayarlar.** Ayarların hiçbirinin varsayılanı yoktur. İndirme kendi ayarlarını (veri dosyası yolu, dönem başlangıcı ve bitişi) ve botun bugünkü ayarlarından beyaz listeyi, mum aralığını, tur aralığını, okuma ayarındaki mum sayısını ve çağrı süresini aynı ayar dosyasından alır. Ayarlar ağa çıkmadan ve diske yazmadan önce denetlenir. Bir ayar eksik ya da geçersizse ilk sorunlu ayar adıyla söylenir ve hiçbir şey yapılmaz. Bitiş başlangıçtan sonra olmak zorundadır. İkisi de tur aralığının sınırına denk gelmek zorundadır. Bitiş indirme anından sonra olamaz.
- R-3: **İndirme.** Beyaz listedeki her çift için ayardaki mum aralığında, ısınma mumları dahil başlangıçtan bitişe kadarki bütün kapanmış mumlar çekilir. Kapanmamış mum dosyaya girmez. Her çiftin o anki kuralları ve fiyat adımı da çekilir. Hepsi istenen dönem, mum aralığı ve indirme anıyla birlikte veri dosyasına yazılır. Mum değerleri borsanın bildirdiği değerlerle birebir aynıdır, yuvarlanmaz. Başarıyla biten indirme, indirme özetini konsola yazar.
- R-4: **Dosya varsa yazılmaz.** Veri dosyası yolunda okunabilir ya da bozuk bir dosya varsa indirme ağa çıkmadan ve hiçbir şey yazmadan reddeder.
- R-5: **Güvenilmeyen veri.** Okumanın bugün güvenilmez saydığı her mum (spec 0017) güvenilmeyen veri sayılır ve indirmeyi durdurur. Buna dönemle ilgisi olmayan, tekrarlanan ya da sırası bozuk mum ve kuralları eksik çift de dahildir.
- R-6: **Geç listelenen çift ve boşluklar.** Çiftin geçmişi dönemin içinde başlıyorsa bu hata değildir; çiftin mumları ilk mumundan başlar. Borsanın mum vermediği aralıklar boşluk olarak kalır, doldurulmaz ve indirme özetinde sayılır. Bir çiftin dönem boyunca hiç mumu yoksa ya da çift borsada yoksa indirme durur ve çifti adıyla söyler.
- R-7: **Hata ve borsa sınırı.** Ağ hatası, okuma ayarındaki çağrı süresinin aşılması, istek sınırı uyarısı (HTTP 429) ya da borsa yasağı (HTTP 418) olursa indirme durur ve nedeni adıyla söyler. 429 ya da 418'den sonra yeniden istek atılmaz. Yasağın bitiş anı biliniyorsa söylenir.
- R-8: **Yarım dosya yok.** İndirme durdurma isteğiyle (Ctrl+C), R-5–R-7'deki bir nedenle ya da beklenmeyen bir hatayla biterse tamamlanmış görünen bir veri dosyası kalmaz. Beklenmeyen hata tip adıyla söylenir, istisna metni yazılmaz.

## User experience
none — no user interface. Kullanıcı yalnız konsol komutunu ve konsol çıktısını görür; çıktı biçimi plana aittir, metinleri Türkçedir.
- Flow: ayar dosyasına veri dosyası yolunu ve dönemi yaz → indirme → indirme özetini oku.
- States: indirme reddedildi (ayar, dosya var), indirme sürüyor, indirme durdu (ağ, zaman aşımı, 429, yasak, güvenilmeyen veri, çift yok, durdurma isteği, beklenmeyen hata), indirme tamam (özetle).
- Design reference: none — the flow above is the design.
- Accessibility: yalnız klavye; renk bilgi taşımaz.

## Constraints & out of scope
- Sensitive area: yok. İndirme emir göndermez, anahtar kullanmaz (R-1), paper deposuna, mod durumuna ve risk kurallarına dokunmaz.
- Okumanın (spec 0017), turun, paper deposunun ve kayıt dosyasının davranışı değişmez. Shipped testlerin beklentileri değişmez.
- Bağımlılık kuralları (`docs/architecture.md`, Forbidden dependencies) sürer. Plan bir kuralı değiştirmeyi gerektirirse bu bir mimari karardır, sessizce yapılmaz (ADR).
- Testler gerçek borsaya çıkmaz. Gerçek borsa yalnız VERIFY'daki tek gözlemde kullanılır (AC-8).
- Coverage: değişen her modül için modül başına %90 branch eşiği geçerlidir (`docs/testing.md`).
- Out of scope: backtest koşusu ve raporu; BR-10 kapısı; mevcut dosyayı güncelleme, eklemeli ya da kaldığı yerden indirme; 429 ve 418 sonrası otomatik yeniden deneme; geçmiş spread ya da emir defteri verisi; Binance dışı borsa; live.
- Split: proposed 0023 geçmiş veri indirme → 0025 backtest koşusu ve rapor → 0026 BR-10 kapısı (eşik, insan onayı kaydı, onaysız paper başlatmanın reddi, `TRIAL_MARK`'ın kalkması; hassas alan: mod/aşama). Accepted — Galip Badem, 2026-11-06 (S1, G-1).
- 0025'e taşınan kararlar (Galip Badem, 2026-11-06; S2–S7, G-2–G-11). 0025 bunları kendi spec'inde yazar:
  - Koşu veri dosyasından ağsız yapılır. Paper deposuna ve kayıt dosyasına dokunmaz.
  - Her aralık sınırında paper turunun aynısı simüle saatle atılır. Stop ve hedef yalnız tur anlarında denetlenir, mum içi high/low'a bakılmaz.
  - Fiyat, sınırda açılan mumun açılış fiyatıdır; o mum yoksa fiyat eksik sayılır. İleriye bakma yoktur.
  - Spread ayardaki sabit varsayımdır, turun spread birimini kullanır, varsayılanı yoktur. Mum ve fiyat yaşı ayarları simüle saatle uygulanır.
  - Ayrım anı örneklem içini ve dışını böler. Koşu kesintisizdir. İşlem kapandığı parçada sayılır. Yalnız örneklem dışı parça "BR-10 kanıtı adayı" işaretini taşır. Rapor geçti/kaldı demez.
  - Metrikler (S6) ve tanımları: kâr faktörü ve kazanma oranı gerektiğinde "tanımsız" yazılır. Ortalama günlük getiri, simüle UTC günlerinin son tur kasasından hesaplanır. Parça drawdown'ı parçanın kendi zirvesine göre ölçülür. Bitiş kasası açık pozisyonları son fiyatla içerir; gerçekleşen ve gerçekleşmemiş kâr/zarar ayrı gösterilir.
  - Günlük zarar limiti simüle UTC gününe göre işler. Drawdown durdurması koşunun sonuna kadar sürer.
  - Turun durum bildirimleri gönderilmez, raporda sayılır. Rapor varsayımları, B-51 sınırlaması dahil, yazar.
  - Süre hedefi: 30 çift, 1 saat, 12 ay koşusu bu makinede 10 dakikanın altında biter. Dönem üst sınırı yoktur.
- Bağımlılık (R-10, PLAN): botun ayar yükleyicisi bilinmeyen bölümü reddeder (spec 0022). `[history]` bölümünü tanıması ayrı bir mini-spec'tir (CHANGE lane, `docs/testing.md` Lists that grow). 0023 BUILD o mini-spec ship edildikten sonra başlar. Galip Badem, 2026-11-06.
- Backlog: B-51 bu spec'te değişmez; 0025 raporunda varsayım olarak yazılacak.

## Acceptance criteria
- [ ] AC-1 — Mutlu yol (R-3): birden çok sayfa gerektiren dönemde sahte borsayla indirme, her çift için ısınma mumları dahil dönemi kapsayan kapanmış mumları borsanın değerleriyle birebir yazar. Dosya çift kurallarını, fiyat adımını, mum aralığını, istenen dönemi ve indirme anını taşır. Kapanmamış mum dosyada yoktur. İndirme özeti her çift için doğru ilk ve son mumu, mum sayısını ve boşluk sayısını gösterir.
- [ ] AC-2 — Yalnız herkese açık veri (R-1): ortamda anahtar varken anahtar okunmaz. Sahte borsada yalnız mum ve çift kuralı çağrıları kaydedilir, emir ve hesap çağrısı yoktur. Paper deposu ve kayıt dosyası bayt bayt değişmez.
- [ ] AC-3 — Ayarlar (R-2): ayar dosyası yok, okunamıyor, her eksik ayar, her geçersiz ayar, başlangıçtan önce ya da ona eşit bitiş, tur aralığı sınırına denk gelmeyen başlangıç ya da bitiş ve indirme anından sonraki bitiş için ağa çıkılmaz, dosya yazılmaz ve ilk sorunlu ayar adıyla söylenir.
- [ ] AC-4 — Dosya varsa (R-4): okunabilir bir veri dosyası ya da bozuk bir dosya varken indirme ağa çıkmadan reddeder ve dosya bayt bayt değişmez.
- [ ] AC-5 — Güvenilmeyen veri (R-5): okumanın güvenilmez saydığı mum, tekrarlanan mum, sırası bozuk mum ve kuralları eksik çiftin her birinde indirme durur, nedeni adıyla söylenir ve tamamlanmış görünen dosya kalmaz.
- [ ] AC-6 — Geç listelenen çift ve boşluklar (R-6): dönem içinde listelenen çift hatasız indirilir ve ilk mumundan başlar. Mum boşluğu doldurulmaz, özette doğru sayılır. Dönem boyunca hiç mumu olmayan çift ve borsada olmayan çift için indirme durur, çift adıyla söylenir, tamamlanmış görünen dosya kalmaz.
- [ ] AC-7 — Hata, borsa sınırı ve yarım dosya (R-7, R-8): ağ hatası, çağrı süresinin aşılması, 429, `Retry-After`'lı 418 ve `Retry-After`'sız 418'in her birinde indirme durur ve nedeni adıyla söylenir. 429 ve 418'den sonra sahte borsaya yeni istek gitmez. Yasağın bitiş anı biliniyorsa söylenir. İndirme ortasındaki durdurma isteğinde ve beklenmeyen hatada tamamlanmış görünen dosya kalmaz. Beklenmeyen hata tip adıyla yazılır, istisna metni ve sır biçimli metin çıktıda yoktur.
- [ ] AC-8 — Gerçek borsa (R-1, R-3): VERIFY'da, `check` dışında, bu makinede Binance spot'tan anahtarsız en az iki çift ve bir aylık dönem indirilir. Dosya ve indirme özeti oluşur. Gözlem kanıtla belgelenir.

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
