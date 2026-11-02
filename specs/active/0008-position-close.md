# Spec 0008 — Pozisyonun stop ya da hedefte kapanışı ve gerçekleşen kâr/zarar

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0008-plan.md`

## Intent
CrytoBot'un sahibi, açılan her paper pozisyonun stop-loss'a ya da hedefe ulaşınca kapanmasını ve sonucun hesaba
yansımasını istiyor. Bugün defter yalnızca alımları kaydediyor: pozisyonlar hiç kapanmıyor, BR-3'ün zorunlu kıldığı
stop hiçbir zaman işlemiyor ve gerçekleşen kâr/zarar bilinmiyor. Bu spec iki şey getirir: güncel fiyatlarla hangi
açık pozisyonların stop'ta ya da hedefte kapanması gerektiğinin kararı ve kapanış satışının deftere silinmez bir
kayıt olarak yazılması (satış geliri bakiyeye eklenir, pozisyon kapanır, komisyonlar dahil net kâr/zarar
hesaplanır). Başarı: karar ve kayıt her an defterle tutarlıdır, bakiye hiçbir zaman negatife düşmez, aynı kapanış
iki kez yazılmaz, hiçbir girdi istisna fırlatmaz. Bilerek yapılmayanlar: paper kapanış satış emrinin oluşturulması
(spec 0009, `execution`), elle ya da kısmi kapanış, trailing stop, günlük kâr/zarar raporu, kalıcı saklama, botun
döngüsüne bağlama, live satış.

## Requirements
- R-1: **Kapanış kararı:** açık bir defterden, çağıranın verdiği çift başına güncel fiyatlarla, kapanması gereken
  açık pozisyonlar belirlenir: güncel fiyat pozisyonun stop'una eşit ya da altındaysa karar "stop'ta kapanış",
  hedefine eşit ya da üstündeyse "hedefte kapanış"tır; ikisi de değilse pozisyon için karar yoktur. İkisi birden
  doğruysa (elle kurulmuş, stop'u hedefine eşit ya da üstünde bir pozisyon) karar "stop'ta kapanış"tır. Kararlar açık
  pozisyonların eklenme sırasıyla verilir ve her biri pozisyonun kimliğini (`clientOrderId`), çiftini, miktarını,
  nedenini ve karara esas fiyatı taşır. Karar defteri değiştirmez ve zaman girdisi taşımaz.
- R-2: **Fiyatı eksik çift:** açık pozisyonu olan bir çiftin fiyatı verilmemişse ya da geçersizse (spec 0007 R-7'nin
  fiyat kuralı) o çiftin pozisyonları için karar verilemez; sonuç bu çiftleri "fiyat eksik" olarak adlandırır,
  fiyatı geçerli çiftlerin kararları yine verilir (bir çiftin eksik fiyatı başka bir çiftin stop'unu engellemez;
  BR-11'in güvenli tarafı). Pozisyonu olmayan çiftlerin fiyatları yok sayılır; açık pozisyon yoksa karar listesi
  boştur ve fiyat gerekmez. Fiyatlar çift → fiyat eşlemesi olarak verilir; eşleme değilse "geçersiz girdi".
  Açılmamış defter için karar isteği "defter açılmamış" ile reddedilir.
- R-3: **Kapanış kaydı isteği** dolan bir kapanış satışının şu bilgilerini taşır: kendi `clientOrderId`'si, kapattığı
  pozisyonun `clientOrderId`'si, miktar, dolum fiyatı, komisyon (USDT), kapanış nedeni (`stop` ya da `hedef`) ve
  dolum zamanı. Defter, nedenin dolum fiyatıyla uyumunu yeniden denetlemez (fiyat stop'un altından boşlukla
  geçebilir; dolum fiyatı slippage taşır).
- R-4: **Yalnızca tam kapanış:** miktar kapatılan pozisyonun miktarına eşit olmalıdır; değilse "geçersiz girdi:
  miktar pozisyonla uyuşmuyor", iki miktar adlandırılır. Kısmi kapanış yoktur.
- R-5: **Kabul edilen kapanış** üç etki yapar: USDT bakiyesi satış geliri (miktar × dolum fiyatı − komisyon) kadar
  artar; pozisyon açık pozisyonlardan çıkar ve kapanmış pozisyonlar arasına, kapanış satışının bilgileri ve
  gerçekleşen kâr/zararıyla birlikte, kapanma sırasıyla girer; deftere bir kapanış kaydı eklenir. Hesap tam
  aritmetikle yapılır, yuvarlanmaz.
- R-6: **Gerçekleşen kâr/zarar** (net): satış geliri (miktar × satış dolum fiyatı − satış komisyonu) − alış maliyeti
  (miktar × alış dolum fiyatı + alış komisyonu). Pozitif kâr, negatif zarardır. Defter bütün kapanmış pozisyonların
  gerçekleşen kâr/zarar toplamını da verir (kapanış yoksa 0). Değişmez: açılış − Σ açık pozisyonların alış maliyeti
  + Σ gerçekleşen kâr/zarar = USDT bakiyesi.
- R-7: **Bakiye negatife düşmez:** komisyon satış tutarından (miktar × dolum fiyatı) büyükse istek "geçersiz girdi"
  ile reddedilir (satış geliri negatif olamaz). Tam eşitlik kabul edilir (gelir 0).
- R-8: **Kapanış zamanı** kapatılan pozisyonun açılış (dolum) zamanından önce olamaz ("geçersiz girdi"); kapanışlar
  arasında zaman sırası aranmaz.
- R-9: **Tekrar koruması:** aynı kapanış `clientOrderId`'siyle bir kapanış zaten kayıtlıysa yeni kayıt oluşmaz:
  içerik (kapatılan pozisyon, miktar, dolum fiyatı, komisyon, neden) aynıysa sonuç "zaten kayıtlı"dır, kayıtlı
  kapanış olduğu gibi döner; içerik farklıysa "kayıt çakışması". Dolum zamanı içerik değildir. Reddedilmiş bir
  istek kimliği tüketmez. Alım ve kapanış kimlikleri tek bir kimlik alanını paylaşır: bir alımın kimliğiyle gelen
  kapanış (ya da bir kapanışın kimliğiyle gelen alım) "kayıt çakışması" ile reddedilir.
- R-10: **Pozisyon bulunamadı / kapalı:** kapatılacak kimlikte hiç pozisyon yoksa "pozisyon bulunamadı"; pozisyon
  başka bir kapanış kimliğiyle zaten kapanmışsa "pozisyon kapalı" ile reddedilir ve kapatan kapanışın kimliği
  adlandırılır.
- R-11: **Hesap durumu** (spec 0007 R-7) kapanıştan sonra yalnızca açık pozisyonları sayar ve değerler; kapanmış bir
  pozisyonun çifti için fiyat istenmez. Hesap durumu gerçekleşen kâr/zarar toplamını da verir. Kasa, serbest bakiye
  ve açık pozisyon sayısı spec 0007 R-8'deki gibi `risk`'in hesap girdisidir: kapanan pozisyon BR-7'nin pozisyon
  sayısından düşer.
- R-12: **Silinmez defter** (spec 0007 R-9): kapanış yeni bir kayıttır; alım kaydı ve önceki kayıtlar değişmez;
  her kabul edilen istek yeni bir defter döndürür; reddedilen istek defteri değiştirmez. Spec 0007'nin alım
  davranışı (R-1…R-11) değişmez; satış yönlü alım isteği "desteklenmeyen yön" almaya devam eder.
- R-13: **Ret sırası** (kapanış kaydı): geçersiz girdi → defter açılmamış → zaten kayıtlı / kayıt çakışması →
  pozisyon bulunamadı → pozisyon kapalı → miktar uyuşmuyor / kapanış zamanı açılıştan önce. Birden fazla sorun
  varsa bu sıradaki ilki döner. Satış gelirinin ölçeği geçersiz girdi adımında, bakiyeye eklenmesinin ve kâr/zarar
  hesabının ölçeği son adımda denetlenir.
- R-14: **Sayı ve girdi kuralları** spec 0007 R-11 ile aynıdır: miktar ve dolum fiyatı sıfırdan büyük, komisyon
  negatif olmayan; sonlu `Decimal`/`int` (mantıksal değer ve kayan nokta hariç), üssü ±999999 içinde, en fazla 28
  anlamlı basamak; iki `clientOrderId` de 1–36 karakterlik, yalnızca ASCII harf, rakam, `-` ve `_`; neden yalnızca
  `stop` ya da `hedef`; zaman dilimi taşıyan zaman. Değilse "geçersiz girdi", girdi adlandırılır. Tam sonucu 28
  basamağa sığmayan bir hesap yuvarlanmaz, "geçersiz girdi: ölçek hesaplanamıyor" ile reddedilir. Hiçbir girdi
  için karar ya da kayıt istisna fırlatmaz; ret mesajı ham girdiyi kısa yazar (uzun sayı basamak sayısıyla).

## User experience
none — no user interface. (Kapanışların ve kâr/zararın CLI/Telegram'dan görüntülenmesi `control` ve `reporting`
spec'lerinde gelir.)

## Constraints & out of scope
- Sensitive area: Portföy / defter (`portfolio`) — `docs/domain.md`. `portfolio` için %90 branch coverage; kapanış,
  bakiye ve kâr/zarar kuralları `hypothesis` property testleriyle ve bağımsız bir beklenen-sonuç modeliyle (oracle,
  `Fraction`) kanıtlanır. `risk` ve `execution` değişmez.
- Bölme: istek üç yetenek içeriyordu (tetik, kapanış emri, defter). Bölündü: bu spec kapanış kararı + defterde
  kapanış; paper kapanış satış emri spec 0009 (`execution`) — Galip Badem, 2026-11-02, clarify S1. Yol haritasında
  SQLite kalıcılığı 0010'a, `app` paper döngüsü 0011'e kayar.
- Boyut: tek spec. Split değerlendirildi (12 kabul kriteri, karar ve kayıt); tek tutuldu — yetenek tektir
  (pozisyonu kapat), karar ve kayıt aynı pozisyon kuralını ve ret akışını paylaşır (Galip Badem, 2026-11-02,
  self-critique G-6).
- Risk limitleri ve kapanış (spec 0009 için kayıt, clarify S7): kapanış "yeni işlem" değildir; günlük zarar limiti
  (BR-5), drawdown durdurması (BR-6) ve kill switch kapanışı engellemez. Bu spec emir oluşturmadığı için kuralı
  uygulamaz; spec 0009 kural olarak yazar.
- Fiyat kaynağı: karar çağıranın verdiği güncel (son) fiyatla verilir; mumun en yüksek/en düşük fiyatıyla tetik
  backtest spec'inde gelir. Fiyatın bayatlığı (BR-11 "veri bayat") kapsam dışıdır.
- Kalıcılık: defter bellekte, değişmez bir değerde (spec 0007). Bağlantı (kararın satış emrine, dolumun deftere
  verilmesi) `app`'in işidir.
- Out of scope: kapanış satış emri (spec 0009), elle kapanış, kısmi kapanış, trailing stop, stop/hedefin sonradan
  değiştirilmesi, günlük (UTC) kâr/zarar raporu ve günlük hedef metriği (BR-1), gerçekleşmemiş kâr/zarar raporu,
  canlı borsa bakiyesiyle mutabakat, live satış ve coinden kesilen komisyon.
- Yeni runtime bağımlılığı gerekirse plan gerekçesiyle önerir; insan onayı olmadan eklenmez (`docs/security.md`).
- Para/oran değerleri `decimal.Decimal`; zaman damgaları UTC, timezone-aware (`docs/conventions.md`, Data rules).

## Acceptance criteria
<!-- Örnek pozisyon: spec 0007 AC-2 (`cb-s1-btc-0001`, BTC/USDT, 19.249 @ 100.1, alış komisyonu 1.9268249, stop 95,
     hedef 110; USDT 8071.2482751 / açılış 10000). -->
- [ ] AC-1 — Karar: örnek pozisyonla BTC 110 → "hedefte kapanış", BTC 95 → "stop'ta kapanış", BTC 94 → "stop'ta
  kapanış", BTC 100 ve 109.99 → karar yok; karar kimliği, çifti, miktarı, nedeni ve fiyatı taşır; stop'u hedefine
  eşit ya da üstünde bir pozisyonda iki koşul birden doğruysa → "stop'ta kapanış"; defter değişmez (R-1).
- [ ] AC-2 — Karar sırası ve eksik fiyat: üç açık pozisyon (iki çift) → kararlar eklenme sırasıyla; bir çiftin
  fiyatı yok, sıfır, negatif, `NaN` ya da kayan nokta → o çift "fiyat eksik" ile adlandırılır, diğer çiftin
  kararları yine verilir; pozisyonu olmayan çiftin fiyatı yok sayılır; açık pozisyon yoksa boş liste, fiyat
  gerekmez; açılmamış defter → "defter açılmamış"; eşleme olmayan fiyat → "geçersiz girdi" (R-1, R-2).
- [ ] AC-3 — Hedefte kapanış: örnek pozisyona `cb-x1` kapanışı (19.249 @ 109.945, komisyon 2.116331305, neden
  hedef) → USDT 10185.463248795, açık pozisyon 0, kapanmış pozisyon 1, gerçekleşen kâr 185.463248795, toplam
  185.463248795; kasa fiyat istemeden 10185.463248795 (R-5, R-6, R-11).
- [ ] AC-4 — Stop'ta kapanış: aynı pozisyona 19.249 @ 93.953, komisyon 1.808501297, neden stop → gerçekleşen zarar
  −122.058929197, USDT 9877.941070803; değişmez (açılış − Σ açık alış maliyeti + Σ K/Z = USDT) tutar (R-5, R-6).
- [ ] AC-5 — Tam kapanış: miktar 19.248 ya da 19.25 → "geçersiz girdi: miktar pozisyonla uyuşmuyor", iki miktar
  adlandırılır, defter değişmez (R-4).
- [ ] AC-6 — Gelir: komisyon satış tutarını aşan kapanış → "geçersiz girdi", defter değişmez; komisyon satış
  tutarına tam eşit → kabul, gelir 0, bakiye değişmez, zarar = alış maliyeti (R-7).
- [ ] AC-7 — Tekrar: aynı kapanış kimliği ve içerik, farklı zaman → "zaten kayıtlı", tek kapanış; pozisyon, miktar,
  dolum fiyatı, komisyon ya da neden farklı → "kayıt çakışması"; alım kimliğiyle gelen kapanış ve kapanış
  kimliğiyle gelen alım → "kayıt çakışması"; reddedilmiş istek kimliği tüketmez (R-9).
- [ ] AC-8 — Pozisyon: olmayan kimlik → "pozisyon bulunamadı"; başka kimlikle zaten kapanmış pozisyon → "pozisyon
  kapalı", kapatan kimlik adlandırılır (R-10).
- [ ] AC-9 — Geçersiz girdi: miktar, dolum fiyatı 0/negatif/`NaN`/kayan nokta/mantıksal değer/aralık dışı üs/29
  anlamlı basamak; negatif komisyon; biçime uymayan iki kimlik; `stop`/`hedef` dışında neden; zaman dilimi taşımayan
  zaman; pozisyon açılışından önceki kapanış zamanı → "geçersiz girdi", girdi adlandırılır, istisna yok; sığmayan
  hesap → "ölçek hesaplanamıyor"; mesaj kısa (R-8, R-14).
- [ ] AC-10 — Ret sırası: geçersiz girdi + açılmamış defter → "geçersiz girdi"; tekrar eden kimlik + olmayan pozisyon
  → "zaten kayıtlı"/"kayıt çakışması"; olmayan pozisyon + uyuşmayan miktar → "pozisyon bulunamadı"; kapalı
  pozisyon + uyuşmayan miktar → "pozisyon kapalı" (R-13).
- [ ] AC-11 — Silinmez defter ve risk girdisi: kapanıştan sonra önceki kayıtlar ve sıraları aynıdır, reddedilen istek
  defteri aynen bırakır; spec 0007'nin alım testleri değişmeden geçer; beş açık pozisyonlu defterde biri
  kapanınca hesap durumu 4 açık pozisyon verir ve spec 0003 onayı pozisyon limitine takılmaz (R-11, R-12).
- [ ] AC-12 — Property: rastgele açılış, alım, karar ve kapanış dizilerinde (bağımsız `Fraction` modeliyle birebir)
  USDT hiçbir zaman negatif değildir, USDT = açılış − Σ açık alış maliyeti + Σ gerçekleşen K/Z, açık ve kapanmış
  pozisyonlar ve kararlar modelle aynıdır, hiçbir girdi istisna fırlatmaz; her sonuç türü yeterince üretilir
  (R-1…R-14).

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
