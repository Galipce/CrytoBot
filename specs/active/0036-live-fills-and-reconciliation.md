# Spec 0036 — Canlı modda gerçek dolum, kesinliği olmayan emir ve coin mutabakatı

- Status: Approved
- Mode: strict
- Plan: `specs/plans/0036-plan.md`
- Self-critique: done

## Intent
Botun sahibi, canlı modda botun defterinin borsada gerçekte olanı yansıtmasını istiyor. Bugün defter canlı emirde bile paper tahminini (tahmini fiyat ve ücret) yazıyor. Binance komisyonu alınan coinden kestiği için bot elinde olmayan miktarı satmaya çalışıyor; ilk alımdan sonra USDT mutabakatı da kalıcı olarak durabiliyor (denetim 2026-11-10: A-2, A-3, A-4, A-5, A-15, S-2). Başarı şöyle görünür: alım ve satış borsanın bildirdiği fiyat, miktar ve komisyonla deftere geçer; satış ve borsa stop emri gerçekten elde olan miktarla verilir; durumu kesin olmayan emir hiçbir koşulda "reddedildi" sayılmaz; borsadaki coin defterdekinden azsa bot alımı durdurur. Bilerek yapılmayanlar: kontrol komutlarının canlı modu (0035), testnet, Telegram düzeltmeleri, BR-10 kapısı, 0034'ün kendi fix turu (S-1, S-3…S-8), eski canlı depo için geçiş (bot canlıda hiç çalışmadı).

## Requirements
Terimler:
- **Gerçek dolum:** borsanın bir emir için bildirdiği ortalama fiyat, dolan miktar, komisyon tutarı ve komisyonun varlığı.
- **Net miktar:** dolan miktardan coin cinsinden kesilen komisyon düşülmüş, çiftin miktar adımına aşağı yuvarlanmış miktar.
- **Toz:** net miktarın yuvarlanmasından ya da komisyondan kalan, miktar adımının altındaki coin artığı.
- **Kesin ret:** borsanın emri açıkça reddettiği durum (yetersiz bakiye, geçersiz emir/filtre, yetki hatası).

