# Spec 0010 — Dolan her emir deftere yazılır: hesap sınırı ve modüller arası sözleşme

- Status: Approved
- Mode: strict
- Plan: `specs/plans/0010-plan.md`
- Self-critique: done
- Source: backlog B-19 (spec 0009, review round 4 F-1; Severity: High)
- Supersedes: 0006 R-12 ve plan Risk 3 (28 basamaklı hesap), 0007 R-11 (dolum fiyatı ve komisyon 28 basamak; hesap sınırı),
  0008 R-14 (hesap sınırı), 0009 R-13 (hesap sınırı) ve R-14 (ayrışma metni). `specs/done/` dosyaları değişmez.

## Intent
Sistemin sahibi, dolan her emrin deftere yazılabilmesini istiyor. Bugün `execution` ile `portfolio` aynı 28 basamak
sınırını farklı hesaplara uyguluyor; bu yüzden 8 ondalıklı olağan değerlerde emir "dolu" olurken defter "ölçek
hesaplanamıyor" diyebiliyor, pozisyon açık kalıyor ve iki kayıt ayrışıyor. Başarı: gerçekçi değerlerde dolan her alım ve
satış deftere yazılır, bakiye tam aritmetikle tutar; bir hesap yine de sığmazsa adlandırılarak görünür, sessizce
yuvarlanmaz. Bilerek yapılmayanlar: üç modülün sayı kopyalarını birleştirmek (B-15, B-18), reddedilmiş kapanışın yeniden
denenmesi (B-17), borsa hassasiyetine yuvarlama (live spec'i), `app` döngüsü.

## Requirements
- R-1: **Girdi sınırı değişmez:** çağıranın verdiği miktar, güncel fiyat, stop, hedef ve başlangıç tutarı en fazla 28 anlamlı
  basamaklıdır (0006 R-12, 0007 R-11). Oran, adım ve asgarilerin kuralı da aynı kalır.
- R-2: **Hesap sınırı 60 basamaktır:** `execution` ve `portfolio`'daki tam hesaplar (dolum fiyatı, tutar, komisyon, maliyet,
  satış geliri, bakiye, gerçekleşen kâr/zarar, kasa) en fazla 60 anlamlı basamak taşır. Sonucu sığmayan hesap
  yuvarlanmaz, "geçersiz girdi: ölçek hesaplanamıyor" ile reddedilir.
- R-3: **Defterin dolum girdileri:** `record_fill` ve `close_position` dolum fiyatını ve komisyonu en fazla 60 anlamlı
  basamakla kabul eder; miktar, stop ve hedef 28'de kalır. Üs kuralı (±999999) aynıdır.
- R-4: **`execution` çıktısı defterin kapısından geçer:** `place_order` ve `place_close_order`, emri simülatöre vermeden önce
  dolum fiyatının ve komisyonun R-3'e uyduğunu, kapanışta ayrıca satış gelirinin (tutar − komisyon) R-2'ye sığdığını
  denetler; alımda ise maliyetin (tutar + komisyon) sığdığını denetler. Uymuyorsa emir oluşmaz, "geçersiz girdi: ölçek hesaplanamıyor". Bu denetimin ret sırasındaki yeri ölçek
  adımıdır (0006 R-11, 0009 R-12).
