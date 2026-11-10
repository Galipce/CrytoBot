# Spec 0035 — Kontrol komutları ve pano canlı modda

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0035-plan.md`
- Self-critique: done

## Intent
Botun sahibi, bot gerçek parayla canlı modda çalışırken de acil durdurmayı (`kill-switch`), durdurmayı kaldırmayı (`resume`), temiz durdurmayı (`stop`), durum sorgusunu (`status`) ve salt okunur panoyu kullanabilmek istiyor. Bugün bu komutlar depoyu yalnız paper depo olarak açtığı için canlı depoda "mod uyuşmuyor" diye reddediliyor; canlı botu durdurmanın tek yolu süreci kesmek (denetim 2026-11-10, A-1). Başarı şöyle görünür: canlı bot çalışırken `kill-switch` devreye girer ve sonraki turdan itibaren yeni alım olmaz; `stop` botu temiz durdurur; `status` ve pano gerçek modu gösterir; paper modda davranış bugünküyle aynı kalır. Bilerek yapılmayanlar: borsadaki gerçek dolumun deftere işlenmesi ve bakiye mutabakatı (spec 0036), "tüm pozisyonları kapat" acil eylemi, Telegram'dan kontrol, testnet desteği.

## Requirements
Terimler:
- **Ayardaki mod:** `crytobot.toml` `bot.mode` değeri (`paper` ya da `live`).
- **Deponun modu:** deponun oluşturulurken kaydettiği mod.
- **Sıkılaştıran eylem:** yeni alımı engelleyen ya da botu durduran eylem (`kill-switch`, `stop`). **Gevşeten eylem:** engeli kaldıran eylem (`resume`).

Davranış:
- R-1: **Moda göre depo.** `status`, `kill-switch`, `resume`, `stop` ve pano depoyu ayardaki modla açar. Canlı depoda bu komutlar paper depodaki davranışın aynısını gösterir (spec 0030 R-1…R-8, spec 0031).
- R-2: **Mod uyuşmazlığı.** Ayardaki mod ile deponun modu farklıysa:
  - Gevşeten eylem (`resume`) depoya dokunmadan, iki modu da adıyla söyleyerek reddedilir.
  - Sıkılaştıran eylem (`kill-switch`) deponun kendi modunda uygulanır; çıktı ve denetim kaydı uyuşmazlığı adıyla belirtir. Gerekçe: acil durdurma, ayar hatası yüzünden başarısız olmamalıdır.
  - `stop` modlardan bağımsızdır, çalışan sürece iletilir; çıktı uyuşmazlığı belirtir.
  - `status` ve pano deponun gerçek modunu gösterir ve uyuşmazlığı uyarı olarak belirtir.
- R-3: **Gerçek mod gösterimi.** `status` çıktısı ve pano, deponun modunu (`paper`/`live`) gösterir; sabit "paper" metni kalmaz. Canlı modda `status` çıktısının ve panonun ilk satırı tam olarak `CANLI MOD — gerçek para` metnidir (G-2).
- R-4: **Çalışan canlı bota etki.** Canlı bot çalışırken `kill-switch` verilirse, botun bir sonraki turundan itibaren yeni alım yapılmaz; açık pozisyonların stop ve hedef kapanışları sürer (BR-9, spec 0030 R-5). `stop` canlı botu temiz durdurur (spec 0030 R-4). Bir tur sürerken verilen `kill-switch` o turun kaydıyla silinmez; tur bittiğinde de devrededir (G-1; paper için de geçerlidir).
- R-5: **Borsaya çıkmama.** Bu komutların hiçbiri borsaya istek göndermez ve API anahtarı istemez; anahtar eksik ya da geçersiz olsa da çalışırlar.
- R-6: **Denetim kaydı.** Her kontrol eylemi denetim kaydına deponun modunu da yazar; uyuşmazlık varsa kayıt bunu taşır.
- R-7: **Çalışan botta `resume`.** Bot çalışırken `resume` depoya dokunmadan `çalışan bot var: önce stop` ile reddedilir; ret denetim kaydına yazılır (plan 0035 Risk 2, R-08 — Galip Badem, 2026-11-10).

## User experience
none — no user interface (CLI) ve mevcut salt okunur pano. Değişen yalnız gösterilen mod bilgisi.
- Flow: canlı bot çalışırken ikinci bir terminalden `python -m crytobot kill-switch` → onay satırı → sonraki turda alım yok.
- States: canlı depoda başarılı komut · ayar/depo mod uyuşmazlığı (her komut için R-2'deki sonuç) · depo yok · depo bozuk (spec 0030 R-8).
- Design reference: none — mevcut pano; yalnız mod satırı eklenir.
- Accessibility: mod bilgisi yalnız renkle verilmez, metin olarak da yazılır.

## Constraints & out of scope
- Sensitive area: Paper ↔ live mod anahtarı; Kalıcı durum (`persistence`); Risk limitleri (kill switch) — `docs/domain.md`.
- Paper modda davranış ve mevcut testlerin beklentileri değişmez.
- Kapsam dışı: gerçek dolum ve bakiye mutabakatı (0036), "tüm pozisyonları kapat", Telegram kontrolü, testnet (denetim A-14), depo şeması değişikliği.
- Split: denetimdeki canlı mod düzeltmeleri 0035 (bu spec, kontrol) ve 0036 (defter ↔ borsa) olarak bölündü — Galip Badem, 2026-11-10.
- Self-critique kararları G-1, G-2 (Galip Badem, 2026-11-10) R-3, R-4 ve AC-2, AC-11'e işlendi.

## Acceptance criteria
- [ ] AC-1 — Canlı depoda `kill-switch` (R-1, R-4): `bot.mode = "live"` ve canlı depo ile `kill-switch` kalıcı durumu devreye alır, onay yazar; aynı depoyla bir sonraki canlı turda alım önerisi `KILL_SWITCH_ACTIVE` ile onaylanmaz, açık pozisyonun stop kapanışı yine yapılır.
- [ ] AC-2 — Canlı depoda `resume` ve `status` (R-1, R-3): `resume` kill switch'i kaldırır; `status` canlı depoda çalışır, modu "live" olarak gösterir ve ilk satırı tam olarak `CANLI MOD — gerçek para` metnidir.
- [ ] AC-3 — Canlı botu `stop` ile durdurma (R-4): çalışan canlı bot `stop` ile turunu tamamlayıp temiz çıkar; bayrak temizlenir.
- [ ] AC-4 — Pano canlı depoda (R-1, R-3): pano canlı depoyu okur, `/api/status` modu `live` döner, sayfa modu metin olarak gösterir.
- [ ] AC-5 — Uyuşmazlıkta `resume` reddi (R-2): ayar `paper`, depo `live` (ve tersi) iken `resume` depoya dokunmadan, iki modu adıyla söyleyerek reddedilir; çıkış kodu ret kodudur.
- [ ] AC-6 — Uyuşmazlıkta `kill-switch` uygulanır (R-2): ayar ile depo modu farklıyken `kill-switch` deponun modunda devreye alınır; çıktı ve denetim kaydı uyuşmazlığı belirtir.
- [ ] AC-7 — Uyuşmazlıkta `status`, pano ve `stop` (R-2): deponun gerçek modu ve uyuşmazlık uyarısı gösterilir; `stop` çalışan sürece iletilir.
- [ ] AC-8 — Borsaya çıkmama (R-5): API anahtarı tanımsızken dört komut ve pano canlı depoda çalışır; hiçbir borsa isteği gönderilmez.
- [ ] AC-9 — Denetim kaydı modu taşır (R-6): her eylemin kaydında deponun modu, uyuşmazlıkta da uyuşmazlık bilgisi yer alır.
- [ ] AC-10 — Paper davranışı korunur: paper depoda dört komutun ve panonun çıktısı, mod satırı dışında bugünküyle aynıdır; mevcut testler değişmeden yeşildir.
- [ ] AC-11 — Tur sırasında kill switch kaybolmaz (R-4, G-1): bir tur depoyu yükledikten sonra ve kaydetmeden önce `kill-switch` yazılırsa, tur bittiğinde depoda kill switch devrededir ve sonraki turda alım onaylanmaz (canlı ve paper).
- [ ] AC-12 — Çalışan botta `resume` reddi (R-7): bot çalışırken (`.lock` tutuluyor) `resume` depoyu değiştirmeden `çalışan bot var: önce stop` ile reddedilir, ret denetim kaydına yazılır, çıkış kodu ret kodudur; bot durunca aynı komut kill switch'i kaldırır.

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