Davranış:
- R-1: **Alımda gerçek dolum.** Canlı modda dolan alım, deftere gerçek dolumla geçer: maliyet fiyatı = ortalama fiyat, ücret = gerçek komisyon. Paper tahmini canlı defterde kullanılmaz.
- R-2: **Coinden komisyon.** Komisyon alınan coinden kesildiyse pozisyon miktarı net miktardır; toz pozisyon dışında kayda geçer, satılmaz ve kasaya (equity) katılmaz (G-4). Komisyon USDT'den kesildiyse maliyete eklenir.
- R-2a: **Üçüncü varlıktan komisyon (G-3).** Komisyon başka bir varlıktan (ör. BNB) kesildiyse pozisyon miktarı dolan miktardır; komisyon kendi varlığıyla kaydedilir, USDT değeri o turda okunan `<varlık>/USDT` fiyatıyla hesaplanır. Fiyat okunamazsa ayardaki ücret oranıyla tahmin edilir, kayıt "tahmini" işaretini taşır ve bildirim üretilir; güvenli mod devreye girmez.
- R-3: **Satışta gerçek dolum ve miktar.** Kapanış satışı pozisyonun net miktarıyla verilir; kapanış deftere ortalama fiyat, dolan miktar ve gerçek komisyonla geçer.
- R-4: **Borsa stop miktarı (S-2).** Spec 0034'ün borsa stop emri pozisyonun net miktarıyla verilir.
- R-5: **Kısmi dolum.** Emir kısmen dolup kalanı borsada sona ererse dolan kısım gerçek pozisyon (alımda) ya da gerçek kapanış (satışta) olarak deftere geçer ve bildirim üretilir. Alımda dolan net miktar çiftin asgari miktarının ya da asgari tutarının altındaysa bot güvenli moda geçer, alım durur, bildirim üretilir; satışta kalan pozisyon açık kalır ve sonraki turda yeniden değerlendirilir.
- R-6: **Kesinliği olmayan emir.** Yalnız kesin ret `REJECTED` sayılır. Ağ, zaman aşımı, borsa erişilemezliği, bakım, hız sınırı ve tanınmayan her hata `UNKNOWN` sayılır ve güvenli mod (BR-11) devreye girer.
- R-7: **"Emir yok" yanıtı.** Borsa bir emir için "böyle emir yok" derse emir, verilişinden en az 5 dakika geçmeden ve en az bir sonraki turdaki sorgu da aynı yanıtı vermeden `REJECTED` sayılmaz; o zamana kadar `UNKNOWN` kalır. Süre, emrin deftere kaydedilen veriliş anından botun saatiyle ölçülür (G-6) ve ayarla değiştirilemez.
- R-8: **USDT mutabakatı.** Tur başındaki USDT karşılaştırması (spec 0033, tolerans 0,05 USDT) gerçek dolumla tutulan deftere karşı yapılır.
- R-9: **Coin mutabakatı (A-15).** Canlı tur başında açık pozisyonu olan her coin için borsadaki toplam coin (serbest + borsa stop emrinde bekleyen), o coindeki bütün açık pozisyonların net miktarları toplamından (G-5) bir miktar adımından fazla azsa yeni alım durur, kapanışlar sürer ve çift adıyla bildirim üretilir. Borsadaki fazla coin (sahibin bottan bağımsız varlığı, toz) yok sayılır. Koşul düzelince alım durdurması kalkar ve çıkış bildirimi gider.
- R-10: **Eksik dolum bilgisi.** Borsa `FILLED` dediği halde ortalama fiyat ya da dolan miktar bildirmezse tahmin yazılmaz: emir `UNKNOWN` sayılır, güvenli mod devreye girer.
- R-11: **Eski canlı depo.** Bu spec'ten önce açılmış (gerçek dolum bilgisi taşımayan) bir canlı depo adıyla reddedilir ve yeniden `prepare --live` istenir. Paper ve backtest depoları etkilenmez.
- R-12: **Paper ve backtest değişmez.** Paper ve backtest modlarında dolum, ücret ve boyutlama bugünkü kurallarla sürer.

## User experience
none — no user interface. Kullanıcı yalnız konsol/kayıt satırlarını ve Telegram bildirimlerini görür; dolum bildirimi gerçek fiyatı ve miktarı gösterir.
- States: tam dolum · coinden komisyonlu dolum · kısmi dolum · asgarinin altında kısmi dolum (güvenli mod) · kesinliği olmayan emir (güvenli mod) · "emir yok" bekleme süresi · coin eksikliği (alım durur) · coin fazlası (yok sayılır) · eski canlı depo reddi.
- Design reference: none.
- Accessibility: yok (metin çıktısı).

## Constraints & out of scope
- Sensitive area: Emir gönderimi (`execution`); Portföy / defter (`portfolio`); Kalıcı durum (`persistence`); Risk limitleri — `docs/domain.md`.
- 0034 dalının üstüne gelir; 0034 ship edilmeden PLAN'a geçilmez.
- Kapsam dışı: kontrol komutları (0035), testnet (A-14), Telegram (A-7, A-8), BR-10 (A-6, A-9…A-11), 0034 fix turu, eski canlı depo için geçiş kodu.
- Size: 14 kriter, tek kullanıcı yeteneği (defter ↔ borsa doğruluğu).
- Split: proposed 0036a (gerçek dolum, komisyon, kısmi dolum) → 0036b (kesinliği olmayan emir ve coin mutabakatı); kept as one — Galip Badem, 2026-11-10, hepsi aynı dolum/sorgu akışından geçiyor ve canlı mod ikisi birden bitmeden kullanılamaz (G-7).
- Split (üst): denetimin canlı mod düzeltmeleri 0035 ve 0036 olarak bölündü — Galip Badem, 2026-11-10.
- Self-critique kararları G-3…G-7 (Galip Badem, 2026-11-10) R-2, R-2a, R-7, R-9 ve AC-2, AC-14'e işlendi.

