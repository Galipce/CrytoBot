# Spec 0030 — CLI kontrol ve acil durdurma (kill switch)

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0030-plan.md`
- Self-critique: done

## Intent
Sistemin sahibi, çalışan veya durmuş CrytoBot'un durumunu konsoldan anlık olarak sorgulayabilmek (`status`), beklenmedik piyasa durumlarında yeni alımları tek bir komutla derhal durdurabilmek (`kill-switch`), durdurmayı güvenle kaldırabilmek (`resume`) ve çalışan bot sürecini turu yarıda bırakmadan kontrollü şekilde kapatabilmek (`stop`) istiyor. Bu iş, ADR 0002 Faz 1 kapsamındaki operasyonel CLI kontrolünü tamamlar ve sahibine bot üzerinde doğrudan, şeffaf müdahale imkanı verir. Başarı: bot çalışırken veya kapalıyken `status`'un doğru ve anlaşılır özet vermesi; kill switch devredeyken açık pozisyonların stop/hedef kapanışları aksamadan yeni alımların engellenmesi; bot yeniden başlasa bile kill switch'in devrede kalması; `stop` ile çalışan sürecin temiz durdurulması ve her eylemin değiştirilemez bir denetim kaydı (audit log) bırakmasıdır. Bilerek yapılmayanlar: Telegram komutları (Faz 2), CLI üzerinden dinamik limit gevşetme/değiştirme (config üzerinden yönetilir) ve web arayüzü kontrolü.

## Requirements
Terimler:
- **Kill switch:** Tüm yeni alım işlemlerini ve pozisyon açılışlarını anında durduran acil durum anahtarı.
- **Durdurma kaldırma (resume):** Hem kill switch'i hem de kasanın zirveden düşüşüyle tetiklenen drawdown durdurmasını kaldıran açık insan eylemi.
- **Temiz durdurma (stop):** Çalışan bot sürecine döngüyü sonlandırma isteği ileten, o an sürmekte olan tur varsa bitmesini bekleyen ve döngüden çıkaran komut.
- **Durum (status):** Botun süreç durumu, risk göstergeleri, kasa/bakiye ve pozisyon özetini konsola yazdıran salt okunur komut.
- **Denetim kaydı (audit log):** Kontrol komutlarının zamanı, kaynağı, türü ve sonucunu içeren değiştirilemez olay kaydı.

Davranış:
- R-1: **Durum sorgulama (`status`).** `status` komutu depoyu salt okunur inceler ve kilit durumunu (`<depo>.lock`) yoklar. Sürecin çalışıp çalışmadığını, çalışma modunu (`paper`), güncel USDT serbest bakiyesini ve toplam kasayı, açık pozisyon sayısını (çift, yön, miktar, giriş fiyatı), günün gerçekleşen ve açık kâr/zararını, zirve kasayı ve güncel drawdown oranını, aktif durdurmaları (yok / drawdown durdurması / kill switch devrede) ve son tamamlanan turun zaman damgası ile özetini anlaşılır bir Türkçe metinle konsola basar. Depoyu değiştirmez, kilidi meşgul etmez; yazım anına denk gelirse standart bekleme süresince (4 s) dener.
- R-2: **Acil alım durdurma (`kill-switch`).** `kill-switch` (veya `kill-switch on`) komutu verildiğinde acil durum anahtarı derhal devreye girer ve depodaki kalıcı risk durumuna işlenir. Durum zaten devredeyse durum değişmez, bilgi verilir. Durdurmayı kaldırmak için `kill-switch off` yerine `resume` zorunludur. Eylem denetim kaydına yazılır ve kullanıcıya onay bildirilir.
- R-3: **Durdurma kaldırma (`resume`).** `resume` komutu verildiğinde aktif olan kill switch ve/veya drawdown durdurması kaldırılır; risk durumundaki zirve kasa son gözlenen kasa seviyesine çekilir (BR-6) ve kalıcı duruma kaydedilir. Hiçbir durdurma yoksa ("ne kill switch ne drawdown durdurması devrede") hiçbir şey değiştirilmeden adıyla bildirilir. Eylem denetim kaydına yazılır.
- R-4: **Temiz süreç durdurma (`stop`).** `stop` komutu çalışan bot sürecine durdurma isteğini kontrol bayrağıyla iletir. Çalışan bot süreci beklemedeyse hemen; tur sürüyorsa turun ve veri kayıtlarının tamamlanmasının ardından temiz biçimde döngüyü sonlandırır (spec 0022 R-12) ve kontrol bayrağını temizler. Çalışan bot yoksa komut adıyla bildirir ve depoya dokunmaz. Eylem denetim kaydına yazılır.
- R-5: **Açık pozisyonların korunması (BR-9).** Kill switch devredeyken bot döngüsü çalışmaya devam ediyorsa, piyasa okunur ve açık pozisyonların stop-loss ve hedef kapanışları (`approve_close`) her zamanki gibi değerlendirilip uygulanır; yalnızca yeni alım önerileri `risk` katmanı tarafından `KILL_SWITCH_ACTIVE` gerekçesiyle onaylanmaz.
- R-6: **Kalıcılık ve yeniden başlama.** Kill switch durumu bot kapatılıp yeniden başlatılsa dahi depoda korunur; insan açık bir `resume` komutu vermediği sürece bot yeni alım yapamaz.
- R-7: **Denetim günlüğü (audit log).** Her kontrol eylemi (`kill-switch`, `resume`, `stop`), eylemin UTC zamanı, kanal adı (`cli`), eylem adı, sonucu ve varsa gerekçesiyle hem kayıt dosyasına hem de kalıcı depoya (append-only) yazılır.
- R-8: **Depo ve kilit durumları.** Depo dosyası henüz oluşturulmamışsa (`prepare` çalıştırılmamışsa) ya da bozuksa, komutlar depoyu kendiliğinden oluşturmaz veya bozmaz; durumu adıyla bildirir.

## User experience
none — no user interface. Kullanıcı konsol komutlarını ve metin çıktılarını görür.
- Flow:
  - Durum inceleme: `python -m crytobot status` → durum özeti konsola basılır.
  - Acil durdurma: `python -m crytobot kill-switch` → durdurma kaydedilir, onay basılır.
  - Yeniden açma: `python -m crytobot resume` → durdurma kaldırılır, onay basılır.
  - Botu kapatma: `python -m crytobot stop` → durdurma isteği iletilir, onay basılır.
- States:
  - Süreç çalışıyor / süreç durdu.
  - Durdurma yok / Drawdown durdurması devrede / Kill switch devrede / İkisi birden devrede.
  - Depo yok / Depo bozuk / Defter açılmamış.
  - Başarılı işlem / Reddedilen eylem (durdurma yokken resume, çalışmayan botta stop).
- Design reference: none — the flow above is the design.
- Accessibility: yalnız klavye; renk bilgi taşımaz.

## Constraints & out of scope
- Sensitive area: `Risk limitleri (risk)`, `Kalıcı durum (persistence)`, `Telegram komut yetkilendirmesi (control)` — `docs/domain.md`. Kill switch ve drawdown durdurması kalıcıdır; silinmiş veya bozuk bir durum sessizce durdurmayı kaldıramaz.
- Out of scope: Telegram komutları (Faz 2); dinamik risk limiti değiştirme (BR-13) — limitler `crytobot.toml` üzerinden yönetilir; web pano kontrolleri (Faz 2); otomatik kurtarma / watchdog.
- Boyut: 9 kabul kriteri. Propose split: 0030 CLI durum ve kill switch (`status`, `kill-switch`, `resume`) ve 0031 Süreç kontrolü (`stop` IPC/sinyal); kept as one — Galip Badem, 2026-11-09, ADR 0002 spec bütçesi korunarak CLI kontrol bütünlüğü tek seferde teslim edilir.

## Acceptance criteria
- [ ] AC-1 — Durum sorgulama (R-1): Hazırlanmış depoda `status` komutu botun süreç durumunu (çalışıyor/durdu), modunu (`paper`), serbest bakiyesini, toplam kasasını, açık pozisyonlarını, günün kâr/zararını, zirve kasayı, drawdown oranını, aktif durdurmaları ve son tur özetini doğru biçimde konsola basar; depoda hiçbir değişiklik yapmaz.
- [ ] AC-2 — Kill switch devreye alma (R-2, R-6): `kill-switch on` komutu kill switch'i kalıcı duruma işler, audit log'a yazar ve onay mesajı basar. Zaten devredeyse durumu bozmadan bilgi verir. Bot kapalıyken veya çalışırken komut güvenle çalışır.
- [ ] AC-3 — Kill switch altında tur davranışı (R-5): Kill switch devredeyken çalışan bot turlarını atmaya devam eder; yeni alım önerileri `risk` katmanı tarafından `KILL_SWITCH_ACTIVE` ile reddedilir; açık pozisyonların stop ve hedef kapanışları (`approve_close`) engellenmeden normal şekilde gerçekleşir.
- [ ] AC-4 — Durdurma kaldırma (R-3): `resume` komutu hem kill switch'i hem de drawdown durdurmasını kaldırır, risk zirve kasasını son gözlenen seviyeye günceller, depoya kaydeder, audit log'a yazar ve onay mesajı basar.
- [ ] AC-5 — Resume reddi (R-3): Hiçbir durdurma aktif değilken (ne kill switch ne drawdown) `resume` komutu durumu değiştirmeden adıyla reddeder ve audit log'a ret kaydı düşer.
- [ ] AC-6 — Temiz süreç durdurma (R-4): `stop` komutu çalışan bot sürecine durdurma isteği iletir; çalışan süreç mevcut turu tamamlar ve temiz biçimde (`ExitReason.STOPPED`) çıkar; çalışan bot yokken komut durumu adıyla bildirir; her iki durum audit log'a işlenir.
- [ ] AC-7 — Kalıcılık ve yeniden başlama (R-6): Kill switch devredeyken bot süreci kapatılıp yeniden başlatıldığında kill switch devrede kalır, alım engeli sürer ve `status` çıktısında durdurma devrede görünür.
- [ ] AC-8 — Denetim günlüğü (R-7): Her kontrol komutu (`kill-switch on`, `resume`, `stop`), UTC zamanı, kanal (`cli`), eylem adı ve sonucu ile hem kayıt dosyasına (`crytobot.log`) hem de kalıcı depoya append-only olarak yazılır.
- [ ] AC-9 — Depo ve hata durumları (R-8): Depo dosyası henüz oluşturulmamışken (`prepare` öncesi) veya bozukken `status`, `kill-switch`, `resume` ve `stop` komutları çökmeden anlamlı hata mesajı basar, yeni depo oluşturmaz ve bozuk dosyayı ezmez.

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
