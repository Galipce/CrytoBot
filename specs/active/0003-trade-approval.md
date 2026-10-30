# Spec 0003 — İşlem önerisi onayı: stop, boyutlama, pozisyon sayısı

- Status: Approved
- Mode: strict
- Plan: `specs/plans/0003-plan.md`

## Intent
CrytoBot'un sahibi, stratejinin ürettiği her alım önerisinin borsaya gitmeden önce risk kurallarından
geçmesini istiyor (BR-9): reddedilen öneri nedenini adlandırır, onaylanan öneride ne kadar alınacağını
strateji ya da sahip değil bot belirler. Başarı: stop-loss'u olmayan veya yanlış tarafta stop taşıyan öneri
asla onaylanmaz; onaylanan miktarda stop'a gelinirse ücretler dahil kayıp işlem başına risk limitini aşmaz;
açık pozisyon sayısı limitteyken yeni pozisyon açılmaz; onaylanan miktar borsa kurallarına göre aşağı
yuvarlanmıştır. Bilerek yapılmayanlar: emrin gönderilmesi, pozisyon kapatan satış, günlük zarar ve
drawdown'ın canlı hesabı (BR-5, BR-6), maliyet/kâr eşiği (BR-8), belirsiz durum kuralı (BR-11), kill switch.

## Requirements
- R-1: Bir işlem önerisi çifti, yönü, giriş fiyatını ve stop-loss fiyatını taşır. Onay, önerinin yanında şu
  girdilerle karar verir: geçerli risk limitleri (spec 0002), kasa, serbest bakiye, açık pozisyon sayısı,
  beyaz liste, çiftin borsa kuralları (miktar adımı, asgari miktar, asgari tutar) ve taker ücret oranı.
  Sonuç ya bir onaylı miktardır ya da adlandırılmış bir ret nedenidir; ikisi birden olmaz.
- R-2: Yalnızca spot alım önerileri onaylanabilir; yön alım değilse öneri reddedilir. Çift beyaz listede
  birebir (büyük/küçük harf ve boşluk dahil) yoksa öneri reddedilir. (BR-2)
- R-3: Stop-loss zorunludur. Stop yoksa, sayı değilse (`NaN`, sonsuz dahil), sıfır veya negatifse, girişe
  eşit veya girişin üstündeyse öneri reddedilir. Giriş fiyatı da sonlu ve sıfırdan büyük olmalıdır. Stop'un
  girişe uzaklığı için üst sınır yoktur. (BR-3)
- R-4: Açık pozisyon sayısı en fazla açık pozisyon limitine eşit veya üstündeyse öneri reddedilir. Aynı
  çiftte zaten açık pozisyon olması ayrıca bir ret nedeni değildir; yeni alım ayrı bir pozisyon sayılır.
  (BR-7)
- R-5: Onaylı miktar, çiftin miktar adımının katı olan ve aşağıdaki iki koşulu birlikte sağlayan **en büyük**
  miktardır (aşağı yuvarlama; yukarı yuvarlama asla yapılmaz):
  - stop'a gelinirse kayıp ≤ kasa × işlem başına risk; kayıp = miktar × (giriş − stop) + alışta ve stop'ta
    satışta ödenen taker ücreti (miktar × giriş × ücret + miktar × stop × ücret). (BR-4)
  - alış tutarı ücret dahil ≤ serbest bakiye: miktar × giriş × (1 + ücret). Serbest bakiye risk bütçesinden
    küçükse miktar serbest bakiyeyle sınırlanır (öneri reddedilmez) ve sonuç bunu belirtir.
- R-6: Onaylı miktar asgari miktarın altında ya da miktar × giriş asgari tutarın altında kalırsa öneri
  "borsa asgarisinin altında" nedeniyle reddedilir; asgariye eşit değer geçerlidir.
