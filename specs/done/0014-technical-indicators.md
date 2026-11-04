# Spec 0014 — Teknik indikatörler

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0014-plan.md`
- Self-critique: done

## Intent
Sistemin sahibi, botun teknik sinyallerini dayandıracağı indikatör hesaplarının güvenilir olmasını istiyor; `strategy` ileride
bu değerleri kullanacak. Başarı, her indikatörün yayımlanmış referans değerlerle aynı sonucu vermesi ve yalnız geçmiş mumlara
dayanmasıdır: gelecek bir mum değişince geçmiş değerler değişmez. Hesaplar backtest, paper ve live'da aynıdır; ağa, depoya veya
saate dokunmaz. Sinyal üretme, strateji, veri çekme ve emirle ilgili hiçbir şey bu işte yoktur.

## Requirements
Terimler:
- **Mum serisi:** açılış zamanı, açılış, yüksek, düşük ve kapanış değerleri taşıyan, zamana göre artan mumlar.
- **Değer yok:** o konum için hesaplanmış sayı bulunmadığını söyleyen, sayıyla karışmayan işaret.

Davranış:
- `analysis`, public arayüzünden şu altı indikatörü sunar: SMA, EMA, RSI, MACD, Bollinger, ATR.
- Her indikatör bir mum serisi ve açıkça verilen parametreler alır; sonucu girdiyle aynı uzunluktadır, her konum o mumun değeridir.
- Yeterli geçmişi olmayan konum "değer yok" taşır. Bu olağan bir durumdur, hata değildir.
- Geçersiz veri ya da geçersiz parametre adı konmuş bir hatayla reddedilir; kısmi sonuç dönmez.
- Modül yalnız sayı döndürür; "al/sat" yorumu yapmaz.

Formül uzlaşıları:
- SMA: son `n` kapanışın aritmetik ortalaması.
- EMA: çarpan `2/(n+1)`; ilk değer ilk `n` kapanışın SMA'sıdır.
- RSI ve ATR: Wilder yumuşatması (`(önceki × (n−1) + yeni) / n`).
- RSI düz piyasada: hiç hareket yoksa "değer yok", yalnız kazanç varsa 100, yalnız kayıp varsa 0. TA-Lib'in düz piyasadaki 0'ından bilerek ayrılır: 0 aşırı satım gibi okunur.
- ATR başlangıcı (Wilder'ın özgün tanımı): ilk mumun gerçek aralığı `high − low`; ilk ATR `n-1` konumunda ilk `n` aralığın ortalamasıdır.
- Bollinger: orta bant `n` kapanışın SMA'sı; bantlar `orta ± k × σ`, σ aynı `n` kapanışın popülasyon standart sapması.
- MACD: MACD çizgisi, sinyal çizgisi ve histogram (MACD − sinyal) üçlüsü; hızlı, yavaş ve sinyal periyotları çağırandan gelir. Hızlı ve yavaş EMA ayrı ayrı yukarıdaki EMA tanımıyla hesaplanır; sinyal, MACD çizgisinin ilk `sinyal` değerinin SMA'sıyla başlayan EMA'sıdır.

## User experience
none — no user interface

## Constraints & out of scope
- Sensitive area: yok; `analysis` `docs/domain.md`'deki hassas alanlar arasında değildir. Yan etkisi olmayan hesaptır, emir üretmez.
- `analysis` başka proje modülünü ve I/O kütüphanesini import etmez (`docs/architecture.md`). Saat, ağ, depo ve global durum kullanmaz.
- Sayılar `docs/conventions.md`, Data rules'a uyar: `analysis` içinde `float`; `Decimal`'e çevirme `strategy → risk` sınırının işidir.
- Testler ağa çıkmaz; referans değerler repoda sabitlenir ve kaynağı adlandırılır. Referansla "aynı": kaynağın gösterdiği basamağa yuvarlanınca eşit. Ayrıca her indikatör için elle hesaplanmış küçük bir seride `1e-9` toleransla eşitlik aranır.
- Mumların kapanmış olduğunu çağıran garanti eder: `analysis` saat kullanmadığı için bunu bilemez.
- Eksik mum (zaman boşluğu) burada denetlenmez: veri tazeliği `market_data` ve BR-11'in işidir.
- Split: proposed 0014 (SMA, EMA, MACD ve ortak kurallar), 0015 (RSI, Bollinger, ATR); kept as one — Galip Badem, tek yetenek; altı indikatör yetersiz veri, geçersiz veri ve look-ahead kurallarını paylaşıyor.
- Out of scope: sinyal, yön ya da güç skoru; strateji ve varsayılan periyotlar (RSI 14 gibi değerler `strategy`'ye aittir); veri çekme ve
  saklama; hacim indikatörleri ve Ichimoku gibi daha karmaşık indikatörler; `strategy → risk` sınırındaki çevirme.

## Acceptance criteria
- [x] AC-1 — SMA: `n` periyotluk sonuç, yayımlanmış referans serisiyle aynıdır; ilk değer `n-1` konumundadır.
- [x] AC-2 — EMA: sonuç referans serisiyle aynıdır; ilk değer `n-1` konumunda ilk `n` kapanışın SMA'sıdır.
- [x] AC-3 — RSI: sonuç, Wilder yumuşatmasıyla referans serisiyle aynıdır; ilk değer `n` konumundadır ve her değer 0 ile 100 arasındadır; düz piyasa, yalnız kazanç ve yalnız kayıp durumları Formül uzlaşıları'ndaki gibidir.
- [x] AC-4 — MACD: MACD çizgisi, sinyal çizgisi ve histogram referans serisiyle aynıdır; çizgi `yavaş-1`, sinyal ve histogram `yavaş+sinyal-2` konumunda başlar; her konumda histogram = MACD − sinyal.
- [x] AC-5 — Bollinger: orta, üst ve alt bant referans serisiyle aynıdır; σ popülasyon standart sapmasıdır; değişmeyen kapanışlarda üç bant eşittir.
- [x] AC-6 — ATR: sonuç, Wilder yumuşatmasıyla referans serisiyle aynıdır; ilk değer `n-1` konumundadır; ilk mumun gerçek aralığı `high − low`, sonrakiler önceki kapanışı hesaba katar; hiçbir değer negatif değildir.
- [x] AC-7 — Yetersiz veri: sonuç her indikatörde girdiyle aynı uzunluktadır; hesaplanamayan konumlar "değer yok" taşır; periyottan kısa seri tümüyle "değer yok", boş seri boş sonuç verir ve ikisi de hata değildir.
- [x] AC-8 — Geçersiz veri: sıfır ya da negatif fiyat, sayı olmayan ya da sonsuz değer, `high < low`, `low`-`high` aralığı dışında açılış ya da kapanış ve kesin artmayan zaman damgası adı konmuş hatayla reddedilir; indikatörün kullanmadığı alanlar da denetlenir; sonlu olmayan sonuç da aynı biçimde reddedilir; hata nedeni ayırt edilebilir, kısmi sonuç dönmez.
- [x] AC-9 — Geçersiz parametre: sıfır, negatif ya da tam sayı olmayan periyot (mantıksal değer dahil) adı konmuş hatayla reddedilir; MACD'de hızlı periyot yavaştan küçük değilse ve Bollinger'da `k` pozitif ve sonlu değilse de reddedilir; periyotların ve `k`'nın varsayılanı yoktur, verilmeyen parametre hesap üretmez.
- [x] AC-10 — Look-ahead yok: her indikatörde `t` konumundaki değer, `t`'den sonraki mumlar değiştirilse, eklense ya da silinse aynı kalır (seri geçerli kaldığı sürece).
- [x] AC-11 — Saflık: aynı girdi her çağrıda aynı sonucu verir; girdi değişmez; `analysis`'in import sınırları `scripts/check`'te korunur.

## Definition of Done
- [x] Every acceptance criterion mapped to proof (test or reproducible observation)
- [x] `scripts/check` green
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Docs / ADRs updated if behavior or architecture changed
- [x] Spec moved to `specs/done/` (it becomes immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | 0 onay sonrası; plan: A-1, A-2, A-3 |
| Fix rounds | 2 (fix-1 review r1; fix-2 review r2); review r2 Medium'suz, VERIFY r1 PASS |
| Review findings: real / noise / deferred | 8 / 5 / 4 (r1: F-1…F-5 real, F-8, F-9 noise, F-6 B-35, F-7 B-36 · r2: F-10, F-11, F-13 real, F-12 B-37 · VERIFY r1: V-2, V-3, V-4 noise, V-1 B-38) |
| Regressions introduced | 0 (fix-2'deki flake önceden vardı: 0010'un testi, A-3) |
| Bugs escaped to production | 0 (henüz üretim yok) |

DoD'nin `scripts/check` kutusu koşullu işaretlendi (`doctor`, `specs/done/`'da işaretsiz kriteri reddediyor); koşul bu PR'ın full koşusudur, yeşil olmadan merge yapılmaz (`docs/testing.md`, Two speeds, rule 10). R-03 (A-3) de aynı koşuyla kapanır.
