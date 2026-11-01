# Spec 0005 — Kâr / maliyet eşiği ve onay girdilerinin ölçeği

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0005-plan.md`

## Intent
CrytoBot'un sahibi, kazancı maliyete gidecek işlemlerin açılmasını istemiyor: strateji her alım önerisiyle bir hedef
fiyat da verir ve `risk`, hedefe ulaşıldığında birim başına elde edilecek kârın efektif maliyetin (komisyon + spread
+ tahmini slippage) config'teki katını geçmediği öneriyi adlandırılmış bir nedenle reddeder (BR-8). Kat bir risk
limitidir; güvenli yönü artırmak olduğu için Telegram'dan yalnızca yükseltilebilir. Aynı spec onayın her sayısal
girdisinin ölçeğini sınırlar — aşırı ölçekli girdi istisna değil adlandırılmış rettir (backlog B-8) — ve "ölçek
hesaplanamıyor" reddinin sorunlu değeri göstermesini sağlar (B-5). Başarı: eşiği geçmeyen hiçbir öneri onaylanmaz,
hiçbir girdi onaydan istisna fırlatmaz. Bilerek yapılmayanlar: spread/slippage'ın piyasadan ölçülmesi, hedef
fiyatın belirlenmesi (strateji), take-profit emri, BR-11, B-6.

## Requirements
- R-1: Bir alım önerisi, spec 0003'teki çift, yön, giriş ve stop'a ek olarak bir **hedef fiyat** taşır. Hedef yoksa,
  sayı değilse (`NaN`, sonsuz, kayan nokta ve mantıksal değerler dahil; spec 0003 R-7 ile aynı sayı kuralı) ya da
  girişten büyük değilse (eşit dahil) öneri "geçersiz hedef" ile reddedilir.
- R-2: Onay, spec 0003'teki komisyon oranının yanında iki girdi daha alır: **spread oranı** ve **slippage oranı**
  (fiyata oran, `0.001` = %0,1). İkisi de 0 ile 1 arasında olmalıdır (0 dahil, 1 hariç); verilmemişse, sayı değilse
  ya da aralık dışındaysa öneri "geçersiz girdi" ile reddedilir ve hangi girdinin geçersiz olduğu adlandırılır.
  Varsayılan değer yoktur (eksik maliyet gizlice sıfır sayılmaz).
- R-3: Birim başına beklenen kâr = hedef − giriş. Birim başına efektif maliyet = (giriş + hedef) × komisyon oranı
  + giriş × spread oranı + (giriş + hedef) × slippage oranı (komisyon ve slippage iki bacakta, spread gidiş-dönüşte
  bir kez). Beklenen kâr, **kâr/maliyet katı** × efektif maliyetten büyük değilse (eşitlik dahil) öneri "yetersiz
  kâr beklentisi" ile reddedilir; ret mesajı çifti, beklenen kârı, efektif maliyeti ve katı adlandırır. Karşılaştırma
  tam aritmetikle yapılır; sınırda yuvarlama kararı değiştiremez. Kat, onaydaki limitlerden okunur: gün içinde
  değiştirilen kat bir sonraki onayda hemen etkilidir (spec 0004'teki günlük limit gibi).
- R-4: Kâr/maliyet katı beşinci risk limitidir (BR-8). Config'in `[risk]` tablosundan yüklenir; yazılmamışsa
  varsayılan `2`'dir ve yükleme sonucu bunu belirtir. Kodda sabit bir **alt** sınırı vardır: `1`. Alt sınıra eşit
  değer geçerlidir; altındaki değer, sayı olmayan değer ve spec 0002 R-4/R-5'teki diğer geçersiz değerler yüklemeyi
  reddeder ve mesaj limiti, değeri ve (alt sınır ihlalinde) alt sınırı adlandırır. Alt sınır hiçbir kanaldan
  değiştirilemez. Katın üst sınırı yoktur; ölçek kuralı (R-7) uygulanır.
- R-5: Katı değiştirme isteği spec 0002 R-6'daki gibi karara bağlanır, ancak yön terstir (güvenli yön artırmak):
  - yükseltme veya aynı değer: her kanaldan kabul;
  - düşürme: yalnızca CLI'den, en az alt sınıra kadar kabul; Telegram'dan reddedilir;
  - alt sınırın altındaki değer: her kanaldan reddedilir;
  - geçersiz değer, bilinmeyen limit adı ya da bilinmeyen kanal: reddedilir.
  Reddin nedeni adlandırılır. Katın üst sınırı olmadığından onun için "üst sınır aşımı" nedeni hiç oluşmaz; alt
  sınır ihlali kendi nedeniyle adlandırılır. Diğer dört limitin kuralı değişmez.
- R-6: Ret sırası spec 0003 R-8 ve spec 0004 R-7'deki gibidir; iki yeni neden "geçersiz stop"tan sonra, "pozisyon
  limiti"nden önce gelir: geçersiz girdi → drawdown durdurması → günlük zarar limiti → alım dışı yön → beyaz liste
  dışı çift → geçersiz giriş → geçersiz stop → **geçersiz hedef** → **yetersiz kâr beklentisi** → pozisyon limiti →
  borsa asgarisi.
- R-7: Onayın her sayısal girdisinin üssü varsayılan ondalık aralığında (±999999, spec 0004 A-2 ile aynı) olmalıdır;
  değilse öneri adlandırılmış bir nedenle reddedilir ve hiçbir girdi için onay istisna fırlatmaz: giriş → "geçersiz
  giriş", stop → "geçersiz stop", hedef → "geçersiz hedef", diğerleri (kasa, serbest bakiye, komisyon, spread,
  slippage, miktar adımı, asgari miktar, asgari tutar) → "geçersiz girdi". Mesaj değeri ve aralığı adlandırır.
- R-8: Aralık içindeki girdilerle hesap yine de temsil edilemeyen bir sonuca varırsa öneri spec 0003'teki "ölçek
  hesaplanamıyor" (geçersiz girdi) ile reddedilir; mesaj hesaba giren tüm değerleri (giriş, stop, hedef, komisyon,
  spread, slippage, serbest bakiye, miktar adımı, kasa) adlandırır (B-5).
- R-9: Spec 0003'ün boyutlama kuralı (R-5, R-6) değişmez: onaylanan miktar spread ve slippage'dan etkilenmez; eşik
  yalnızca onay/ret kararıdır.
- R-10: Hiçbir girdi için onaylanan bir öneri R-1…R-3'ü ya da spec 0003/0004'ün kurallarını ihlal edemez; Telegram'dan
  gelen hiçbir istek katı düşüremez (`docs/domain.md`, Key domain invariants).

## User experience
none — no user interface. (Ret mesajlarının sahibe gösterilmesi ve gerçek CLI/Telegram komutları `control`
spec'inde gelir.)

## Constraints & out of scope
- Sensitive area: Risk limitleri (`risk`) — `docs/domain.md`. `risk` için %90 branch coverage; kural `hypothesis`
  property testleriyle ve bağımsız bir beklenen-sonuç modeliyle (oracle) kanıtlanır (spec 0003/0004 dersi).
- Supersedes (genişletir): 0002 R-1, R-2, R-6, R-7 (beşinci limit; üst değil alt sınır; ters yönlü kanal kuralı;
  değişmez "Telegram limiti gevşetemez" olarak genelleşir), 0003 R-1, R-7, R-8 (hedef fiyat, iki yeni girdi, ölçek
  kuralı, iki yeni ret nedeni), B-5'in "ölçek hesaplanamıyor" mesajı. Spec 0002/0003/0004'ün kabul kriterleri
  korunur (AC-10); `specs/done/` içindeki dosyalar değiştirilmez.
- Domain dili: BR-13 bugün "risk limitleri Telegram'dan yalnızca düşürülebilir" diyor; bu limitte güvenli yön
  artırmak olduğundan `docs/domain.md` BR-13 "yalnızca sıkılaştırılabilir" anlamına güncellenir (insan onayıyla, bu
  spec'in parçası).
- Backlog: B-8 ve B-5 bu spec'le kapanır. B-6 (hash'lenemeyen çift) kapsam dışıdır; `approve_trade`'i `strategy`'ye
  bağlayan spec'te kapanır. Spec 0002 R-4'teki "oranların alt sınırı yoktur" kuralı limitler için korunur; ölçek
  kuralı (R-7) onay girdilerine ve katın kendisine uygulanır; plan, aşırı küçük diğer limitlerin (ör. işlem başına
  risk `1E-999999999`) sınırsız bir hesaba yol açmadığını testle gösterir.
- Hedefin gerçekçiliği (girişten ne kadar uzak olduğu) için ek kural yoktur; bu stratejinin işidir. Aşırı uzak hedef
  ölçek kuralı (R-7) ve "ölçek hesaplanamıyor" (R-8) ile karşılanır.
- Boyut: tek spec. Ölçek (R-7, R-8) ve eşik aynı onayın aynı girdilerine dokunur; bölmek aynı doğrulamayı iki kez
  değiştirmek olurdu (self-critique, 2026-11-01).
- Out of scope: spread ve slippage'ın piyasa verisinden ölçülmesi (çağıran doldurur), hedef fiyatın nasıl
  belirlendiği (strateji), take-profit/çıkış emri (execution), slippage'ın stop'taki kayba (risk bütçesine)
  eklenmesi, BR-11, gerçek CLI/Telegram komutları, TOTP/teyit.
- Yeni runtime bağımlılığı gerekirse plan gerekçesiyle önerir; insan onayı olmadan eklenmez (`docs/security.md`).
- Para/oran değerleri `decimal.Decimal`; zaman damgaları UTC, timezone-aware (`docs/conventions.md`, Data rules).

## Acceptance criteria
- [ ] AC-1 — Giriş 100, stop 95, hedef 110, komisyon 0.001, spread 0.0005, slippage 0.001, kat 2: efektif maliyet
  0.47, eşik 0.94, kâr 10 → öneri onaylanır; spec 0003 AC-1'in kasa, serbest bakiye ve çift kurallarıyla miktar
  aynıdır (19.249) (R-3, R-9).
- [ ] AC-2 — Sınır: giriş 100, komisyon 0, slippage 0, spread 0.005, kat 2 (maliyet 0.5, eşik 1): hedef 101 → "yetersiz
  kâr beklentisi" (eşitlik), hedef 101.01 → onay; ret mesajı çifti, kârı, maliyeti ve katı adlandırır (R-3).
- [ ] AC-3 — Hedef yok, `NaN`, sonsuz, kayan nokta, mantıksal değer, girişe eşit ya da girişten küçük → "geçersiz
  hedef" (R-1).
- [ ] AC-4 — Spread ya da slippage verilmemiş, negatif, 1 ya da üstü, `NaN`, kayan nokta → "geçersiz girdi", girdi
  adlandırılır; 0 geçerlidir (R-2).
- [ ] AC-5 — Ret sırası: geçersiz stop ve geçersiz hedef birlikte → "geçersiz stop"; geçersiz hedef ve pozisyon limiti
  dolu → "geçersiz hedef"; eşik altı ve pozisyon limiti dolu → "yetersiz kâr beklentisi"; günlük limit dolu ve eşik
  altı → "günlük zarar limiti" (R-6).
- [ ] AC-6 — Yükleme: kat yazılmamış → `2`, varsayılandan geldiği belirtilir; `1` geçerli; `0.99`, `0`, negatif, `NaN`,
  mantıksal değer, aralık dışı üs → yükleme reddedilir, mesaj limiti, değeri ve (alt sınırda) `1`'i adlandırır (R-4).
- [ ] AC-7 — Değiştirme: Telegram'dan yükseltme ve aynı değer kabul; Telegram'dan düşürme ret; CLI'den `1`'e düşürme
  kabul; `0.5` her kanaldan ret; bilinmeyen kanal ret; diğer dört limitin kuralı aynen (spec 0002 AC'leri). Aynı
  AC-1 önerisi kat 2 ile onaylanıp kat 25 ile (eşik 11.75) "yetersiz kâr beklentisi" alır — değişen kat hemen
  etkilidir (R-3, R-5).
- [ ] AC-8 — Ölçek: giriş, stop, hedef ve diğer her sayısal girdi için üssü aralığın hemen dışındaki değer (ör.
  `1E+1000000`, `1E-1000000`) kendi nedeniyle reddedilir, hemen içindeki değer ölçek yüzünden reddedilmez; stop
  `1E-999999999999` ve komisyon `1E-999999999999` (B-8 kanıtı) istisna değil adlandırılmış rettir (R-7).
- [ ] AC-9 — Aralık içinde ama hesabı temsil edilemeyen girdi (ör. giriş `9.999E+999999`) → "ölçek hesaplanamıyor";
  mesajda giriş değeri ve hesaba giren diğer değerler görünür (R-8).
- [ ] AC-10 — Spec 0002, 0003 ve 0004'ün kabul kriterleri, eşiği rahatça geçen bir hedef ve sıfır spread/slippage ile
  aynen geçer (R-9, Supersedes).
- [ ] AC-11 — Property: rastgele girdilerle, beklenen kârı kat × efektif maliyetten büyük olmayan hiçbir öneri
  onaylanmaz (karar `Fraction` ile bağımsız modelle birebir); hiçbir girdi istisna fırlatmaz; hiçbir Telegram isteği
  dizisi katı düşüremez; çıktı dağılımı ölçülür, boş geçmez (R-10).

## Definition of Done
- [ ] Every acceptance criterion mapped to proof (test or reproducible observation)
- [ ] `scripts/check` green
- [ ] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [ ] Docs / ADRs updated if behavior or architecture changed
- [ ] Spec moved to `specs/done/` (it becomes immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | 0 onay sonrası (sapmalar plan amendment A-1…A-3) |
| Fix rounds | 2 (fix-1 review r1, fix-2 review r2); review r3 fix turu getirmedi |
| Review findings: real / noise / deferred | 8 / 1 / 4 (r1: F-1, F-2, F-3, F-5 real; F-4 defer B-11; F-6 defer B-4 · r2: F-1, F-3, F-4 real; F-2 real (`_limits.py`) + `state.day` kısmı defer B-10 · r3: F-1, F-2 defer B-4; F-3 noise · VERIFY: gap yok; residue önerisi B-12) |
| Regressions introduced | 1 (fix-2: Telegram mesajında `Decimal(current)` elle kurulmuş `Fraction` limitte `TypeError` — r3 F-1, defer B-4) |
| Bugs escaped to production | 0 (henüz üretim yok) |
