# Spec 0036 — Canlı modda gerçek dolum, coinden komisyon ve kesinliği olmayan emir

- Status: Approved
- Mode: strict
- Plan: `specs/plans/0036-plan.md`
- Self-critique: done

## Intent
Botun sahibi, canlı modda defterin borsada gerçekte olanı yansıtmasını istiyor. Bugün defter canlı emirde bile paper tahminini (tahmini fiyat ve ücret) yazıyor. Binance komisyonu varsayılan olarak alınan coinden kestiği için bot, elinde olmayan miktarı satmaya ya da borsa stopuna koymaya çalışıyor; ilk alımdan sonra USDT mutabakatı da kalıcı olarak durabiliyor (denetim 2026-11-10: A-2, A-3, A-5, S-2). Başarı şöyle görünür:
- Tam dolan alım ve satış, borsanın bildirdiği fiyat, miktar ve komisyonla deftere geçer.
- Komisyon coinden kesildiyse pozisyon gerçekten elde olan net miktardır; satış ve borsa stopu bu miktarla verilir.
- Durumu kesin olmayan emir hiçbir koşulda "reddedildi" sayılmaz.
- Henüz desteklenmeyen dolumlar (kısmi dolum, üçüncü varlıktan komisyon) tahminle yazılmaz; bot güvenli moda geçer.

Bilerek yapılmayanlar:
- Kısmi dolumun deftere işlenmesi, üçüncü varlıktan komisyon ve coin mutabakatı: spec 0037.
- Testnet, Telegram düzeltmeleri, BR-10 kapısı.
- Eski canlı depo için geçiş (bot canlıda hiç çalışmadı).

## Requirements
Terimler:
- **Gerçek dolum:** borsanın bir emir için bildirdiği ortalama fiyat, dolan miktar, komisyon tutarı ve komisyonun varlığı.
- **Net miktar:** dolan miktardan coin cinsinden kesilen komisyon düşülmüş, çiftin miktar adımına aşağı yuvarlanmış miktar.
- **Toz:** net miktarın yuvarlanmasından kalan, miktar adımının altındaki coin artığı.
- **Kesin ret:** borsanın emri açıkça reddettiği durum (yetersiz bakiye, geçersiz emir ya da filtre, yetki hatası).

