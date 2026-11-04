# Spec 0012 — Kalıcı risk durumunda sessiz değişiklik olmasın (mini)

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0012-plan.md`
- Self-critique: done
- Source: backlog B-28, B-23 (spec 0011, VERIFY Q-5 ve review round 3 L-2)
- Supersedes: 0011/R-8 ve 0011/AC-8'i genişletir (yasak yazım listesi büyür); 0011'in "kurcalamaya karşı koruma kapsam dışı" notunu B-23'ün dar vakası için daraltır. `specs/done/` dosyaları değişmez.

## Intent
Sistemin sahibi, `app` yazılmadan önce kalıcı risk durumunun hatalı bir çağıran yüzünden sessizce değişmesini engellemek istiyor.
Bugün depo düşürülmüş zirveyi ya da değiştirilmiş gün başı kasayı kabul edebiliyor; bu, drawdown durdurmasını (BR-6) ve günlük zarar
limitini (BR-5) geciktirebilir. Kayıt anında diskteki risk satırı değişmişse de fark sessizce üzerine yazılıyor. Başarı: `observe` ve
`resume`'un üretemeyeceği bu yazımlar reddedilir, depo değişmez, meşru akışlar eskisi gibi sürer.

## Changed behavior
Terimler: **önceki kayıt** diskte duran risk durumudur. **Durdurma kapanışı**, önceki kayıtta durdurma varken yeni durumda olmamasıdır;
biçim koşulları 0011/R-8'deki gibidir (zirve son kasaya eşit, son gözlem zamanı ve son kasa önceki kayıttakiyle aynı). "Durdurma yok" ve
"durdurma sürüyor" önceki kayda göre söylenir.

**Sonuç sırası:** bir yazım birkaç kuralı ihlal ederse ilk uyan döner: "geçersiz girdi" → "eski yazım" → "depo okunamıyor" → "geçmiş değiştirilemez".
Örneğin zirveyi son kasanın altına düşüren yazım R-6'ya takılır, "geçersiz girdi" döner.

- [x] CB-1 — Zirve yalnız geçerli bir durdurma kapanışında düşebilir. Şu yazımlar "geçmiş değiştirilemez" ile reddedilir, depo bayt bayt
  aynı kalır: durdurma yokken zirveyi düşürmek (aynı yazımda durdurma başlatılsa da); durdurma sürerken zirveyi düşürmek; durdurma diske hiç yazılmadan yapılan kapanış (önceki kayıt
  zirve 11000 ve durdurma yok; bellekte `observe(8000)` ve `resume`; sonra kayıt). Karşılaştırma sayısaldır: `1.10` → `1.1` düşüş sayılmaz.
- [x] CB-2 — Aynı UTC gününde gün başı kasa birebir aynı kalır. Değişirse "geçmiş değiştirilemez" ile reddedilir, depo bayt bayt aynı kalır:
  durdurma yokken, durdurma sürerken ve durdurma kapanışında. Karşılaştırma metin üzerindendir: `1.10` → `1.1` de reddedilir. Önceki kayıtta gün yoksa
  (ilk gözlem) bu kural uygulanmaz.
- [x] CB-3 — Kayıt sırasında diskteki risk satırının metni `base.risk`'in metninden farklıysa "depo okunamıyor" döner, depo bayt bayt aynı kalır.
  Vakalar: `halted` metin, zirveye rakam eklenmiş, alanların tamamı boş. Aynı anda revizyon da geride kalmışsa sonuç bugünkü gibi "eski yazım"dır.
  Elle kurulmuş `base.risk` R-6'yı geçiyor ama diskten farklıysa sonuç yine "depo okunamıyor"dur (disk sağlam olsa da; ayrı sonuç türü açılmaz).
- [x] CB-4 — `base.risk` geçersizse (`RiskState` değil ya da R-6'yı geçmiyor) kayıt "geçersiz girdi" ile başlayan mesajla döner (`geçersiz girdi: <sorun>`): istisna yok, depo bayt bayt aynı, mesajda
  sır ya da sınırsız girdi yok (0011/R-10).
- [x] CB-5 — Property: 0011/AC-11'in rastgele dizilerinde, her kayıttan sonra CB-1 ve CB-2'nin o durumda kurulabilen yasak yazımları reddedilir ve
  depo değişmez; dizinin meşru kayıtları kabul edilmeye devam eder.

## Preserved behavior
- [x] PB-1 — `observe` akışları kabul edilir ve birebir geri yüklenir: yeni zirve; zirvenin altında gözlem; aynı zamanda ikinci gözlem; yeni UTC gününde
  değişen gün başı kasa; durdurma sürerken gelen yeni gün gözlemi (durdurma sürer, gün başı kasa yenilenir, zirve korunur).
- [x] PB-2 — `resume` sonucu durdurma kapanışı kabul edilir, zirve son kasaya düşer. 0011/AC-8'in yasak yazımları aynı sonucu ve mesajı verir.
- [x] PB-3 — 0011'in izin verdiği diğer yazımlar kabul edilmeye devam eder (`tests/persistence/test_history.py`, `ALLOWED`). Bu spec'in kapsam dışı
  bıraktığı yazımlar da bugünkü gibi kabul edilir: zirveyi `observe` olmadan yükseltmek, durdurmayı elle başlatmak.
- [x] PB-4 — Yükleme davranışı değişmez: R-6'yı geçen depo yüklenir, geçmeyen "depo okunamıyor" döner. Biçim sürümü aynıdır; bu spec'ten önce yazılmış
  depo yüklenir ve kaydedilir. `risk_lost` vakası bugünkü gibi "yazılamadı" olarak kalır; `test_save_over_a_damaged_store_writes_nothing`'in diğer sonuçları da aynıdır.
- [x] PB-5 — Shipped testlerin assert'leri değişmez (`docs/testing.md`, Protected-tests rule); `risk`, `execution`, `portfolio` ve kalıcılık kodunda
  %90 branch coverage eşiği korunur. `observe` ve `resume` kodu değişmez. 0011/AC-12'nin 1 saniyelik sınırı gevşetilmez: kırmızı olursa ve bu spec
  kaydı yavaşlatmadıysa B-29'a yazılır, yavaşlattıysa bu spec'in bulgusudur.

## Constraints
- Sensitive area: Kalıcı durum (`persistence`), Risk limitleri (`risk`) — `docs/domain.md`.
- `app` spec'i için bağlayıcı kural (0011 Constraints (c)'yi genişletir; BR-11): kayıt "geçmiş değiştirilemez" dönerse yeni alım durur ve bildirim gider.
  CB-1'in diske yazılmamış durdurma vakasında diskteki zirve korunur; sonraki gözlem yeniden durdurur, kaldırmak yine insanın işidir (BR-6).
- Para/oran değerleri `decimal.Decimal`; yeni runtime bağımlılığı yok.

## Out of scope
- Yeni günde gün başı kasanın değerini denetlemek: aynı gün iki gözlem arasında kayıt yapılmazsa "gün başı = son kasa" meşru olarak bozulur.
- Zirveyi `observe` olmadan yükseltmek ve durdurmayı elle başlatmak: `observe`'un üretemeyeceği yazımlar ama güvenli yönde, durdurmayı öne çeker.
- Genel kurcalama koruması: yüklemeden önce yapılan ve R-6'yı geçen değişiklik yakalanmaz. Biçim taşıma: üretimde depo yok.
- B-22 açık kalır (`base.revision` ve `base.ledger` denetimleri; `base.ledger=None` gibi yollar bugünkü gibi davranır); B-24, B-25, B-26, B-27, B-29; `app`, CLI, bildirimin gönderimi.

## Definition of Done
- [x] `scripts/check` green
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Criterion ↔ evidence table complete for CB-* **and** PB-*
- [x] `specs/backlog.md`: B-28 ve B-23 satırları silinir
- [x] Spec moved to `specs/done/` (immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | 0 onay sonrası; plan: A-1, A-2, A-3 |
| Fix rounds | 3 (fix-1 review r1; fix-2 VERIFY r1; fix-3 VERIFY r2); review r4 temiz, VERIFY r3 PASS |
| Review findings: real / noise / deferred | 7 / 4 / 5 (r1: M-1, L-1 real, I-1, I-2 noise, belge çelişkisi defer B-30 · r2: L-2 defer B-31, VERIFY r1'de geri alındı · r3: L-2 real, I-1 noise, L-1 defer B-32 · VERIFY r1: CB-5 gap, CB-3 real · VERIFY r2: Gap 1, Q-3 real, Q-2 defer B-32 · VERIFY r3: Q-1 defer B-33, Q-2 noise) |
| Regressions introduced | 0 (üretim kodu fix turlarında değişmedi) |
| Bugs escaped to production | 0 (henüz üretim yok) |

PB-5 ve DoD'nin `scripts/check` kutusu koşullu işaretlendi (`doctor`, `specs/done/`'da işaretsiz kriteri reddediyor); koşul bu PR'ın full koşusudur, yeşil olmadan merge yapılmaz (`docs/testing.md`, Two speeds, rule 10).
