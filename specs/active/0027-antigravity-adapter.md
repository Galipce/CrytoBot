# Spec 0027 — Antigravity adaptörü ve Gemini ile devam

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0027-plan.md`
- Self-critique: done

## Intent
Galip'in birincil asistanı Claude'dur; Claude'un kullanım hakkı bittiğinde iş durmamalı, Gemini
(Antigravity CLI, `agy`) aynı depoda aynı kurallarla kaldığı yerden devam edebilmelidir. Başarı:
Galip tek komutla Gemini'yi açar; Gemini işin hangi aşamada kaldığını dosyalardan doğru söyler,
sıradaki adımı önerir ve onay almadan hiçbir kapıdan geçmez; Claude'daki komutların aynısı
Antigravity'de de vardır. Geçiş elle tetiklenir — hak bitişini otomatik algılama yapılmaz.
Gemini'nin bağımsız reviewer olarak destek rolü (2. aşama, 10 Kasım 2026 sonrası) bu spec'in
dışındadır.

## Requirements
1. **Kurulum.** `./scripts/init antigravity`, ANEW komutlarının tamamını Antigravity'nin proje
   düzeyi komutları (skill) olarak `.agents/skills/` altına kurar. Var olan dosyalar `--force`
   verilmedikçe korunur ve korunanlar adıyla bildirilir; yardım metni `antigravity`yi listeler.
2. **Komut eşliği.** Claude Code'daki her komutun (beş segment, `/new-feature`, `/change`,
   `/bootstrap`, `/fix-bug`, `/refactor`, `/adr`, `/recover`) Antigravity karşılığı vardır.
   Her biri yalnızca işaretçidir: `AGENTS.md`'yi ve ilgili `workflows/` / `prompts/` dosyalarını
   gösterir, kural metni kopyalamaz (ince adaptör ilkesi). Çağrı biçimi `/ad`'dır; tek istisna PLAN'dır: Antigravity'nin yerleşik `/plan` komutu aynı adlı
   skill'i gölgelediği için Antigravity'de `/anew-plan` adını taşır (R-07, Galip Badem, 2026-11-07).
3. **Yalnızca açık çağrı.** Antigravity'de "kendiliğinden başlatma" kapatılamadığı için her komutun
   açıklaması, komutun yalnızca kullanıcı `/ad` yazdığında çalıştırılacağını söyler. Bu boşluk
   adaptör belgesinde açıkça yazılır; asıl güvence dosyadan yapılan giriş kontrolleri ve CI'daki
   `doctor --strict`'tir.
4. **Doğrulama (doctor).** `scripts/doctor` adaptör eşliğine Antigravity'yi de katar: eksik bir
   komut ve "yalnızca açık çağrı" ifadesi taşımayan bir komut başarısızlıktır. `.agents/skills/`
   kurulu adaptör sayılmaya devam eder.
5. **Gemini ile devam başlatıcısı.** Galip tek bir PowerShell komutuyla (`scripts/gemini-devam.ps1`)
   Gemini'yi depo kökünde etkileşimli açar. Başlatıcı `agy`'yi önce PATH'te, sonra
   `%USERPROFILE%\.gemini\bin\agy.exe` konumunda arar; Gemini'yi varsayılan izin modunda açar
   (her işlem için onay sorar; izinleri otomatik geçen hiçbir seçenek kullanılmaz).
6. **Açılış talimatı.** Başlatıcı Gemini'ye şunu yaptırır: `AGENTS.md`'yi uygula; branch'i, aktif
   spec'i ve `Status`'unu, planın onay satırını ve bitmemiş ilk adımını, commit edilmemiş
   değişiklikleri ve devir notunu oku; kalınan aşamayı ve sıradaki segmenti (komutuyla) öner;
   onay gelene kadar dosya değiştirme ve komut çalıştırma başlatma. `specs/active/` içinde birden
   çok spec varsa hepsi `Status`'larıyla listelenir; numarası branch adıyla eşleşen ana iş sayılır.
   Devir notunda kayıtlı branch ya da commit o anki branch/HEAD'den farklıysa not **eski** sayılır.
7. **Devir notu.** Claude'un her turu bittiğinde depo içinde makineye özel, git'e girmeyen bir devir
   notu güncellenir: tarih-saat, branch, son commit, aktif spec(ler) ve `Status`'u, planın onay
   satırı ve bitmemiş ilk adımı, değişmiş dosyaların listesi. Not yalnızca dosyalardan ve git'ten
   türetilir; sohbet içeriği içermez. Notu yazmak başarısız olursa Claude'un çalışması etkilenmez.
   Not yazma bir turu en fazla 2 saniye uzatır. Bu davranış Claude Code adaptör şablonunda da
   bulunur; `./scripts/init claude-code` ile kurulan her kopya onu alır.
8. **Gemini commit imzası.** Gemini'nin hazırladığı commit mesajları
   `Co-Authored-By: Gemini (Antigravity) <noreply@google.com>` satırıyla biter. Kural çekirdekte
   (`docs/git.md`) tek yerde tanımlanır; adaptör yalnızca ona işaret eder.
9. **Belgeler.** Araç listeleri (README, `adapters/README.md`, `docs/commands.md`) Antigravity'yi
   diğer araçların yanında anar; Codex ile aynı klasörü paylaşma durumu ve elle geçiş akışı
   adaptör belgesinde anlatılır; `CHANGELOG.md`'ye kayıt düşülür.

## User experience
Arayüz yok — komut satırı akışı.
- Flow: Claude hakkı biter → Galip PowerShell'de depo kökünde `scripts\gemini-devam.ps1` çalıştırır
  → Gemini açılır, durum özetini ve önerdiği sıradaki adımı yazar → Galip onaylar ya da başka bir
  `/komut` verir → Gemini yalnızca onaylananı yapar.
- States:
  - **Normal:** aktif iş var, devir notu güncel → özet + öneri.
  - **Aktif iş yok:** aktif spec yok ve çalışma ağacı temiz → "aktif iş yok" der, yeni iş için
    `/analyze` önerir, başlatmaz.
  - **Devir notu yok / eski:** not yoksa ya da eskiyse (Req. 6) bunu söyler ve durumu
    yalnızca dosyalardan çıkarır.
  - **`agy` bulunamadı:** Gemini açılmaz; Türkçe hata, aranan konumlar ve kurulum ipucu yazılır,
    komut sıfır olmayan kodla çıkar.
  - **Depo kökü dışında çalıştırma:** başlatıcı kendi konumundan depo kökünü bulur ve orada açar.
- Design reference: none — yukarıdaki akış tasarımdır.
- Accessibility: tüm mesajlar düz metin, Türkçe; renk tek bilgi taşıyıcısı değildir.

## Constraints & out of scope
- Sensitive area: yok (emir, risk, sırlar, paper/live, Telegram, portföy, kalıcı durum dokunulmaz).
- Başlatıcı ve devir notu hiçbir sırrı (API anahtarı, `.env`, config içeriği) okumaz ya da yazmaz.
- Kapsam dışı: hak bitişinin otomatik algılanması ve otomatik geçiş; Gemini'nin reviewer rolü
  (2. aşama, ayrı spec); Antigravity IDE (masaüstü uygulaması) entegrasyonu; Antigravity hook'ları;
  MCP bağlantısı; macOS/Linux başlatıcısı.
- Antigravity skill biçimi `agy` sürümüyle değişebilir; değişiklik yalnızca adaptör dosyalarını
  etkiler, çekirdeği değil.
- Split: proposed 0027 (Antigravity komutları) + 0028 (başlatıcı ve devir notu); kept as one —
  Galip, 2026-11-07, ikisi birbirine bağlı ve tek geliştiricide bölmenin yükü getirisinden fazla.
- Kanıt: Gemini'nin söylediklerine dayanan kriterler (AC-7, AC-8, AC-10) ve PowerShell başlatıcısı
  (AC-5, AC-6) `scripts/check` ile otomatik sınanmaz; her biri gerçek bir çalıştırmanın kaydıyla
  (komut, çıktı, öncesi/sonrası `git status`) gözlem olarak kanıtlanır.
- Tek araç kuralı: Codex ve Antigravity aynı `.agents/skills/` klasörünü kullanır; ikisi birden
  kuruluysa ilk kurulanın dosyaları korunur (Req. 1).

## Acceptance criteria
- [ ] AC-1 — Boş bir kopyada `./scripts/init antigravity` her komut için `.agents/skills/<ad>/SKILL.md` oluşturur; aynı komut ikinci kez çalışınca hiçbir dosya değişmez ve her biri "kept" olarak bildirilir; `--force` ile üzerine yazılır; yardım metninde `antigravity` satırı vardır.
- [ ] AC-2 — Claude Code adaptöründeki her komutun `adapters/antigravity/` içinde karşılığı vardır; PLAN'ın karşılığı `anew-plan`'dır (Req. 2); bir tanesi silinince `scripts/doctor` `adapter parity: <ad> missing in antigravity` ile başarısız olur; geri gelince temizdir (selftest senaryosu).
- [ ] AC-3 — Her Antigravity komutunun açıklaması yalnızca `/ad` ile açık çağrıda çalışacağını söyler; bu ifade silinince `scripts/doctor` başarısız olur (selftest senaryosu).
- [ ] AC-4 — Hiçbir Antigravity komut dosyası kural metni içermez: gövdesi, aynı komutun Codex karşılığıyla çağrı biçimi (`$ad` ↔ `/ad`, `$plan` ↔ `/anew-plan`) ve araç adı dışında aynıdır.
- [ ] AC-5 — `scripts/gemini-devam.ps1`, `agy` PATH'te yokken `%USERPROFILE%\.gemini\bin\agy.exe`'yi bulup Gemini'yi depo kökünde varsayılan izin moduyla açar; depo dışındaki bir klasörden çalıştırıldığında da depo kökünde açar; komut satırında izinleri otomatik geçen seçenek yoktur.
- [ ] AC-6 — `agy` iki konumda da yoksa başlatıcı Gemini'yi açmaz, aranan iki konumu ve kurulum ipucunu Türkçe yazar, sıfır olmayan kodla çıkar.
- [ ] AC-7 — Aktif bir spec ve onaylı planı olan bir branch'te başlatıldığında (`specs/active/`'de ikinci bir spec de varken) Gemini iki spec'i `Status`'larıyla listeler, branch'le eşleşeni ana iş sayar ve onun `Status`'unu, bitmemiş ilk plan adımını ve sıradaki segment komutunu söyler; onay gelmeden hiçbir dosya değişmez (`git status` öncesi ve sonrası aynı).
- [ ] AC-8 — Aktif spec yokken ve çalışma ağacı temizken Gemini "aktif iş yok" der ve `/analyze` önerir; hiçbir şey başlatmaz.
- [ ] AC-9 — Claude'da bir tur bittikten sonra devir notu Req. 7'deki alanların hepsini güncel değerlerle taşır; sohbet metni içermez; `git status` notu göstermez (izlenmiyor); not yazılamadığında Claude turu hatasız biter; not yazma turu 2 saniyeden fazla uzatmaz (Req. 7; not arka planda yazılır, A-3); aynı davranış `adapters/claude-code/` şablonunda da vardır.
- [ ] AC-10 — Devir notu yoksa ya da eskiyse (kayıtlı branch veya commit o anki branch/HEAD'den farklı) Gemini bunu açıkça söyler ve durumu dosyalardan çıkarır.
- [ ] AC-11 — `docs/git.md` Gemini commit imzası satırını tanımlar; Antigravity adaptör belgesi ona işaret eder, satırı kopyalamaz.
- [ ] AC-12 — README, `adapters/README.md` ve `docs/commands.md` Antigravity'yi listeler; adaptör belgesi elle geçiş akışını, açık-çağrı boşluğunu ve Codex ile klasör paylaşımını anlatır; `CHANGELOG.md` kaydı vardır; `scripts/check` yeşildir.

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
