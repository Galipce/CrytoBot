# Spec 0001 — Proje iskeleti, modül sınırları ve doğrulama sözleşmesi

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0001-plan.md`

## Intent
CrytoBot'un sahibi, uygulama mantığı yazılmadan önce projenin **çalışan ve kendini denetleyen bir
iskelete** sahip olmasını istiyor: bootstrap'ta kararlaştırılan 13 modülün yapısı, modüller arası yasak
bağımlılık kuralları ve kalite kontrolleri (lint, format, tip, mimari sınırlar, testler, coverage) tek bir
komutla (`scripts/check`) hem geliştirici makinesinde (Windows) hem CI'da doğrulanmalı. Başarı: temiz
iskelette `check` yeşil; bir kural bilerek bozulduğunda kırmızı ve bozulan kuralı adlandırıyor. Bilerek
yapılmayanlar: risk config ve sabit üst sınırlar (ayrı spec 0002, hassas alan), borsa / haber / LLM /
Telegram işlevleri ve bunların runtime kütüphaneleri, herhangi bir işlem mantığı.

## Requirements
- R-1: Proje Python 3.12 ve `uv` ile kurulur; Python 3.12'yi `uv` sağlar (sistemde Python gerekmez).
  Bağımlılık sürümleri kilit dosyasıyla sabittir ve doğrulama sırasında kilit dosyası değiştirilmez.
  Kurulum ve doğrulama komutları README'nin "Geliştirme" bölümünde belgelenir.
- R-2: `docs/architecture.md` tablosundaki 13 modülün (market_data, news, research, llm, analysis,
  strategy, risk, execution, portfolio, backtest, control, reporting, app) her biri tek bir uygulama
  paketi altında ayrı bir modül olarak vardır ve dışa açık bir public arayüzü vardır. Modüller
  bu spec'te içerik (davranış) taşımaz.
- R-3: `docs/architecture.md` "Forbidden dependencies" bölümündeki **proje-içi** kurallar otomatik
  olarak doğrulanır:
  - `strategy`, `analysis`, `news`, `research`, `llm` hiçbir zaman `execution`'ı import etmez;
  - `execution`'ı yalnızca `risk`, `app` ve `backtest` import eder;
  - `analysis` hiçbir proje modülünü import etmez;
  - hiçbir modül başka bir modülün iç alt modülünü import etmez. **Tanım:** bir modüle dışarıdan
    yalnızca modül kökü (ör. `crytobot.risk`) üzerinden erişilir; modülün altındaki her alt modül
    (ör. `crytobot.risk.<herhangi>`) o modülün içidir.
- R-4: `scripts/check` şu adımları yürütür: lint, format kontrolü, katı tip kontrolü, mimari sınırlar,
  hızlı testler (fast profil) ve yavaş testler (yalnızca full profil). Hızlı/yavaş ayrımı bir seçiciyle
  yapılır (`docs/testing.md`, Two speeds kural 4).
- R-5: Testler ağa çıkamaz; bir testin ağ bağlantısı denemesi testin başarısız olmasıyla sonuçlanır.
- R-6: `risk`, `execution`, `portfolio` modülleri için %90 branch coverage eşiği full profilde zorlanır.
- R-7: CI, full profili gerçek araç zinciriyle çalıştırır ve ayrı bir adımda bağımlılık güvenlik
  taraması (bilinen zafiyetler) yapar.
- R-8: Bu spec yalnızca onaylı geliştirme araçlarını ekler: ruff, mypy, pytest, pytest-cov, hypothesis,
  pytest-socket, import-linter (ve bunların kendi bağımlılıkları). Runtime kütüphanesi eklenmez.
- R-9: `check` hiçbir süreç ve koşudan koşuya taşınan veri bırakmaz (`docs/testing.md`, Resource hygiene).

## User experience
none — no user interface. (Tek kullanıcı yüzeyi geliştiricinin çalıştırdığı `./scripts/check [--fast]`
komutu ve CI çıktısıdır.)

## Constraints & out of scope
- Split: proposed 0001 (iskelet + sınırlar + check/CI) and 0002 (risk config + sabit üst sınırlar);
  accepted — Galip Badem, 2026-10-29. Risk config bu spec'te YOK.
- Size: 11 acceptance criteria (> ~10) — kept as one: Galip Badem, 2026-10-29, tek yetenek
  (doğrulama altyapısı); kriterlerin çoğu aynı `check`'in farklı adımlarını kanıtlar.
- Sensitive area: none (risk limitleri 0002'ye taşındı).
- Out of scope: GitHub'da `main` dal koruması ("CI yeşil olmadan merge yok") — insanın elle yaptığı
  depo ayarı.
- Out of scope: borsa/haber/LLM/Telegram işlevleri; runtime kütüphaneleri (ccxt, pandas, anthropic,
  Telegram); uygulamanın çalışan bir giriş noktası (CLI komutları); `Clock` arayüzü ve config yükleme.
- Out of scope: **dış kütüphane** sınır kuralları (`ccxt` / `anthropic` / Telegram yalnızca belirli
  modüllerde). Kütüphane projede yokken kural bozularak kanıtlanamaz; her kural, kütüphaneyi ekleyen
  spec'te gelir.
- Yerel geliştirme ortamı Windows + Git Bash; CI Linux. `check` ikisinde de aynı sonucu vermeli.
- `CLAUDE.md`/`.claude/` ve bootstrap çıktıları bu spec'in kapsamında değildir (önceden birleştirilir).

## Acceptance criteria
- [ ] AC-1 — Temiz bir klondan, README "Geliştirme" bölümündeki kurulum komutu ve ardından `./scripts/check` çalıştırıldığında
  `CHECK GREEN (full, …)` alınır; bu hem Windows/Git Bash'te hem CI'da (Linux) geçerlidir. (R-1, R-4)
- [ ] AC-2 — `./scripts/check --fast` lint, format, tip, sınır ve hızlı test adımlarını çalıştırır, yavaş
  test adımını "full only" diye atlar ve yeşildir. (R-4)
- [ ] AC-3 — Henüz hiç yavaş test yokken full profil yeşildir; tek bir yavaş test bilerek başarısız
  yapıldığında full profil kırmızı olur, fast profil o testi çalıştırmaz. (R-4)
- [ ] AC-4 — 13 modülün her biri uygulama paketi altında import edilebilir ve public arayüzü vardır; bir
  test bu listeyi `docs/architecture.md` tablosuyla birebir doğrular (eksik veya fazla modül → kırmızı). (R-2)
- [ ] AC-5 — R-3'teki kuralların her biri için bilerek ihlal eden bir import eklendiğinde `check` sınır
  adımında kırmızı olur ve çıktı ihlal edilen kuralı adlandırır; import kaldırılınca yeşile döner. (R-3)
- [ ] AC-6 — Bilerek eklenen bir lint ihlali, format bozukluğu ve tip hatasının her biri `check`'i ilgili
  adımda kırmızı yapar. (R-4)
- [ ] AC-7 — Ağ bağlantısı deneyen bir test başarısız olur (bağlantı engellendiği için). (R-5)
- [ ] AC-8 — `risk`, `execution` veya `portfolio`'ya test edilmemiş dallı kod eklendiğinde full profil
  coverage eşiği nedeniyle kırmızı olur; içeriksiz iskelette yeşildir. (R-6)
- [ ] AC-9 — CI'da check job'ı full profili uv ile çalıştırır; ayrı bir job bağımlılıkları bilinen
  zafiyetlere karşı tarar ve zafiyetli bir sürüm sabitlendiğinde kırmızı olur. Kırmızı durumun kanıtı:
  bir kerelik deneme dalındaki CI koşusunun linki, PR'da (Evidence policy kural 3). (R-7)
- [ ] AC-10 — Kilit dosyasındaki doğrudan bağımlılıklar yalnızca R-8 listesidir; `check` kilit dosyasını
  değiştirmez (koşu sonrası `git status` temiz). (R-1, R-8)
- [ ] AC-11 — `./scripts/residue` ve `./scripts/residue --fast` hiçbir artık süreç bildirmez; her profilin
  süresi 3 koşunun medyanı olarak raporlanır; hijyen ayarlarından sonra test sayısı değişmez. (R-9)

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
