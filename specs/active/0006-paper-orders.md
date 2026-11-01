# Spec 0006 — Onaylı öneriden paper emir ve belirsiz emir durumunda güvenli mod

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0006-plan.md`

## Intent
CrytoBot'un sahibi, `risk`'in onayladığı bir alım önerisinin emre dönüştüğü ilk yolu istiyor — yalnızca paper modda.
`execution`, risk onayından geçmiş bir öneriden simüle edilmiş bir piyasa alımı oluşturur; onaysız, borsa kurallarına
uymayan ya da daha önce emre dönüşmüş bir öneri ikinci bir emir doğurmaz (BR-9). Bunun için risk onayı,
onayladığı öneriyi de taşır; başka bir öneri için verilmiş onayla emir oluşmaz. Bir emrin durumu bilinmiyorsa bot
durum netleşene kadar hiçbir yeni emir oluşturmaz ve bunu bir bildirimle haber verir (BR-11). Başarı: onaysız,
kurala aykırı ya da tekrar eden hiçbir öneri emre dönüşmez; belirsizlik varken yeni emir çıkmaz; hiçbir girdi
istisna fırlatmaz. Bilerek yapılmayanlar: live emir ve gerçek borsa bağlantısı, limit emir ve kısmi dolum, pozisyonun
stop/hedefte kapatılması, bakiye ve defter güncellemesi (`portfolio`), emir kayıtlarının kalıcı saklanması,
bildirimin Telegram'a gönderilmesi, BR-11'in "veri bayat" ve "bakiye mutabakatı tutmuyor" tetikleyicileri.

## Requirements
- R-1: Emir oluşturma isteği şunları taşır: işlem önerisi (spec 0003/0005: çift, yön, giriş, stop, hedef), o
  öneriye verilmiş risk onayı (spec 0003 R-1: miktar ya da ret), çağıranın verdiği **öneri kimliği**, çiftin borsa
  kuralları (miktar adımı, asgari miktar, asgari tutar), güncel fiyat, komisyon oranı, slippage oranı, mod ve şu
  anki zaman.
- R-2: Emir yalnızca **onaylanmış** bir öneriden oluşur (BR-9). Şu durumlarda istek "onaysız öneri" ile reddedilir ve
  emir oluşmaz: onay bir ret taşıyor; onaylı miktar sıfırdan büyük bir sayı değil; istekteki öneri, onayın taşıdığı
  öneriyle (çift, yön, giriş, stop, hedef) birebir aynı değil.
- R-3: Yalnızca paper mod desteklenir. Mod `paper` değilse (ör. `live`, `backtest`, bilinmeyen değer) istek "mod
  desteklenmiyor" ile reddedilir ve emir oluşmaz; hiçbir yol gerçek bir borsaya emir göndermez.
- R-4: Borsa kuralları emir miktarı üzerinde son kapı olarak denetlenir; miktar **yuvarlanmaz** (yukarı da aşağı da):
  miktar miktar adımının tam katı değilse, asgari miktarın altındaysa ya da dolum fiyatıyla tutarı (miktar × dolum
  fiyatı) asgari tutarın altındaysa istek "borsa kuralı" ile reddedilir; mesaj ihlal edilen kuralı, miktarı ve
  kuralın değerini adlandırır. Asgariye eşit değer geçerlidir.
- R-5: Paper emir bir **piyasa alımıdır** ve simülatörde anında dolar: dolum fiyatı = güncel fiyat × (1 + slippage
  oranı); komisyon = miktar × dolum fiyatı × komisyon oranı (USDT). Hesap tam aritmetikle yapılır, yuvarlanmaz.
- R-6: Öneri kimliği 1–32 karakterlik bir metindir ve yalnızca ASCII harf, rakam, `-` ve `_` içerir; değilse istek
  "geçersiz girdi" ile reddedilir. Emrin `clientOrderId`'si `cb-` + öneri kimliğidir: aynı kimlik → aynı
  `clientOrderId`, farklı kimlik → farklı `clientOrderId` (birebir); en fazla 35 karakter, borsaların ortak sınırı
  (36 karakter, harf/rakam/`-`/`_`) içinde.
- R-7: **Tekrar koruması:** aynı öneri kimliğiyle bir emir zaten varsa yeni emir oluşmaz:
  - istek içeriği (çift, yön, giriş, stop, hedef, onaylı miktar) mevcut emirle aynıysa mevcut emir, "zaten var"
    sonucuyla olduğu gibi döner (durumu ne olursa olsun);
  - içerik farklıysa istek "kimlik çakışması" ile reddedilir; mevcut emir değişmez.
  Güncel fiyat, oranlar, mod ve zaman içerik değildir: yeniden denemede değişmeleri çakışma sayılmaz. Reddedilmiş
  bir istek (emir oluşmamışsa) kimliği tüketmez; aynı kimlikle sonraki geçerli istek emir oluşturur.
- R-8: Her emrin durumu `dolu`, `reddedildi` ya da `bilinmiyor`'dur. Emir kaydı `clientOrderId`'yi, öneri
  kimliğini, çifti, yönü, miktarı, dolum fiyatını ve komisyonu (dolu ise), öneriden stop ve hedefi, durumu ve
  oluşturma zamanını (UTC) taşır.
- R-9: **Güvenli mod (BR-11):** en az bir emrin durumu `bilinmiyor` iken her yeni emir isteği "durum belirsiz" ile
  reddedilir; ret mesajı durumu bilinmeyen emirlerin `clientOrderId`'lerini adlandırır. Güvenli mod, durumu
  bilinmeyen son emir netleşince (sorgu sonucu `dolu` ya da `reddedildi`) kendiliğinden sona erer; insan onayı
  gerekmez. Paper simülatörü, bir emri `bilinmiyor` ya da `reddedildi` olarak döndürecek ve sonraki sorguda gerçek
  durumunu verecek şekilde ayarlanabilir. Sorgu kuralları: kayıtlı olmayan `clientOrderId` → "bilinmeyen emir"
  reddi, durum değişmez; sorgu sonucu yine `bilinmiyor` → durum ve güvenli mod aynen sürer, bildirim yok; zaten
  netleşmiş emir → değişiklik yok, bildirim yok.
- R-10: **Bildirim:** güvenli moda giriş ve güvenli moddan çıkış birer bildirim kaydı üretir (her geçişte bir kez;
  güvenli moddayken reddedilen her istek için ayrıca bildirim yok). Bildirim ne olduğunu, ilgili `clientOrderId`'yi,
  çifti ve zamanı (UTC) taşır ve sonuçla birlikte döner; gönderimi `reporting`'in işidir.
- R-11: Ret sırası: geçersiz girdi → mod desteklenmiyor → (aynı kimlik varsa) zaten var / kimlik çakışması → durum
  belirsiz → onaysız öneri → borsa kuralı. Birden fazla sorun varsa bu sıradaki ilki döner.
- R-12: Sayı kuralları spec 0003 R-7 ve spec 0005 R-7 ile aynıdır: güncel fiyat sıfırdan büyük, komisyon ve slippage
  oranı 0 ile 1 arasında (1 hariç), adım sıfırdan büyük, asgariler negatif olmayan sonlu `Decimal`/`int`
  (mantıksal değer ve kayan nokta hariç) ve üssü varsayılan aralıkta (±999999) olmalıdır; şu anki zaman zaman
  dilimi taşımalıdır; değilse "geçersiz girdi", girdi adlandırılır. Ayrıca emir miktarı ve güncel fiyat en fazla 28 anlamlı basamak taşır (gerçek borsa
  değerlerinin tümü sığar); fazlası "geçersiz girdi" ile reddedilir (B-11, execution tarafı). Hiçbir girdi için
  emir isteği istisna fırlatmaz; ret mesajı ham girdiyi istisnasız yazar (spec 0005 `_show` dersi).
- R-13: Durum ve emir kayıtları değişmez değerlerdir: her istek ve sorgu yeni bir durum döndürür; reddedilen istek
  ve başarısız sorgu durumu değiştirmez.
- R-14: Risk onayı (spec 0003 R-1) onayladığı ya da reddettiği öneriyi değiştirmeden taşır. Onayın diğer davranışı
  (karar, miktar, ret nedeni ve sırası, mesajlar) değişmez.

## User experience
none — no user interface. (Bildirimlerin Telegram'a gönderimi ve emirlerin CLI'den görüntülenmesi `reporting` ve
`control` spec'lerinde gelir.)

## Constraints & out of scope
- Sensitive area: Emir gönderimi (`execution`), Paper ↔ live mod anahtarı ve Risk limitleri (`risk`, R-14) —
  `docs/domain.md`. `execution` ve `risk` için ayrı ayrı %90 branch coverage; tekrar koruması, güvenli mod ve "onaysız emir yok" `hypothesis` property testleriyle ve bağımsız
  bir beklenen-sonuç modeliyle (oracle) kanıtlanır (spec 0003/0004/0005 dersi).
- Kalıcılık: emir kayıtları ve güvenli mod bellekte, değişmez bir durum değerinde tutulur. Yeniden başlatma sonrası
  tekrar koruması ve güvenli modun korunması **kapsam dışıdır**; kalıcı depo (SQLite) ayrı spec'te gelir (B-10 de
  onu bekliyor).
- Supersedes (genişletir): 0003 R-1 — onay sonucu onayladığı öneriyi de taşır (R-14). Spec 0002–0005'in kabul
  kriterleri korunur (AC-12); `specs/done/` içindeki dosyalar değiştirilmez.
- Komisyon birimi: paper'da USDT. Gerçek spot alımında borsalar komisyonu çoğu zaman alınan coinden keser; birim
  live spec'inde yeniden ele alınır.
- Boyut: tek spec. Split değerlendirildi; tek tutuldu — güvenli mod emir isteğinin ret nedenlerinden biridir,
  ayırmak aynı akışı iki kez değiştirmek olurdu (Galip Badem, 2026-11-01, self-critique G-7).
- BR-11 kapsamı: yalnızca "emir durumu bilinmiyor" tetikleyicisi. "Veri bayat" (`market_data`) ve "bakiye mutabakatı
  tutmuyor" (`portfolio`) kendi spec'lerinde gelir.
- Backlog: B-11'in execution tarafı (emir miktarının uzunluğu) R-12 ile kapanır; B-11 açık kalır ama risk tarafına
  (onaylı miktarın `_size`'ta üretim süresi ve mesaj uzunluğu) daraltılır — backlog satırı bu spec'in parçası olarak
  güncellenir.
- Out of scope: live adaptör ve gerçek borsa/ccxt çağrısı, testnet, limit emir, kısmi dolum, satış/çıkış emri
  (stop ve hedef yalnızca kayda yazılır), pozisyonun izlenmesi, bakiye/defter güncellemesi, emirlerin kalıcı
  saklanması, bildirimin gönderimi, `strategy`'nin öneri kimliğini nasıl ürettiği, kill switch (`risk`/`control`),
  B-6.
- Yeni runtime bağımlılığı gerekirse plan gerekçesiyle önerir; insan onayı olmadan eklenmez (`docs/security.md`).
- Para/oran değerleri `decimal.Decimal`; zaman damgaları UTC, timezone-aware; zaman enjekte edilir
  (`docs/conventions.md`, Data rules).

## Acceptance criteria
- [ ] AC-1 — Spec 0005 AC-1'in onaylı önerisi (miktar 19.249), güncel fiyat 100, slippage 0.001, komisyon 0.001, mod
  paper → durum `dolu`, miktar 19.249, dolum fiyatı 100.1, komisyon 1.9268249; kayıt öneri kimliğini, stop 95'i,
  hedef 110'u ve zamanı taşır (R-1, R-5, R-8).
- [ ] AC-2 — Onaysız öneri: ret taşıyan onay; elle kurulmuş miktarı yok/sıfır/negatif/`NaN` onay; BTC önerisi için
  verilmiş onayla ETH önerisi; aynı çiftte girişi, stop'u ya da hedefi farklı öneri → "onaysız öneri", emir oluşmaz,
  durum değişmez (R-2, R-13).
- [ ] AC-3 — Mod `live`, `backtest`, `"PAPER"`, boş → "mod desteklenmiyor", emir oluşmaz (R-3).
- [ ] AC-4 — Borsa kuralı: adımın katı olmayan miktar (19.2495, adım 0.001), asgari miktarın altı, dolum fiyatıyla
  asgari tutarın altı → "borsa kuralı", ihlal edilen kural ve değerler adlandırılır; asgari tutara tam eşit tutar
  kabul edilir; miktar hiçbir durumda değişmez (R-4).
- [ ] AC-5 — Tekrar: aynı kimlik ve içerikle ikinci istek → "zaten var", aynı emir (aynı `clientOrderId`), emir sayısı
  1; aynı kimlik ve içerik ama farklı güncel fiyat ve zamanla → "zaten var", dolum fiyatı ilk emirdeki gibi; aynı
  kimlik farklı miktar ya da hedefle → "kimlik çakışması", mevcut emir değişmez; ilk isteği reddedilmiş kimlikle
  geçerli istek → emir oluşur (R-7).
- [ ] AC-6 — `clientOrderId`: kimlik `a1-B_2` → `cb-a1-B_2`; aynı kimlik iki ayrı durumda aynı değeri verir; 32
  karakterlik kimlik kabul edilir (35 karakterlik `clientOrderId`); boş, 33 karakterlik, boşluklu, Unicode harfli,
  `.`/`/` içeren ya da metin olmayan kimlik → "geçersiz girdi" (R-6).
- [ ] AC-7 — Güvenli moda giriş: simülatör emri `bilinmiyor` döndürür → emir `bilinmiyor` durumunda kaydedilir, tek
  bir giriş bildirimi üretilir; sonraki farklı kimlikli istek "durum belirsiz" ile reddedilir ve mesaj bilinmeyen
  emrin `clientOrderId`'sini adlandırır, yeni bildirim üretilmez; aynı kimlikle tekrar istek → "zaten var" (R-7, R-9,
  R-10, R-11).
- [ ] AC-8 — Güvenli moddan çıkış: sorgu emri `dolu` ya da `reddedildi` olarak netleştirir → durum güncellenir, tek bir
  çıkış bildirimi üretilir, sonraki istek emir oluşturur. İki emir `bilinmiyor` iken biri netleşince güvenli mod
  sürer, ikisi de netleşince biter. Sorgu yine `bilinmiyor` dönerse güvenli mod sürer, bildirim yok; kayıtlı olmayan
  `clientOrderId` sorgusu → "bilinmeyen emir", durum değişmez; netleşmiş emrin sorgusu → değişiklik yok (R-9, R-10).
- [ ] AC-9 — Simülatör emri `reddedildi` döndürür → emir `reddedildi`, güvenli mod yok, bildirim yok; aynı kimlikle
  tekrar → "zaten var" (R-7, R-8).
- [ ] AC-10 — Geçersiz girdi: güncel fiyat yok/0/negatif/`NaN`/kayan nokta/aralık dışı üs; komisyon ya da slippage
  aralık dışı; adım ya da asgariler geçersiz; 29 anlamlı basamaklı miktar ya da fiyat; `10**4300` gibi dev `int`;
  zaman dilimi taşımayan zaman → "geçersiz girdi", girdi adlandırılır, istisna yok (R-12).
- [ ] AC-11 — Property: rastgele istek ve sorgu dizileriyle (oracle ile birebir) onaysız ya da kurala aykırı hiçbir
  istek emir oluşturmaz; aynı kimlik hiçbir zaman ikinci bir emir oluşturmaz; `bilinmiyor` bir emir varken yeni emir
  oluşmaz; her güvenli mod geçişi tam bir bildirim üretir; hiçbir girdi istisna fırlatmaz; çıktı dağılımı ölçülür,
  boş geçmez (R-2, R-4, R-7, R-9, R-10, R-12).
- [ ] AC-12 — Risk onayı onayladığı ve reddettiği öneriyi değiştirmeden taşır; spec 0002, 0003, 0004 ve 0005'in kabul
  kriterleri aynen geçer (R-14, Supersedes).

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
