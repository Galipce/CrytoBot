# Spec 0013 — Süreç metinleri tek full koşu kuralıyla hizalansın (mini)

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0013-plan.md`
- Self-critique: done
- Source: backlog B-30 (spec 0012, review round 1), B-12 (spec 0005, VERIFY)

## Intent
Sistemin sahibi, her spec'te izlenen süreç metinlerinin proje kararıyla çelişmemesini istiyor. `docs/testing.md`, Two speeds, kural 10'a
göre spec başına tek full koşu vardır ve ship onayından sonra açılan PR'da koşar; dört metin ise hâlâ triage'ın bu koşuyu beklediğini
ya da VERIFY'ın ona dayandığını söylüyor. Başarı: bu metinleri okuyan bir rol kural 10'a uygun davranır ve iki backlog kaydı kapanır.
Botun davranışı değişmez. B-12'de kod işi yoktur: istenen davranış ANEW v1.24 yükseltmesiyle (`2ba92f0`) geldi, yalnız kaydı silinir.

## Changed behavior
Terimler: **proje notu**, ilgili yere eklenen ve kural 10'a atıf yapan kısa cümledir (örnek: `prompts/build.md:25`).

- [ ] CB-1 — `prompts/review.md` review talimatı, kural 10'a atıf yapan bir proje notu taşır: triage full koşuyu beklemez; review `--fast`
  kanıtını (`CHECK GREEN (fast, …)`) plandaki `## Build evidence`'tan aktarır; full koşu review'dan sonra, ship PR'ında gelir.
- [ ] CB-2 — `workflows/segments.md` REVIEW satırı aynı notu taşır: bu projede triage full koşuyu beklemez, kural 10'a atıf yapılır.
- [ ] CB-3 — `prompts/build.md`'nin "TRIAGE waits for it to be green" cümlesinin yanında kural 10'a atıf yapan bir not bulunur: bu projede
  handoff'ta çalışan bir full koşu yoktur, handoff `--fast` yeşilini ve full'un PR'da koşacağını gösterir, triage beklemez. Kırmızı PR koşusu BUILD'e döner.
- [ ] CB-4 — `prompts/verify.md`'nin "fast satırı kanıt değildir" cümlesinin yanında kural 10'a atıf yapan bir not bulunur: bu projede
  VERIFY kanıtı adı geçen test, `--fast` ve kasıtlı bozmadır.
- [ ] CB-5 — `specs/backlog.md`'de B-30 ve B-12 kayıtları yoktur; diğer kayıtların metni aynıdır.

## Preserved behavior
- [ ] PB-1 — `docs/testing.md`, Two speeds, kural 10 ve diğer kurallar bayt bayt aynıdır. Merge koşulu korunur: PR'daki full koşu yeşil olmadan merge yok.
- [ ] PB-2 — Dört dosyada mevcut şablon cümleleri silinmez ve yeniden yazılmaz; fark yalnız eklenen notlardır (`git diff` silinmiş satır olarak
  yalnız not eklemek için değişen satırları gösterir). `workflows/segments.md`'nin lite one-pass bölümü (`:68`) değişmez.
- [ ] PB-3 — Bu dört dosya ve `specs/backlog.md` dışında üretim kodu, test, araç ve CI dosyası değişmez; `./scripts/check --fast` yeşil kalır, `./scripts/selftest` ve `./scripts/doctor --strict` geçer.

## Constraints
- Sensitive area: yok; `docs/domain.md`'deki hassas alanlara dokunulmaz.
- Notlar, bulundukları dosyanın dilinde yazılır: bu dosyalar İngilizce (örnek: `prompts/build.md:25`). Etiketler ve komut adları olduğu gibi kalır.
- Kural 10 yeniden anlatılmaz, atıf yapılır; yeni süreç kuralı eklenmez.

## Out of scope
- `scripts/residue` ve `scripts/selftest`: B-12'nin istediği davranış zaten var.
- `docs/decisions/anew/ANEW-0009-two-speeds-one-contract.md`: ANEW kararları olduğu gibi alınır.
- `docs/commands.md:96-111`: `scripts/check`'in genel başvuru metni; bir rolün adım talimatı değil, kural 10 kendi önceliğini yazıyor.
- `prompts/build.md`, `prompts/verify.md` ve `workflows/segments.md`'de bu çelişkiyle ilgisiz "full" geçen diğer yerler: kural 10 ve `prompts/build.md:25` bunları karşılıyor.
- Şablon metinlerini ANEW tarafında değiştirmek; diğer backlog kayıtları.

## Definition of Done
- [ ] `scripts/check` green
- [ ] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [ ] Criterion ↔ evidence table complete for CB-* **and** PB-*
- [ ] Spec moved to `specs/done/` (immutable there)
