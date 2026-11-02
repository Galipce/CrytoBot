# Spec 0007 — Portföy defteri: dolan paper alımlardan bakiye, pozisyon ve kasa

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0007-plan.md`

## Intent
CrytoBot'un sahibi, paper modda dolan her alımın hesaba yansımasını istiyor. Bugün emir oluşuyor ama bakiye, pozisyon
ve kasa hiçbir yerde tutulmuyor; risk onayı (BR-4, BR-7) ve zarar/drawdown takibi (BR-5, BR-6) elle verilen
sayılarla çalışıyor. `portfolio`, bir başlangıç yatırmasıyla açılan ve her dolan alımı silinmez bir kayıt olarak
yazan bir defter tutar. Defterden serbest bakiye, açık pozisyonlar ve güncel fiyatlarla değerlenmiş kasa türetilir;
`risk` bu hesap durumunu kullanabilir. Başarı: defterden türetilen hesap durumu her an kayıtlarla tutarlıdır, hiçbir
kayıt bakiyeyi negatife düşürmez, aynı emir iki kez yazılmaz, hiçbir girdi istisna fırlatmaz. Bilerek yapılmayanlar:
satış ve pozisyonun kapatılması, gerçekleşen kâr/zarar, kalıcı saklama, canlı borsa bakiyesiyle mutabakat, botun
döngüsüne bağlama.

## Requirements
- R-1: Defter boş başlar ve önce bir **başlangıç yatırmasıyla** açılır: çağıranın verdiği USDT tutarı (varsayılan
  yok). Açılış defterin ilk kaydıdır ve zamanını (UTC) taşır. Açılmamış deftere dolum kaydı ve hesap durumu isteği
  "defter açılmamış" ile reddedilir; açık bir defteri yeniden açma isteği "defter zaten açık" ile reddedilir. Başka
  bir yatırma, çekme ya da transfer kaydı yoktur (para çekme hiçbir kod yolunda yoktur).
- R-2: Dolum kaydı isteği, dolan bir alımın şu bilgilerini taşır: `clientOrderId`, çift, yön, miktar, dolum fiyatı,
  komisyon (USDT), stop, hedef ve dolum zamanı. Yalnızca dolan alımlar kayda geçer; reddedilen ya da durumu
  bilinmeyen bir emir, dolduğu netleşene kadar çağıran tarafından deftere verilmez (spec 0006 R-8, R-9). Dolum
  zamanı açılış zamanından önce olamaz ("geçersiz girdi"); dolumlar arasında zaman sırası aranmaz (durumu
  bilinmeyen bir emir geç netleşebilir). Defter stop, maliyet ve hedef arasındaki ilişkiyi yeniden denetlemez; bu
  `risk`'in kararıdır (BR-3, spec 0005).
- R-3: Yalnızca alım (`buy`) desteklenir. Yön `buy` değilse istek "desteklenmeyen yön" ile reddedilir ve defter
  değişmez.
- R-4: Kabul edilen dolum kaydı iki etki yapar: USDT bakiyesi miktar × dolum fiyatı + komisyon kadar azalır; yeni bir
  **pozisyon** açılır. Her dolum ayrı bir pozisyondur (aynı çiftteki iki dolum iki pozisyondur); pozisyon
  `clientOrderId`'yi, çifti, miktarı, maliyet fiyatını (dolum fiyatı), stop'u, hedefi ve açılış zamanını taşır.
  Hesap tam aritmetikle yapılır, yuvarlanmaz.
- R-5: USDT bakiyesi hiçbir zaman negatife düşmez (BR-2: spot, kaldıraçsız). Miktar × dolum fiyatı + komisyon güncel
  USDT bakiyesini aşıyorsa istek "yetersiz bakiye" ile reddedilir; mesaj gereken tutarı ve bakiyeyi adlandırır.
  Tam eşitlik kabul edilir (bakiye sıfır olur).
- R-6: **Tekrar koruması:** aynı `clientOrderId` ile bir dolum zaten kayıtlıysa yeni kayıt oluşmaz:
  - içerik (çift, yön, miktar, dolum fiyatı, komisyon, stop, hedef) aynıysa sonuç "zaten kayıtlı"dır, mevcut
    pozisyon olduğu gibi döner;
  - içerik farklıysa istek "kayıt çakışması" ile reddedilir; mevcut kayıt değişmez.
  Dolum zamanı içerik değildir. Reddedilmiş bir istek `clientOrderId`'yi tüketmez.
- R-7: **Hesap durumu:** açık bir defterden, çağıranın verdiği çift başına güncel fiyatlarla şunlar türetilir: serbest
  bakiye (= USDT bakiyesi), açık pozisyon sayısı ve kasa (= USDT bakiyesi + her pozisyonun miktarı × çiftinin güncel
  fiyatı). Açık pozisyonu olan bir çiftin fiyatı verilmemişse ya da geçersizse kasa hesaplanmaz: istek "fiyat eksik"
  ile reddedilir ve eksik çiftler adlandırılır (BR-11'in güvenli tarafı; kasa bilinmeden yeni işlem açılmaz).
  Pozisyonu olmayan çiftlerin fiyatları yok sayılır; pozisyon yoksa fiyat gerekmez. Fiyatlar çift → fiyat eşlemesi
  olarak verilir; eşleme değilse "geçersiz girdi". Hesap durumu açık pozisyonları da eklenme sırasıyla verir. Hesap
  durumu yalnızca kayıtlardan ve verilen fiyatlardan türer; zaman girdisi taşımaz.
- R-8: Hesap durumu `risk`'in beklediği hesap girdisidir: kasa, serbest bakiye ve açık pozisyon sayısı spec 0003'ün
  onayına, kasa spec 0004'ün kasa gözlemine aynen verilebilir. Defterden gelen durumla yapılan onay ve gözlem, aynı
  değerleri elle veren onay ve gözlemle aynı sonucu verir.
- R-9: **Silinmez defter:** kayıtlar eklendikleri sırayla tutulur; hiçbir kayıt değiştirilmez ya da silinmez;
  düzeltme yeni bir kayıtla yapılır (domain invariant). Defter değişmez bir değerdir: her kabul edilen istek yeni bir
  defter döndürür; reddedilen istek defteri değiştirmez.
- R-10: Ret sırası: geçersiz girdi → defter açılmamış / defter zaten açık → zaten kayıtlı / kayıt çakışması →
  desteklenmeyen yön → yetersiz bakiye. Birden fazla sorun varsa bu sıradaki ilki döner.
- R-11: Sayı ve girdi kuralları spec 0006 R-12 ile aynıdır: başlangıç tutarı, miktar, dolum fiyatı, stop, hedef ve
  güncel fiyatlar sıfırdan büyük; komisyon negatif olmayan; hepsi sonlu `Decimal`/`int` (mantıksal değer ve kayan
  nokta hariç), üssü varsayılan aralıkta (±999999) ve en fazla 28 anlamlı basamaklı olmalıdır; `clientOrderId`
  1–36 karakterlik, yalnızca ASCII harf, rakam, `-` ve `_` içeren bir metin; çift ve yön metin; zamanlar zaman dilimi
  taşımalıdır. Değilse "geçersiz girdi", girdi adlandırılır. Tam sonucu 28 basamağa sığmayan bir hesap
  yuvarlanmaz, "geçersiz girdi: ölçek hesaplanamıyor" ile reddedilir (spec 0006 Risk 3). Hiçbir girdi için defter
  istisna fırlatmaz; ret mesajı ham girdiyi istisnasız ve kısa yazar (uzun sayı basamak sayısıyla, spec 0006 F-4).

## User experience
none — no user interface. (Bakiye ve pozisyonların CLI/Telegram'dan görüntülenmesi `control` ve `reporting`
spec'lerinde gelir.)

## Constraints & out of scope
- Sensitive area: Portföy / defter (`portfolio`) — `docs/domain.md`. `portfolio` için %90 branch coverage; bakiye,
  pozisyon ve kasa kuralları `hypothesis` property testleriyle ve bağımsız bir beklenen-sonuç modeliyle (oracle,
  `Fraction`) kanıtlanır (spec 0003–0006 dersi). `risk` ve `execution` değişmez.
- Kalıcılık: defter bellekte, değişmez bir değerde tutulur. Yeniden başlatma sonrası defterin korunması **kapsam
  dışıdır**; kalıcı depo (SQLite) ayrı spec'te gelir.
- Bağlantı: dolan emrin deftere verilmesi, hesap durumunun risk onayına ve gözlemine verilmesi `app`'in işidir; bu
  spec yalnızca defterin davranışını ve risk girdisiyle uyumunu (R-8) tanımlar.
- Komisyon birimi: paper'da USDT (spec 0006). Gerçek spot alımında komisyonun alınan coinden kesilmesi live spec'inde
  ele alınır.
- Out of scope: satış ve pozisyonun stop/hedefte kapatılması, gerçekleşen ve gerçekleşmemiş kâr/zarar raporu, kasa
  geçmişi, ek yatırma/çekme, canlı borsa bakiyesiyle mutabakat (BR-11 "bakiye mutabakatı tutmuyor" tetikleyicisi),
  fiyatın bayatlığı (BR-11 "veri bayat"), kalıcı saklama, döngüye bağlama, birden fazla para birimi (yalnızca USDT
  çiftleri, BR-2).
- Boyut: tek spec. Split değerlendirildi (12 kabul kriteri); tek tutuldu — yetenek tektir (dolumu yaz, hesap
  durumunu türet) ve ret akışı ortaktır (Galip Badem, 2026-11-02, self-critique G-1).
- Yeni runtime bağımlılığı gerekirse plan gerekçesiyle önerir; insan onayı olmadan eklenmez (`docs/security.md`).
- Para/oran değerleri `decimal.Decimal`; zaman damgaları UTC, timezone-aware; zaman enjekte edilir
  (`docs/conventions.md`, Data rules).

## Acceptance criteria
- [ ] AC-1 — Açılış: boş defter 10000 USDT ile açılır → serbest bakiye 10000, kasa 10000, açık pozisyon 0; fiyat
  verilmeden hesap durumu oluşur (R-1, R-7).
- [ ] AC-2 — Dolum: spec 0006 AC-1'in dolumu (`cb-s1-btc-0001`, BTC/USDT, `buy`, 19.249 @ 100.1, komisyon 1.9268249,
  stop 95, hedef 110) → USDT 8071.2482751, bir pozisyon (maliyet 100.1, stop, hedef, `clientOrderId`, açılış
  zamanı); BTC fiyatı 105 ile kasa 10092.3932751 (R-4, R-7).
- [ ] AC-3 — Aynı çiftte iki dolum → iki ayrı pozisyon, açık pozisyon 2, hesap durumu ikisini eklenme sırasıyla
  verir; kasa iki pozisyonun değerini toplar; farklı çiftlerde her çift kendi fiyatıyla değerlenir (R-4, R-7).
- [ ] AC-4 — Fiyat: açık pozisyonu olan çiftin fiyatı yok, sıfır, negatif, `NaN` ya da kayan nokta → "fiyat eksik",
  çift adlandırılır; pozisyonu olmayan çiftin fiyatı yok sayılır (geçersiz olsa da) (R-7).
- [ ] AC-5 — Bakiye: tutar + komisyon USDT bakiyesini aşan dolum → "yetersiz bakiye", gereken tutar ve bakiye
  adlandırılır, defter değişmez; tam eşit dolum kabul, USDT 0 (R-5).
- [ ] AC-6 — Tekrar: aynı `clientOrderId` ve içerik, farklı zaman → "zaten kayıtlı", tek pozisyon; çift, yön, miktar,
  dolum fiyatı, komisyon, stop ya da hedef farklı → "kayıt çakışması", kayıt değişmez; reddedilmiş bir istek
  kimliği tüketmez (R-6).
- [ ] AC-7 — Açılış kuralları: açılmamış deftere dolum ve hesap durumu isteği → "defter açılmamış"; ikinci açılış →
  "defter zaten açık"; satış yönlü dolum → "desteklenmeyen yön" (R-1, R-3).
- [ ] AC-8 — Geçersiz girdi: başlangıç tutarı, miktar, dolum fiyatı, stop, hedef 0/negatif/`NaN`/kayan nokta/mantıksal
  değer/aralık dışı üs/29 anlamlı basamak; negatif komisyon; biçime uymayan `clientOrderId` (boş, 37 karakter,
  boşluk, Unicode, metin değil); metin olmayan çift ya da yön; zaman dilimi taşımayan zaman; açılıştan önceki
  dolum zamanı; eşleme olmayan fiyat girdisi; negatif dev `int` (`-(10**4300)`) → "geçersiz girdi", girdi
  adlandırılır, istisna yok; pozitif `10**4300` tek anlamlı basamaklı ve ölçek içidir, R-11'e göre geçerlidir:
  açılış "açıldı", stop ya da hedefte "kaydedildi", miktarda "ölçek hesaplanamıyor", istisna yok (plan A-1,
  backlog B-15); dolum ya da kasa hesabı 28 basamağa sığmayan girdi → "ölçek hesaplanamıyor"; uzun sayı mesajda
  basamak sayısıyla, mesaj kısa (R-2, R-7, R-11).
- [ ] AC-9 — Ret sırası: geçersiz girdi + açılmamış defter → "geçersiz girdi"; tekrar eden kimlik + satış yönü →
  "zaten kayıtlı"/"kayıt çakışması"; satış yönü + yetersiz bakiye → "desteklenmeyen yön" (R-10).
- [ ] AC-10 — Silinmez defter: yeni kayıt eklendikten sonra önceki kayıtlar ve sıraları aynıdır; reddedilen her istek
  defteri aynen bırakır (R-9).
- [ ] AC-11 — Risk girdisi: defterden türetilen hesap durumuyla spec 0003 onayı ve spec 0004 gözlemi, aynı değerleri
  elle veren çağrılarla birebir aynı sonucu verir; beş açık pozisyonlu defterin durumu spec 0003'ün pozisyon
  limiti reddini doğurur (R-8).
- [ ] AC-12 — Property: rastgele açılış, dolum ve hesap durumu dizilerinde (bağımsız `Fraction` modeliyle birebir)
  USDT hiçbir zaman negatif değildir, USDT = açılış − Σ(miktar × dolum fiyatı + komisyon), pozisyonlar kabul edilen
  dolumlardır, kasa modelle aynıdır, hiçbir girdi istisna fırlatmaz; her sonuç türü yeterince üretilir (boş geçmez)
  (R-4…R-11).

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