- R-7: Onay girdileri kendi içinde geçerli olmalıdır; değilse öneri reddedilir ve geçersiz girdi
  adlandırılır: kasa sıfırdan büyük, serbest bakiye negatif olmayan ve kasadan büyük olmayan, açık pozisyon sayısı negatif olmayan
  tam sayı, ücret oranı 0 ≤ ücret < 1, miktar adımı sıfırdan büyük, asgari miktar ve tutar negatif olmayan;
  tüm sayılar sonlu. Risk limitlerinden biri — bu onayda kullanılmayan günlük zarar ve drawdown dahil —
  spec 0002'nin sabit üst sınırlarını aşıyorsa veya geçersizse (spec 0002 R-4) öneri reddedilir; limitler
  nereden gelirse gelsin (B-3).
- R-8: Ret nedenleri ayrı ayrı adlandırılır: alım dışı yön, beyaz liste dışı çift, geçersiz/eksik stop,
  geçersiz giriş, pozisyon limiti dolu, borsa asgarisinin altında, geçersiz girdi. Ret mesajı çifti ve
  ilgili değeri adlandırır. Reddedilen öneri için hiçbir miktar üretilmez. Birden fazla sorun varsa tek
  neden döner, şu sırayla ilk geçerli olan: geçersiz girdi → alım dışı yön → beyaz liste dışı çift →
  geçersiz giriş → geçersiz/eksik stop → pozisyon limiti dolu → borsa asgarisinin altında.
- R-9: Hiçbir girdi için onaylanan bir öneri R-2…R-7'den birini ihlal edemez (`docs/domain.md`, Key domain
  invariants: hiçbir kod yolu sabit risk üst sınırlarını aşamaz).

