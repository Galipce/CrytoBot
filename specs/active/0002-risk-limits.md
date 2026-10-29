# Spec 0002 — Risk limitleri ve sabit üst sınırlar

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0002-plan.md`

## Intent
CrytoBot'un sahibi, gerçek parayla tek işlem yapılmadan önce risk limitlerinin (işlem başına risk, günlük
zarar, drawdown, en fazla açık pozisyon) tek, doğrulanmış ve aşılamaz bir kaynaktan gelmesini istiyor:
sahip limitleri config'ten ayarlar, kodda ise hiçbir config'in veya komutun aşamayacağı sabit üst sınırlar
vardır (%2 / %5 / %25 / 8). Başarı: geçersiz veya üst sınırı aşan bir limit sessizce kabul edilmez — limitler
hiç oluşmaz ve hata nedenini adlandırır; limit değiştirme isteği geldiği kanala (Telegram yalnızca düşürür)
ve üst sınıra göre kabul ya da reddedilir. Bilerek yapılmayanlar: işlem önerisi onayı (zorunlu stop-loss,
pozisyon boyutlama, pozisyon sayısı kontrolü), günlük zarar / drawdown'ın canlı takibi, kill switch, gerçek
CLI/Telegram komutları ve değişikliklerin kalıcılığı.

## Requirements
- R-1: Dört risk limiti vardır: işlem başına risk (BR-4), günlük zarar limiti (BR-5), drawdown limiti (BR-6)
  — üçü de kasaya oran olarak (`0.01` = %1) — ve en fazla açık pozisyon sayısı (BR-7, tam sayı).
- R-2: Her limitin kodda sabit bir üst sınırı vardır: işlem başına risk `0.02`, günlük zarar `0.05`,
  drawdown `0.25`, pozisyon sayısı `8`. Üst sınırlar hiçbir kanaldan (config, değiştirme isteği)
  değiştirilemez; yalnızca yeni bir spec ve kod değişikliğiyle değişir. Üst sınıra eşit değer geçerlidir.
- R-3: Limitler sahibin config'inden yüklenir. Config'te yazılmamış bir limit için iş kuralındaki varsayılan
  kullanılır (`0.01` / `0.03` / `0.15` / `5`); yükleme sonucu hangi limitlerin varsayılandan geldiğini belirtir.
- R-4: Oranlar config'te yazıldığı haliyle tam ondalık olarak yorumlanır (ör. `0.1` tam olarak 0,1'dir;
  kayan nokta yuvarlaması yoktur). Oranlar sıfırdan büyük, pozisyon sayısı en az 1 olmalıdır. Sıfırdan
  büyük her sonlu oran — çok küçük değerler ve bilimsel gösterim (`1e-2`) dahil — geçerlidir; alt sınır yoktur.
  `NaN`, sonsuz değerler ve mantıksal değerler (`true`/`false`) sayı sayılmaz.
- R-5: Yükleme şu durumların her birinde reddedilir ve limitler oluşmaz: bir değer üst sınırı aşıyor;
  değer sayı değil, sıfır veya negatif; pozisyon sayısı tam sayı değil; config bilinmeyen bir limit adı
  içeriyor (yazım hatası dahil; limit adları yalnızca birebir eşleşir — büyük/küçük harf veya boşluk farkı
  "bilinmeyen limit"tir). Hata mesajı ilgili limiti, verilen değeri ve — üst sınır aşımında —
  üst sınırı adlandırır. Birden fazla hata varsa hepsi birlikte bildirilir.
- R-6: Bir limit değiştirme isteği; limit adını, yeni değeri ve isteğin geldiği kanalı (CLI veya Telegram)
  taşır ve şöyle karara bağlanır (BR-13):
  - düşürme veya aynı değer: her kanaldan kabul;
  - artırma: yalnızca CLI'den, en fazla üst sınıra kadar kabul; Telegram'dan reddedilir;
  - üst sınırı aşan değer: her kanaldan reddedilir;
  - geçersiz değer (R-4), bilinmeyen limit adı (birebir eşleşme, R-5) veya bilinmeyen kanal: reddedilir
    (varsayılan: reddet).
  Kabul edilen istek yalnızca o limiti değiştirir; reddedilen istek hiçbir limiti değiştirmez ve reddin
  nedenini (Telegram'dan artırma, üst sınır aşımı, geçersiz değer, bilinmeyen limit/kanal) adlandırır.
- R-7: Hiçbir yükleme girdisi ve hiçbir değiştirme isteği dizisi için geçerli limitler sabit üst sınırları
  aşamaz ve Telegram'dan gelen hiçbir istek bir limiti yükseltemez (`docs/domain.md`, Key domain invariants).

## User experience
none — no user interface. (Sahibin yüzeyi config'teki limit değerleri ve yükleme/değiştirme hata
mesajlarıdır; komutlar `control` spec'inde gelir.)

## Constraints & out of scope
- Sensitive area: Risk limitleri (`risk`) — `docs/domain.md`. `risk` modülü için %90 branch coverage
  eşiği geçerlidir; risk kuralları `hypothesis` property testleriyle de kanıtlanır (`docs/testing.md`).
- Split: proposed 0002 (limitler: tanım, doğrulama, değiştirme kuralı) and 0003 (işlem önerisi onayı:
  BR-3 zorunlu stop-loss, BR-4 boyutlama, BR-7 pozisyon sayısı kontrolü); accepted — Galip Badem, 2026-10-30.
- Out of scope: işlem önerisi onayı ve pozisyon boyutlama (0003); günlük zarar ve drawdown'ın canlı
  hesaplanıp aşımda işlem durdurulması; kill switch; BR-8 maliyet kuralı.
- Out of scope: gerçek CLI/Telegram komutları, TOTP/teyit, audit log ve değiştirilen limitin yeniden
  başlatmadan sonra kalıcılığı — `control` spec'inde birlikte gelir. Bu spec yalnızca risk tarafındaki
  karar kuralını tanımlar; bugün değiştirme kanalı olmadığından "yeniden başlatınca düşürülen limit geri
  yükselir" riski henüz doğmaz. `control` spec'i kalıcılığı çözmeden Telegram'dan düşürme etkinleştirilmez.
- Out of scope: uygulamanın çalışan giriş noktası (bileşim kökü `app`, "bot başlamaz" davranışı); bu spec
  limitlerin yüklenip yüklenemediğini tanımlar, başlatmayı reddetmeyi bağlayan kod `app` spec'inde gelir.
- Yeni runtime bağımlılığı gerekirse plan gerekçesiyle önerir; insan onayı olmadan eklenmez (`docs/security.md`).
- Para/oran değerleri `decimal.Decimal`, asla `float` (`docs/conventions.md`, Data rules).

## Acceptance criteria
- [ ] AC-1 — Dört limitin de üst sınır içinde yazıldığı bir config yüklenince limitler tam yazılan değerlerdir
  (ör. `0.1` drawdown tam olarak 0,1); hiçbiri "varsayılandan" işaretlenmez. (R-1, R-3, R-4)
- [ ] AC-2 — Bazı limitleri eksik config'te eksikler BR varsayılanlarını alır ve yükleme sonucu tam olarak
  onları "varsayılandan" diye adlandırır; limit içermeyen config'te ve risk bölümü hiç olmayan config'te
  dördü de varsayılandır. (R-3)
- [ ] AC-3 — Her limit için: üst sınıra eşit değer kabul edilir; üst sınırın en küçük ondalık adım üstü
  (ör. `0.0200001`, pozisyon için `9`) reddedilir ve hata limiti, değeri ve üst sınırı adlandırır. (R-2, R-5)
- [ ] AC-4 — Geçersiz değerler reddedilir ve hata limiti adlandırır: sayı olmayan, `NaN`, sonsuz, sıfır,
  negatif oran; `0`, negatif, tam sayı olmayan veya mantıksal (`true`/`false`) pozisyon sayısı. Çok küçük
  pozitif oran (`0.0000001`) ve bilimsel gösterim (`1e-2`) kabul edilir. (R-4, R-5)
- [ ] AC-5 — Bilinmeyen limit adı (yazım hatası, büyük/küçük harf veya boşluk farkı, ya da bir üst sınırı
  ayarlamaya çalışan anahtar) içeren config
  reddedilir ve hata adı söyler; birden fazla hatalı config'te tüm hatalar birlikte bildirilir. (R-2, R-5)
- [ ] AC-6 — Değiştirme: düşürme ve aynı değer CLI'den de Telegram'dan da kabul edilir; yalnızca istenen limit
  değişir, diğerleri aynı kalır. (R-6)
- [ ] AC-7 — Telegram'dan artırma isteği (üst sınırın altında olsa bile) reddedilir, neden "Telegram'dan
  artırma" olarak adlandırılır ve limitler değişmez. (R-6, BR-13)
- [ ] AC-8 — CLI'den artırma üst sınıra kadar (eşit dahil) kabul edilir; üst sınırı aşan değer her iki kanaldan
  da reddedilir, neden "üst sınır aşımı" olarak adlandırılır ve limitler değişmez. (R-2, R-6)
- [ ] AC-9 — Geçersiz değer, bilinmeyen limit adı veya bilinmeyen kanal taşıyan istek reddedilir, neden
  adlandırılır ve limitler değişmez. (R-6)
- [ ] AC-10 — Property testi: rastgele config girdileri ve rastgele (kanal, limit, değer) değiştirme istek
  dizileri için, kabul edilen her durumda tüm limitler üst sınır içindedir ve Telegram'dan gelen hiçbir kabul
  edilmiş istek bir limiti yükseltmemiştir. (R-7)

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
