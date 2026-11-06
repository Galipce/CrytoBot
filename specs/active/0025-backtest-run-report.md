# Spec 0025 — Backtest koşusu ve rapor

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0025-plan.md`
- Self-critique: done

## Intent
Botun sahibi, teknik stratejinin maliyetler düştükten sonra kâr edip etmediğini paper'a geçmeden önce geçmiş veride görmek istiyor (BR-10, ADR 0002 Faz 1). Bu, üç parçalı işin ikinci parçasıdır. Backtest, 0023'ün indirdiği veri dosyasından ağa çıkmadan koşar ve her aralık sınırında paper turunun aynısını simüle saatle atar. Strateji, risk ve emir kodu paper'dakiyle aynıdır. Fiyat, sınırda açılan mumun açılış fiyatıdır, ileriye bakılmaz. Bir ayrım anı kesintisiz koşuyu örneklem içi ve dışı olarak ikiye böler. Rapor her parça ve tüm koşu için metrikleri, koşunun varsayımlarını (B-51 dahil) konsola ve bir rapor dosyasına yazar. Başarı şöyle görünür: aynı dosya ve aynı ayarlar bayt bayt aynı raporu verir, paper deposu ve kayıt dosyası değişmez. Bilerek yapılmayanlar: rapor geçti/kaldı demez. BR-10 kapısı ve insan onayı kaydı BR-10 kapı spec'inindir. Mum içi stop/hedef, geçmiş spread, parametre taraması, live da yapılmaz.

## Requirements
Terimler:
- **Koşu:** veri dosyası ve ayarlarla, dönemin her tur anında paper turunu simüle saatle atıp sonunda raporu yazan, açık ve tek seferlik adım.
- **Veri dosyası:** spec 0023'ün indirdiği, tamamlanmış dosya. Mumları, çift kurallarını ve fiyat adımını, mum aralığını, dönemi ve indirme anını taşır.
- **Dönem:** veri dosyasındaki başlangıç ve bitiş (UTC, bitiş hariç). Koşu bu dönemi kullanır.
- **Tur anı:** dönemin içindeki, tur aralığının sınırına denk gelen her an. İlki dönem başıdır, sonuncusu bitişten önceki son sınırdır.
- **Simüle saat:** turun gördüğü zaman. Her turda o turun anıdır. Gerçek saat koşunun hiçbir kararına girmez.
- **Tur fiyatı:** bir çiftin, tur anında açılan mumunun açılış fiyatı. Fiyatın zamanı tur anıdır. O mum dosyada yoksa çiftin o turdaki fiyatı eksiktir.
- **Turun mumları:** tur anına kadar kapanmış mumlardan son `candle_count` kadarı. Kapanışı tur anından sonra olan hiçbir mum ve hiçbir fiyat tura verilmez.
- **Ayrım anı:** örneklem içini (ayrım anından önceki turlar) ve örneklem dışını (ayrım anı ve sonrası) bölen an.
- **Parça:** örneklem içi, örneklem dışı ya da tüm koşu.
- **İşlem:** bir alımla açılıp bir kapanışla kapanan pozisyon. Kapandığı turun parçasında sayılır.
- **Rapor:** koşunun sonunda yazılan, parçaların metriklerini ve koşunun varsayımlarını taşıyan çıktı.

Davranış:
- R-1: **Ağsız ve dokunmasız.** Koşu ağa çıkmaz, API anahtarı okumaz ve kullanmaz. Ortamda anahtar olsa da davranış değişmez. Paper deposuna ve botun kayıt dosyasına dokunmaz, kilit almaz. Çalışan bir paper botu etkilenmez. Koşunun durumu yalnız koşu boyunca tutulur, hiçbir yere kalıcı yazılmaz. Turun depo ya da kayıt hatası sonucu (spec 0016 R-5, R-6) oluşursa koşu durur, neden adıyla söylenir ve R-13 uygulanır.
- R-2: **Ayarlar.** Ayarların hiçbirinin varsayılanı yoktur. Koşu kendi ayarlarını (veri dosyası yolu, rapor dosyası yolu, ayrım anı, spread) aynı ayar dosyasının kendi bölümünden alır. Turun, riskin, stratejinin ayarlarını, beyaz listeyi, mum aralığını, tur aralığını, `candle_count`'u ve açılış kasasını (`bot.opening_balance`) botun bugünkü ayarlarından alır. Ayarlar dosya okunmadan ve hiçbir şey yazılmadan önce denetlenir. Turun ve okumanın bugün reddettiği her ayar burada da reddedilir. Eksik ya da geçersiz bir ayar, ilk sorunlu ayarın adıyla söylenir ve hiçbir şey yapılmaz. Spread, turun spread birimindedir (oran, 0 ≤ spread < 1). Rapor dosyası yolu; veri dosyasının, paper deposunun ya da kayıt dosyasının yolu olamaz.
- R-3: **Veri dosyası ile ayar uyumu.** Koşu şu durumlarda tur atmadan reddeder ve nedeni adıyla söyler: veri dosyası yoksa, okunamıyorsa, bozuksa ya da tamamlanmamışsa; ayardaki beyaz listenin çift kümesi dosyadakinden farklıysa; mum aralığı farklıysa; dönem sınırları bugünkü tur aralığının sınırına denk gelmiyorsa; ayrım anı tur aralığı sınırında değilse ya da başlangıç ile bitişin kesinlikle arasında değilse. Dosyadaki değerler okunurken spec 0017'nin güvenilmez saydığı her mum güvenilmeyen veri sayılır ve koşuyu durdurur.
- R-4: **Rapor dosyası varsa.** Rapor dosyası yolunda okunabilir ya da bozuk bir dosya varsa koşu tur atmadan ve hiçbir şey yazmadan reddeder.
- R-5: **Tur.** Koşu başlarken konsola başladığını, dönemi ve çift sayısını yazar. Her tur anında, ilkinden sonuncusuna sırayla, paper turunun aynısı atılır. Sıra, kapılar, emir yolu, risk kararları ve durdurmalar paper'daki gibidir (spec 0016, 0020). Tura simüle saat, turun mumları, tur fiyatı, dosyadaki çift kuralları ve fiyat adımı, ayardaki sabit spread verilir. Mum yaşı ve fiyat yaşı ayarları simüle saatle uygulanır. Stop ve hedef yalnız tur anlarında, tur fiyatıyla denetlenir. Mum içi en yüksek ve en düşük değere bakılmaz.
- R-6: **Eksik fiyat ve boşluklar.** Fiyatı eksik ya da mumları bayat olan çift için tur, paper'ın bayat ve eksik veri davranışını uygular: o turda alım durur, fiyatsız kapanış yapılmaz (BR-11). Geç listelenen çiftin ilk mumundan önceki turları da böyle işlenir. Koşu sürer, bu turlar raporda sayılır.
- R-7: **Gün ve durdurmalar.** Günlük zarar limiti simüle UTC gününe göre işler (BR-5). Drawdown durdurması başladığı turdan koşunun sonuna kadar sürer (BR-6). Koşu yeniden başlatma kabul etmez.
- R-8: **Bildirimler.** Turun durum bildirimleri hiçbir yere gönderilmez. Türlerine göre sayılır ve raporda görünür.
- R-9: **Kesintisiz koşu ve parçalar.** Koşu dönem boyunca tek bir kasa ve durumla kesintisiz ilerler. Örneklem dışı parça, ayrım anındaki kasa ve açık pozisyonlarla başlar. Her işlem kapandığı turun parçasında sayılır.
- R-10: **Metrikler.** Rapor her parça (örneklem içi, örneklem dışı, tüm koşu) için şunları yazar:
  - başlangıç ve bitiş kasası
  - net kâr/zarar ve getiri yüzdesi, gerçekleşen ve gerçekleşmemiş ayrı
  - işlem sayısı, kazanma oranı, kâr faktörü
  - en büyük drawdown
  - ortalama günlük getiri
  - ödenen komisyon ve ödenen slippage, ayrı ayrı
  - günlük zarar durdurmalı gün sayısı ve drawdown durdurmasının başladığı tur anı (varsa)
  - fiyatı ya da verisi eksik tur sayısı, çift başına
  - "öneri yok" ve ret sayıları, nedene göre
  - gönderilmeyen durum bildirimlerinin sayısı, türe göre

  Tanımlar:
  - Kazanan işlem, komisyon ve slippage sonrası net kârı sıfırdan büyük olan işlemdir. Zararlı işlem, net kârı sıfırdan küçük olandır. Net sıfır olan işlem ikisine de girmez.
  - Kazanma oranı = kazanan işlem ÷ işlem. İşlem yoksa "tanımsız" yazılır.
  - Kâr faktörü = kârlı işlemlerin toplam kârı ÷ zararlı işlemlerin toplam zararının mutlak değeri. Zararlı işlem yoksa "tanımsız" yazılır.
  - Kasa, turun kasa gözlemiyle aynı tanımdır (`docs/domain.md`).
  - Getiri yüzdesi = (bitiş kasası − başlangıç kasası) ÷ başlangıç kasası.
  - Bitiş kasası, açık pozisyonları her çiftin koşudaki son bilinen tur fiyatıyla içerir. Açık pozisyonlar kapatılmaz.
  - Parçanın drawdown'ı, parçanın kendi turlarındaki kasa zirvesine göre ölçülür.
  - Ortalama günlük getiri, parçanın simüle UTC günlerinin son tur kasasından hesaplanan günlük getirilerin aritmetik ortalamasıdır. Her gün, bir önceki günün son tur kasasına göre ölçülür. Parçanın ilk günü parçanın başlangıç kasasına göre ölçülür. Ayrım anına denk gelen gün iki parçada ayrı sayılır, her parça o günün yalnız kendi turlarını kullanır. Tüm koşuda o gün tek gündür.
  - Günlük kâr hedefi metriği raporda yoktur (BR-1, ayarı yok).
- R-11: **Varsayımlar ve işaret.** Rapor, koşunun varsayımlarını yazar:
  - fiyat: tur anında açılan mumun açılışı
  - spread: ayardaki sabit değer; dolumlara eklenmez, yalnız maliyet kapısında (BR-8) kullanılır
  - çift kuralları: indirme anındaki hâliyle, dönem boyunca sabit
  - stop ve hedef yalnız tur anlarında denetlenir
  - B-51: risk, stop fiyatında, satış slippage'ı ve boşluklu düşüş olmadan hesaplanır; gerçekleşen zarar işlem başına risk sınırını aşabilir
  - mum boşlukları doldurulmaz

  Rapor ayrıca dosyanın dönemini, mum aralığını, tur aralığını, ayrım anını, çift listesini ve indirme anını yazar. Yalnız örneklem dışı parça "BR-10 kanıtı adayı" işaretini taşır. Rapor hiçbir parça için geçti ya da kaldı demez.
- R-12: **Belirlenimcilik.** Aynı veri dosyası ve aynı ayarlar bayt bayt aynı raporu verir. Rapor gerçek saati, makine adını ya da koşu süresini taşımaz.
- R-13: **Yarım rapor yok.** Koşu durdurma isteğiyle (Ctrl+C), R-3'teki güvenilmeyen veriyle ya da beklenmeyen bir hatayla biterse tamamlanmış görünen bir rapor dosyası kalmaz. Konsola rapor yazılmaz, nedeni adıyla söylenir. Beklenmeyen hata tip adıyla söylenir, istisna metni yazılmaz. Koşu tamamlanır ama rapor dosyası yazılamazsa rapor konsola yazılır, "rapor dosyası yazılamadı" nedeniyle söylenir ve tamamlanmış görünen rapor dosyası kalmaz.
- R-14: **Süre.** 30 çift, 1 saatlik mum ve tur aralığı, 12 aylık dönem içeren bir koşu `candle_count` 200 ile bu makinede 60 dakikanın altında biter. Dönemin üst sınırı yoktur. (Plan 0025 Risk 1, karar A, Galip Badem, 2026-11-06; hızlandırma B-54.)

## User experience
none — no user interface. Kullanıcı yalnız konsol komutunu, konsol çıktısını ve rapor dosyasını görür. Çıktı biçimi plana aittir, metinler Türkçedir.
- Flow: veri dosyasını indir (0023) → ayar dosyasına koşunun bölümünü yaz → koşu → konsoldaki raporu ya da rapor dosyasını oku.
- States: koşu reddedildi (ayar, veri dosyası yok/bozuk/tamamlanmamış/uyumsuz, rapor dosyası var); koşu sürüyor; koşu durdu (güvenilmeyen veri, depo ya da kayıt hatası sonucu, durdurma isteği, beklenmeyen hata); rapor dosyası yazılamadı (rapor yalnız konsolda); koşu tamam (rapor konsolda ve dosyada).
- Design reference: none — the flow above is the design.
- Accessibility: yalnız klavye; renk bilgi taşımaz.

## Constraints & out of scope
- Sensitive area: yok. Koşu emir göndermez, anahtar kullanmaz, paper deposuna, mod durumuna ve risk kurallarına dokunmaz (R-1). Risk ve emir kodu değişmeden, simüle saatle kullanılır. Mod/aşama kapısı BR-10 kapı spec'indedir. (Q7, Galip Badem, 2026-11-06.)
- Turun (spec 0016, 0020), okumanın (spec 0017), döngünün (spec 0022), indirmenin (spec 0023), paper deposunun ve kayıt dosyasının davranışı değişmez. Shipped testlerin beklentileri değişmez. Strateji kodu backtest ve paper'da aynıdır (`docs/domain.md`, invariants).
- Bağımlılık kuralları (`docs/architecture.md`, Forbidden dependencies) sürer. Plan bir kuralı değiştirmeyi gerektirirse bu bir mimari karardır, sessizce yapılmaz (ADR).
- Testler gerçek borsaya çıkmaz. Koşu ağa hiç çıkmaz.
- Coverage: değişen her modül için modül başına %90 branch eşiği geçerlidir (`docs/testing.md`).
- Bağımlılık (Q1, Galip Badem, 2026-11-06): botun ayar yükleyicisi bilinmeyen bölümü reddeder (spec 0022, 0024). Koşunun ayar bölümünün tanınması ayrı bir mini-spec'tir (CHANGE lane, 0024 gibi). 0025 BUILD o mini-spec ship edildikten sonra başlar.
- 0023'ten taşınan kararlar (S2–S7, G-2–G-11, Galip Badem, 2026-11-06) R-1, R-5–R-11 ve R-14'e yazıldı. Plan 0025 Risk 1 (R-14 ve AC-10: 60 dk) ve Risk 2 ("0026" atıfları "BR-10 kapı spec'i" oldu; ön koşul mini-spec'i 0026 numarasını alır) kararları (Galip Badem, 2026-11-06) buraya yazıldı. Clarify kararları Q1–Q7 (Galip Badem, 2026-11-06) R-2–R-4, R-10, R-12 ve bu bölüme yazıldı.
- Out of scope: BR-10 kapısı, metrik eşiği, insan onayı kaydı, `TRIAL_MARK`'ın kalkması (BR-10 kapı spec'i); rapor için geçti/kaldı kararı; mum içi stop/hedef; geçmiş spread ya da emir defteri; parametre taraması ya da optimizasyon; birden çok ayrım anı ya da yürüyen pencere; günlük kâr hedefi metriği; veri dosyasını indirme ya da güncelleme; Binance dışı borsa; live.
- Split: proposed 0025a koşu → 0025b rapor; kept as one — Galip Badem, 2026-11-06, rapor koşunun çıktısıdır, ayrı test edilemez (self-critique G-2).
- Self-critique kararları G-1–G-8 (Galip Badem, 2026-11-06) R-1, R-5, R-10, R-11 ve R-13'e yazıldı.
- Backlog: B-51 bu spec'te değişmez, raporda varsayım olarak yazılır (R-11).

## Acceptance criteria
- [ ] AC-1 — Mutlu yol (R-5, R-9, R-10): bilinen mumlu küçük bir veri dosyasıyla koşu, başlarken konsola başladığını, dönemi ve çift sayısını yazar, her tur anında bir tur atar. Tura verilen fiyat, tur anında açılan mumun açılışıdır. Kapanışı tur anından sonra olan hiçbir mum ve fiyat tura verilmez. Beklenen alımlar, stop ve hedef kapanışları el hesabıyla aynı turda ve fiyatta olur. Her parçanın her metriği el hesabıyla aynıdır. Rapor konsolda ve rapor dosyasında aynıdır.
- [ ] AC-2 — Paper turunun aynısı (R-5): aynı mumlar, fiyat, kurallar ve ayarlarla bir tur anında koşunun turu ile paper turu aynı kararları (alım, kapanış, ret ve "öneri yok" nedenleri, durdurmalar) verir.
- [ ] AC-3 — Ağsız ve dokunmasız (R-1): ortamda anahtar varken anahtar okunmaz, ağ çağrısı yapılmaz. Paper deposu, kayıt dosyası ve veri dosyası bayt bayt değişmez. Aynı depoyla çalışan bir botun kilidi varken koşu tamamlanır.
- [ ] AC-4 — Ayarlar (R-2): ayar dosyası yok, okunamıyor, koşunun her eksik ayarı, her geçersiz ayarı (spread < 0 ya da ≥ 1 dahil), rapor yolunun veri dosyası, depo ya da kayıt yoluna eşitliği ve turun reddettiği her ayar için hiçbir şey yazılmaz ve ilk sorunlu ayar adıyla söylenir.
- [ ] AC-5 — Veri dosyası ve uyum (R-3, R-4): veri dosyası yok, bozuk ya da tamamlanmamış; beyaz liste kümesi farklı; mum aralığı farklı; dönem tur aralığı sınırına denk değil; ayrım anı sınırda değil, başlangıca ya da bitişe eşit ya da dönem dışında; rapor dosyası var. Bu durumların her birinde tur atılmaz, rapor dosyası yazılmaz ya da değişmez, neden adıyla söylenir. Güvenilmez mum içeren dosyada koşu durur ve tamamlanmış görünen rapor kalmaz.
- [ ] AC-6 — Eksik fiyat, boşluk, geç çift (R-6): tur anında mumu olmayan çiftte o turda alım olmaz, o çiftin açık pozisyonu fiyatsız kapatılmaz. Geç listelenen çiftin önceki turları aynı biçimde işlenir. Eksik turlar raporda çift başına doğru sayılır.
- [ ] AC-7 — Gün, durdurmalar ve bildirimler (R-7, R-8): günlük zarar limiti aşılan simüle UTC gününde yeni alım olmaz, ertesi simüle günde sürer. Drawdown durdurması başladıktan sonra koşunun sonuna kadar alım olmaz, kapanışlar sürer. Hiçbir bildirim alıcıya gitmez, bildirimler türe göre doğru sayılır.
- [ ] AC-8 — Parçalar ve tanımlar (R-9, R-10): ayrım anının iki yanına uzanan işlem kapandığı parçada sayılır. Örneklem dışı parça ayrım anındaki kasa ve pozisyonlarla başlar. Parça drawdown'ı kendi zirvesine göre ölçülür. İşlemsiz parçada kazanma oranı, zararlı işlemi olmayan parçada kâr faktörü "tanımsız" yazılır. Net kârı sıfır olan işlem kazanan ya da zararlı sayılmaz. Ayrım anına denk gelen gün iki parçada ayrı sayılır. Bitiş kasası açık pozisyonları son bilinen tur fiyatıyla içerir, son turda mumu olmayan çift dahil. Gerçekleşen ve gerçekleşmemiş kâr/zarar ayrı ve doğrudur.
- [ ] AC-9 — Rapor içeriği ve belirlenimcilik (R-11, R-12): rapor R-11'deki her varsayımı (B-51 dahil) ve koşu bilgisini taşır. "BR-10 kanıtı adayı" işareti yalnız örneklem dışı parçadadır. Raporda geçti/kaldı ifadesi yoktur. Aynı dosya ve ayarla iki koşu, farklı gerçek saatlerde bayt bayt aynı rapor dosyası üretir.
- [ ] AC-10 — Yarım rapor yok ve süre (R-1, R-13, R-14): koşu ortasındaki durdurma isteğinde, turun depo ya da kayıt hatası sonucunda ve beklenmeyen hatada tamamlanmış görünen rapor dosyası kalmaz. Rapor dosyası yazılamazsa rapor konsola yazılır, neden adıyla söylenir, tamamlanmış görünen dosya kalmaz. Beklenmeyen hata tip adıyla yazılır, istisna metni ve sır biçimli metin çıktıda yoktur. 30 çift, 1 saat, 12 aylık sentetik dosyayla, `candle_count` 200 ile koşu bu makinede 60 dakikanın altında biter (VERIFY'da, `check` dışında, süre ölçümüyle belgelenir).

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