Davranış:
- R-1: **Alımda gerçek dolum.** Canlı modda tam dolan alım, deftere gerçek dolumla geçer: maliyet fiyatı = ortalama fiyat, ücret = gerçek komisyon. Paper tahmini canlı defterde kullanılmaz.
- R-2: **Coinden komisyon.** Komisyon alınan coinden kesildiyse pozisyon miktarı net miktardır. Toz pozisyon dışında kayda geçer, satılmaz ve kasaya (equity) katılmaz. Defterin USDT bakiyesinden düşen tutar, borsada gerçekten ödenen USDT'dir (dolan miktar × ortalama fiyat). Net miktar çiftin asgari miktarının ya da asgari tutarının altındaysa pozisyon yine kaydedilir, ama güvenli mod devreye girer, alım durur ve bildirim üretilir (G-1).
- R-3: **USDT'den komisyon.** Komisyon USDT'den kesildiyse pozisyon miktarı dolan miktardır, komisyon maliyete eklenir.
- R-4: **Satış.** Kapanış satışı pozisyonun net miktarıyla verilir; tam dolan kapanış deftere ortalama fiyat ve gerçek komisyonla geçer. Satışta komisyon USDT'den kesilir; başka varlıktan kesildiyse R-5 uygulanır.
- R-5: **Henüz desteklenmeyen dolum.** Kısmi dolum (dolan miktar emrin miktarından az) ya da USDT ve alınan coin dışında bir varlıktan kesilen komisyon, spec 0037 ship edilene kadar deftere yazılmaz. Emir kesinliği olmayan emir gibi ele alınır: güvenli mod (BR-11) devreye girer, yeni alım durur, çift ve emir kimliğiyle bildirim üretilir. Kısmi dolan kapanışta o pozisyonun kapanışı otomatik olarak yeniden denenmez; "elle bakılmalı" bildirimi sürer (G-2).
- R-6: **Borsa stop miktarı (S-2).** Spec 0034'ün borsa stop emri pozisyonun net miktarıyla verilir.
- R-7: **Kesinliği olmayan emir.** Yalnız kesin ret `REJECTED` sayılır. Ağ hatası, zaman aşımı, borsa erişilemezliği, bakım, hız sınırı ve tanınmayan her hata `UNKNOWN` sayılır ve güvenli mod devreye girer.
- R-8: **"Emir yok" yanıtı.** Borsa bir alım ya da kapanış emri için "böyle emir yok" derse emir, verilişinden en az 5 dakika geçmeden ve bir sonraki turdaki sorgu da aynı yanıtı vermeden `REJECTED` sayılmaz; o zamana kadar `UNKNOWN` kalır. Süre, emrin kayıtlı veriliş anından botun saatiyle ölçülür ve ayarla değiştirilemez. Önceki turun gözlemi bot süreci içinde tutulur; bot yeniden başlarsa sayım baştan başlar (en az bir tur daha beklenir).
- R-9: **Netleşen emirde gerçek dolum (D-1).** Durumu bilinmeyen canlı emir sonradan dolmuş çıkarsa deftere borsanın gerçek dolumu yazılır, emir verilirken tutulan tahmin değil. Paper'da netleşen dolum bugünkü gibi kayıtlı tahmindir.
- R-10: **Defter ile emir kaydı eşleşir (D-3).** Gerçek dolumla (net miktar dahil) yazılan alım ve kapanış, defter ↔ emir mutabakatında çelişki üretmez.
- R-11: **Eksik dolum bilgisi.** Borsa emri "doldu" dediği halde ortalama fiyat, dolan miktar ya da komisyon bildirmezse tahmin yazılmaz: emir `UNKNOWN` sayılır, güvenli mod devreye girer. Sıfır komisyon geçerli bir değerdir; yalnız komisyonun hiç bildirilmemesi eksik bilgidir (G-4).
- R-12: **USDT mutabakatı.** Tur başındaki USDT karşılaştırması (spec 0033, tolerans 0,05 USDT) gerçek dolumla tutulan deftere karşı yapılır.
- R-13: **Eski canlı depo.** Bu spec'ten önce açılmış (gerçek dolum bilgisi taşımayan) bir canlı depo adıyla reddedilir ve yeniden `prepare --live` istenir. Paper ve backtest depoları etkilenmez.
- R-14: **Paper ve backtest değişmez.** Paper ve backtest modlarında dolum, ücret, boyutlama ve netleşme bugünkü kurallarla sürer.

## User experience
none — no user interface. Kullanıcı yalnız konsol ve kayıt satırlarını ve Telegram bildirimlerini görür; dolum bildirimi gerçek fiyatı ve miktarı gösterir.
- States: tam dolum (USDT komisyonu) · tam dolum (coinden komisyon, toz) · henüz desteklenmeyen dolum (güvenli mod) · kesinliği olmayan emir (güvenli mod) · "emir yok" bekleme süresi · eksik dolum bilgisi (güvenli mod) · eski canlı depo reddi.
- Design reference: none.
- Accessibility: yok (metin çıktısı).

