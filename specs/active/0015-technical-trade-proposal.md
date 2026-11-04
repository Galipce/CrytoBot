# Spec 0015 — Teknik işlem önerisi

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0015-plan.md`
- Self-critique: done

## Intent
Sistemin sahibi, botun teknik verilerden kuralları açık ve tekrarlanabilir işlem önerileri üretmesini istiyor; böylece `risk`
onayına ve ileride backtest'e girecek bir girdi oluşur. Başarı, aynı mum serisi ve ayarlarla her zaman aynı kararın çıkması ve
her önerinin giriş, stop ve hedef taşımasıdır; koşullar oluşmazsa öneri yerine adı konmuş bir "öneri yok" nedeni döner. Kurallar
backtest, paper ve live'da aynıdır. Bu iş kârlılık kanıtlamaz: stratejinin paper'a geçişi ayrı bir backtest kararına bağlıdır
(BR-10). Günlük kâr hedefi kararları etkilemez (BR-1). Emir, pozisyon boyutlama, haber ve whitepaper sinyalleri bu işte yoktur.

## Requirements
Terimler:
- **Son mum:** verilen mum serisinin son elemanı. Seri yalnız kapanmış mumlardan oluşur; bunu sağlamak çağıranın işidir.
- **Yukarı kesişim:** önceki mumda hızlı EMA ≤ yavaş EMA, son mumda hızlı EMA > yavaş EMA. Dört değerin de sayı olması gerekir.
- **Öneri yok:** hata olmayan, nedeni adı konmuş olağan sonuç.

Davranış:
- `strategy`, bir çift, bir mum serisi, o çiftte açık pozisyon olup olmadığı, çiftin fiyat tick'i ve strateji ayarlarından tek
  sonuç üretir: ya bir alım önerisi ya da "öneri yok" nedeni.
- Ayarlar her çağrıda açıkça verilir: hızlı ve yavaş EMA periyodu, RSI periyodu ve üst eşiği, ATR periyodu, `k`, `r`. Kodda gizli
  varsayılan yoktur. `k`, `r`, RSI eşiği ve tick yalnız `Decimal` ya da tam sayıdır; `float` ve mantıksal değer reddedilir.
- Öneri koşulu: son mumda yukarı kesişim vardır ve son mumun RSI'sı eşiğin altındadır.
- Öneri, `risk`'in kabul ettiği biçimdedir: yön alım, çift, giriş, stop ve hedef.
- Fiyat kuralları, yuvarlamadan önce:
  - giriş = son kapanış
  - stop = `giriş − k × ATR` (son mumun ATR'si)
  - hedef = `giriş + r × (giriş − stop)`
- Çevirme ve yuvarlama: `analysis`'ten gelen sayı, en kısa ondalık gösterimiyle `Decimal`'e çevrilir (`0.1` → `0.1`, ikilik artığı değil). Fiyatlar `Decimal`'dir ve tick'in tam katıdır. Giriş yukarı, stop ve hedef aşağı yuvarlanır. Üçü de ihtiyatlı yöndedir:
  risk mesafesi ve boyutlama küçülmez, beklenen kâr fazla görünmez.
- Birden çok neden varsa şu sıradaki ilki döner:
  1. `POSITION_OPEN`: o çiftte açık pozisyon var
  2. `INSUFFICIENT_HISTORY`: kesişim için gereken EMA değerlerinden biri yok
  3. `NO_CROSSOVER`: son mumda yukarı kesişim yok
  4. `RSI_MISSING`: son mumda RSI "değer yok" (yetersiz geçmiş ya da düz piyasa, B-36 dahil)
  5. `RSI_TOO_HIGH`: RSI eşiğe eşit ya da üstünde
  6. `ATR_MISSING`: son mumda ATR "değer yok"
  7. `INVALID_PRICES`: yuvarlamadan sonra `0 < stop < giriş < hedef` sağlanmıyor
- Geçersiz ayar, tick, çift ya da açık pozisyon bilgisi ile geçersiz mum serisi adı konmuş hatayla reddedilir; kısmi sonuç dönmez.
  Önce ayar ve diğer girdiler, sonra mum serisi denetlenir. `analysis`'in sonlu olmayan sonuç hatası da adı konmuş hata olarak çıkar.
- Karar yalnız verilen girdilere dayanır. Kâr hedefi, gerçekleşen kâr-zarar ve işlem sıklığı girdi değildir (BR-1).

## User experience
none — no user interface

## Constraints & out of scope
- Kurallar ve başlangıç aday değerleri (EMA 20/50, RSI 14 eşik 70, ATR 14, `k=2`, `r=2`) backtest'e kadar kanıtsızdır. Bu spec bu
  değerlerin kârlı olduğunu iddia etmez; değerler ne kodda varsayılandır ne de testlerde "doğru" sayılır.
- Saf hesap: saat, ağ, depo ve global durum kullanılmaz; `strategy` `execution`'ı import etmez (`docs/architecture.md`).
- Aynı son mumla yinelenen çağrı aynı sonucu verir; aynı önerinin ikinci kez işleme dönüşmesini önlemek çağıranın işidir.
- Hassas alana girmez: `risk`, `execution` ve `portfolio` değişmez.
- Çift yalnız boş olmayan metin diye denetlenir; beyaz liste `risk`'tedir. `approve_trade`'in ölçek dışı fiyat reddi de `risk`'in işidir.
- Out of scope:
  - Haber ve whitepaper sinyalleri, güç skoru, kaynak birleştirme.
  - Çıkış sinyali ve satış önerisi: çıkış yalnız stop ya da hedefle olur (spec 0009).
  - `risk`'i çağırmak, zamanlayıcı ve döngü, veri çekme, mum aralığı seçimi.
  - Ayarların config dosyasından okunması.
  - Bayat veri denetimi (BR-11, B-39) ve B-6: `app` bağlantı spec'ine aittir.
  - Backtest ve parametre seçimi (BR-10).

## Acceptance criteria
- [ ] AC-1 — Öneri: yukarı kesişim ve eşik altı RSI olan elle hesaplanmış seride sonuç alım önerisidir; çift, giriş, stop ve hedef Fiyat kurallarıyla elle hesaplanan değerlere eşittir.
- [ ] AC-2 — Kesişim sınırları: önceki mumda EMA'lar eşitken son mumda hızlı üstteyse öneri çıkar. Son mumda eşitlik, hızlının zaten üstte olması ve aşağı kesişim `NO_CROSSOVER` verir. Aynı kesişimden sonraki mumda öneri tekrar çıkmaz.
- [ ] AC-3 — RSI sınırları: eşiğin altındaki RSI öneri verir; eşiğe eşit ve üstü `RSI_TOO_HIGH`, "değer yok" `RSI_MISSING` verir.
- [ ] AC-4 — Yetersiz geçmiş: boş seri ve kesişim için gereken uzunluğun bir eksiği `INSUFFICIENT_HISTORY` verir; gereken uzunlukla bu neden dönmez. ATR yoksa `ATR_MISSING` döner.
- [ ] AC-5 — Açık pozisyon: öneri koşulları sağlansa da o çiftte açık pozisyon varsa `POSITION_OPEN` döner. Birden çok neden birlikteyken Requirements'taki sıradaki ilki döner.
- [ ] AC-6 — Fiyat geçerliliği: stop'u sıfır ya da altına düşüren büyük `k × ATR` ve tick nedeniyle bozulan sıra `INVALID_PRICES` verir; kısmi öneri dönmez. Her öneride `0 < stop < giriş < hedef` sağlanır (property).
- [ ] AC-7 — Yuvarlama: üç fiyat da `Decimal` ve tick'in tam katıdır; giriş yukarı, stop ve hedef aşağı yuvarlanır. Zaten tick katı olan değer değişmez; `float` kapanış `0.1`, tick `0.1` ile giriş `0.1` kalır. Bu örnek yuvarlama biriminde ve public yolda `1.1` ile kanıtlanır: `0.1`/`0.1` ile `propose` `INVALID_PRICES` döner, çünkü `0.1`'in altında tick'in pozitif katı yoktur ve stop sıfıra iner.
- [ ] AC-8 — Geçersiz girdi: sıfır, negatif ya da tam sayı olmayan periyot (mantıksal değer dahil), `hızlı ≥ yavaş`, eşiğin 0–100 aralığı dışında olması (`0 < eşik ≤ 100`), pozitif ve sonlu olmayan `k` ya da `r`, `float` ya da mantıksal değer olan `k`, `r`, eşik ya da tick, pozitif olmayan tick, boş ya da metin olmayan çift, mantıksal değer olmayan açık pozisyon bilgisi ve geçersiz mum adı konmuş hatayla reddedilir; ayar hatası mum hatasının önüne geçer.
- [ ] AC-9 — `risk` uyumu: gerçekçi fiyat aralığında üretilen öneri `approve_trade`'e, onaya uygun hesap ve limitlerle verildiğinde biçim nedeniyle reddedilmez (`NOT_BUY`, `INVALID_ENTRY`, `INVALID_STOP`, `INVALID_TARGET`, `INVALID_INPUT` dönmez); her öneri alımdır ve stop taşır (BR-3).
- [ ] AC-10 — Saflık: aynı girdi aynı sonucu verir, girdi değişmez; son mumdan sonraki mumlar kararı etkilemez (seri o mumda kesilince sonuç aynıdır); kâr hedefi ya da kâr-zarar girdisi yoktur (BR-1); import sınırları `scripts/check`'te korunur.

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
