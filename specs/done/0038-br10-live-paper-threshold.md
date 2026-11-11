# Spec 0038 — BR-10 live kapısında paper performans eşiği (mini)

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0038-plan.md`
- Self-critique: done
- Source: `specs/audit-0028-0033.md` A-6 (BR-10 live kapısında paper performans eşiği yok)
- Design: —
- Supersedes: 0033/AC-3 (canlı aşama kapısı yalnız onay alanlarını denetliyordu; bu spec paper kanıtını ve onay sırasını ekler)

## Intent
Botun sahibi, gerçek parayla işleme ancak strateji kanıtlı paper koşusunda yeterince uzun süre ve yeterince çok işlemle maliyet sonrası kârlı çıktıktan ve kendisi bu sonucu gördükten sonra açık onay verdiğinde geçmek istiyor (BR-10: "aşama geçişi metrik eşiği + insan onayı ister"; ADR 0002 Faz 2). Bugün `start --live` paper koşusunun sonucuna hiç bakmıyor. Başarı: eşikleri karşılayan kanıtlı bir paper deposu ve o koşudan sonra verilmiş canlı onay olmadan canlı başlatma olmaz; ret nedeni karşılanmayan eşiğin adıyla söylenir.

Terimler:
- **Paper kanıt deposu:** `[stage]` bölümünde yolu beyan edilen, modu `paper` olan, salt okunur açılan depo.
- **Kanıtlı başlatma kaydı:** paper deposunun her başlatmada tuttuğu kayıt: başlatmanın kanıtlı mı deneme (`--trial`) mi olduğu ve kanıtlıysa onaylı backtest raporu.
- **Paper eşikleri:** asgari süre (gün), asgari kapanmış işlem sayısı, net sonuç > 0, en büyük düşüş sınırı.

Kararlar (clarify S-1…S-7, Galip Badem, 2026-11-11): BR-10 daraltılmaz, eşik kurulur (S-1); kanıt kaynağı paper deposu (S-2); eşikler ve alt sınırlar (S-3); deneme koşusu kanıt sayılmaz, kaydı olmayan depo da sayılmaz (S-4); tek rapor bağı (S-5); onay sırası (S-6); kapı yalnız `start --live`, testnet'te de aynen (S-7). Öz eleştiri G-1…G-8 (Galip Badem, 2026-11-11) CB-3, CB-4, CB-5'e katlandı: gün = 24 saat UTC (G-1), işlem = tam kapanan pozisyon (G-2), açık pozisyon eşiğe girmez ama gösterilir (G-3), kilitli depo ret (G-4), rapor yolu mutlak karşılaştırma (G-5), denetim sırası (G-6), son tur tanımı (G-7), kayıt öncesi geçmiş ret (G-8).

## Changed behavior
- [x] CB-1 — **Kanıtlı başlatma kaydı.** Paper modda her başarılı başlatma, paper deposuna başlatmanın türünü (kanıtlı / deneme) ve kanıtlıysa onaylı backtest raporunun yolunu kalıcı olarak yazar. `--trial` başlatması "deneme" olarak kaydedilir. Kayıt yalnız eklenir, sonradan değiştirilemez; reddedilen başlatma kayıt bırakmaz.
- [x] CB-2 — **Paper kanıt deposunun okunması.** `start --live`, `[stage]` bölümünde `paper_store_path` arar ve o depoyu salt okunur açar; depoya hiçbir şey yazmaz, kilitlemez. Alan yok, boş ya da metin değilse `stage.paper_store_path` adıyla; dosya yoksa, okunamıyor ya da bozuksa, modu `live` ise, ya da canlı deponun kendisiyle aynı dosyaysa nedeniyle reddedilir. Ret, canlı depoya dokunmadan, borsaya istek gitmeden, tur atmadan olur ve çıkış kodu 1'dir.
- [x] CB-3 — **Kanıt bütünlüğü.** Paper deposunda en az bir kanıtlı başlatma kaydı olmak zorundadır. Herhangi bir "deneme" kaydı varsa, hiç başlatma kaydı yoksa (bu specten önce açılmış depo) ilk başlatma kaydından önce depoda tur ya da emir varsa (kayıt öncesi geçmiş), ya da kanıtlı kayıtlar birden fazla rapora bağlıysa ya da bağlandıkları rapor live ayarındaki `stage.report_path` ile aynı değilse canlı başlatma nedeniyle reddedilir ("paper kanıtı: deneme koşusu var", "paper kanıtı: başlatma kaydı yok", "paper kanıtı: başlatma kaydı eksik", "paper kanıtı: rapor uyuşmazlığı"). Rapor yolları mutlak yola çözümlenerek karşılaştırılır (göreli/mutlak yazım farkı ret nedeni değildir). Paper deposu çalışan bir bot tarafından kilitliyse "paper deposu kullanımda" ile reddedilir.
- [x] CB-4 — **Paper eşikleri.** Kanıtlı paper koşusunun (ilk kanıtlı başlatmadan son tura kadar) sonuçları denetlenir; ilk karşılanmayan eşik adıyla söylenir ("paper eşiği karşılanmadı: <ad>"):
  (a) `paper_min_days` — ilk kanıtlı başlatma ile son tur arası en az `paper_min_days` × 24 saat (UTC, takvim günü değil); varsayılan 14, 7'den küçük değer ayar hatası;
  (b) `paper_min_trades` — kapanmış işlem sayısı en az bu kadar; tamamen kapanan her pozisyon (hedef, stop ya da sinyal kapanışı fark etmez) 1 işlemdir; varsayılan 10, 5'ten küçük değer ayar hatası;
  (c) komisyon dahil gerçekleşen net kâr/zarar sıfırdan büyük; sıfır ya da negatif ret;
  (d) gerçekleşen kasa eğrisinin (açılış bakiyesi + kapanışlar sırasıyla) en büyük düşüşü `risk.max_drawdown`'dan ve %25 tavanından büyük değil.
  "Son tur", depoya yazılmış en son turdur; veri bayatlığı nedeniyle işlem yapılmayan turlar dahildir. Net sonuç ve düşüş yalnız gerçekleşmiş kapanışlardan hesaplanır; açık pozisyonların gerçekleşmemiş sonucu eşiğe girmez, açık pozisyon sayısı başlatma satırında gösterilir.
  Eşik ayarları tam sayı değilse, sıfır/negatifse ya da alt sınırın altındaysa ayar adıyla reddedilir.
- [x] CB-5 — **Onay sırası.** `stage.live_approved_at`, paper deposunun son turundan sonra ve şimdiki andan önce (ya da eşit) olmak zorundadır; değilse `stage.live_approved_at` adıyla "onay paper sonucundan önce" ya da "onay gelecekte" nedeniyle reddedilir. Kapı testnet'te (`[exchange] testnet = true`) aynen uygulanır; atlama yolu yoktur. Geçen canlı başlatmanın başlatma satırı ve kaydı paper kanıtını taşır (paper deposu yolu, gün, işlem sayısı, net sonuç, açık pozisyon sayısı). Denetim sırası: mevcut ayar ve rapor kapıları → paper kanıtı (CB-2…CB-5) → kimlik ve yetki denetimi (ağa çıkan tek adım en sonda); paper kanıtı reddi borsaya hiç istek göndermez.

## Preserved behavior
- [x] PB-1 — Paper başlatma (kanıtlı ve `--trial`) spec 0028 kapısıyla bugünkü gibi çalışır: aynı ret nedenleri, aynı başlatma satırları ve `TRIAL_MARK`; paper başlatma `paper_store_path` ve `paper_min_*` alanlarını aramaz, varlıkları paper başlatmayı bozmaz.
- [x] PB-2 — Canlı başlatmanın mevcut kapıları değişmeden ve fail-closed çalışır: çift kilit (`MODE_MISMATCH` / `LIVE_FLAG_REQUIRED`), `live_approved_by`/`live_approved_at` varlık ve biçim denetimi, backtest rapor kapısı (0028 R-3…R-5), kimlik ve yetki denetimi (0033 AC-1, AC-3, AC-4).
- [x] PB-3 — `prepare` ve `prepare --live` bu kapıya tabi değildir ve bugünkü gibi çalışır; `status`, `stop`, `kill-switch`, `resume` ve pano paper deposunu bugünkü gibi okur.

## Out of scope
- Sensitive area: Paper ↔ live mod anahtarı / aşama geçişi; Kalıcı durum (persistence) — `docs/domain.md`.
- Paper onayının rapora bağlanması ve rapor özeti/tarih denetimi (A-9), ücret/slippage/risk karşılaştırması (A-10), fail-open strateji/spread denetimi (A-11), asgari OOS süresi (A-12).
- Kâr faktörü eşiği ve paper sonucunun tazeliği (son paper turunun live başlangıcına uzaklığı) — backlog adayı.
- TOTP onaylı mod geçişi; pano ya da Telegram üzerinden onay.
- Eski paper depolarının geriye dönük "kanıtlı" sayılması (CB-3 gereği sayılmaz; yeni kanıtlı paper deposu açılır).
- Yeni backtest, strateji değişikliği; testnet okuma tutarlılığı (A-14).
- Coverage: değişen her modül için modül başına %90 branch eşiği (`docs/testing.md`).

## Definition of Done
- [x] `scripts/check` green
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Criterion ↔ evidence table complete for CB-* **and** PB-* (UI: before/after screenshots, agent-captured, judged at SHIP)
- [x] Spec moved to `specs/done/` (immutable there)
