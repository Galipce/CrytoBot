# Spec 0011 — SQLite kalıcılık: defter, emirler ve risk durumu yeniden başlatmada korunsun

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0011-plan.md`
- Self-critique: done
- Source: yol haritası (0008 bölme notu); 0004, 0006 ve 0007'nin kapsam dışı bıraktığı kalıcılık; backlog B-10, B-13
- Supersedes: 0004, 0006 ve 0007'nin "kalıcılık kapsam dışı" notları (genişletir). `specs/done/` dosyaları değişmez.

## Intent
Sistemin sahibi, bot yeniden başladığında parasal durumunun kaybolmamasını istiyor. Bugün defter, emirler ve risk durumu
yalnız bellekte duruyor; yeniden başlatma drawdown durdurmasını ve güvenli modu siliyor, tekrar korumasını kaldırıyor.
Başarı: kapanıp açılan bot aynı bakiyeyi, pozisyonları, emirleri ve durdurma durumunu birebir görür; durum güvenilir
okunamıyorsa boş durumla devam etmez ve yeni işlem açılmasına yol açmaz. Bilerek yapılmayanlar: `app` döngüsüne bağlama,
live, risk limitlerinin kalıcılığı (`control`), yedekleme ve şifreleme.

## Requirements
Terim: **kalıcı durum** defter, tüm emirler (durumu bilinmeyen emrin dolum tahmini dahil) ve risk durumunun birlikte
adıdır. **Depo** kalıcı durumun çağıranın verdiği dosya yolundaki kaydıdır; yolu çağıran verir.

- R-1: **Açık ilk kurulum:** depo yalnız açık bir kurulum çağrısıyla, bir modla (`paper` ya da `live`) oluşur ve boş kalıcı
  durumla başlar. Yol üzerinde dosya varsa "depo zaten var" döner, içeriğe dokunulmaz. Üst dizin yoksa "yazılamadı" döner, dizin
  oluşturulmaz. `backtest` ve bilinmeyen mod
  "geçersiz girdi" ile reddedilir; backtest depoya yazmaz.
- R-2: **Depo yoksa boş durum yok:** olmayan depoyu yüklemek "depo yok" döner ve yol üzerinde dosya bırakmaz; boş durum
  döndürülmez (BR-6).
- R-3: **Birebir geri yükleme:** kaydedilen kalıcı durum, başka bir süreçte yüklendiğinde birebir aynıdır: sayılar tüm
  basamakları ve sondaki sıfırlarıyla, zamanlar aynı an ve aynı UTC farkıyla, kayıt ve emir sıraları aynen. Tutarlar
  hiçbir aşamada `float`'a çevrilmez, yuvarlanmaz.
- R-4: **Kaydedilen davranış sürer:** yüklenen durumda aynı öneri "zaten var" döner, durumu bilinmeyen emir güvenli modu ve
  sorgusunu sürdürür, drawdown durdurması yalnız CLI ile kalkar, aynı UTC gününde gün başı kasa ve zirve sıfırlanmaz. Yeni
  günde ya da bayat durumda 0004 R-7 aynen geçerlidir: gözlem gelene kadar onay yoktur.
- R-5: **Hep birlikte yazım:** bir kayıt üç durumu tek seferde yazar; kesinti ya da hata sonrasında depoda ya önceki ya yeni
  durumun tamamı bulunur. Yazılamazsa "yazılamadı" döner, önceki durum okunabilir kalır.
- R-6: **Okunamayan depo:** aşağıdakilerde "depo okunamıyor" (bilinmeyen sürümde "bilinmeyen biçim sürümü") döner; kısmi ya da
  boş durum döndürülmez, otomatik onarım yapılmaz: bozuk içerik; geçersiz sayı veya zaman; bilinmeyen durum değeri; defter
  bakiyesi, açık pozisyonları, kapanışları ya da gerçekleşen toplamı kayıtlarından türeyenle aynı olmayan defter; `observe`'un
  üretemeyeceği risk durumu (alanlar kısmen boş, gün son gözlem zamanının UTC günü değil, zirve son kasanın altında); dolum
  tahmini olmayan bilinmeyen emir.
- R-7: **Mutabakat işareti:** biçimce geçerli ama birbiriyle çelişen durum yüklenir ve "mutabakat tutmuyor" işareti ile
  çelişen kimlikleri taşır. Çelişki: dolu alım emrinin defter kaydı yok; dolu kapanış emrinin kapanış kaydı yok; defterdeki
  pozisyonun ya da kapanışın aynı kimlikte dolu emri yok; miktar, dolum fiyatı ya da komisyon iki tarafta farklı. Bu spec
  işareti üretir; yeni alımı durdurmak ve kapanışları sürdürmek `app`'in işidir (Constraints).
- R-8: **Geçmiş diskte de değişmez:** kayıt, son yüklenen ya da kaydedilen duruma dayanmıyorsa "eski yazım" ile reddedilir.
  Şunlar "geçmiş değiştirilemez" ile reddedilir: defter kaydı silmek ya da değiştirmek; emir silmek; emrin kimliğini ya da
  içeriğini değiştirmek; `bilinmiyor` dışındaki emrin durumunu değiştirmek; risk gözlem zamanını geri almak ya da boşaltmak;
  drawdown durdurmasını `resume`'un üretmediği biçimde kapatmak (zirve son kasaya eşit, son gözlem zamanı ve son kasa önceki
  kayıttakiyle aynı olmalı; depo CLI yetkisini doğrulayamaz, bu kural hatalı yazımı yakalar). Reddedilen kayıt depoyu değiştirmez.
  "Mutabakat tutmuyor" işaretli durum kaydedilebilir, sonuç aynı işareti taşır.
- R-9: **Mod ayrımı:** depo oluşturulduğu modu saklar. Başka modla yükleme "mod uyuşmuyor" döner ve durum döndürmez.
- R-10: **Hata adıyla döner:** depo işlemleri istisna fırlatmaz (0009 R-13'ün güvence dışı bıraktığı `__repr__`'i fırlatan
  nesneler ve benzerleri hariç): erişilemeyen yol "depo okunamıyor" ya da "yazılamadı"; başka süreç tutuyorsa en fazla 5 saniye sonra
  "depo meşgul". Kaydedilmek istenen durum R-6'yı geçmiyorsa "geçersiz girdi" ile reddedilir: okunamayacak bir durum hiç
  yazılmaz. Mesajlar kısadır, sır içermez (depoda da sır yoktur).
- R-11: **Hacim:** 10.000 defter kaydı olan depoda yükleme ve kayıt her biri 1 saniyenin altındadır. Bu değer varsayımdır;
  yüksek frekanslı işlem kapsam dışıdır. Kayıtlar hiç silinmez.
- R-12: **Biçim sürümü:** depo biçim sürümü taşır; bu spec tek sürüm tanımlar, taşıma aracı ilk biçim değişikliğinde gelir.
- R-13: **B-10 ve B-13 kapanır:** `approve_trade`, eksik kasalı durumda bugünkü mesajı aynen korur; elle kurulmuş `NaN`, `Infinity`
  ya da `int` kasalı durumu "risk durumu geçersiz: gün başı, zirve ya da son kasa geçersiz" mesajıyla, aşırı büyük `day` değerini
  istisnasız olarak reddeder. `query_order`, dolum tahmini olmayan
  bilinmeyen emirde `KeyError` yerine "geçersiz girdi" döner, durum değişmez.

## User experience
none — no user interface.

## Constraints & out of scope
- Sensitive area: Emir gönderimi (`execution`), Risk limitleri (`risk`), Portföy / defter (`portfolio`), Paper ↔ live mod anahtarı —
  `docs/domain.md`. `risk`, `execution` ve `portfolio` için ayrı ayrı %90 branch coverage; kalıcılık kodu hangi modüle girerse
  girsin aynı eşikle ölçülür. Birebir geri yükleme ve geçmişin değişmezliği `hypothesis` property testleri ve bağımsız bir
  beklenen-sonuç modeliyle kanıtlanır.
- Depo SQLite'tır, repository katmanı arkasındadır (`docs/architecture.md`). Yeni runtime bağımlılığı yok. Kalıcılık kodunun yeri
  ve modül sınırları planın kararıdır; yeni modül ya da sınır değişikliği `docs/architecture.md`, import-linter sözleşmeleri ve
  gerekirse ADR ile birlikte gelir.
- Testler ve depo dosyaları: her test kendi `tmp_path` deposunu kullanır (`docs/testing.md`); depo repoya girmez (`.gitignore`).
- `app` spec'i için bağlayıcı kurallar (0004 kısıtı, 0010 S3; BR-11): (a) depo okunamıyor, yok, meşgul ya da modu uyuşmuyorsa bot işlem
  yapmaz ve bildirim gönderir; (b) "mutabakat tutmuyor" işaretinde yeni alım durur, kapanışlar sürer, bildirim gider; (c)
  "yazılamadı" ya da "eski yazım"da yeni alım durur, bildirim gider; (d) her adım (emir → defter → gözlem) sonrası kalıcı durum
  kaydedilir.
- Live için kural: live spec'i emri göndermeden önce yazmayı ayrıca tanımlar. Paper'da kaydedilmemiş son adımın kaybı para
  kaybettirmez; aynı öneri aynı kimlikle yeniden denenir.
- Out of scope: `app` döngüsü ve giriş noktası, CLI kurulum komutu, bildirimin gönderimi, risk limitleri, kill switch, mod/aşama
  durumu, piyasa verisi, yedekleme, şifreleme, kurcalamaya karşı koruma, otomatik onarım, biçim taşıma aracı, ayrı süreç kilidi, B-15,
  B-17, B-18, live.
- Shipped davranış (0002–0010) R-13 dışında değişmez. Shipped testlerin assert'leri değişmez (`docs/testing.md`, Protected-tests rule).
  `tests/risk/test_tracking_approval.py`'nin sabitlediği eksik kasa mesajı değişmez; B-10'un yeni mesajı yeni vakalarla kanıtlanır.
- AC-12'nin sınırı CI'da tutmazsa test gevşetilmez; R-08 ile insana gelir.
- Boyut: tek spec. Split: proposed 0011 kayıt, yükleme ve okunamayan depo; 0012 mutabakat, geçmiş koruması ve mod ayrımı; kept as one —
  Galip Badem, 2026-11-03, yetenek tektir (durumu koru) ve ilk parça hassas alanda eksik bir depo bırakırdı (self-critique G-6).
- Varsayılan dosya yolu (`data/`) `app` spec'inin işidir.
- Para/oran değerleri `decimal.Decimal`; zamanlar timezone-aware (`docs/conventions.md`).

## Acceptance criteria
- [ ] AC-1 — Kurulum: yeni yolda depo boş durumla oluşur; aynı yolda ikinci kurulum "depo zaten var" döner, içerik değişmez; üst dizin yoksa
  "yazılamadı", dizin oluşmaz; `backtest` ve bilinmeyen mod "geçersiz girdi" (R-1).
- [ ] AC-2 — Olmayan depo "depo yok" döner, yolda dosya kalmaz, boş durum dönmez (R-2).
- [ ] AC-3 — Birebir geri yükleme: alım → defter → gözlem → kapanış → defter dizisi kaydedilir, ayrı bir süreçte yüklenir; defter, emirler,
  dolum tahminleri ve risk durumu birebir aynıdır: 60 basamaklı değer, `1.10` gibi sondaki sıfır, UTC dışı fark ve sıralar dahil (R-3).
- [ ] AC-4 — Kaydedilen davranış: yüklemeden sonra aynı öneri "zaten var"; bilinmeyen emir güvenli modda, sorgusu çözülür; durdurulmuş bot
  onay almaz, Telegram kaldıramaz, CLI kaldırır; aynı gün gün başı kasa ve zirve korunur; yeni günde gözlem öncesi onay yok (R-4).
- [ ] AC-5 — Kesinti: yazım hatası enjekte edildiğinde ve gerçek süreç yazım sırasında öldürüldüğünde depoda önceki ya da yeni durumun
  tamamı bulunur, yarım durum yok; hata "yazılamadı" döner (R-5).
- [ ] AC-6 — Okunamayan depo: R-6'daki her vaka için ayrı örnek (bozuk dosya, bozuk sayı, bilinmeyen durum, bakiye ya da pozisyon
  uyuşmazlığı, tutarsız risk durumu, tahminsiz bilinmeyen emir, bilinmeyen sürüm) adlandırılmış sonuç verir, durum dönmez (R-6, R-12).
- [ ] AC-7 — Mutabakat: R-7'deki her çelişki türü yüklenir, işaret ve kimlik taşır; çelişkisiz durum ve boş depo işaret taşımaz; 0010 R-6'daki
  "emir dolu, defter reddetti" durumu yüklenebilir ve işaretlidir; işaretli durum kaydedilir, sonuç işareti korur (R-7, R-8).
- [ ] AC-8 — Geçmiş: R-8'deki her yasak yazım için ayrı örnek reddedilir, depo değişmez; bilinmeyen emrin dolu ya da reddedilmiş olması ve
  yeni kayıt eklemek kabul edilir; iki açık bağlantıdan geride kalanın kaydı "eski yazım"; `resume` sonucu durdurma kapanışı kabul, zirve ya da son
  gözlem uymayan kapanış "geçmiş değiştirilemez" (R-8).
- [ ] AC-9 — Mod: `paper` depo `live` ile, `live` depo `paper` ile yüklenince "mod uyuşmuyor", durum dönmez (R-9).
- [ ] AC-10 — Hatalar: erişilemeyen yol, başka süreçte tutulan depo ("depo meşgul", ≤ 5 s) ve R-6'yı geçmeyen durumu kaydetme adlandırılmış sonuç
  verir, istisna yok, depo değişmez; mesajda sır ya da sınırsız girdi yok (R-10).
- [ ] AC-11 — Property: rastgele alım, kapanış, ret, bilinmeyen, gözlem ve durdurma dizilerinde her kayıt-yükleme sonrası durum bağımsız modelle
  birebir aynıdır, geçmiş kaybolmaz, çelişkisiz dizide işaret yoktur (R-3, R-5, R-8).
- [ ] AC-12 — Hacim: 10.000 kayıtlı depoda yükleme ve kayıt < 1 s (`slow` test) (R-11).
- [ ] AC-13 — Backlog: B-10 ve B-13 vakaları R-13'teki sonucu verir, eksik kasa mesajı aynen kalır, `specs/backlog.md` satırları silinir; `risk` ve `execution`'ın shipped
  testleri geçer (R-13).

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