## User experience
none — no user interface. (Önerileri `strategy` üretir, onaylı miktarı `execution` kullanır; ikisi de
sonraki spec'lerde bağlanır. Sahibin göreceği tek yüzey ret mesajlarıdır.)

## Constraints & out of scope
- Sensitive area: Risk limitleri (`risk`) — `docs/domain.md`. `risk` modülü için %90 branch coverage eşiği
  geçerlidir; kurallar `hypothesis` property testleriyle de kanıtlanır (`docs/testing.md`).
- Spec 0002'den ders (A-5, B-4): AC-10 property testi, her onay için beklenen sonucu bağımsız hesaplayan bir
  model (oracle) ile karşılaştırır; yalnızca "ihlal yok" demek yetmez, miktarın en büyük olduğu da sınanır.
- Out of scope: pozisyon kapatan satış (sonraki spec "kapanış her zaman serbest" kuralıyla); açığa satış
  zaten yok (BR-2).
- Out of scope: günlük zarar ve drawdown limitlerinin canlı hesaplanması ve aşımda işlem durdurulması
  (BR-5, BR-6), maliyet/kâr eşiği (BR-8), belirsiz durum kuralı (BR-11), kill switch — spec 0004 adayı.
- Out of scope: slippage; ücret yalnızca taker ücretidir. Bilinen eksik: gerçek kayıp slippage kadar risk
  bütçesini aşabilir; maliyet modeli BR-8 ile gelir.
- Out of scope: girdilerin gerçek kaynakları — kasa, serbest bakiye ve açık pozisyonlar (`portfolio`), beyaz
  liste ve ücretin config'ten yüklenmesi, çift kurallarının borsadan çekilmesi (`market_data`/`execution`),
  önerinin `strategy`'den gelmesi, onaylı emrin gönderilmesi ve kaydı. Bu spec yalnızca karar kuralını
  tanımlar; borsaya ve ağa bağlanmaz.
- Out of scope: "aynı çiftte tek pozisyon" kuralı — `docs/domain.md`'de yok; istenirse önce iş kuralı olarak
  eklenir (insan kararı).
- Yeni runtime bağımlılığı gerekirse plan gerekçesiyle önerir; insan onayı olmadan eklenmez (`docs/security.md`).
- Para/oran/fiyat/miktar değerleri `decimal.Decimal`, asla `float` (`docs/conventions.md`, Data rules).

## Acceptance criteria
- [ ] AC-1 — Mutlu yol: kasa `10000`, serbest bakiye `5000`, işlem başına risk `0.01`, giriş `100`, stop `95`,
  ücret `0.001`, adım `0.001`, asgari miktar `0.001`, asgari tutar `5`, açık pozisyon `0`, limit `5`,
  çift beyaz listede → onaylı miktar tam olarak `19.249`; serbest bakiyeyle sınırlanmadığı belirtilir. (R-5)
- [ ] AC-2 — Aşağı yuvarlama ve en büyüklük: AC-1'de onaylı miktarın kaybı (`99.998555`) risk bütçesi
  `100`'ü aşmaz, bir adım fazlası (`19.250`, kayıp `100.00375`) aşar. Kayıp tam olarak bütçeye eşit
  olduğunda o miktar onaylanır: kasa `10000`, serbest bakiye `5000`, risk `0.01`, giriş `100`, stop `90`,
  ücret `0` → miktar tam olarak `10`. (R-5)
- [ ] AC-3 — Serbest bakiye sınırı: AC-1 girdileri, serbest bakiye `1000` → onaylı miktar `9.990` ve sonuç
  serbest bakiyeyle sınırlandığını belirtir; serbest bakiye `0` → "borsa asgarisinin altında" reddi. (R-5, R-6)
- [ ] AC-4 — Borsa asgarisi: onaylı miktar asgari miktara veya miktar × giriş asgari tutara eşitse onaylanır;
  bir adım altıysa "borsa asgarisinin altında" nedeniyle reddedilir. (R-6)
- [ ] AC-5 — Stop zorunlu: stop yok, `0`, negatif, girişe eşit, girişin üstünde, `NaN`, sonsuz → "geçersiz
  stop" reddi; giriş `0`, negatif, `NaN`, sonsuz → "geçersiz giriş" reddi. Girişin çok altında (ör. `0.01`)
  stop kabul edilir. (R-3)
- [ ] AC-6 — Yön ve beyaz liste: satış önerisi "alım dışı yön"; beyaz listede olmayan, büyük/küçük harf veya
  boşluk farkı olan çift "beyaz liste dışı" nedeniyle reddedilir. (R-2)
- [ ] AC-7 — Pozisyon limiti: açık pozisyon = limit − 1 → onay; = limit veya üstü → "pozisyon limiti dolu"
  reddi; aynı çiftte açık pozisyon olması tek başına ret nedeni değildir. (R-4)
- [ ] AC-8 — Geçersiz girdiler: kasa `0`/negatif, serbest bakiye negatif, açık pozisyon negatif veya tam
  sayı olmayan, serbest bakiye kasadan büyük, ücret negatif veya `≥ 1`, adım `0`, sonsuz/`NaN` değerler,
  sabit üst sınırı aşan ya da geçersiz bir risk limiti → "geçersiz girdi" reddi ve geçersiz girdi
  adlandırılır. (R-7)
- [ ] AC-9 — Her ret nedeninde miktar üretilmez ve mesaj çifti ve ilgili değeri adlandırır; birden fazla
  sorunu olan öneride R-8'deki sıradaki ilk neden döner (ör. satış yönlü ve stop'suz öneri → "alım dışı
  yön"; geçersiz kasa ve beyaz liste dışı çift → "geçersiz girdi"). (R-8)
- [ ] AC-10 — Property testi: rastgele öneri ve girdiler için sonuç, beklenen sonucu bağımsız hesaplayan
  modelle aynıdır; onaylanan her öneride stop'ta ücret dahil kayıp ≤ kasa × işlem başına risk, alış tutarı
  ücret dahil ≤ serbest bakiye, miktar adımın katı ve asgarilerin üstünde, stop < giriş, çift beyaz listede,
  açık pozisyon < limit; ve bir adım fazlası bu sınırlardan birini ihlal eder. (R-5, R-9)

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
