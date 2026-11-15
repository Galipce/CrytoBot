# Spec 0045 — Kriptoya ayarlı indikatörler ve isabet ölçümü

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0045-plan.md`
- Self-critique: done
- Source: spec 0044 sonucu (`aday yok`); clarify Q-1…Q-8 — Galip Badem, 2026-11-15
- Approved by / on: Galip Badem, 2026-11-15
- Design: —

## Intent
Botun sahibi, hisse senedi için konmuş varsayılan ayarlarla kullanılan indikatörlerin kriptoda yanılttığını düşünüyor; 0044'te bu ayarlarla kurulan sekiz adayın hiçbiri maliyetlerden sonra kâr etmedi. Bu spec, seçilmiş indikatörlerin "al" sinyallerinin kriptonun gerçek yükselişlerini ne kadar isabetle yakaladığını ölçer: önce varsayılan ayarla, sonra bir yıllık BTC verisinde beş aralıkta (15m, 30m, 1h, 4h, 1d) isabeti en yükseğe çıkaran ayarla; ayar değiştirilmeden diğer dört coinde ve hiç ayarlamada kullanılmamış bir dönemde bir kez sınanır. Başarı: her indikatör × aralık için varsayılan ve ayarlı isabeti, rastgele girişin taban oranını ve olağandışı hareketlerin etkisini gösteren, yeniden üretilebilir bir rapor; sabitlenmiş bir ayar seti; sonraki işlerin (kendi indikatörümüz, LLM sinyalinin doğrulanması) kullanacağı sinyal kayıtları. "Hiçbir indikatör kullanılabilir değil" sonucu da başarıdır. Botun işlem davranışı değişmez; ayarlı indikatörlerin stratejide kullanılması, LLM sinyalleri ve live kapsam dışıdır (live, LLM fazından sonra gelir — sahip kararı, 2026-11-15). Kararlar: clarify Q-1…Q-8 ve self-critique K-1…K-10 — Galip Badem, 2026-11-15.

Terimler:
- **Sinyal:** Bir indikatörün bir mumun kapanışında verdiği "al" (ya da çıkış tablosu için "sat") işareti. Giriş fiyatı sinyal mumundan sonraki mumun açılışıdır.
- **İsabet (Q-1):** "Al" sinyalinden sonraki en çok 24 mum içinde fiyat, giriş fiyatının hedef mesafesi kadar üstüne, giriş fiyatının 1×ATR altına inmeden önce ulaşır. Hedef mesafesi 2×ATR ile bir alım-satım turunun maliyetinin büyüğüdür; maliyet backtest'le aynı formülle ölçüm ayarındaki ücret, slippage ve spread'den hesaplanır (K-4). ATR(14) sinyal mumunda ölçülür. Aynı mumda iki sınıra da değilirse ya da 24 mum dolarsa isabet yoktur. Pencere dosyada var olan 24 mumdur; veri boşluğundaki eksik mumlar atlanır ve penceresine boşluk denk gelen sinyallerin sayısı raporlanır (K-10). Penceresi dönemin bitişini aşan sinyal sayılmaz (K-3). Bir sinyalin penceresinde yeni sinyal gelirse ikisi de ayrı sayılır (K-2).
- **İsabet oranı (Q-2):** İsabetli sinyal sayısı / sinyal sayısı.
- **Taban oran (Q-3):** Aynı çift, aralık ve dönemde her mumun kapanışı bir "al" sinyali sayıldığında, sinyalle aynı kurallarla (pencere, boşluk, dönem sonu) elde edilen isabet oranı (rastgele girişin isabeti).
- **Olağandışı mum (Q-8):** Şunlardan birini taşıyan mum: (a) boyu (yüksek − düşük) 4×ATR'den büyük; (b) hacmi önceki 20 mumun ortalamasının 5 katından büyük; (c) gövdesi 3×ATR'den büyük ve sonraki 3 mum içinde hareketin en az üçte ikisi geri döner; (d) aynı açılış anında beş çiftin en az dördünde mum boyu 3×ATR'den büyük.
- **Olağandışıya denk gelen sinyal:** Değerlendirme penceresinde (sinyal mumu dahil sonraki 24 mum) olağandışı mum bulunan sinyal.
- **Komşu ayar (Q-6):** Izgarada tek bir parametresi bir adım farklı olan ayar.

## Requirements
- R-1 — **Sabit indikatör listesi (Q-4).** Sekiz indikatör ölçülür; listesi, "al" ve "sat" kuralları, varsayılan ayarları ve ayar ızgaraları bu spec'te sabittir, ayarla ya da sonuca bakılarak değişmez:

  | İndikatör | "Al" sinyali | "Sat" sinyali | Varsayılan | Izgara |
  |---|---|---|---|---|
  | RSI (n, alt, üst) | RSI alt eşiği aşağıdan yukarı keser | RSI üst eşiği yukarıdan aşağı keser | 14, 30, 70 | n ∈ {7, 10, 14, 21, 28}; alt ∈ {20, 25, 30, 35, 40}; üst = 100 − alt |
  | MACD (hızlı, yavaş, sinyal) | MACD çizgisi sinyal çizgisini aşağıdan yukarı keser | yukarıdan aşağı keser | 12, 26, 9 | hızlı ∈ {6, 8, 12, 16}; yavaş ∈ {20, 26, 34, 42}; sinyal ∈ {5, 9, 13}; hızlı < yavaş |
  | Bollinger (n, m) | kapanış alt bandın altından bandın içine döner | kapanış üst bandın üstünden bandın içine döner | 20, 2 | n ∈ {10, 15, 20, 30, 40}; m ∈ {1.5, 2, 2.5, 3} |
  | Stochastic (k, d, alt, üst) | %K, %D'yi aşağıdan yukarı keser ve %K alt eşiğin altındadır | %K, %D'yi yukarıdan aşağı keser ve %K üst eşiğin üstündedir | 14, 3, 20, 80 | k ∈ {5, 9, 14, 21}; d ∈ {3, 5}; alt ∈ {10, 20, 30}; üst = 100 − alt |
  | ADX/DI (n, eşik) | +DI, −DI'yi aşağıdan yukarı keser ve ADX ≥ eşik | −DI, +DI'yi aşağıdan yukarı keser ve ADX ≥ eşik | 14, 25 | n ∈ {7, 10, 14, 21}; eşik ∈ {15, 20, 25, 30} |
  | Supertrend (n, m) | yön aşağıdan yukarıya döner | yukarıdan aşağıya döner | 10, 3 | n ∈ {7, 10, 14, 21}; m ∈ {1.5, 2, 3, 4} |
  | Donchian (n) | kapanış önceki n mumun en yükseğini aşar (eşitlik aşmaz) | kapanış önceki n mumun en düşüğünün altına iner | 20 | n ∈ {10, 20, 30, 55, 100} |
  | EMA kesişimi (hızlı, yavaş) | hızlı EMA yavaşı aşağıdan yukarı keser | yukarıdan aşağı keser | 9, 21 | hızlı ∈ {5, 9, 12, 20}; yavaş ∈ {21, 26, 50, 100}; hızlı < yavaş |

  Varsayılan ayar her ızgaranın içindedir.
- R-2 — **Veri ve dönemler (Q-5).** Çiftler BTC, ETH, BNB, SOL, XRP / USDT; aralıklar 15m, 30m, 1h, 4h, 1d. Üç dönem: **ayarlama** 2024-01-01 → 2025-01-01 (bitiş hariç), yalnız BTC; **çapraz sınama** aynı dönem, ETH, BNB, SOL, XRP; **görülmemiş dönem** 2025-07-01 → 2026-11-12 (bitiş hariç), beş çift. Görülmemiş dönem 0044'te yalnız S0…S3'ün hükümleriyle görüldü; bu küçük sızıntı raporda yazılır. 2025-01-01 → 2025-07-01 bilerek kullanılmaz: 0044'ün dönem bölünmesi korunur (K-7). Veri her aralıkta 2023-01-01'den indirilir; dönem başından önceki mumlar yalnız göstergelerin ısınması için kullanılır (K-5). Veri boşlukları doldurulmaz ve raporda görünür (0044 R-2 ile aynı tanım).
- R-3 — **Taban ölçüm.** Her indikatörün varsayılan ayarıyla, her çift × aralık × dönem için sinyal sayısı, isabet oranı ve taban oran ölçülür.
- R-4 — **Ayarlama (Q-2, Q-6).** Her indikatör × aralık için ayarlama döneminde BTC'de ızgaranın her ayarı ölçülür. En az 30 "al" sinyali veren ayarlar arasından isabet oranı en yüksek olan seçilir (eşitlikte ızgaradaki ilk ayar). Hiçbir ayar 30 sinyale ulaşmazsa o indikatör × aralık için ayar seçilmez ve raporda nedeni yazılır. Seçilen ayarın komşularının en az yarısı taban oranı geçmiyorsa ayar "dayanıksız" diye işaretlenir.
- R-5 — **Çapraz sınama (Q-6).** Seçilen ayarlar değiştirilmeden ayarlama döneminde diğer dört çiftte ölçülür. Ayar, dört çiftin en az üçünde taban oranın üstünde isabet vermezse "çapraz sınamada geçmedi" diye işaretlenir.
- R-6 — **Ayar setinin sabitlenmesi.** Ayarlama ve çapraz sınama, seçilen ayarları ve işaretlerini taşıyan bir ayar seti dosyası yazar; dosyanın parmak izi rapora yazılır. Görülmemiş dönem yalnız bu dosyayla ve sahibin onayı kayda geçtikten sonra koşulur: ölçüm ayarı ayar setinin sha256'sını, onaylayanın adını ve onay anını taşır (aşama kapısındaki düzen, K-6).
- R-7 — **Görülmemiş dönem, bir kez (Q-3, Q-5).** Görülmemiş dönem ayar setiyle beş çiftte ölçülür. Bir indikatör × aralık şu koşulların hepsini sağlarsa "kullanılabilir" hükmü alır: ayarı seçilmiş, dayanıksız ve "çapraz sınamada geçmedi" değil; beş çiftin birleşik sinyallerinde en az 30 sinyal; birleşik isabet oranı birleşik taban oranı en az 5 puan geçer; olağandışıya denk gelen sinyaller çıkarıldığında da isabet oranı o kümenin taban oranının altına düşmez. Hükmü birleşik sonuç belirler; çift başına sonuçlar raporda ayrıca görünür (K-9). Hükmü vermeyen koşul raporda değeriyle ve eşiğiyle yazılır. Sonuca bakılarak dönem, çift, indikatör, ızgara, eşik ya da maliyet değiştirilmez; aynı girdilerle tekrar serbesttir.
- R-8 — **Olağandışı hareketler (Q-8).** Olağandışı mumlar veriden çıkarılmaz. Her isabet ve taban oranı iki kez raporlanır: bütün sinyallerle ve olağandışıya denk gelenler çıkarılmış halde. Rapor her çift × aralık × dönem için olağandışı mum sayısını yazar.
- R-9 — **Çıkış sinyalleri (Q-2).** "Sat" sinyalleri ayrı bir tabloda raporlanır: sinyalden sonraki 24 mum içinde fiyat girişin 2×ATR altına, 1×ATR üstüne çıkmadan önce iniyorsa sinyal isabetlidir. "Sat" sinyalleri ayarlama seçimini ve hükmü etkilemez.
- R-10 — **Sinyal kayıtları (Q-7).** Rapordan ayrı, makinece okunur bir kayıt dosyası her ölçülen sinyal için indikatörü, ayarı, çifti, aralığı, sinyal anını, yönü, giriş fiyatını, isabet sonucunu ve olağandışıya denk gelip gelmediğini; her olağandışı mum için anını, çiftini, aralığını ve hangi kuraldan işaretlendiğini taşır. Aynı girdilerle iki koşu bayt bayt aynı rapor ve kayıt dosyası üretir (üretim anı satırı hariç).
- R-11 — **İşlem davranışı değişmez.** Paper, live, backtest, aşama kapısı, risk limitleri ve S0…S3 bugünkü gibi çalışır; çalışan `crytobot.toml` ve kökteki veri ve rapor dosyaları değişmez.

## User experience
none — no user interface. Etkileşim CLI komutu, ayar dosyası, rapor dosyası, ayar seti dosyası ve sinyal kayıt dosyasıdır; pano ve Telegram değişmez.

## Constraints & out of scope
- Sensitive area: none — emir gönderimi, risk limitleri, defter, kalıcı durum, mod anahtarı ve aşama kapısı değişmez (R-11).
- Split: proposed 0045 (ölçüm, ayarlama, çapraz sınama) + 0046 (görülmemiş dönem, hüküm); kept as one — Galip Badem, 2026-11-15, görülmemiş dönem aynı kuralları kullanır, yeni olan yalnız hükümdür (K-1).
- Süre sınırı yoktur; toplam süre kaydedilir (K-8).
- Ağ yalnız veri indirmede kullanılır (mevcut indirme komutu); ölçüm ağa çıkmaz, API anahtarı okumaz.
- Veri, ayar seti, rapor ve kayıt dosyaları git'e girmez; deponun dışında durur.
- Kapsam dışı: ayarlı indikatörlerin stratejide ya da botta kullanılması; kendi indikatörümüzü tasarlamak (sonraki spec, R-10'un kayıtlarıyla); LLM, haber ve olağandışı hareketlerin nedenini bulmak (LLM fazı); kâr/zarar backtest'i; indikatör listesinin ya da ızgaraların genişlemesi; live ve testnet (live LLM fazından sonra gelir — sahip kararı, 2026-11-15; ADR 0002'nin faz sırası ayrıca revize edilir).

## Acceptance criteria
- [ ] AC-1 — İsabet kuralı: hedef mesafesine 24. mumda ulaşan sinyal isabetlidir, 25. mumda ulaşan değildir; stop sınırına hedeften önce değen değildir; aynı mumda iki sınıra değen değildir; 2×ATR maliyetten küçükse hedef maliyet mesafesidir; penceresi dönem bitişini aşan sinyal sayılmaz; penceredeki eksik mumlar atlanır ve pencere 24 mevcut mumdur; üst üste binen sinyaller ayrı sayılır. "Sat" sinyali için aynı kural ters yönde uygulanır (R-9).
- [ ] AC-2 — Her indikatörün "al" ve "sat" sinyali R-1'deki kuralla üretilir: kesişme yalnız kesiştiği mumda sinyal verir; Donchian'da eşitlik sinyal vermez; ısınma yetmeyen mumlarda sinyal yoktur. Varsayılan ayar ızgaranın içindedir.
- [ ] AC-3 — Taban oran, dönemin her mumu sinyal sayılarak aynı isabet kuralıyla hesaplanır; isabet ve taban oranı bütün sinyallerle ve olağandışıya denk gelenler çıkarılmış halde raporlanır (R-3, R-8).
- [ ] AC-4 — Olağandışı mum kuralları (a)–(d) tek tek işaretlenir; tam eşik değerindeki mum işaretlenmez, eşiği aşan işaretlenir; olağandışı mumlar ölçümden çıkarılmaz (R-8).
- [ ] AC-5 — Ayarlama yalnız BTC'nin ayarlama dönemini kullanır; en az 30 sinyalli ayarlar arasından en yüksek isabet seçilir, eşitlikte ızgaradaki ilk ayar; 29 sinyalli ayar seçilemez; hiçbir ayar 30'a ulaşmazsa "ayar yok" nedeniyle yazılır; komşularının yarısından azı taban oranı geçen ayar "dayanıksız" işaretlenir, tam yarısı geçen işaretlenmez (R-4).
- [ ] AC-6 — Çapraz sınama ayarları değiştirmez; dört çiftin üçünde taban oranı geçen ayar işaretsiz kalır, ikisinde geçen "çapraz sınamada geçmedi" işaretlenir (R-5).
- [ ] AC-7 — Görülmemiş dönem yalnız ayar seti dosyasıyla koşar; dosya yoksa, parmak izi kayıtlı onayla tutmuyorsa ya da dönemlerden birinde bir çiftin aralıkta hiç mumu yoksa hiçbir ölçüm yapılmadan, nedeni adlandırılarak reddedilir, rapor yazılmaz, çıkış 1 (R-6, R-2).
- [ ] AC-8 — Hüküm: R-7'nin koşullarından biri tutmayan indikatör × aralık "kullanılabilir" değildir ve rapor tutmayan değeri ve eşiği yazar (ör. `geçmedi: isabet taban oranı 5 puan geçmiyor (+3.2 < +5)`); taban oranı tam 5 puan geçen "kullanılabilir"dir.
- [ ] AC-9 — Rapor her indikatör × aralık için varsayılan ve ayarlı ayarı, sinyal sayısını, isabet ve taban oranını üç dönemde ayrı ayrı; olağandışı mum sayılarını; veri boşluklarını; ayar seti parmak izini; görülmemiş dönemin sızıntı notunu yazar. Sinyal kayıt dosyası R-10'un bütün alanlarını taşır; aynı girdilerle iki koşu bayt bayt aynı rapor ve kayıt üretir (üretim anı satırı hariç).
- [ ] AC-10 — Ölçüm boyunca çalışan `crytobot.toml` ve kökteki veri ve rapor dosyaları değişmez (öncesi/sonrası sha256); yeni dosyalar git'e girmez; paper, backtest ve aşama kapısı testleri değişmeden geçer (R-11).
- [ ] AC-11 — Gerçek veriyle ölçüm koşulur ve kayda geçer: veri dosyalarının sha256'sı, indirme anı, ayar seti parmak izi ve onayı, her indikatör × aralığın hükmü, rapor parmak izi, tarih ve toplam süre planın `## Build evidence` bölümüne yazılır.

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
