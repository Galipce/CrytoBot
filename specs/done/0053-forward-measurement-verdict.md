# Spec 0053 — İleriye dönük ölçüm raporu ve hüküm

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0053-plan.md`
- Self-critique: done
- Source: ADR 0003 (sıranın altıncı işi: ileriye dönük ölçüm; ilke 3, Revisit triggers); spec 0051 (skor kaydı ve
  sabit ölçüm şartları), spec 0052 (gölge kayıt), spec 0048 (düşüş isabeti, 30 günlük taban oran), spec 0045 (isabet
  kuralı, hüküm eşiği)

## Intent
Sahip, LLM filtresi live'ın şartı olmadan önce filtrenin işe yarayıp yaramadığını ileriye dönük ve dürüst bir ölçümle
bilmek istiyor (ADR 0003, sıranın altıncı işi). Bu spec, 0051'in skor kaydını, 0052'nin gölge kaydını ve gerçek
fiyatları yalnız okuyarak her olumsuz olay skorunun ardından fiyatta ne olduğunu 0048'in düşüş isabeti ve taban
oranıyla ölçen bir rapor ve **veri görülmeden önce sabitlenen** bir hüküm kuralı getirir. Başarı: yeniden üretilebilir
bir rapor; şart dolmadan (en az 90 gün ve beyaz listede en az 30 ölçülmüş olumsuz olay) `hüküm yok` ve nedeni; şart
dolunca `olumlu` ya da `olumsuz` hüküm, değeri ve eşiğiyle. `olumsuz` hüküm de başarıdır. Asıl hüküm koşusu şart
dolunca (en erken ~2027-02) ayrı bir koşu kaydı spec'iyle kayda geçer (0049 gibi). Bilerek yapılmayanlar: filtreyi
gerçekten açmak, live, prompt'u sonuca bakarak ayarlamak, hükmün herhangi bir şeyi (emir, mod, beyaz liste, ayar)
kendiliğinden değiştirmesi — hüküm bilgi verir, kararı sahip verir. Clarify kararları Q-1…Q-6 Galip Badem, 2026-11-18
tarihinde kabul etti ("önerilerini kabul ediyorum"); öz eleştiri kararları G-1…G-8 Galip Badem, 2026-11-18
tarihinde kabul etti ("onaylıyorum").

Terimler:
- **Olumsuz olay skoru:** 0051 skor kaydındaki, yönü olumsuz ve şiddeti ≥ 2 olan olay skoru (0051'de sabit).
- **Üçlü (Q-4):** bir "skorlandı" sonucunun model adı, prompt sürümü parmak izi ve bağlam parmak izi.
- **Güncel üçlü:** rapor anına kadarki en son "skorlandı" sonucunun üçlüsü.
- **Rapor anı:** raporun hesaplandığı an; verilmezse şimdiki an. Rapor anından sonraki hiçbir skor, satır ya da mum
  kullanılmaz.
- **Örnek:** bir olumsuz olay skoru (haber × coin).
- **Skor anındaki beyaz liste (G-1):** gölge kayıtta skor anından önceki (ya da eşit) son turun beyaz listesi; o ana
  kadar gölge satırı yoksa bot ayarındaki beyaz liste.
- **Giriş mumu (Q-1):** coinin USDT spot çiftinin, açılış anı skor anından kesin sonra olan ve skor anından en geç 1
  saat sonra açılan 1h mumu; giriş fiyatı bu mumun açılışıdır (0048 kuralı, referans an yerine skor anı).
- **Düşüş isabeti (Q-1, 0048):** giriş mumu dahil en çok 24 mum içinde fiyat, giriş fiyatının hedef mesafesi kadar
  altına, 1×ATR üstüne çıkmadan önce iner. Hedef mesafesi 2×ATR ile bir alım-satım turunun maliyetinin büyüğüdür;
  maliyet ve varsayılanları 0048'deki gibidir ve rapora yazılır. ATR(14) giriş mumundan önceki mumda ölçülür. Aynı
  mumda iki sınıra değilirse ya da 24 mum dolarsa isabet yoktur. **Yükseliş isabeti** aynı kuralın ters yönüdür.
- **Taban oran (Q-2, 0048):** aynı coinde skor anından önceki 720 mumun her kapanışı giriş sayılarak, aynı yön ve
  kuralla elde edilen isabet oranı; değerlendirme penceresi skor anını aşan mumlar sayılmaz. Bir kümenin taban oranı,
  kümedeki ölçülmüş örneklerin taban oranlarının ortalamasıdır.
- **Örtüşen örnek (G-2):** giriş mumu, aynı coinde daha önce sayılmış bir örneğin 24 mumluk penceresi içinde kalan
  örnek.

## Requirements
- R-1 — **Girdiler ve sınır.** Rapor skor kaydını, gölge kaydı, haber kaydını ve kayıtlı 1h fiyatları yalnız okur;
  ağa ve LLM'e çıkmaz, kilit almaz, skorlayıcı, toplayıcı ve bot çalışırken okunabilir ve onları beklemez. Fiyatlar
  ayrı bir indirme adımıyla gelir (G-8); raporun kendisi indirme yapmaz.
- R-2 — **Örnekler (Q-1).** Rapor anına kadarki her olumsuz olay skoru bir örnektir. Her örnek için: haber kimliği,
  kaynak (`binance-duyuru` / `rss`), olay türü, şiddet, coin, skor anı, üçlü, skor anındaki beyaz listede olup
  olmadığı, giriş mumu ve fiyatı, düşüş ve yükseliş isabeti, iki yönün taban oranı, olağandışı muma denk gelip
  gelmediği (0045 R-8 kuralı), örtüşen olup olmadığı, ölçülmediyse nedeni. Ölçülmeme nedenleri: `ölçüm bekliyor`
  (24 mum rapor anına kadar dolmadı, G-3), `giriş mumu yok ya da geç`, `fiyat verisi yok`, `çift yok`, `mum yetmiyor`
  (720 mum yok, G-5). Ölçülmeyen örnek hiçbir orana ve sayıya girmez, nedeniyle sayılır. Skor anının saat
  tabanı + 25 saat rapor anından sonraysa örnek `ölçüm bekliyor`dur (fiyata bakılmaz); nedenler bu sırayla denetlenir:
  `çift yok` → `ölçüm bekliyor` → `fiyat verisi yok` → `giriş mumu yok ya da geç` → `mum yetmiyor` (plan Risk 2).
  Olağandışı muma denk gelen: penceresinde (giriş mumu…24. mum) 0045 R-8'in (a) ya da (c) kuralıyla işaretli mum olan
  örnek; (b) hacim ister (fiyat verisinde hacim yok), (d) beş çift ister — ikisi uygulanamaz ve rapor bunu yazar
  (plan Risk 1).
- R-3 — **Hüküm (Q-2, Q-3, Q-4).** Hüküm yalnız güncel üçlünün, skor anındaki beyaz listede olan, ölçülmüş ve
  örtüşmeyen örnekleriyle verilir. Sırayla:
  1. `hüküm yok: skor yok` — skor kaydı yok ya da güncel üçlü yok.
  2. `hüküm yok: süre yetersiz (<g>/90 gün)` — güncel üçlünün ilk "skorlandı" sonucundan rapor anına 90 günden
     (90 × 24 saat) az geçti; tam 90 gün yeterlidir.
  3. `hüküm yok: olay yetersiz (<n>/30)` — hükme giren örnek sayısı 30'dan az.
  4. `olumlu` — birleşik düşüş isabeti, birleşik düşüş taban oranını en az 5 puan geçer (tam 5 puan olumludur).
  5. `olumsuz` — aksi; rapor tutmayan değeri ve eşiği yazar (ör. `olumsuz: isabet taban oranı 5 puan geçmiyor
     (+3.2 < +5)`).
  `hüküm yok` satırı kalan gün ve kalan örnek sayısını da yazar. Olağandışı mumlar hükme girmez (Q-2); yalnız R-4'te
  gösterilir.
- R-4 — **Hüküm tablosu.** Hükme giren küme için: örnek sayısı, düşüş isabeti ve taban oranı, farkı; yükseliş isabeti
  ve taban oranı (bilgi); aynı oranlar olağandışıya denk gelenler çıkarılmış halde (bilgi); örtüşen, ölçülmeyen
  (nedene göre) ve beyaz liste dışı örnek sayıları; kaynağa, olay türüne, şiddete ve coine göre dağılım.
- R-5 — **Üçlü ayrımı (Q-4).** Her üçlü kendi tablosunu alır (ilk ve son skor anı, R-4'ün sayıları). Güncel üçlü
  dışındakiler `hüküm dışı` diye işaretlenir. Güncel üçlü değiştiğinde 90 gün ve 30 örnek şartı yeni üçlünün ilk
  sonucundan yeniden sayılır. Bir üçlünün ilk sonucu o üçlünün en eski "skorlandı" sonucudur: üçlü A → B → A dönerse
  A'nın saati ilk A sonucundan sayılır (plan A-4).
- R-6 — **Yardımcı tablo (Q-5).** Güncel üçlünün, beyaz liste dışı da dahil USDT spot çifti olan bütün coinlerdeki
  örnekleri, aynı kuralla ayrı bir tabloda, `hüküm dışı` başlığıyla gösterilir. Bu tablo hükmü etkilemez; beyaz liste
  hiçbir koşulda kendiliğinden genişlemez.
- R-7 — **Gölge kayıt bölümü (Q-6).** Gölge kayıttan, rapor anına kadarki satırlarla: tur sayısı, ilk ve son tur
  anı, filtre durumuna göre satır dağılımı (çift başına), `filtre yok` nedenlerinin dağılımı, teknik "al"ların filtre
  durumuna göre yükseliş isabeti ve taban oranı (giriş mumu: tur anından sonraki ilk 1h mum). Bu bölüm hükme şart
  olarak girmez; gölge kayıt yoksa bölüm "gölge kayıt yok" der, rapor ve hüküm yine üretilir.
- R-8 — **Rapor ve örnek dosyası.** Rapor insan okunur bir metin ve makinece okunur bir örnek dosyasıdır (R-2'nin
  bütün alanları). Rapor başında rapor anı, girdi yolları, maliyet ayarı, güncel üçlü ve hüküm yazar. Aynı girdiler ve
  aynı rapor anıyla iki koşu bayt bayt aynı rapor ve örnek dosyası üretir (üretim anı satırı hariç).
- R-9 — **Gölge mod: hiçbir şey değişmez (ADR 0003 ilke 5).** Rapor ve hüküm hiçbir aksiyonu (emir, limit, mod,
  beyaz liste, ayar, bildirim) tetiklemez; bot, skorlayıcı, toplayıcı ve bütün mevcut komutlar bugünkü gibi çalışır.
  Okunan kayıtlar rapordan sonra değişmemiştir.
- R-10 — **Ayar ve hatalar.** Rapor çıktı yolları skor kaydı, gölge kayıt, haber kaydı, arşiv, fiyat verisi, bot
  deposu, paper kanıt deposu ya da bir kayıt dosyasıyla (çözülmüş mutlak yollarla) aynıysa rapor başlamayı adıyla
  reddeder ve hiçbir yere yazmaz. Skor kaydı yoksa rapor yine yazılır ve `hüküm yok: skor yok` der (G-7); istisna:
  gölge kayıtta teknik "al" varsa fiyat verisi yine gerekir ve fiyat deposu yoksa rapor
  `fiyat verisi yok: <yol>; önce forward download` ile reddeder (plan A-5). Okunamayan (bozuk) bir kayıt satırı raporu durdurmaz; atlanan satır sayısı kayda göre yazılır.

## User experience
none — no user interface (CLI). Akış: sahip fiyatları indirir → rapor komutunu (isteğe bağlı rapor anıyla)
çalıştırır → rapor ve örnek dosyası yazılır, hüküm satırı ekranda da görünür. Durumlar: skor yok (`hüküm yok: skor
yok`), süre yetersiz, olay yetersiz, `olumlu`, `olumsuz`, gölge kayıt yok (bölüm notu), yol çakışması (başlamaz,
adıyla), fiyat verisi eksik (ölçülecek bir örneğin gerekli aralığı indirilmemiş: başlamaz, `önce forward download`
der; sessiz boşluk yok, plan Risk 2). Komut adları plan aşamasında belirlenir; davranış değişmez.

## Constraints & out of scope
- **Ön kayıt (Q-3; ADR 0003 Consequences — sonradan gevşetilemez):** R-3'ün koşulları, isabet kuralı, taban oran,
  90 gün, 30 örnek, 5 puan eşiği, örtüşen örnek ve beyaz liste kuralı bu spec'le sabitlenir. Sonuca bakılarak
  değiştirilmez; değiştirmek yeni bir ADR ister ve ölçüm saatini sıfırlar.
- **Hüküm koşusu ayrıdır:** şart dolunca gerçek veriyle yapılan koşu ve sahibin kararı ayrı bir koşu kaydı spec'idir;
  bu spec'in AC'leri sentetik ve kurgusal girdilerle kanıtlanır.
- **Risk — beyaz liste darlığı (0052 S-6, Q-5):** BTC ve ETH ile 30 örnek 90 günde dolmayabilir. Ne yapılacağı
  (genişletme, bekleme, ADR'yi yeniden açma) sahibin kararıdır, kapsam dışıdır.
- **Bağımlılık:** yeni Python bağımlılığı yok. Strateji, risk, execution, portföy, skorlayıcı ve gölge kayıt kodu
  davranışı değişmez.
- **Split:** yok — tek yetenek (ölçüm raporu ve hüküm).
- OUT OF SCOPE: filtreyi gerçekten açmak (ADR 0003, hükümden sonra ayrı spec); live; prompt ya da bağlamı ayarlamak;
  olumlu olayların "al" açtırması; beyaz liste değişikliği; Telegram ve pano; yerel sınıflandırıcı (ADR 0003 ilke 6);
  B-92, B-94, B-95, B-96, B-97.
- Sensitive area: yok — emir, risk limitleri, defter, bot deposu, sırlar, mod anahtarı ve Telegram yetkisine dokunmaz;
  yalnız okur ve rapor yazar.

## Acceptance criteria
- [x] AC-1 — Örnek seçimi: olumsuz yön şiddet 2 ve 3 örnek olur; şiddet 1, olumlu ve belirsiz yön örnek olmaz;
  rapor anından sonraki skor girmez; skor anındaki beyaz liste gölge kayıttaki son turdan (eşit an dahil), tur yoksa
  ayardan alınır.
- [x] AC-2 — Giriş mumu ve isabet: giriş mumu skor anından kesin sonra açılan ilk 1h mumdur, tam skor anında açılan
  değildir; 1 saatten geç açılan mum `giriş mumu yok ya da geç` olur; düşüş isabeti 24. mumda hedefe ulaşan için var,
  25. mumda yok; stopa önce değen ve aynı mumda iki sınıra değen isabetsizdir; 2×ATR maliyetten küçükse hedef
  maliyettir; yükseliş isabeti ters yönde aynı kuraldır.
- [x] AC-3 — Taban oran skor anından önceki 720 mumla, aynı kuralla hesaplanır; penceresi skor anını aşan mum
  sayılmaz; 719 mumla `mum yetmiyor` olur; küme taban oranı örnek taban oranlarının ortalamasıdır.
- [x] AC-4 — Ölçülmeme: `ölçüm bekliyor`, `giriş mumu yok ya da geç`, `fiyat verisi yok`, `çift yok`, `mum yetmiyor`
  her biri ayrı örnekte adıyla sayılır ve hiçbir orana girmez; örtüşen örnek gösterilir ama hükme girmez.
- [x] AC-5 — Hüküm sırası: skor yok; 89 gün 23 saat → `süre yetersiz`, tam 90 gün geçer; 29 örnek → `olay yetersiz`,
  30 geçer; fark tam +5 puan → `olumlu`; +4.9 → `olumsuz` değer ve eşikle; `hüküm yok` kalan gün ve örneği yazar.
- [x] AC-6 — Üçlü: üçlü değişince eski üçlü `hüküm dışı` olur ve güncel üçlünün 90 gün / 30 örnek şartı kendi ilk
  sonucundan sayılır; eski üçlünün örnekleri hükmü etkilemez.
- [x] AC-7 — Tablolar: R-4'ün bütün kalemleri (olağandışı çıkarılmış oranlar dahil) yazılır ve olağandışı oranlar
  hükmü değiştirmez; R-6 yardımcı tablosu beyaz liste dışı coinleri gösterir ve hükmü değiştirmez; R-7 gölge bölümü
  bütün kalemleriyle yazılır, gölge kayıt yokken "gölge kayıt yok" der ve hüküm aynıdır.
- [x] AC-8 — Yeniden üretim ve dosya: aynı girdiler ve rapor anıyla iki koşu bayt bayt aynı rapor ve örnek dosyası
  üretir (üretim anı satırı hariç); örnek dosyası R-2'nin bütün alanlarını taşır.
- [x] AC-9 — Sınır: rapor ağa ve LLM'e çıkmaz, kilit almaz; skorlayıcı ve bot kilitliyken çalışır; okunan kayıtlar
  rapordan sonra bayt bayt aynıdır; bot, skorlayıcı, toplayıcı ve mevcut komutların bugünkü testleri değiştirilmeden
  geçer.
- [x] AC-10 — Ayar ve hata: R-10'daki her yol çakışması adıyla reddeder ve hiçbir yere yazmaz; skor kaydı yokken rapor
  `hüküm yok: skor yok` ile yazılır; bozuk satır atlanır ve kayda göre sayılır.

## Definition of Done
- [x] Every acceptance criterion mapped to proof (test or reproducible observation)
- [x] `scripts/check` green
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Docs / ADRs updated if behavior or architecture changed (`docs/commands.md`, `docs/architecture.md`, örnek ayar)
- [x] Spec moved to `specs/done/` (it becomes immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | 3 (BUILD adım 1: Risk 1, 2 metni; fix-1: R-5 A → B → A, R-10 G-7 istisnası) |
| Fix rounds | 2 (fix-1: review R1-1/2/3/6; fix-2: VERIFY V-1, yalnız test) |
| Review findings: real / noise / deferred | 5 / 1 / 2 (round 1: R1-1, R1-2, R1-3, R1-6 real, R1-7 noise, R1-4 → B-98, R1-5 → B-99; VERIFY: V-1 real) |
| Regressions introduced | 0 |
| Bugs escaped to production | 0 (ship anında) |