- R-5: **Gerçekçi aralıkta kabul:** miktar ve fiyat en fazla 10 tam + 8 ondalık, slippage en fazla 6 ondalık (0,001'in altı),
  komisyon oranı en fazla 5 ondalık (0,1'in altı), bakiye en fazla 13 tam basamak iken borsa kuralına uyan her alım ve
  kapanış dolar ve defter tarafından kabul edilir (bakiye yetiyorsa). Aralık varsayımdır; `market_data` geldiğinde gerçek
  değerlerle yeniden bakılır (self-critique G-1).
- R-6: **Kalan ayrışma adlandırılır:** defterin bakiyeye bağlı hesabı (bakiye toplamı, gerçekleşen toplam) R-2'yi aşarsa
  defter "ölçek hesaplanamıyor" ile reddeder ve değişmez; emir dolu kalır. `execution` bakiyeyi bilmediği için bunu önceden
  göremez. Bu yalnız R-5'in dışındaki değerlerde olur. Tepkisi `app` spec'inin işidir.
- R-7: Bakiyeyi aşan alımda sıra değişmez: tam karşılaştırma önce gelir, "yetersiz bakiye" (0007 A-2). 28 basamağı aşan
  değerler mesajda basamak sayısıyla yazılır (`_brief`, eşik değişmez).
- R-8: Tam aritmetik korunur: hiçbir tutar yuvarlanmaz. Bu sınır dışındaki davranış (ret nedenleri, mesajlar, tekrar koruması,
  güvenli mod, kimlikler) değişmez. `risk` değişmez.

## User experience
none — no user interface.

## Constraints & out of scope
- Sensitive area: Emir gönderimi (`execution`), Portföy / defter (`portfolio`) — `docs/domain.md`. `execution` ve `portfolio`
  için %90 branch coverage; property testi ve bağımsız `Fraction` modeli. `risk` değişmez.
- `app` spec'i için kural (S3): defterin dolu bir emri reddetmesi BR-11'deki "bakiye mutabakatı tutmuyor" sayılır: yeni alım
  durur, bildirim gider. Bu spec arayüz eklemez.
- Shipped testler: 28 basamak hesap sınırını sayıyla sabitleyen testlerde yalnız girdi **değerleri** yeni sınırı aşacak
  şekilde değişir; assert'ler aynen kalır; her değişiklik planda listelenir (`docs/testing.md`, Protected-tests rule).
- Sayı yardımcıları: `DIGITS` (28) girdi sınırı olarak kalır, hesap sınırı `execution/_numbers.py` ve `portfolio/_numbers.py`'de
  ayrı sabittir; iki kopya aynı kalır. `risk`'in kendi tam aritmetik bağlamı değişmez. Known traps satırı güncellenir.
- Out of scope: borsa hassasiyetine yuvarlama, B-15, B-17, B-18, `app` döngüsü, kalıcılık, live.
- Para/oran değerleri `decimal.Decimal`; yeni runtime bağımlılığı yok.

## Acceptance criteria
- [ ] AC-1 — B-19 örneği: açılış 100000; alım 12345.67890123 @ 0.12, komisyon 1.11 → USDT 98517.4085318524; aynı miktarın
  kapanışı fiyat 0.12345678, slippage 0.0005, komisyon oranı 0.00075 → emir dolu, dolum 0.123395051610, komisyon
  1.1425467638833229568602250; defter kabul eder: USDT 100039.661670266280619523439775, gerçekleşen kâr
  39.661670266280619523439775 (R-2, R-3, R-5, R-8).
- [ ] AC-2 — Alım eşi: aynı değerlerle `place_order` dolumu (`record_fill`) defterce kabul edilir, bakiye tam tutar (R-2, R-3).
- [ ] AC-3 — Hesap sınırı: 60 basamağa tam sığan hesap kabul, 61 basamak gerektiren hesap → "ölçek hesaplanamıyor", yuvarlama
  yok; tutar, komisyon, satış geliri, bakiye, gerçekleşen toplam ve kasa için ayrı ayrı (R-2, R-8).
- [ ] AC-4 — Defterin girdileri: 60 basamaklı dolum fiyatı ve komisyon kabul, 61 → "geçersiz girdi"; 29 basamaklı miktar, stop,
  hedef, başlangıç tutarı ve güncel fiyat hâlâ "geçersiz girdi" (R-1, R-3).
- [ ] AC-5 — Sözleşme: ölçek dışı dolum fiyatı ya da komisyon üreten (fiyat `1E-999999`, slippage 0.5) ve satış geliri ya da alım
  maliyeti sığmayan istek emir oluşturmaz, "ölçek hesaplanamıyor", durum değişmez; alım ve kapanışta (R-4).
- [ ] AC-6 — Kalan ayrışma: emir dolu, bakiye toplamı 60 basamağa sığmayan defter → "ölçek hesaplanamıyor", defter değişmez, emir
  dolu kalır, tekrar isteği "zaten var" (R-6).
- [ ] AC-7 — Değişmeyen davranış: 0003–0009 testleri geçer; yalnız sınır değerini taşıyan vakalar planda listeli olarak değişir,
  assert'leri aynıdır (R-8).
- [ ] AC-8 — Property: R-5 aralığında rastgele alım → defter → karar → onay → satış → defter dizilerinde (bağımsız `Fraction`
  modeliyle) borsa kuralına uyan her emir dolar, defter her dolumu kabul eder, bakiye ve gerçekleşen toplam modelle
  birebir aynıdır, 60 basamak aşılmaz; üreteç sonuçları yeterince üretir (R-2…R-5).

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
