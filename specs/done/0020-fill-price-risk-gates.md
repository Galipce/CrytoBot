# Spec 0020 — Dolum fiyatında işlem riski ve kâr/maliyet kapıları

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0020-plan.md`
- Self-critique: done

## Intent
Sistemin sahibi, bot gerçek veriyle ilk kez koşmadan önce dolum fiyatındaki işlem riskinin config limitini aşmamasını ve BR-8 katının güncel fiyata göre de sağlanmasını istiyor; bugün fiyat girişten uzaklaşınca risk %1 ile %2 arasında kalabiliyor, kat ise yalnız girişe göre denetleniyor. Başarı, bu koşullardan biri tutmadığında emir oluşmaması ve çiftin sonucunda adı konmuş bir nedenin görünmesidir. Fiyat girişe eşitken risk limiti slippage yüzünden aşılmaz; bunun için miktar baştan slippage'lı girişe göre belirlenir. Güncel fiyata göre yeniden boyutlama yapılmaz, tolerans ya da yeni config ayarı eklenmez. Bedel bilerek kabul edilir: riskle sınırlı alım, fiyat girişin üstündeyse o turda olmaz.

## Requirements
Terimler:
- **Giriş:** önerinin giriş fiyatı (son mumun kapanışı).
- **Güncel fiyat:** turun çift için kullandığı fiyat.
- **Dolum fiyatı:** güncel fiyat × (1 + slippage).
- **Dolumdaki risk:** miktar × ((dolum fiyatı − stop) + dolum fiyatı × ücret + stop × ücret) ÷ kasa. Stop'taki satışın slippage'ını içermez.
- **Riskle sınırlı alım:** miktarı serbest bakiyenin değil, işlem başına risk limitinin belirlediği alım.

Davranış:
- R-1: **Boyutlama.** Onaylı miktarın risk koşulu, girişi slippage'lı dolum fiyatı olarak hesaplar: miktar × ((giriş × (1 + slippage) − stop) + giriş × (1 + slippage) × ücret + stop × ücret) ≤ kasa × işlem başına risk limiti. Bu kural spec 0005 R-9'un slippage kısmının yerini alır. Spread miktarı etkilemez. Serbest bakiye koşulu ve borsa asgarileri değişmez. Slippage 0 iken miktar bugünküyle aynıdır.
- R-2: **Config limiti kapısı.** Dolumdaki risk, işlem başına config limitini aşarsa emir oluşmaz; neden `RISK_LIMIT_AT_FILL`. Limite tam eşit risk geçer.
- R-3: **Sabit üst sınır kapısı.** Dolumdaki risk sabit üst sınırı aşarsa emir oluşmaz; neden `RISK_CAP_AT_FILL` olarak kalır. Hiçbir config değeri bunu değiştirmez.
- R-4: **BR-8 kapısı.** Kat, `risk` onayındaki formülle, girişin yerine güncel fiyat konarak yeniden denetlenir: beklenen kâr = hedef − güncel fiyat; efektif maliyet = (güncel fiyat + hedef) × ücret + güncel fiyat × spread + (güncel fiyat + hedef) × slippage. Giriş bacağının slippage'ı maliyette olduğu için dolum fiyatı formüle ayrıca konmaz. Beklenen kâr, kat × maliyetten büyük değilse emir oluşmaz; neden `INSUFFICIENT_EDGE_AT_FILL`.
- R-5: **Sıra.** Kapılar yalnız `risk` onayından sonra ve şu sırayla işler; ilk tutmayan koşul nedeni belirler: bakiye → sabit üst sınır → stop/hedef → config limiti → BR-8. Bakiye ve stop/hedef kapılarının koşulları değişmez.
- R-6: **Yeniden boyutlama yok.** Kapılar yalnız emrin oluşup oluşmayacağına karar verir. Onaylı miktar değiştirilmez, kapıdan dönen çift için daha küçük emir denenmez.
- R-7: **Sessiz ret.** Bu kapılar bildirim göndermez, alımı durdurmaz, diğer çiftleri etkilemez, emir, defter ya da risk durumu değiştirmez. Ret yalnız çiftin sonucunda görünür.
- R-8: **Yeniden deneme.** Kapıdan dönen çift için emir oluşmadığından aynı mumda sonraki tur yeniden değerlendirir; o an koşullar tutuyorsa alım olur.
- R-9: **Hesaplanamayan değer.** Risk hesabı sığmazsa neden `RISK_CAP_AT_FILL`, BR-8 hesabı sığmazsa `INSUFFICIENT_EDGE_AT_FILL` olur; emir oluşmaz, istisna fırlamaz.

## User experience
none — no user interface

## Constraints & out of scope
- Sensitive area: Risk limitleri (`risk`) — `docs/domain.md`. Boyutlama `risk`'te değişir; kapılar BR-4 ve BR-8'in emir kararını belirler. Emir gönderimi, defter ve kalıcı durum davranışı değişmez.
- `docs/domain.md` kuralları (BR-4, BR-8) ve sabit üst sınır değerleri değişmez; config'e yeni ayar eklenmez, tolerans yoktur.
- Değişmesi beklenen shipped test beklentileri yalnız şunlardır; her biri plan haritasında adıyla yazılır ve daha zayıf hâle getirilmez:
  - Slippage'lı miktara bağlı değerler: `FIRST_AMOUNT` ve ondan türeyen beklentiler, `test_trade_clearing_the_threshold_is_sized_as_spec_0003`, `tests/risk/test_edge_properties.py` ve `tests/app/model.py` boyutlama hesapları.
  - `test_risk_under_hard_cap_at_fill_still_buys`: fiyat 11'deki alım, kapatılan açığın kendisidir; yerine AC-4 gelir.
  - `test_fill_just_inside_stop_and_target_still_buys` üst yarısı: fiyat 11.99'daki risk config limitini aşar; "hedefin hemen içi alınır" iddiası ücret, slippage ve spread 0, adım 25.01 girdileriyle korunur (plan Risk 1a, R-10).
  - `test_spread_and_slippage_leave_the_balance_limit_as_spec_0003`: miktar slippage'lı girişle `18.885`; aynı bakiye sınırı iddiası yeni sınır değerleriyle korunur (plan Risk 1b, R-10).
  - `tests/execution` onay fikstürleri (`test_paper_orders.py`, `test_safe_mode.py`, `test_order_properties.py`): onay slippage 0 ile çağrılır, `19.249` ve hiçbir assert değişmez (plan Risk 1c, R-10).
- `test_risk_over_hard_cap_at_fill_places_no_order` (fiyat 15), `test_fill_above_target_places_no_order` (fiyat 12) ve `test_fill_below_stop_places_no_order` (fiyat 7.9) adlı nedenlerini korur.
- Out of scope: stop'taki satış slippage'ının ve stop altına boşluklu düşüşün riske katılması; serbest bakiye koşulunun slippage'lı hesaplanması (bakiye kapısı korur); güncel fiyata göre boyutlama; sapma toleransı; giriş noktası; live.
- Backlog: B-41 bu spec'le kapanır. Stop'taki satış slippage'ı ve boşluklu düşüş yeni bir backlog kaydı olur (örnekte ~0,39 USDT, kasanın %0,004'ü).
- Bilinen bedel: riskle sınırlı alımlar güncel fiyat girişin üstündeyken yapılmaz; sıklığı ölçülmedi, paper sonuçlarında çift nedenlerinden izlenir.
- Bilinen sonuç: `risk` onayını geçmiş riskle sınırlı alımda fiyat girişin üstündeyse önce config limiti keser; fiyat giriş ya da altındaysa kat onaydakinden kötü olamaz. BR-8 kapısına bu yüzden pratikte adım yuvarlaması ya da bakiye sınırı nedeniyle risk payı kalan alımlar ulaşır.
- Coverage: `risk` ve `app` için modül başına %90 branch eşiği sürer (`docs/testing.md`).
- Boyut: tek yetenek, 12 kriter. Split: proposed 0020 boyutlama ve config limiti; 0021 BR-8 kapısı; kept as one — Galip Badem, 2026-11-05, ikisi aynı kapıda ve sıralamaları birbirine bağlı.
- Doküman: `docs/conventions.md` Known traps'teki "`risk` girişle boyutlar" satırı yeni davranışa göre güncellenir.
- ADR gerekmez: mimari değil tek kural değişir, gerekçesi bu spec'tedir (spec 0005 R-9'un slippage kısmı).
- Ret mesajı: kapılar bugünkü ortak metni paylaşır, ayrımı neden adı taşır; sayısal ayrıntı raporlama işine kalır.

## Acceptance criteria
Aksi yazılmadıkça: kasa 10000, işlem riski %1, sabit üst sınır %2, ücret 0.001, slippage 0.001, spread 0.0005, kat 2, adım 0.001, giriş 10, stop 8, hedef 14. Tutarlar elle hesaplanmıştır.

- [x] AC-1 — Boyutlama (R-1): onaylı miktar tam olarak `49.309`, risk ~99.999 USDT. Bir adım fazlası (`49.310`) limiti aşar. Slippage 0 ile aynı öneride miktar `49.554` kalır.
- [x] AC-2 — Slippage bağımsızlığı sınırı (R-1): spread değişince miktar değişmez. Serbest bakiyeyle sınırlı onayda miktar, slippage'dan etkilenmez.
- [x] AC-3 — Fiyat girişe eşit (R-1, R-2): fiyat 10, dolum 10.01, risk en fazla limit: `49.309` birimlik emir oluşur.
- [x] AC-4 — Config limiti (R-2): fiyat 10.01'de (risk ~100.49) ve fiyat 11'de (risk ~149.41, sabit üst sınırın altında) emir oluşmaz; neden `RISK_LIMIT_AT_FILL`.
- [x] AC-5 — Tam sınır (R-2): ücret ve slippage 0, adım 1, miktar 50: fiyat 10'da risk tam 100 USDT, emir oluşur. Fiyat 10.01'de risk 100.5 USDT, emir oluşmaz.
- [x] AC-6 — Sabit üst sınır (R-3, R-5): fiyat 15'te (risk ~347.04) neden `RISK_CAP_AT_FILL`. Config limiti sabit üst sınıra eşitken sınırı aşan alım da aynı nedenle reddedilir.
- [x] AC-7 — BR-8 (R-4): adım 25, hedef 12, miktar 25. Fiyat 11.9'da (kâr 0.1, maliyet 0.05375, risk ~98.30) emir oluşmaz, neden `INSUFFICIENT_EDGE_AT_FILL`. Fiyat 11'de (kâr 1, maliyet 0.0515, risk ~75.75) emir oluşur.
- [x] AC-8 — BR-8 tam sınırı (R-4): ücret ve slippage 0, spread 0.005, kat 2, giriş 99, stop 90, hedef 101, adım 10, miktar 10: fiyat 100'de risk tam 100 USDT ve kâr maliyetin katına tam eşittir; emir oluşmaz, neden `INSUFFICIENT_EDGE_AT_FILL`. Fiyat 99.9'da emir oluşur.
- [x] AC-9 — Çift sayım yok (R-4): giriş ve fiyat 10, hedef 10.10: `risk` onayladıysa BR-8 kapısı da geçer.
- [x] AC-10 — Sıra (R-5): fiyat 12 ve hedef 12 iken neden `FILL_OUTSIDE_STOP_TARGET`; fiyat 7.9'da aynı neden. Bakiyeyi aşan dolum `FILL_EXCEEDS_BALANCE` kalır. Hedef 12, fiyat 11.9 iken hem config limiti hem BR-8 bozulur (risk ~193.9, sabit üst sınırın altında); neden `RISK_LIMIT_AT_FILL`.
- [x] AC-11 — Etkisizlik ve yeniden deneme (R-6, R-7, R-8): `RISK_LIMIT_AT_FILL` ya da `INSUFFICIENT_EDGE_AT_FILL` turunda emir, defter, durdurma ve bildirim oluşmaz; miktar küçültülerek emir denenmez; diğer çift aynı turda işlem görür. Aynı mumda fiyat 11 ile dönen çift, sonraki turda fiyat 10 ile `49.309` birim alır.
- [x] AC-12 — Hesaplanamayan değer (R-9): risk ya da BR-8 hesabı sığmayan girdide istisna fırlamaz, emir oluşmaz, nedenler R-9'daki gibidir.

## Definition of Done
- [x] Every acceptance criterion mapped to proof (test or reproducible observation)
- [x] `scripts/check` green
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Docs / ADRs updated if behavior or architecture changed
- [x] Spec moved to `specs/done/` (it becomes immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | 0 |
| Fix rounds | 1 (VERIFY round 1) |
| Review findings: real / noise / deferred | 2 / 1 / 0 (real: F-V1, I-1; noise: F-1) |
| Regressions introduced | 0 |
| Bugs escaped to production | 0 (henüz üretim yok) |

DoD'nin `scripts/check` kutusu koşullu işaretlendi (`doctor`, `specs/done/`'da işaretsiz kriteri reddediyor); koşul bu PR'ın `check` ve `doctor` işleridir, yeşil olmadan merge yapılmaz (`docs/testing.md`, Two speeds, rule 10). Full kanıt: CI run 42103497567, `3b062a8`, `CHECK GREEN (full, 7 steps, 355 s)`.
