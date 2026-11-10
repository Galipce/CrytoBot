# Spec 0037 — Canlı modda kısmi dolum, üçüncü varlıktan komisyon ve coin mutabakatı

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0037-plan.md`
- Self-critique: done

## Intent
Botun sahibi, spec 0036'dan sonra canlı defterin kalan doğruluk boşluklarının kapanmasını istiyor. 0036 kısmi dolumu ve üçüncü varlıktan (ör. BNB) kesilen komisyonu deftere yazmaz, güvenli moda geçer. Bot ayrıca borsadaki coinin defterdeki pozisyonlardan az olduğunu fark etmez (denetim 2026-11-10: A-4, A-15). Başarı şöyle görünür:
- Kısmen dolan alım dolan kısmıyla pozisyon olur.
- Kısmen dolan satış dolan kısmıyla kapanır; kalan pozisyon açık ve korumalı kalır.
- BNB komisyonlu dolum doğru miktar ve doğru USDT değeriyle yazılır.
- Borsadaki coin defterdekinden azsa bot yeni alımı durdurur.

Bilerek yapılmayanlar: 0036'nın kapsamı, testnet, Telegram düzeltmeleri, BR-10 kapısı, eski canlı depo için geçiş.

## Requirements
Terimler 0036'daki gibidir (gerçek dolum, net miktar, toz).

Davranış:
- R-1: **Alımda kısmi dolum.** Alım emri kısmen dolup kalanı borsada sona ererse dolan net miktar gerçek pozisyon olarak deftere geçer ve bildirim üretilir. Borsa stopu (spec 0034) bu net miktarla verilir.
- R-2: **Asgarinin altında kısmi dolum.** Alımda dolan net miktar çiftin asgari miktarının ya da asgari tutarının altındaysa güvenli mod devreye girer, alım durur, bildirim üretilir.
- R-3: **Satışta kısmi dolum (D-2).** Kapanış satışı kısmen dolarsa dolan kısım gerçek kapanış olarak deftere geçer, kalan pozisyon açık kalır, sonraki turda yeniden değerlendirilir ve borsa stopu kalan net miktarla yeniden verilir. Defter, pozisyonun bir kısmının kapanmasını ve gerçekleşen kâr/zararı o kısım için kaydeder; kapanan kısmın maliyeti miktarla orantılıdır: kısım / miktar × (miktar × maliyet fiyatı + alım ücreti) (G-7).
- R-4: **Üçüncü varlıktan komisyon (D-4).** Komisyon başka bir varlıktan (ör. BNB) kesildiyse pozisyon miktarı dolan miktardır; komisyon kendi varlığıyla kaydedilir. USDT değeri, o turda ek olarak okunan `<varlık>/USDT` fiyatıyla hesaplanır. Fiyat okunamazsa ya da `<varlık>/USDT` çifti borsada yoksa (G-9) ayardaki ücret oranıyla tahmin edilir, kayıt "tahmini" işaretini taşır ve bildirim üretilir; güvenli mod devreye girmez.
- R-5: **Coin mutabakatı (A-15).** Canlı tur başında açık pozisyonu olan her coin için borsadaki toplam coin (serbest + borsa stop emrinde bekleyen), o coindeki bütün açık pozisyonların net miktarları toplamından bir miktar adımından fazla azsa yeni alım durur, kapanışlar sürer ve çift adıyla bildirim üretilir. Borsadaki fazla coin (sahibin bottan bağımsız varlığı, toz) yok sayılır. Koşul düzelince alım durdurması kalkar ve çıkış bildirimi gider. Borsa bakiye sorgusu başarısız olursa spec 0033'teki gibi güvenli mod devreye girer, alım durur, bildirim üretilir (G-8).
- R-6: **0036'nın geçici güvenli modu kalkar.** 0036 R-5'in kısmi dolum ve üçüncü varlıktan komisyon için uyguladığı güvenli mod, bu spec'in davranışıyla değiştirilir.
- R-7: **Paper ve backtest değişmez.** Paper ve backtest modlarında dolum, kapanış ve boyutlama bugünkü kurallarla sürer (tam kapanış).

## User experience
none — no user interface. Kullanıcı yalnız konsol ve kayıt satırlarını ve Telegram bildirimlerini görür.
- States: kısmi dolan alım · asgarinin altında kısmi dolum (güvenli mod) · kısmi dolan satış (kalan pozisyon açık) · BNB komisyonu (fiyat okundu) · BNB komisyonu (tahmini) · coin eksikliği (alım durur) · coin fazlası (yok sayılır) · koşul düzeldi (çıkış bildirimi).
- Design reference: none.
- Accessibility: yok (metin çıktısı).

## Constraints & out of scope
- Sensitive area: Emir gönderimi (`execution`); Portföy / defter (`portfolio`); Kalıcı durum (`persistence`); Risk limitleri — `docs/domain.md`.
- Spec 0036'nın üstüne gelir; 0036 ship edilmeden PLAN'a geçilmez.
- D-2: spec 0008 R-4'ün "yalnız tam kapanış" kuralı canlı modda kısmi kapanışla genişler (R-3); paper ve backtest tam kapanışla sürer.
- D-4: komisyon varlığının `/USDT` çifti, beyaz listede olmasa da o tur ek olarak okunur (R-4).
- Kapsam dışı: 0036'nın kapsamı; testnet (A-14); Telegram (A-7, A-8); BR-10; eski canlı depo için geçiş kodu.
- Split: 0036'dan bölündü — Galip Badem, 2026-11-10 (0036 Constraints'e bakın). Canlı mod iki spec de ship edilmeden kullanılmaz.

## Acceptance criteria
- [ ] AC-1 — Alımda kısmi dolum (R-1): alım kısmen dolup kalanı sona erdiğinde dolan net miktar pozisyon olur, borsa stopu bu miktarla verilir ve bildirim üretilir.
- [ ] AC-2 — Asgarinin altında kısmi dolum (R-2): alımda dolan net miktar asgari miktar ya da asgari tutarın altındaysa güvenli mod devreye girer, alım durur, bildirim üretilir (sınır: tam asgari değer güvenli moda geçirmez).
- [ ] AC-3 — Satışta kısmi dolum (R-3): kapanış kısmen dolduğunda dolan kısım kapanış olarak, gerçekleşen kâr/zararı miktarla orantılı maliyetle o kısım için deftere geçer; kalan pozisyon açık kalır, borsa stopu kalan miktarla yeniden verilir, sonraki turda yeniden değerlendirilir; defter ↔ emir çelişkisi oluşmaz.
- [ ] AC-4 — Üçüncü varlıktan komisyon (R-4): BNB komisyonlu dolumda pozisyon miktarı dolan miktardır; BNB/USDT fiyatı okunduğunda komisyonun USDT değeri bu fiyatla, okunamadığında ya da çift borsada yokken ayardaki oranla "tahmini" işaretiyle yazılır ve bildirim gider; güvenli mod devreye girmez.
- [ ] AC-5 — Coin mutabakatı (R-5): borsadaki toplam coin, o coindeki açık pozisyonların net toplamından bir adımdan fazla azken (aynı coinde iki pozisyon dahil) alım durur, kapanış sürer, çift adıyla bildirim gider; tam bir adım eksiklik alımı durdurmaz; fazla coin alımı durdurmaz; koşul düzelince çıkış bildirimi gider; bakiye sorgusu başarısızken güvenli mod devreye girer.
- [ ] AC-6 — 0036 geçici güvenli modu kalkar (R-6): 0036'da güvenli moda geçiren kısmi dolum ve BNB komisyonu senaryoları artık deftere yazılır ve güvenli mod devreye girmez.
- [ ] AC-7 — Paper ve backtest değişmezliği (R-7): paper ve backtest testleri değişmeden yeşildir; paper'da kapanış tam kapanıştır.

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
