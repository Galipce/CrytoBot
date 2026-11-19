# Spec 0058 — Süreç ağacı sonlandırma konsol penceresi açmaz (mini)

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0058-plan.md`
- Self-critique: done
- Source: B-102 (`specs/backlog.md`; spec 0057 review round 1 F-2)
- Supersedes: — (0051 ve 0057 `taskkill` başlatmasının penceresini tanımlamıyor)

## Intent
Skorlayıcı konsolsuz zamanlanmış görevde çalışıyor (0057). Bir Claude çağrısı zaman aşımına uğradığında, durdurulduğunda
ya da çıktı sınırını aştığında alt süreç ağacı Windows'ta `taskkill` ile sonlandırılıyor; `taskkill` bugün penceresiz
başlatılmadığı için o anlarda kısa bir konsol penceresi açılıyor. Değişiklikten sonra sonlandırma da pencere açmaz;
sonlandırmanın kendisi bugünkü gibidir.

Self-critique kararları (Galip Badem, 2026-11-19, "devam"):
- **G-1:** Windows'ta penceresiz başlatma tek yardımcıda; Claude alt süreci ve `taskkill` ondan geçer. Kanıt: (1) bu
  yardımcıyla `pythonw` ara süreçten başlatılan sınama süreci `GetConsoleWindow() = 0`; (2) `kill_tree`'nin `taskkill`'i
  bu yardımcıyla başlattığını gösteren test (uygulamaya yakın; kısa ömürlü `taskkill`'in penceresi başka türlü
  ölçülemez — review'a açıkça not).
- **G-2:** `taskkill` takılırsa bugünkü süre sınırı (`_KILL_WAIT_S`) aynen; PB-1 kapsar.
- **G-3:** Kanıt yerel Windows `pytest -m slow tests/llm` (0057 Known trap).
- **G-4:** `docs/security.md` 0057 satırına "sonlandırma da", CHANGELOG; B-102 ship'te kapanır.

## Changed behavior
- [ ] CB-1 — Windows'ta Claude alt süreç ağacının sonlandırılması (zaman aşımı, durdurma, zorla durdurma, çıktı sınırı),
  çağıran süreç konsolsuz olsa da konsol penceresi açmaz.

## Preserved behavior
- [ ] PB-1 — Ağaçla sonlandırma aynı (0051 AC-5): zaman aşımında, durdurmada ve zorla durdurmada alt süreç torunlarıyla
  sonlanır; torun süreç kalmaz; sonlandırma bekleme sınırı aynı.
- [ ] PB-2 — 0057 aynı: Claude alt süreci ve torunları pencere almaz.
- [ ] PB-3 — Windows dışı platformlarda sonlandırma (`killpg`) değişmez.

## Out of scope
- Toplayıcı, bot ya da başka komutların süreç başlatması.
- Sonlandırmanın sırası ve süreleri (yalnız pencere davranışı).

## Definition of Done
- [ ] `scripts/check` green
- [ ] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [ ] Criterion ↔ evidence table complete for CB-* **and** PB-* (UI: before/after screenshots, agent-captured, judged at SHIP)
- [ ] Spec moved to `specs/done/` (immutable there)

## Handoff
Next: PLAN — Developer runs /plan 0058
