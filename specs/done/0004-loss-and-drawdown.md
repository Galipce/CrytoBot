# Spec 0004 — Günlük zarar ve drawdown takibi

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0004-plan.md`

## Intent
CrytoBot'un sahibi, kötü bir günün ya da kötü bir dönemin kasayı eritmesini istemiyor: bir UTC gününde zarar,
gün başı kasanın günlük zarar limitine ulaşınca o gün yeni pozisyon açılmaz (BR-5) ve ertesi UTC günü kendiliğinden
açılır; kasa en yüksek değerinden drawdown limiti kadar düşünce bot tüm yeni işlemleri durdurur ve bu durdurmayı
yalnızca sahip CLI'den kaldırabilir (BR-6). Başarı: limite ulaşıldıktan sonra hiçbir alım önerisi onaylanmaz, ret
nedeni hangi limitin dolduğunu söyler, durdurma sahip kaldırana kadar sürer. Bilerek yapılmayanlar: maliyet/kâr
eşiği (BR-8), belirsiz durum kuralı (BR-11), kill switch, açık pozisyonların zorla kapatılması, durumun kalıcı
saklanması, gerçek CLI/Telegram komutları.

## Requirements
- R-1: Risk durumu şunları taşır: geçerli UTC günü, gün başı kasa, zirve kasa, son gözlemin zamanı ve kasası, ve
  drawdown durdurmasının olup olmadığı.
- R-2: Durum, bir kasa gözlemiyle (zaman + kasa) güncellenir; güncelleme önceki durumu ve gözlemi alır, yeni durumu
  verir (saat dışarıdan gelir, `docs/conventions.md`). İlk gözlemde gün, gözlemin UTC günüdür; gün başı kasa ve zirve
  kasa gözlenen kasadır. Yeni bir UTC gününün ilk gözlemi o günün gün başı kasasını belirler. Zirve kasa, gözlenen
  en yüksek kasadır.
- R-3: Günlük zarar oranı = (gün başı kasa − güncel kasa) ÷ gün başı kasa. Güncel kasa açık pozisyonların piyasa
  değerini içerir (`docs/domain.md`, Kasa). Oran günlük zarar limitine **eşit veya üstündeyse** o UTC günü yeni
  pozisyon açılmaz; yeni UTC günüyle bu kilit kendiliğinden kalkar. Kârlı gün (oran negatif) kilit yaratmaz. (BR-5)
- R-4: Drawdown oranı = (zirve kasa − güncel kasa) ÷ zirve kasa. Oran drawdown limitine **eşit veya üstündeyse**
  durum "durduruldu" olur ve tüm yeni işlemler durur. Durdurma kendiliğinden kalkmaz: kasa toparlansa da, yeni UTC
  günü gelse de sürer. (BR-6)
- R-5: Durdurmayı kaldırma isteği kanalı (CLI veya Telegram) taşır. Yalnızca CLI'den gelen istek kabul edilir:
  durdurma kalkar ve zirve kasa son gözlenen kasa olur (yoksa bot hemen yeniden durur). Telegram'dan ya da bilinmeyen
  kanaldan gelen istek reddedilir ve durum değişmez. Durdurma yokken gelen istek durumu değiştirmez ve bunu belirtir.
  Kaldırma yalnız drawdown durdurmasını kaldırır; aynı gün dolu günlük zarar limiti sürer. Hiç gözlem yapılmamış
  (boş) durumda kaldırma isteği geçersizdir.
- R-6: Geçersiz gözlem reddedilir ve durum değişmez, neden adlandırılır: zaman dilimi bilgisi olmayan zaman, son
  gözlemden daha eski zaman (aynı zaman geçerlidir), sıfır/negatif/sonlu olmayan ya da sayı olmayan kasa (spec 0003
  R-7 ile aynı sayı kuralı).
- R-7: İşlem önerisi onayı (spec 0003) risk durumunu ve şu anki zamanı da girdi olarak alır. Şu durumlarda öneri
  "geçersiz girdi" ile reddedilir (bayat ya da eksik durum): durum boş, durumun günü şu anki zamanın UTC günü değil,
  ya da durumun son gözlenen kasası onaydaki kasaya eşit değil. Ret sırası şöyle genişler: geçersiz girdi
  → **drawdown durdurması** → **günlük zarar limiti** → spec 0003 R-8'in kalan sırası. Durdurma ya da limit, onaydaki
  limitlerle (R-3, R-4 oranları) ve durumdaki gün başı/zirve kasayla hesaplanır; durumdaki "durduruldu" bilgisi de
  tek başına ret nedenidir.
- R-8: Hiçbir gözlem dizisi ve kaldırma isteği dizisi için, günlük zarar oranı limitte/üstündeyken, drawdown oranı
  limitte/üstündeyken ya da durum "durduruldu"yken bir alım önerisi onaylanamaz; "durduruldu" yalnızca CLI kaldırma
  isteğiyle kalkar (`docs/domain.md`, Key domain invariants).

## User experience
none — no user interface. (Kaldırma isteğinin gerçek CLI komutu ve ret mesajlarının sahibe gösterilmesi `control`
spec'inde gelir.)

## Constraints & out of scope
- Sensitive area: Risk limitleri (`risk`) ve kasa hesabı — `docs/domain.md`. `risk` için %90 branch coverage;
  kurallar `hypothesis` property testleriyle ve bağımsız bir beklenen-sonuç modeliyle (oracle) kanıtlanır (spec 0002
  A-5, spec 0003 AC-10 dersi).
- Supersedes: 0003 R-1 ve R-8 (genişletir) — onay artık risk durumunu da alır ve iki ret nedeni eklenir. Spec 0003'ün
  kabul kriterleri korunur (AC-9); `specs/done/0003-trade-approval.md` değiştirilmez.
- Out of scope: durumun kalıcı saklanması. Bu spec saf bir durum geçişi tanımlar; kalıcılığı getiren spec (`app` /
  `portfolio`) şu kısıtı taşımalıdır: kalıcı durum yüklenemezse işlem açılmaz — aksi halde yeniden başlatma
  drawdown durdurmasını atlatır.
- Out of scope: gün içinde para yatırma; bilinen eksik — yatırma günlük zararı ve drawdown'ı olduğundan küçük
  gösterir. Para çekme kodda yoktur (`docs/domain.md`).
- Out of scope: maliyet/kâr eşiği (BR-8), belirsiz durum kuralı (BR-11, bayat veri ve mutabakat), kill switch,
  açık pozisyonların zorla kapatılması, pozisyon kapatan satış (spec 0003 ile aynı), gerçek CLI/Telegram komutları,
  TOTP/teyit, kasanın `portfolio`'dan hesaplanması.
- Yeni runtime bağımlılığı gerekirse plan gerekçesiyle önerir; insan onayı olmadan eklenmez (`docs/security.md`).
- Para/oran değerleri `decimal.Decimal`; zaman damgaları UTC, timezone-aware (`docs/conventions.md`, Data rules).

## Acceptance criteria
- [ ] AC-1 — İlk gözlem (2026-11-02 10:00 UTC, kasa `10000`): gün 2026-11-02, gün başı ve zirve kasa `10000`, kilit
  ve durdurma yok; daha yüksek kasalı sonraki gözlem zirveyi yükseltir, düşük kasalı gözlem değiştirmez. (R-1, R-2)
- [ ] AC-2 — Günlük zarar (gün başı ve zirve `10000`, limit `0.03`, drawdown limiti `0.15`): kasa `9701` → öneri günlük
  limit yüzünden reddedilmez; kasa `9700` (tam %3) ve altı → "günlük zarar limiti" reddi; kasa `10500` → kilit yok;
  kasa `9800` iken limit `0.02`'ye düşürülmüşse (onaydaki limit) → "günlük zarar limiti" reddi. (R-3, R-7)
- [ ] AC-3 — Gün sınırı: 23:59:59 UTC'de kilitli gün, 00:00:00 UTC'deki ilk gözlemle açılır ve o gözlemin kasası yeni
  gün başı kasa olur; UTC dışı zaman dilimli bir zaman UTC gününe göre değerlendirilir (ör. 2026-11-03 01:30+03:00 →
  2026-11-02). (R-2, R-3)
- [ ] AC-4 — Drawdown (zirve `10000`, limit `0.15`): kasa `8501` → durdurma yok; kasa `8500` (tam %15) ve altı →
  durum "durduruldu", öneri "drawdown durdurması" ile reddedilir. (R-4, R-7)
- [ ] AC-5 — Durdurma kalıcıdır: durdurulduktan sonra kasa `10000`'e dönse de, yeni UTC günü gelse de durum
  "durduruldu" kalır ve öneriler reddedilir. (R-4)
- [ ] AC-6 — Kaldırma: CLI isteği durdurmayı kaldırır ve zirve kasa son gözlenen kasa olur (sonraki öneri drawdown
  yüzünden reddedilmez); Telegram ve bilinmeyen kanal (`"CLI"`, `"sms"`) reddedilir, durum değişmez; durdurma yokken
  CLI isteği durumu değiştirmez ve bunu belirtir; aynı gün günlük limit de doluysa kaldırmadan sonra öneri "günlük
  zarar limiti" ile reddedilir; boş durumda kaldırma isteği reddedilir. (R-5)
- [ ] AC-7 — Ret sırası: hem drawdown durdurması hem günlük limit doluyken neden "drawdown durdurması"dır; günlük
  limit dolu ve stop'suz öneri → "günlük zarar limiti"; geçersiz girdi her ikisinden önce gelir. (R-7)
- [ ] AC-8 — Geçersiz gözlem ve bayat durum: zaman dilimsiz zaman, son gözlemden daha eski zaman, kasa `0`/negatif/
  `NaN`/`float` → gözlem reddedilir, durum değişmez, neden adlandırılır; son gözlemle aynı zamanlı gözlem kabul
  edilir; boş durum, günü şu anki UTC gününden farklı durum ya da son kasası onaydaki kasadan farklı durum →
  öneri "geçersiz girdi" ile reddedilir. (R-6, R-7)
- [ ] AC-9 — Spec 0003 korunur: kilit ve durdurma olmayan, kasası onaydakiyle aynı bir durumla spec 0003'ün tüm
  örnek ve property testleri aynı sonucu verir. (R-7)
- [ ] AC-10 — Property testi: rastgele gözlem, kaldırma isteği ve öneri dizileri için sonuç, beklenen sonucu
  bağımsız hesaplayan modelle aynıdır; hiçbir onay, günlük zarar oranı ya da drawdown oranı limitte/üstündeyken veya
  durum "durduruldu"yken verilmez; "durduruldu" yalnızca CLI isteğiyle kalkar. (R-8)

## Definition of Done
- [ ] Every acceptance criterion mapped to proof (test or reproducible observation)
- [ ] `scripts/check` green
- [ ] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [ ] Docs / ADRs updated if behavior or architecture changed
- [ ] Spec moved to `specs/done/` (it becomes immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | 0 onay sonrası (sapmalar plan amendment A-1…A-4) |
| Fix rounds | 3 (fix-1 review r1, fix-2 review r2, fix-3 review r3); review r4 fix turu getirmedi |
| Review findings: real / noise / deferred | 7 / 3 / 4 (r1: F-1, F-2 real; F-3 real, yalnız kayıt; F-4, F-5 noise · r2: F-6 real · r3: F-7 defer B-8; F-8, F-9 real; F-10 defer B-9; F-11 real, yalnız kayıt; F-12 noise · r4: N-1, N-2 defer B-10; N-3 yalnız kayıt · VERIFY: gap yok; I-1, I-2 Info ship öncesi kapandı) |
| Regressions introduced | 0 |
| Bugs escaped to production | 0 (henüz üretim yok) |