## Constraints & out of scope
- Sensitive area: Emir gönderimi (`execution`); Portföy / defter (`portfolio`); Kalıcı durum (`persistence`); Risk limitleri — `docs/domain.md`.
- Spec 0034 ve 0035 ship edildi (#49, #50); bu spec onların üstüne gelir.
- D-1: spec 0011 R-8'in "netleşen dolum kayıtlı tahmindir" kuralı canlı modda geçerli değildir (R-9); paper'da aynen sürer.
- D-3: emir kaydı dolan ve net miktarı taşır; defter ↔ emir mutabakatı net miktarla eşler (R-10).
- D-5: "emir yok" gözlemi bot sürecinin belleğinde tutulur (R-8).
- İşletim notu (G-3): 0037 ship edilene kadar Binance hesabında "komisyonu BNB ile öde" kapalı olmalıdır; açıksa her dolum R-5'e göre güvenli moda geçirir.
- Kapsam dışı: kısmi dolumun deftere işlenmesi ve defterde kısmi kapanış (D-2), üçüncü varlıktan komisyon ve fiyatının okunması (D-4), coin mutabakatı — spec 0037; testnet (A-14); Telegram (A-7, A-8); BR-10 (A-6, A-9…A-11); eski canlı depo için geçiş kodu.
- Split: denetimin canlı mod düzeltmeleri 0035 ve 0036 olarak bölündü; 0036 da planlamada 0036 (gerçek dolum, coinden komisyon, kesinlik) ve 0037 (kısmi dolum, üçüncü varlıktan komisyon, coin mutabakatı) olarak bölündü — Galip Badem, 2026-11-10. Canlı mod iki spec de ship edilmeden kullanılmaz.
- Size: 12 kriter, tek kullanıcı yeteneği (tam dolumda defter ↔ borsa doğruluğu); bölmeden sonra kalan çekirdek, daha fazla bölünürse parçalar tek başına doğru defter üretmez.

## Acceptance criteria
- [ ] AC-1 — Alımda gerçek dolum (R-1): borsa ortalama fiyatı tahminden farklı bildirdiğinde defterdeki maliyet fiyatı ve ücret borsanın değerleridir.
- [ ] AC-2 — Coinden komisyon (R-2): miktar adımı 0,01 iken 1 coin dolup 0,001 coin komisyon kesildiğinde pozisyon miktarı 0,99'dur; 0,009 toz olarak kayıtlıdır, satılmaz ve kasaya katılmaz; defter USDT bakiyesinden dolan miktar × ortalama fiyat düşer. Net miktar asgarinin altındaysa pozisyon kaydedilir, güvenli mod devreye girer, alım durur, bildirim üretilir.
- [ ] AC-3 — USDT'den komisyon (R-3): komisyon USDT ise pozisyon miktarı dolan miktardır, komisyon maliyete eklenir.
- [ ] AC-4 — Satış ve kapanış (R-4): kapanış satışı net miktarla verilir; tam dolan kapanış ortalama fiyat ve gerçek komisyonla deftere geçer.
- [ ] AC-5 — Henüz desteklenmeyen dolum (R-5): kısmi dolan alım, kısmi dolan kapanış ve üçüncü varlıktan komisyonlu dolumun her biri deftere yazılmaz; güvenli mod devreye girer, alım durur, bildirim üretilir; kısmi dolan kapanıştan sonraki turda o pozisyon için yeni kapanış emri verilmez.
- [ ] AC-6 — Borsa stop miktarı (R-6): 0034 borsa stop emri net miktarla verilir.
- [ ] AC-7 — Hata sınıfları (R-7): ağ hatası, zaman aşımı, borsa erişilemezliği, bakım, hız sınırı ve tanınmayan hata türlerinin her biri `UNKNOWN` verir; yetersiz bakiye, geçersiz emir ve yetki hatası `REJECTED` verir.
- [ ] AC-8 — "Emir yok" bekleme süresi (R-8): verilişten 5 dakikadan az sonra ya da yalnız bir sorguda gelen "emir yok" yanıtı `UNKNOWN` bırakır; 5 dakika geçmiş ve sonraki turda tekrarlanmışsa `REJECTED` olur (sınır değerler: 4 dk 59 s ve 5 dk); bot yeniden başlarsa ilk "emir yok" gözlemi yine `UNKNOWN` bırakır; borsa stop emirleri (`cs-`) bu kurala girmez, 0034'teki gibi kalır (G-6).
- [ ] AC-9 — Netleşen emirde gerçek dolum (R-9, R-10): `UNKNOWN` kalan canlı alım sonraki turda dolmuş çıktığında deftere borsanın gerçek dolumu yazılır ve depo çelişki taşımaz; paper'da netleşme kayıtlı tahminle sürer.
- [ ] AC-10 — Eksik dolum bilgisi (R-11): "doldu" yanıtında ortalama fiyat, dolan miktar ya da komisyon yoksa emir `UNKNOWN` olur, defter tahmin yazmaz; sıfır komisyonlu dolum geçerlidir ve deftere yazılır.
- [ ] AC-11 — USDT mutabakatı gerçek dolumla (R-10, R-12): coinden komisyonlu bir alım ve bir kapanıştan sonra, borsa bakiyesi gerçek dolumlara uyduğunda mutabakat durdurması ve defter ↔ emir çelişkisi oluşmaz.
- [ ] AC-12 — Eski canlı depo ve paper değişmezliği (R-13, R-14): gerçek dolum bilgisi taşımayan canlı depo adıyla reddedilir ve `prepare --live` istenir; paper ve backtest testleri değişmeden yeşildir.

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
