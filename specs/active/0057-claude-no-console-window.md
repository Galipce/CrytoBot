# Spec 0057 — Claude alt süreci konsol penceresi açmaz (mini)

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0057-plan.md`
- Self-critique: done
- Source: istek 2026-11-19 (Galip Badem) — skorlayıcıyı (0051) toplayıcı gibi oturum açılınca konsolsuz çalışan
  zamanlanmış göreve bağlamak; doğrulama: `pythonw` altından bugünkü bayrakla başlatılan alt süreç
  `GetConsoleWindow() = 22153572` (görünür pencere), `CREATE_NO_WINDOW` ile `0`.
- Supersedes: — (0051 süreç başlatma bayraklarını kriter olarak tanımlamıyor; R-5 yalıtım kuralları aynen geçerli)

## Intent
Sahip, LLM olay skorlayıcısını arka planda, konsolsuz (zamanlanmış görev, `pythonw`) çalıştırmak istiyor. Bugün her
Claude çağrısında Windows yeni bir konsol penceresi açıyor; günde 200'e kadar çağrıda bu, masaüstünde yanıp sönen
pencereler demek. Değişiklikten sonra Claude alt süreci ve onun açtığı süreçler pencere açmaz; çağrının sonucu,
yalıtımı ve sonlandırılması bugünkü gibidir.

Self-critique kararları (Galip Badem, 2026-11-19, "tamam onaylıyorum"):
- **G-1:** CB-1 ve CB-2 gerçek alt süreç ve torunla, yalnız Windows'ta koşan bir testle kanıtlanır (başka platformda
  atlanır; CI Linux); kanıt yerel `--fast` koşusu, VERIFY'da ayrıca `pythonw` üst süreçten deneme.
- **G-2:** Durdurma konsol sinyaliyle değil ağaç sonlandırmayla; PB-1 0051'in mevcut testleriyle, testler değişmez.
- **G-3:** Bayrak her zaman eklenir (konsolsuzluğa bağlanmaz): çıktı zaten borulardan okunur, tek davranış kalır.
- **G-4:** `docs/security.md` "`claude -p` yalıtımı" maddesine pencere satırı.

## Changed behavior
- [ ] CB-1 — Windows'ta skorlayıcının başlattığı `claude -p` alt süreci, çağıran süreç konsolsuz olsa da konsol penceresi
  almaz: alt süreç içinden `GetConsoleWindow()` sıfır döner.
- [ ] CB-2 — Alt sürecin kendi başlattığı süreçler (Windows'ta `claude.cmd` → Node) da pencere açmaz: torun süreçte de
  `GetConsoleWindow()` sıfırdır.

## Preserved behavior
- [ ] PB-1 — Süreç ağacıyla sonlandırma aynı (0051 AC-5, R-5): zaman aşımında, durdurma isteğinde ve zorla durdurmada
  alt süreç torunlarıyla sonlanır; torun süreç kalmaz.
- [ ] PB-2 — Yalıtım ve iletişim aynı (0051 R-5): argv ve ortam değişkenleri, boş geçici klasör, istemin stdin'den
  gitmesi, stdout'un en çok 64 KB okunması ve stderr değişmez; çağrı sonucu (yanıt, hata, kota) aynı sınıflanır.
- [ ] PB-3 — Windows dışı platformlarda süreç başlatma değişmez.
- [ ] PB-4 — Terminalden (konsollu) çalışırken de çağrı aynı biçimde sonuçlanır (G-3).

## Out of scope
- Skorlayıcıyı zamanlanmış göreve kurmak (işletim adımı; görev komutu sahibe verilir).
- Skor sonuçlarının Telegram'a bildirilmesi (ayrı spec).
- Toplayıcı ya da başka komutların süreç başlatması.

## Definition of Done
- [ ] `scripts/check` green
- [ ] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [ ] Criterion ↔ evidence table complete for CB-* **and** PB-* (UI: before/after screenshots, agent-captured, judged at SHIP)
- [ ] Spec moved to `specs/done/` (immutable there)

## Handoff
Next: PLAN — Developer runs /plan 0057