## Acceptance criteria
- [ ] AC-1 — Alımda gerçek dolum (R-1): borsa ortalama fiyatı tahminden farklı bildirdiğinde defterdeki maliyet fiyatı ve ücret borsanın değerleridir.
- [ ] AC-2 — Coinden komisyon (R-2): 1 coin dolup 0,001 coin komisyon kesildiğinde pozisyon miktarı adıma yuvarlanmış net miktardır; artık toz olarak kayıtlıdır, satılmaz ve kasaya katılmaz.
- [ ] AC-3 — USDT'den komisyon (R-2): komisyon USDT ise pozisyon miktarı dolan miktardır, komisyon maliyete eklenir.
- [ ] AC-4 — Satış ve kapanış (R-3): kapanış satışı net miktarla verilir; kapanış ortalama fiyat ve gerçek komisyonla deftere geçer.
- [ ] AC-5 — Borsa stop miktarı (R-4): 0034 borsa stop emri net miktarla verilir.
- [ ] AC-6 — Kısmi dolum (R-5): alım kısmen dolup kalanı sona erdiğinde dolan net miktar pozisyon olur ve bildirim üretilir; satışta kısmi dolum kapanışa geçer, kalan pozisyon açık kalır.
- [ ] AC-7 — Asgarinin altında kısmi dolum (R-5): alımda dolan net miktar asgari miktar ya da asgari tutarın altındaysa güvenli mod devreye girer, alım durur, bildirim üretilir.
- [ ] AC-8 — Hata sınıfları (R-6): ağ hatası, zaman aşımı, borsa erişilemezliği, bakım, hız sınırı ve tanınmayan hata türlerinin her biri `UNKNOWN` verir; yetersiz bakiye, geçersiz emir ve yetki hatası `REJECTED` verir.
- [ ] AC-9 — "Emir yok" bekleme süresi (R-7): verilişten 5 dakikadan az sonra ya da yalnız bir sorguda gelen "emir yok" yanıtı `UNKNOWN` bırakır; 5 dakika geçmiş ve sonraki turda tekrarlanmışsa `REJECTED` olur (sınır değerler: 4 dk 59 s ve 5 dk).
- [ ] AC-10 — Eksik dolum bilgisi (R-10): `FILLED` yanıtında ortalama fiyat ya da dolan miktar yoksa emir `UNKNOWN` olur, defter tahmin yazmaz.
- [ ] AC-11 — Coin mutabakatı (R-9): borsadaki toplam coin, o coindeki açık pozisyonların net toplamından bir adımdan fazla azken (aynı coinde iki pozisyon dahil) alım durur, kapanış sürer, çift adıyla bildirim gider; fazla coin alımı durdurmaz; koşul düzelince çıkış bildirimi gider.
- [ ] AC-12 — USDT mutabakatı gerçek dolumla (R-8): bir alım ve bir kapanıştan sonra, borsa bakiyesi gerçek dolumlara uyduğunda mutabakat durdurması oluşmaz.
- [ ] AC-13 — Eski canlı depo ve paper değişmezliği (R-11, R-12): gerçek dolum bilgisi taşımayan canlı depo adıyla reddedilir; paper ve backtest testleri değişmeden yeşildir.
- [ ] AC-14 — Üçüncü varlıktan komisyon (R-2a): BNB komisyonlu dolumda pozisyon miktarı dolan miktardır; BNB/USDT fiyatı okunduğunda komisyonun USDT değeri bu fiyatla, okunamadığında ayardaki oranla "tahmini" işaretiyle yazılır ve bildirim gider; güvenli mod devreye girmez.

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
