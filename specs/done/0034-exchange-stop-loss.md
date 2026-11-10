# Spec 0034 — Borsada Şartlı Stop Emri ve B-51 Satış Slippage Riski

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0034-plan.md`
- Self-critique: done

## Intent
Sistemin sahibi, canlı modda (`live`) açılan spot pozisyonların piyasa dalgalanmalarına, ani sert düşüşlere veya botun/sunucunun kapanması, ağ kopması gibi durumlara karşı korunabilmesi için stop-loss emrinin botun yazılımsal döngüsü yerine doğrudan borsa (Binance Spot) emir defterine koşullu emir olarak iletilmesini ve `specs/backlog.md`'deki **B-51** maddesi uyarınca risk boyutlamasında satış bacağı slippage ve komisyonunun hesaba katılmasını istemektedir. Başarı; canlı modda bir alım emri dolduğunda (`FILLED`), ilgili pozisyon miktarı ve stop fiyatı için borsaya tekil kimlikli (`cs-<id>`) koşullu piyasa stop emrinin (`STOP_LOSS`) otomatik iletilmesi; emir borsa tarafında tetiklenip dolduğunda bir sonraki turda veya emir sorgusunda pozisyonun `CloseReason.STOP_LOSS` ile deftere işlenerek kapatılması ve USDT serbest bakiyesinin mutabakat öncesi eşitlenmesi; pozisyon kâr hedefine ulaştığında (`TAKE_PROFIT`) veya döngü kararıyla piyasadan kapatıldığında borsadaki bekleyen açık stop emrinin iptal edilmesi (`cancel_order`); borsa stop emri verilemez veya belirsiz kalırsa botun fail-closed güvenli moda geçmesi (`STOP_ORDER_FAILED`); ve risk onayında satış bacağı slippage ve komisyonunun da formüle katılarak kasa riskinin BR-4 %1 sınırları içinde tutulmasıdır. Bilerek yapılmayanlar: Kâr hedefi (Take-Profit) için borsaya OCO veya limit emir iletimi (hedef kapanışları mevcut yazılımsal döngü takibinde kalacaktır); vadeli işlem/marjin/short stopları; paper ve backtest modlarında borsaya emir gönderimi (simüle döngü korunur); borsa stop limitlerinde borsa dışı manuel müdahalelerin otomatik portföy mutabakatı dışındaki karmaşık senkronizasyonu.

## Requirements
Terimler:
- **Borsada Şartlı Stop Emri (Exchange Stop-Loss Order):** Canlı modda bir alım emri dolduğunda borsa tarafına iletilen, piyasa fiyatı belirlenen stop fiyatına ulaştığında borsa eşleştirme motoru tarafından otomatik olarak piyasa satış emrine dönüştürülen koşullu emir (`STOP_LOSS`).
- **Koşullu Stop Emri Kimliği (`clientOrderId`):** Borsada stop emrini tekil olarak tanımlamak ve mükerrerliği önlemek için üretilen tekil kimlik (`cs-<position_id>`).
- **B-51 Satış Bacağı Slippage Riski:** Pozisyon boyutlama ve risk onayında, alış slippage'ına ek olarak pozisyon stop seviyesinde kapatılırken oluşacak satış slippage'ı ve komisyonunun da toplam işlem riskine dahil edilmesi.
- **Stop İptal Güvencesi (Cancel-Before-Close):** Pozisyon kâr hedefi veya döngü kararıyla piyasadan kapatılırken, bakiye çakışmasını ve mükerrer satışı önlemek amacıyla önce borsadaki açık stop emrinin iptal edilmesi kuralı.
- **Mutabakat Öncesi Stop Çözümleme (Pre-Reconciliation Stop Sync):** Canlı mod tur başında, borsa bakiye mutabakatı çalıştırılmadan önce açık pozisyonlara ait stop emirlerinin durumunun borsadan sorgulanması ve dolan stopların deftere işlenmesi.

Davranış:
- R-1: **B-51 Satış Bacağı Risk Boyutlaması (`risk._size`).** Risk modülü işlem önerisini onaylarken ve pozisyonu boyutlandırırken (`TradeApproval`), işlem başına risk tutarını (`unit_loss`) hem alış bacağındaki slippage (`slipped_entry = entry * (1 + slippage)`) hem de stop satış bacağındaki slippage (`slipped_stop = stop * (1 - slippage)`) ve her iki bacağın komisyonları üzerinden hesaplar. Hesaplanan toplam risk bütçeyi (`equity * per_trade_risk`) aşamaz.
- R-2: **Alım Dolum Kapısında Satış Slippage Denetimi (`_fill_gate`).** `app` alım kapısı (`_fill_gate`), alım anındaki güncel fiyata göre risk denetimi yaparken satış bacağı slippage'ını (`stop * (1 - slippage)`) ve komisyonunu hesaba katar. Gerçekleşecek tahmini kayıp BR-4 sabit üst sınırını (`cap`) veya config limitini aşarsa alım oluşturulmaz (`RISK_LIMIT_AT_FILL` / `RISK_CAP_AT_FILL`).
- R-3: **Canlı Alım Dolumu Sonrası Şartlı Stop Emri İletimi.** Canlı modda bir alım emri `FILLED` olduğunda, `execution` modülü / `LiveExchange` aracılığıyla borsa spot API'sine pozisyonun tam miktarı ve stop fiyatı ile koşullu stop emri (`STOP_LOSS`, `clientOrderId = cs-<position_id>`) iletilir.
- R-4: **Borsa Stop Emri Borsa Yeteneği ve Fallback.** Borsa adaptörü `place_stop_order` çağrısında sembol için `STOP_LOSS` (piyasa stop) emrini dener; borsa `STOP_LOSS` piyasa emrini desteklemiyorsa veya kısıtlıyorsa, stop fiyatının altına limit koyan `STOP_LOSS_LIMIT` emri iletir (`limit_price = stop * (1 - slippage)`).
- R-5: **Borsa Stop Emri Başarısızlığı ve Belirsizlik (Fail-Closed, BR-11).** Alım dolduktan sonra borsa stop emri reddedilirse (`REJECTED`) veya ağ hatası/zaman aşımı nedeniyle durumu belirsiz kalırsa (`UNKNOWN`), bot derhal güvenli moda geçer (`STOP_ORDER_FAILED` / `safe mode`), durumu bildirir ve yeni alım açmayı durdurur. Bir sonraki turda stop emrinin durumu sorgulanır; çözülemezse açık pozisyon güvenli tarafta piyasadan kapatılır veya durum çözülene kadar yeni alım engeli sürer.
- R-6: **Mutabakat Öncesi Stop Dolum Senkronizasyonu.** Canlı mod turu başında, bakiye mutabakatı (`reconcile_balance`) çalıştırılmadan önce, açık pozisyonlara ait bekleyen borsa stop emirleri `query_order` ile sorgulanır. Borsada `FILLED` olduğu görülen stop emirleri, deftere `CloseReason.STOP_LOSS` ile borsa dolum fiyatı ve zamanıyla işlenerek pozisyon kapatılır. Böylece borsa USDT bakiyesindeki artış defterle senkronize olur ve gereksiz `RECONCILIATION_HALT` önlenir.
- R-7: **Kapanış Öncesi Stop Emrinin İptali (`cancel_order`).** Canlı modda açık bir pozisyon kâr hedefi (`TAKE_PROFIT`) ya da döngü kararıyla piyasadan kapatılmak istendiğinde (kill switch ve günlük zarar limiti pozisyon kapatmaz, yalnız yeni alımı durdurur — spec 0030; R-08 düzeltmesi, 2026-11-10), `app` / `execution` önce borsa üzerindeki açık stop emrini iptal eder (`cancel_order`). İptal teyit edildikten sonra kapanış piyasa satış emri (`cx-<id>`) borsaya iletilir. İptal sırasında stop emrinin zaten borsada dolduğu anlaşılırsa pozisyon stop dolumuyla kapatılmış sayılır ve mükerrer satış yapılmaz.
- R-8: **Paper ve Backtest Modlarında İzolasyon.** Şartlı borsa stop emri iletimi, sorgusu ve iptali yalnızca `mode="live"` turlarında çalışır. `paper` ve `backtest` modlarında harici borsa API çağrısı yapılmaz; pozisyon kapanışları mevcut döngü içi fiyat ve bar kontrolüyle yürümeye devam eder. B-51 risk boyutlaması ise tüm modlarda ortak `risk` kuralı olarak geçerlidir.

## User experience
none — no user interface. Kullanıcı konsol komutlarını ve metin loglarını görür.
- Flow:
  - Canlı modda bir alım sinyali onaylanır ve borsada doldurulur (`FILLED`).
  - Alım dolduğu anda borsa adaptörü borsaya `cs-<id>` kimliğiyle şartlı stop emri iletir.
  - Senaryo A (Stop tetiklenmesi): Piyasa stop seviyesine düşer, borsa stop emrini doldurur. Bot tur başında durumu tespit eder, deftere `STOP_LOSS` yazar, bakiye mutabakatı pürüzsüz geçer.
  - Senaryo B (Kâr hedefi): Fiyat hedefe ulaşır. Bot önce borsadaki `cs-<id>` stop emrini iptal eder, ardından `cx-<id>` piyasa satış emrini iletir ve kârla kapatır.
  - Senaryo C (Hata): Stop emri verilemezse bot fail-closed güvenli moda geçer ve bildirim üretir.
- States:
  - Başarılı stop emri iletimi (`STOP_ORDER_PLACED`).
  - Başarılı stop emri iptali (`STOP_ORDER_CANCELED`).
  - Turlar arası stop dolumu tespiti (`STOP_ORDER_FILLED_SYNC`).
  - Stop emri iletim hatası / belirsizlik (`STOP_ORDER_FAILED` / güvenli mod).
  - Satış slippage'ı nedeniyle risk onay reddi (`RISK_LIMIT_AT_FILL` / `RISK_CAP_AT_FILL`).
- Design reference: none — the flow above is the design.
- Accessibility: yalnız klavye; renk bilgi taşımaz.

## Constraints & out of scope
- Sensitive area: `Emir gönderimi (execution)`, `Risk limitleri (risk)`, `Portföy / defter (portfolio)` — `docs/domain.md`.
- Out of scope:
  - Borsa üzerinde OCO (One-Cancels-the-Other) kâr hedefi ve stop emri kombinasyonu (kâr hedefi döngüsel piyasa takibinde kalır).
  - Trailing stop veya dinamik kayan stop mekanizması (sonraki geliştirmeler).
  - Paper ve backtest simülatöründe harici borsa stop emri simülasyonu (mevcut deterministik kontrol korunur).
  - Vadeli işlem / kaldıraçlı piyasalar (yalnızca spot).
- Boyut: 8 kabul kriteri. Propose split: Gerek yok; B-51 risk boyutlaması ile borsada stop emrinin yaşam döngüsü doğrudan birbirini tamamlayan tek bir güvenlik yeteneğidir ("pozisyonun borsa seviyesinde stop ile korunması").

## Acceptance criteria
- [x] AC-1 — B-51 Satış slippage ve komisyonunun risk onayına ve boyutlamaya dahil edilmesi (R-1): `risk._size`, `TradeApproval` hesaplarken risk tutarına hem alış slippage'ını hem de stop satış slippage'ını (`stop * (1 - slippage)`) ve satış komisyonunu dahil eder; hesaplanan risk `equity * per_trade_risk` bütçesini aşamaz; satış slippage'ı eklendiğinde belirlenen pozisyon miktarının eski formüle göre daha korumacı olduğu birim testle doğrulanır.
- [x] AC-2 — Alım dolum kapısında satış slippage denetimi (R-2): `_buys._fill_gate`, dolum riskini hesaplarken satış slippage'ını (`stop * (1 - slippage)`) ve satış komisyonunu hesaba katar; BR-4 sabit üst sınırı veya risk bütçesi aşıldığında alım emri `RISK_LIMIT_AT_FILL` veya `RISK_CAP_AT_FILL` ile reddedilir.
- [x] AC-3 — Canlı alım dolumu sonrası borsaya şartlı stop emri iletimi (R-3, R-4): Canlı modda bir piyasa alım emri dolduğunda (`FILLED`), `LiveExchange` üzerinden Binance Spot API'sine `newClientOrderId=cs-<id>` formatında, pozisyon miktarı ve stop fiyatı ile koşullu stop emri (`STOP_LOSS` veya fallback `STOP_LOSS_LIMIT`) iletilir.
- [x] AC-4 — Borsa stop emri yaşam döngüsü ve tekil kimlikleme (R-3, R-4): Her borsa stop emri pozisyon kimliğiyle deterministik eşleşir (`cs-<id>`); mükerrer emir iletimi denenmez; adaptör emir durumunu (`NEW` / `FILLED` / `CANCELED` / `REJECTED` / `UNKNOWN`) doğru eşler.
- [x] AC-5 — Tur başında borsada dolmuş stop emrinin tespiti ve mutabakat öncesi kapanış (R-6): Canlı tur başında bakiye mutabakatından önce açık pozisyonlara ait borsa stop emirleri `query_order` ile sorgulanır; borsada `FILLED` olan stop emirleri deftere `CloseReason.STOP_LOSS` ile borsa dolum fiyatı üzerinden işlenir, pozisyon kapatılır ve mutabakat hatasız tamamlanır.
- [x] AC-6 — Kapanış öncesi borsa stop emrinin iptali (R-7): Canlı modda açık bir pozisyon kâr hedefi (`TAKE_PROFIT`) veya döngü kararıyla piyasadan kapatılırken, kapanış satış emri (`cx-<id>`) gönderilmeden önce borsadaki açık `cs-<id>` stop emri iptal edilir (`cancel_order`); iptal teyidi sonrası piyasa satış emri iletilir; stop emri iptal edilirken zaten dolmuşsa mükerrer satış engellenir.
- [x] AC-7 — Borsa stop emri başarısızlığı ve belirsizlikte fail-closed güvenli mod (BR-11) (R-5): Alım dolumu sonrasında borsa stop emri verilemezse (`REJECTED`) veya ağ zaman aşımıyla belirsiz kalırsa (`UNKNOWN`), bot derhal güvenli moda geçer (`STOP_ORDER_FAILED`), yeni alımları durdurur ve bildirim üretir.
- [x] AC-8 — Paper ve backtest modlarında izolasyon (R-8): `paper` ve `backtest` modlarında çalışan bot döngüsü harici borsa stop emri API çağrısı yapmaz; mevcut döngü içi mum ve fiyat kontrolüyle pozisyon kapatma davranışı korunur; B-51 risk boyutlaması ise tüm modlarda geçerliliğini korur.

## Definition of Done
- [x] Every acceptance criterion mapped to proof (test or reproducible observation)
- [x] `scripts/check` green
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Docs / ADRs updated if behavior or architecture changed
- [x] Spec moved to `specs/done/` (it becomes immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | 1 (R-08, ship kapısı: R-7/AC-6 kill-switch ve günlük zarar kapanışı metinden çıkarıldı, plan A-6) |
| Fix rounds | 3 (fix-1: F-1…F-8, F-11; fix-2: review round 2 L-1…L-3, I-1, I-2; fix-3: VERIFY round 1 AC-3, AC-7 test boşlukları) |
| Review findings: real / noise / deferred | 20 / 7 / 7 (review round 1–4 ve VERIFY round 1; deferred: B-60…B-64, B-67, I-1→0036) |
| Regressions introduced | 0 |
| Bugs escaped to production | 0 (henüz üretim yok) |

DoD'nin `scripts/check` kutusu koşullu işaretlendi: yerel kanıt `CHECK GREEN (fast)` @b6ad4d6; full koşu bu PR'ın CI işidir, yeşil olmadan merge yapılmaz (`docs/testing.md`, Two speeds, rule 10). VERIFY round 1 @aef5d74 ve round 2 @150cca9: 8 kriterin 8'i kanıtlı, kasıtlı bozmaların hepsi kırmızı (round 1'de yeşil kalan B3e, B3d, B7g fix-3 sonrası kırmızı).
