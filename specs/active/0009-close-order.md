# Spec 0009 — Kapanış kararından risk onaylı paper satış emri

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0009-plan.md`

## Intent
CrytoBot'un sahibi, stop'a ya da hedefe ulaşan bir pozisyonun gerçekten satılmasını istiyor. Spec 0008 hangi
pozisyonun kapanacağına karar verir ve dolan satışı deftere yazar; ama satış emrini oluşturan yoktur, `execution` bugün
yalnızca alım yapar. Bu spec, kapanış kararındaki pozisyon için `risk`'in kapanış onayından geçen bir paper piyasa
satışı oluşturur. Kapanış koruyucu bir çıkıştır, yeni işlem değildir: giriş limitleri, beyaz liste, kill switch ve
güvenli mod onu engellemez; ama BR-9'un "onaysız emir yok" kuralı ve tek yönlü emir akışı korunur. Başarı: her
kapanış kararından en fazla bir satış emri çıkar, aynı pozisyon iki kez satılmaz, satış spec 0008'in kaydedebileceği
bir dolum üretir, hiçbir girdi istisna fırlatmaz. Bilerek yapılmayanlar: live satış, kısmi ya da elle kapanış, limit ya
da stop-limit emir, reddedilmiş bir kapanış emrinin yeniden denenmesi, kalıcılık, döngüye bağlama.

## Requirements
- R-1: **Kapanış talebi** şunları taşır: kapatılacak pozisyonun `clientOrderId`'si, çifti, miktarı ve kapanış nedeni
  (`stop` ya da `hedef`) — spec 0008'in kapanış kararının alanları. `risk` talebi değerlendirip bir **kapanış onayı**
  ya da adlandırılmış bir ret döndürür; onay talebi değiştirmeden taşır.
- R-2: **Kapanışa giriş kuralı uygulanmaz:** işlem riski (BR-4), günlük zarar limiti (BR-5), drawdown durdurması
  (BR-6), pozisyon limiti (BR-7), kâr/maliyet katı (BR-8), stop zorunluluğu (BR-3), beyaz liste ve kill switch
  kapanış onayını engellemez; kapanış onayı risk durumunu, kasayı ya da zamanı girdi olarak almaz. Kapanış onayı
  yalnızca talebin biçimini denetler (R-13); biçimi geçerli talep onaylanır. İşlem önerisi onayı (spec 0003–0005)
  değişmez.
- R-3: **Kapanış emri isteği** şunları taşır: kapanış onayı, çiftin borsa kuralları (miktar adımı, asgari miktar,
  asgari tutar), güncel fiyat, komisyon oranı, slippage oranı, mod ve şu anki zaman.
- R-4: Kapanış emri yalnızca **kapanış onayından** oluşur (BR-9): onay bir ret taşıyorsa ya da bir kapanış onayı
  değilse (ör. işlem önerisi onayı) istek "onaysız kapanış" ile reddedilir ve emir oluşmaz. İşlem önerisi onayıyla
  satış emri oluşmaz; kapanış onayıyla alım emri oluşmaz.
- R-5: Yalnızca paper mod desteklenir (spec 0006 R-3): mod `paper` değilse "mod desteklenmiyor".
- R-6: **Borsa kuralları** spec 0006 R-4 ile aynıdır ve kapanışta da denetlenir: miktar yuvarlanmaz; miktar adımının
  tam katı değilse, asgari miktarın altındaysa ya da satış tutarı (miktar × dolum fiyatı) asgari tutarın altındaysa
  istek "borsa kuralı" ile reddedilir; mesaj kuralı, miktarı ve kuralın değerini adlandırır. Asgariye eşit değer
  geçerlidir.
- R-7: Paper kapanış emri bir **piyasa satışıdır** ve simülatörde anında dolar: dolum fiyatı = güncel fiyat × (1 −
  slippage oranı); komisyon = miktar × dolum fiyatı × komisyon oranı (USDT). Hesap tam aritmetikle yapılır,
  yuvarlanmaz. Simülatör, spec 0006 R-9'daki gibi bir emri `bilinmiyor` ya da `reddedildi` döndürecek şekilde
  ayarlanabilir.
- R-8: **Kimlik:** kapanış emrinin `clientOrderId`'si pozisyonun `clientOrderId`'sinin `cb-` önekinin `cx-` ile
  değiştirilmiş hâlidir (`cb-s1-btc-0001` → `cx-s1-btc-0001`): deterministik, birebir, en fazla 35 karakter.
  Pozisyon kimliği `cb-` + spec 0006 R-6'daki öneri kimliği biçiminde değilse talep "geçersiz girdi" ile reddedilir.
- R-9: **Tekrar koruması:** aynı `clientOrderId`'li bir kapanış emri zaten varsa yeni emir oluşmaz: içerik (pozisyon
  kimliği, çift, miktar, neden) aynıysa mevcut emir "zaten var" ile olduğu gibi döner (durumu ne olursa olsun);
  farklıysa "kimlik çakışması". Güncel fiyat, oranlar, mod ve zaman içerik değildir. Reddedilmiş bir istek (emir
  oluşmamışsa) kimliği tüketmez. Böylece bir pozisyon iki kez satılmaz.
- R-10: **Emir kaydı** spec 0006 R-8'deki alanları taşır; yön `sell`'dir; ayrıca kapatılan pozisyonun kimliğini ve
  kapanış nedenini taşır (stop ve hedef yerine). Durum `dolu`, `reddedildi` ya da `bilinmiyor`'dur; durum sorgusu
  (spec 0006 R-9) kapanış emirleri için de aynı kurallarla çalışır.
- R-11: **Güvenli mod** (spec 0006 R-9, BR-11) yalnızca **alım** isteklerini durdurur; kapanış emri isteği güvenli
  modda da işlenir. Durumu `bilinmiyor` olan bir kapanış emri de güvenli moda sokar (yeni alımlar durur) ve spec 0006
  R-10'daki gibi giriş ve çıkış bildirimi üretir.
- R-12: **Ret sırası** (kapanış emri): geçersiz girdi → mod desteklenmiyor → zaten var / kimlik çakışması → onaysız
  kapanış → borsa kuralı. Birden fazla sorun varsa bu sıradaki ilki döner. Kapanış onayının ret sırası: geçersiz
  girdi (tek ret nedeni).
- R-13: **Sayı ve girdi kuralları** spec 0006 R-12 ile aynıdır: miktar ve güncel fiyat sıfırdan büyük, en fazla 28
  anlamlı basamak; oranlar 0 ile 1 arasında (1 hariç); adım sıfırdan büyük, asgariler negatif olmayan; sonlu
  `Decimal`/`int` (mantıksal değer ve kayan nokta hariç), üssü ±999999 içinde; çift metin; neden yalnızca `stop` ya da
  `hedef`; zaman dilimi taşıyan zaman. Değilse "geçersiz girdi", girdi adlandırılır. Tam sonucu 28 basamağa sığmayan
  hesap yuvarlanmaz, "geçersiz girdi: ölçek hesaplanamıyor". Hiçbir girdi için onay ya da emir isteği istisna
  fırlatmaz; ret mesajı ham girdiyi kısa yazar.
- R-14: **Deftere uyum:** dolu bir kapanış emrinin `clientOrderId`'si, pozisyon kimliği, miktarı, dolum fiyatı,
  komisyonu, nedeni ve zamanı, spec 0008'in kapanış kaydına aynen verilebilir ve kabul edilir.
- R-15: Durum ve emir kayıtları değişmez değerlerdir (spec 0006 R-13). Spec 0006'nın alım davranışı (R-1…R-14) ve
  spec 0003–0005'in onay davranışı değişmez; mevcut testleri değişmeden geçer.

## User experience
none — no user interface. (Kapanışların ve bildirimlerin gösterimi `control` ve `reporting` spec'lerinde gelir.)

## Constraints & out of scope
- Sensitive area: Emir gönderimi (`execution`) ve Risk limitleri (`risk`) — `docs/domain.md`. `risk` ve `execution`
  için %90 branch coverage; kapanış onayı ve kapanış emri kuralları `hypothesis` property testleriyle ve bağımsız bir
  beklenen-sonuç modeliyle kanıtlanır. `portfolio` değişmez.
- Mimari: kapanış emri de `risk → execution` yolundan geçer (BR-9, docs/architecture.md "Emir akışı tek yönlüdür");
  ADR gerekmez. Bağlantı (kararın talebe, onayın emre, dolumun deftere verilmesi) `app`'in işidir.
- Pozisyonun varlığı ve miktarı (self-critique G-1, G-2): `risk` ve `execution` defteri bilmez; kapanış talebi
  yalnızca spec 0008'in kapanış kararından (açık pozisyonlardan, defterdeki miktarla) kurulur — `app`'in
  sorumluluğu. Olmayan pozisyonun ya da uyuşmayan miktarın son kapısı defterin kaydıdır (spec 0008 R-4, R-10); live'da
  borsa elde olmayan coinin satışını ayrıca reddeder.
- Asgari tutarın altında kalan satış (G-3): R-6 reddi pozisyonu ve kuralı adlandırır; pozisyon açık kalır.
  Bildirimin gönderimi ve yeniden deneme `app` ile `reporting`'in işidir.
- Boyut (G-5): tek spec. Split değerlendirildi (12 kabul kriteri, iki hassas modül: 0009 kapanış onayı, 0010
  kapanış emri); tek tutuldu — tek akıştır (talep → onay → emir), kapanış onayı tek başına bir şey üretmez
  (Galip Badem, 2026-11-02).
- Kill switch henüz yoktur; bu spec kuralı koyar (kill switch kapanışı engellemez), uygulaması kill switch spec'inde
  bu kurala uyar.
- Reddedilmiş bir kapanış emrinin yeniden denenmesi kapsam dışıdır (deterministik kimlik "zaten var" döndürür);
  karar live spec'inde, borsanın aynı `clientOrderId`'yi yeniden kabul davranışıyla birlikte verilir (clarify S7,
  `specs/backlog.md` B-17).
- Out of scope: live satış ve gerçek borsa çağrısı, kısmi ya da elle kapanış, limit/stop-limit emir, kısmi dolum,
  coinden kesilen komisyon, kalıcılık, döngüye bağlama, bildirim gönderimi.
- Yeni runtime bağımlılığı gerekirse plan gerekçesiyle önerir; insan onayı olmadan eklenmez (`docs/security.md`).
- Para/oran değerleri `decimal.Decimal`; zaman damgaları UTC, timezone-aware (`docs/conventions.md`, Data rules).

## Acceptance criteria
<!-- Örnek pozisyon: spec 0007 AC-2 / spec 0008 AC-3 (`cb-s1-btc-0001`, BTC/USDT, 19.249, stop 95, hedef 110);
     kurallar adım 0.001, asgari miktar 0.001, asgari tutar 5; komisyon 0.001, slippage 0.0005. -->
- [ ] AC-1 — Kapanış onayı: örnek pozisyonun hedefte kapanış talebi → onaylandı, talep değişmeden taşınır (R-1).
- [ ] AC-2 — Limitler engellemez: aynı talep günlük zarar limiti dolu, drawdown durdurması etkin, pozisyon limiti dolu,
  çift beyaz listede değil ya da kasa sıfırken de onaylanır; işlem önerisi onayının aynı durumlardaki retleri
  değişmez (R-2, R-15).
- [ ] AC-3 — Hedefte satış: onayla BTC 110 → `cx-s1-btc-0001`, `sell`, 19.249, dolum fiyatı 109.945, komisyon
  2.116331305, durum `dolu`, pozisyon kimliği ve neden kayıtlı (R-3, R-7, R-8, R-10).
- [ ] AC-4 — Deftere uyum: AC-3'ün emri spec 0008'in kapanış kaydına verilir → kabul, USDT 10185.463248795, gerçekleşen
  kâr 185.463248795 (R-14).
- [ ] AC-5 — Onaysız: ret taşıyan kapanış onayı, işlem önerisi onayı ya da onay olmayan değer → "onaysız kapanış";
  kapanış onayıyla alım isteği → alımın "onaysız öneri"si (R-4).
- [ ] AC-6 — Borsa kuralı: adımın katı olmayan miktar, asgari miktarın altı, asgari tutarın altında satış (ör. fiyat
  0.25) → "borsa kuralı", kural ve değeri adlandırılır; asgariye eşit tutar kabul (R-6).
- [ ] AC-7 — Tekrar: aynı pozisyonun kapanışı farklı fiyat ve zamanla yeniden → "zaten var", tek emir; durumu
  `reddedildi` ya da `bilinmiyor` olan kapanış emri de "zaten var" döner; aynı kimlikle farklı miktar ya da neden →
  "kimlik çakışması"; reddedilmiş istek kimliği tüketmez (R-9).
- [ ] AC-8 — Güvenli mod: durumu bilinmeyen bir alım varken kapanış emri oluşur, alım isteği "durum belirsiz" alır;
  durumu `bilinmiyor` dönen kapanış emri güvenli moda sokar ve giriş bildirimi üretir, sorgu `dolu` dönünce çıkış
  bildirimi (R-10, R-11).
- [ ] AC-9 — Geçersiz girdi: talepte biçime uymayan pozisyon kimliği (`cb-` öneki yok, 33 karakterlik öneri kimliği,
  boşluk), metin olmayan çift, 0/negatif/`NaN`/kayan nokta/mantıksal değer/29 basamak miktar, `stop`/`hedef` dışında
  neden; emirde geçersiz fiyat, oran, kural, mod, zaman → "geçersiz girdi", girdi adlandırılır, istisna yok; sığmayan
  hesap → "ölçek hesaplanamıyor"; mesaj kısa (R-1, R-13).
- [ ] AC-10 — Ret sırası: geçersiz girdi + desteklenmeyen mod → "geçersiz girdi"; tekrar eden kimlik + borsa kuralı →
  "zaten var"/"kimlik çakışması"; onaysız + borsa kuralı → "onaysız kapanış"; mod + onaysız → "mod desteklenmiyor"
  (R-12).
- [ ] AC-11 — Değişmeyen davranış: spec 0003–0006'nın testleri değişmeden geçer; durum değişmez değerdir, reddedilen
  istek durumu aynen bırakır (R-15).
- [ ] AC-12 — Property: rastgele alım ve kapanış talebi, onay, emir ve sorgu dizilerinde (bağımsız modelle birebir)
  bir pozisyon için en fazla bir kapanış emri oluşur, kapanış hiçbir giriş limiti ya da güvenli mod yüzünden
  reddedilmez, dolum fiyatı ve komisyon modelle aynıdır, hiçbir girdi istisna fırlatmaz; her sonuç türü yeterince
  üretilir (R-1…R-13).

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
