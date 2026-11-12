# Spec 0041 — Testnet tutarlılığı (mini)

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0041-plan.md`
- Self-critique: done
- Source: `specs/audit-0028-0033.md` A-14
- Design: —
- Supersedes: 0033 R-5 ve 0032 R-8'in "testnet'te yalnız emir/hesap uçları testnet'e bağlanır, yetki denetimi mainnet'teki gibi yapılır" kısmı: testnet'te okumalar da testnet'ten yapılır, yetki denetimi yalnız testnet'te imzalı hesap sorgusuyla değiştirilir (S-1, S-2)

## Intent
Botun sahibi, gerçek paraya geçmeden önce botu Binance Spot Testnet'te uçtan uca deneyebilmek istiyor. Bugün testnet başlatması her zaman reddediliyor; reddedilmese bile bot kararını mainnet fiyat ve kurallarıyla verip emri testnet'e gönderirdi. Başarı: testnet'te fiyat, mum, kurallar, bakiye ve emir tek ağdan okunur ve yazılır; başlatma testnet'te de bütün kapılardan geçerek açılır; mainnet'te hiçbir denetim gevşemez. Clarify kararları S-1…S-7 Galip Badem, 2026-11-12 tarihinde onayladı.

Terimler:
- **Ağ:** Canlı modun bağlandığı Binance Spot ortamı — `mainnet` ya da `testnet` (`[exchange] testnet`).
- **Okumalar:** Döngünün karar için kullandığı borsa verileri: piyasa/kural listesi (lot, fiyat hassasiyeti, asgari tutar), mumlar, son fiyat (ticker).

## Changed behavior
- [ ] CB-1 — **Testnet'te okumalar testnet'ten (S-1).** Canlı modda `[exchange] testnet = true` iken `start --live` ve `prepare --live` bütün okumaları testnet'ten yapar; o koşu boyunca mainnet'e hiçbir istek gitmez. Okuma hataları mainnet'teki sınıflarla birebir aynı davranır (bayat veri, bütçe, 429/418, ban); testnet'e ulaşılamadığında mainnet'e geri dönülmez (S-3).
- [ ] CB-2 — **Testnet'te yetki denetimi (S-2).** Testnet'te borsa anahtar kısıtı sorgusu yapılmaz; yerine testnet anahtarıyla imzalı bir hesap (bakiye) sorgusunun başarılı olması şarttır. Sorgu başarısızsa başlatma `PERMISSION_CHECK_FAILED` ile fail-closed reddedilir (çıkış 1, tur atılmaz). Başarılıysa `testnet: yetki denetimi atlandı` satırı konsola, kayıt dosyasına ve başlatma kaydına yazılır; Telegram'a gönderilmez (G-5). Mainnet'te yetki denetimi bugünkü gibidir; testnet bayrağı dışında hiçbir ayar, argüman ya da ortam değişkeni denetimi atlatmaz.
- [ ] CB-3 — **Paper modda testnet reddi (S-4).** Paper modda (`start`, `start --trial`, `prepare`) ayarda `[exchange] testnet = true` varsa komut `ayar geçersiz: exchange.testnet (testnet yalnız live modda)` ile reddeder; depoya yazılmaz, borsaya istek gitmez, çıkış 1.
- [ ] CB-4 — **Depo ağa bağlıdır (S-5).** Canlı depo ilk açıldığı ağı kaydeder. `start --live` ya da `prepare --live` depoyu kayıtlı ağından farklı bir ağla açmaya çalışırsa `depo ağı uyuşmuyor: depo=<ağ> ayar=<ağ>` ile reddeder; depoya yazılmaz, borsaya istek gitmez, çıkış 1. Ağ kaydı olmayan (0041 öncesi) canlı depo `mainnet` sayılır ve ilk açılışta öyle kaydedilir (G-1). `kill-switch`, `resume`, `stop`, `status` ve pano ağ denetimi yapmaz, depodaki ağı yalnız gösterir (G-2). Denetim sırası: ayar ve rapor kapıları → paper kanıtı → depo ağı → kimlik/yetki (ağa çıkan adım en sonda).
- [ ] CB-5 — **Testnet görünürdür (S-6).** Testnet deposunda `status` çıktısı ve pano ağı `testnet` olarak gösterir; testnet koşusunun gönderdiği her Telegram mesajı — ret, hata, güvenli mod ve kill-switch bildirimleri ile 400 sonrası düz metin yedeği dahil — `[TESTNET]` önekiyle başlar (G-4). Mainnet'te `status`, pano ve Telegram çıktıları değişmez; ağ işareti yalnız testnet'te görünür (G-3).
- [ ] CB-6 — **Gerçek testnet gözlemi (S-7).** Sahibin testnet anahtarıyla bir kez elle `prepare --live` ve en az bir turluk `start --live` çalıştırılır; çıktı (sır içermeden) kanıt olarak kaydedilir: başlatma kabul edilir, okumalar ve emir/bakiye çağrıları testnet adresine gider. Çıktı repo dışında tutulur; VERIFY tablosu yalnız tarih, komut ve sonuç satırlarını alıntılar, anahtar ve imza görünmez. Testnet'e erişilemezse kriter bekletilmez, R-08 ile spec dışına taşınır (G-6).

## Preserved behavior
- [ ] PB-1 — Mainnet canlı mod (`testnet` yok ya da `false`): okumalar, yetki denetimi, emirler, mutabakat, ret metinleri ve çıktılar bugünküyle aynıdır.
- [ ] PB-2 — Paper mod (`testnet` yok ya da `false`), backtest ve geçmiş veri komutları bugünkü gibi mainnet'ten okur.
- [ ] PB-3 — Aşama, rapor ve paper kanıtı kapıları (0038, 0040) testnet'te aynen uygulanır; testnet bunlardan hiçbirini atlatmaz.
- [ ] PB-4 — Testnet'te yalnız `BINANCE_TESTNET_API_KEY`/`SECRET` yüklenir; mainnet anahtarı yüklenmez (0032 R-8).

## Out of scope
- Sensitive area: Paper ↔ live mod anahtarı, API anahtarları / sırlar, emir gönderimi, kalıcı durum (`docs/domain.md`).
- Backtest ve geçmiş veri komutlarının testnet'e taşınması (testnet geçmişi kanıt değeri taşımaz).
- Aşama/rapor/paper kanıtı kapılarında değişiklik; A-12, A-13, A-16…A-22.
- Testnet'e özel strateji, risk ya da eşik değerleri.
- Split: önerilmedi; 6 CB mini sınırını (3–5) aşıyor ama tek yetenek (testnet'te uçtan uca koşu), CB-1…CB-5 aynı ağ seçimini ve denetim sırasını paylaşıyor — Galip Badem, 2026-11-12 (G-7).
- Self-critique kararları G-1…G-7 (Galip Badem, 2026-11-12) CB-2, CB-4, CB-5, CB-6 ve bu bölüme işlendi.

## Definition of Done
- [ ] `scripts/check` green
- [ ] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [ ] Criterion ↔ evidence table complete for CB-* **and** PB-* (UI: before/after screenshots, agent-captured, judged at SHIP)
- [ ] Spec moved to `specs/done/` (immutable there)
