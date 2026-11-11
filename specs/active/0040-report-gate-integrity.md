# Spec 0040 — Rapor kapısı bütünlüğü (mini)

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0040-plan.md`
- Self-critique: done
- Source: `specs/audit-0028-0033.md` A-9, A-10, A-11
- Design: —
- Supersedes: 0028 aşama kapısının "strateji/spread bilgisi yoksa denetim atlanır" davranışı (A-11); 0038 CB-3'ün rapor eşleştirmesi (yalnız yol karşılaştırması); 0025 R-12/AC-9'un "gerçek saat yok, farklı saatlerde aynı bayt" kısmı: rapor üretim anını taşır; aynı veri, ayar ve üretim anı bayt bayt aynı rapor verir (plan 0040 Risk 1, Galip Badem, 2026-11-11)

## Intent
Botun sahibi, paper ve live aşamasına geçişin yalnız onayladığı backtest raporunun birebir aynısıyla ve o rapordaki koşullarla yapılabilmesini istiyor: onaydan sonra değişen ya da yeniden üretilen rapor, raporu iyimser kılan farklı komisyon/slippage/risk ayarı ve eksik bilgi kapıdan geçmez (fail-closed). Metrik eşikleri ve paper kanıtı eşikleri değişmez. Clarify kararları S-1…S-7 Galip Badem, 2026-11-11 tarihinde onayladı.

Terimler:
- **Parmak izi:** Rapor dosyasının diskteki ham baytlarının (satır sonları dahil, dönüştürmesiz) SHA-256 özeti, 64 onaltılık karakter (G-1). Dosyada tek bir bayt değişirse değişir; parmak izi raporun içine yazılmaz (G-7).
- **Üretim anı:** Backtest komutunun raporu yazdığı an (UTC), raporun başlığında.
- **Rapor koşulları:** Raporun üretildiği ayardaki komisyon (`fee`), slippage, risk limitleri (`per_trade_risk`, `daily_loss_limit`, `max_drawdown`, `max_open_positions`, `profit_cost_multiple`) ve ayardaki başlangıç kasası. Her biri botun fiilen kullandığı etkin değerdir; ayarda yazılmayıp varsayılanı kullanılan değer de dahildir (G-5). Canlıda borsadaki gerçek bakiye bu karşılaştırmaya girmez (G-4).

## Changed behavior
- [ ] CB-1 — **Onay rapora bağlıdır (A-9).** Backtest komutu raporu yazdıktan sonra yazdığı baytların parmak izini konsola `rapor parmak izi: <64 karakter>` satırıyla yazar (G-7). Aşama kapısı `[stage] report_sha256` ister; anahtar yoksa `ayar eksik: stage.report_sha256`, 64 onaltılık karakter değilse `ayar geçersiz: stage.report_sha256` ile reddeder; büyük/küçük harf fark etmez (G-2). `stage.report_path`'teki dosyanın parmak izi bu değere eşit değilse `rapor onaylanandan farklı` ile reddeder.
- [ ] CB-2 — **Onay anı sınırlıdır (A-9).** Rapor başlığı üretim anını taşır. `stage.approved_at` üretim anından önceyse `onay rapordan önce`, şimdiki andan sonraysa `onay gelecekte` ile reddedilir; eşitlik kabul edilir, tolerans yoktur.
- [ ] CB-3 — **Rapor koşulları çalışan ayarla aynı olmalıdır (A-10).** Rapor başlığı rapor koşullarının her birini yazar. Kapı her birini çalışan ayardaki değerle birebir sayısal eşitlikle karşılaştırır (`"0.001"` = `"0.0010"`, G-3); ilk farkta `ayar uyuşmazlığı: <ad>` ile reddeder.
- [ ] CB-4 — **Eksik bilgi reddedilir (A-11).** Raporda üretim anı, spread, strateji ya da rapor koşullarından biri yoksa `rapor eksik: <ad>` ile; çalışan ayarın `[backtest]` bölümünde spread yoksa `ayar eksik: backtest.spread` ile reddedilir. Hiçbir denetim bilgi eksikliği yüzünden atlanmaz. Bu specten önce üretilmiş raporlar bu yüzden kapıdan geçmez.
- [ ] CB-5 — **Paper kanıtı aynı rapora bağlıdır (0038 ile).** Kanıtlı paper başlatma kaydı raporun parmak izini de saklar. `start --live`, paper kanıtındaki parmak izi `stage.report_sha256`'ya eşit değilse ya da kayıtta parmak izi yoksa (bu specten önceki kayıt) `paper kanıtı: rapor uyuşmazlığı` ile reddeder.
- [ ] CB-6 — **Ret davranışı.** CB-1…CB-5 retleri kanıtlı paper başlatmada ve `start --live`'da (testnet dahil) uygulanır; ret depoya yazmadan, borsaya istek göndermeden, tur atmadan olur ve çıkış kodu 1'dir. Ret satırı yalnız ilk karşılanmayan denetimin adını taşır. Denetim sırası (G-6): `[stage]` ayar biçimi → rapor okunabilirliği → parmak izi (CB-1) → onay anı (CB-2) → rapor eksik (CB-4) → metrik eşikleri → ayar uyuşmazlıkları (mevcutlar ve CB-3) → paper kanıtı (yalnız canlı, CB-5 dahil) → kimlik/yetki (yalnız canlı, en son).

## Preserved behavior
- [ ] PB-1 — Metrik eşikleri (örneklem dışı net > 0, drawdown sınırı, `min_trades`, `min_profit_factor`) ve mevcut uyuşmazlık denetimleri (whitelist, mum ve tur aralığı, spread, strateji parametreleri) aynı kurallarla ve aynı ret metinleriyle çalışır.
- [ ] PB-2 — `start --trial` aşama kapısına tabi değildir ve bugünkü gibi çalışır; `prepare`, `status`, `stop`, `kill-switch`, `resume` ve pano değişmez.
- [ ] PB-3 — Backtest raporunun mevcut satırları ve metrikleri (örneklem içi, örneklem dışı, tüm koşu) değişmez; yalnız başlığa yeni satırlar eklenir. Backtest'in hesabı değişmez.
- [ ] PB-4 — 0038 paper kanıtı kuralları (deneme kaydı, kayıt yok/eksik, kayıt öncesi geçmiş, gün/işlem/net/düşüş eşikleri, `live_approved_at` sırası) ve denetim sırası (ayar ve rapor kapıları → paper kanıtı → kimlik/yetki) değişmez.

## Out of scope
- Sensitive area: Paper ↔ live mod anahtarı (aşama kapısı) ve risk limitleri (`docs/domain.md`).
- Örneklem dışı dönemin asgari süresi (A-12) — backlog'da kalır (S-7).
- Testnet okuma tutarsızlığı (A-14), A-13, A-16…A-22.
- Metrik eşiklerinin değerleri ve paper kanıtı eşikleri.
- Stratejinin kendisi ve kârlılığı.
- Mevcut rapor dosyalarının dönüştürülmesi: yeniden üretilir.
- Split: önerilmedi; 6 CB mini sınırını (3–5) aşıyor ama tek yetenek (rapor kapısı bütünlüğü), A-9…A-11 aynı denetim sırasını ve rapor başlığını paylaşıyor — Galip Badem, 2026-11-11 (G-8).
- Self-critique kararları G-1…G-8 (Galip Badem, 2026-11-11) Terimler, CB-1, CB-3, CB-6 ve bu bölüme işlendi.

## Definition of Done
- [ ] `scripts/check` green
- [ ] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [ ] Criterion ↔ evidence table complete for CB-* **and** PB-* (UI: before/after screenshots, agent-captured, judged at SHIP)
- [ ] Spec moved to `specs/done/` (immutable there)
