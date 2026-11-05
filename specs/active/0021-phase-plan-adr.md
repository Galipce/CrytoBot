# Spec 0021 — Faz planı ve salt okunur pano kararı kayda geçsin (mini)

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0021-plan.md`
- Self-critique: done
- Source: sahibin talebi ve kararı, Galip Badem, 2026-11-06 ("faz1 belirleyelim kaç spec daha", "ekranları hangi fazda yapalım"; öneriler kabul edildi)

## Intent
Sistemin sahibi, ürünün ne zaman tamamlanacağını ve sıradaki spec'lerin hangi amaca hizmet ettiğini dosyadan okuyabilmek istiyor. Faz planı ve ekranların zamanı sohbette kararlaştırıldı, ama hiçbir dosyada yazılı değil; `docs/architecture.md` ise web dashboard'u zamanı belirsiz bir "sonraki feature" olarak sayıyor. Başarı: altı ay sonra okuyan biri, fazların sırasını ve panonun neden salt okunur olduğunu ADR 0002'den tek başına anlayabiliyor ve mimari belge bu kararla çelişmiyor. Botun davranışı değişmez.

## Changed behavior
- [ ] CB-1 — `docs/decisions/0002-phase-plan-and-dashboard.md` vardır, `Status: Accepted`, `Date: 2026-11-06` taşır ve `docs/decisions/TEMPLATE.md`'nin beş bölümünün (Context, Decision, Consequences, Alternatives considered, Revisit triggers) hepsi doludur; Consequences'taki her madde hem kazancı hem bedeli yazar.
- [ ] CB-2 — ADR'ın Decision bölümü üç fazı adlandırır. Faz 1: giriş noktası ve döngü, config ve CLI (başlat, durdur, kill switch, durum), yalnız gönderen Telegram bildirimi, günlük rapor ve metrikler, out-of-sample backtest; live ve API anahtarı yok. Faz 2: önce localhost'ta salt okunur pano, ardından küçük sermayeyle live. Faz 3: `llm`, `news`, `research` ve sinyallerin `strategy`'de birleşmesi. Pano kontrol komutu taşımaz.
- [ ] CB-3 — ADR, BR-10'u Faz 1'de backtest'in gerekçesi olarak gösterir ve B-29, B-42, B-45, B-48, B-50'yi Faz 1'e, B-51'i Faz 2'nin stop emri işine bağlar.
- [ ] CB-4 — `docs/architecture.md`'nin "Deliberately out of scope" listesinde "Web dashboard (sonraki feature)" satırı yoktur; yerinde kontrol komutlu ya da localhost dışından açılan web arayüzünün kapsam dışı olduğunu, salt okunur localhost panonun Faz 2'de olduğunu söyleyen ve ADR 0002'ye atıf yapan tek satır vardır.

## Preserved behavior
- [ ] PB-1 — `docs/domain.md` (BR-1…BR-13, invariantlar, hassas alanlar), `docs/security.md` ve `docs/decisions/0001-persistence-module.md` bayt bayt aynıdır. `docs/architecture.md`'de yalnız CB-4'ün satırı değişir.
- [ ] PB-2 — `specs/backlog.md` değişmez: hiçbir kayıt eklenmez, silinmez, metni değişmez; bağ ADR'dan backlog'a doğrudur.
- [ ] PB-3 — `src/`, `tests/`, `scripts/`, `.github/` ve adaptör dosyaları değişmez; `./scripts/check --fast` yeşil kalır ve `./scripts/doctor --strict` geçer.

## Constraints
- Sensitive area: yok. ADR live ve Telegram'dan söz eder ama hiçbir kuralı, limiti ya da güvenlik şartını değiştirmez; o işler kendi spec'lerinde, hassas alan kurallarıyla gelir.
- Spec sayıları ve süreler tahmindir, ADR'da tahmin olarak yazılır; kriter değildir.
- Belgeler Türkçe (AGENTS.md, Language); ADR alan etiketleri İngilizce.

## Out of scope
- Faz 1 spec'lerinin kendileri (giriş noktası, CLI, bildirim, rapor, backtest): her biri ayrı spec, `/analyze` ile.
- `specs/backlog.md` kayıtlarına faz notu eklemek (PB-2).
- Panonun teknolojisi, ekran listesi ya da tasarımı: Faz 2'nin pano spec'i.
- ANEW kararları (`docs/decisions/anew/`) ve süreç metinleri.

## Definition of Done
- [ ] `scripts/check` green
- [ ] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [ ] Criterion ↔ evidence table complete for CB-* **and** PB-*
- [ ] Spec moved to `specs/done/` (immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | |
| Fix rounds | |
| Review findings: real / noise / deferred | |
| Regressions introduced | |
| Bugs escaped to production | |
