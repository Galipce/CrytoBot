# Spec 0048 — Geçmiş olaylardan örnek kütüphanesi ve kalibrasyon tablosu

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0048-plan.md`
- Self-critique: done
- Source: ADR 0003 (sıranın üçüncü işi: geçmiş olaylardan örnek kütüphanesi ve kalibrasyon; ilke 3 ve 4); spec 0047
  (arşiv), spec 0046 (ileriye dönük kayıt), spec 0045 (isabet kuralı ve taban oran)
- Approved by / on: Galip Badem, 2026-11-16

## Intent
Botun sahibi, LLM fazından önce geçmiş Binance duyurularının fiyat üzerinde gerçekte ne yaptığını gösteren bir örnek
kütüphanesi ve bir kalibrasyon tablosu istiyor (ADR 0003 ilke 4). Kaynak, 0047 arşivi ile 0046'nın ileriye dönük Binance
duyuru kayıtlarıdır. Her duyuruya başlığından, sabit kurallarla, sabit bir listeden bir olay türü ve ilgili coin(ler)
atanır. Her olay × coin için 0045'in isabet kuralıyla gerçek fiyat sonucu ölçülür. Tablo, olay türü başına örnek
sayısını, isabet oranını ve taban oranı gösterir. Başarı: yeniden üretilebilir bir kütüphane dosyası ve bir rapor.
Sonraki LLM spec'i bunları "benzer olay ve gerçek sonucu" örneği olarak kullanabilir. "Hiçbir olay türünün belirgin
etkisi yok" sonucu da başarıdır. Bilerek yapılmayanlar: LLM çağrısı ve LLM skoru (sonraki spec), RSS haberleri,
strateji filtresi, işlem davranışında herhangi bir değişiklik ve tablodan hüküm çıkarmak. Hüküm yalnız ileriye dönük
ölçümle verilir (ADR 0003 ilke 3). Clarify kararları Q-1…Q-7 ve self-critique kararları G-1…G-9 Galip Badem,
2026-11-16 tarihinde onayladı.

Terimler:
- **Duyuru:** 0047 arşivindeki ya da 0046 ileriye dönük kaydındaki `binance-duyuru` türü bir kaynaktan gelmiş tek
  kayıt. Aynı Binance duyuru kimliği iki kayıtta da varsa tek duyurudur (Q-5).
- **Olay türü (Q-2):** Aşağıdaki sabit listeden biri. Her türün **beklenen yönü** sabittir:

  | Olay türü | Anlamı (örnek başlık) | Beklenen yön |
  |---|---|---|
  | spot listeleme | coin Binance spot'ta işleme açılır ("Binance Will List X (X)") | olumlu |
  | listeden çıkarma | coin Binance'ten tümüyle kaldırılır ("Binance Will Delist X, Y") | olumsuz |
  | işlem çifti kaldırma | coinin bazı spot çiftleri kaldırılır, coin kalır ("Notice of Removal of Spot Trading Pairs") | olumsuz |
  | izleme etiketi | coine izleme etiketi eklenir ("Binance Will Extend the Monitoring Tag to Include X") | olumsuz |
  | launchpool / launchpad / HODLer | yeni coin Binance'in dağıtım programıyla gelir | olumlu |
  | vadeli / marjin listeleme | coin için vadeli işlem ya da marjin açılır | olumlu |
  | askıya alma ve bakım | coinde yatırma/çekme askıya alınır, cüzdan bakımı | nötr |
  | ağ yükseltmesi | coinin ağında yükseltme ya da hard fork desteği | nötr |
  | diğer | hiçbir kurala uymayan başlık | nötr |

- **Etiket kuralları (Q-1):** Başlığa uygulanan, ağsız ve belirlenimci kurallar. Bir başlık listedeki ilk eşleşen
  türü alır (sıra tablodaki sıradır). Kurallar LLM kullanmaz.
- **Örnek:** bir duyuru × o duyuruda geçen tek coin. Birden çok coin geçen duyuru coin başına bir örnek verir; hiç coin
  geçmeyen duyuru kütüphanede "coin yok" örneği olarak tek satırla durur ve ölçülmez (Q-4).
- **Referans an:** duyurunun yayın anı (UTC). İleriye dönük kayıttan gelen duyuruda ilk görme anı da kütüphaneye
  yazılır. Yayın anı varsa referans an olarak kullanılmaz (Q-5). Yayın anı "bilinmiyor" ama ilk görme anı varsa
  referans an ilk görme anıdır ve örnek "ilk görme anı kullanıldı" işaretini taşır (G-2).
- **Giriş mumu:** coinin USDT spot çiftinin, açılış anı referans andan kesin sonra olan ilk 1h mumu. Giriş fiyatı bu
  mumun açılışıdır (Q-3).
- **İsabet (Q-3):** 0045'in kuralı aynen geçerlidir: giriş mumu dahil en çok 24 mum içinde fiyat, hedef mesafesine
  stop mesafesinden önce ulaşır. Hedef mesafesi 2×ATR ile bir alım-satım turunun maliyetinin büyüğü, stop mesafesi
  1×ATR'dir. Maliyet 0045'in formülüyle, ayardaki ücret, slippage ve spread'den hesaplanır. Varsayılanlar 0045'in
  ölçüm ayarındaki değerlerdir ve rapora yazılır (G-4). ATR(14), giriş mumundan önceki mumda ölçülür. Aynı mumda iki sınıra da değilirse ya da 24 mum dolarsa
  isabet yoktur. **Yükseliş isabeti** hedefi yukarıda, **düşüş isabeti** hedefi aşağıda arar.
- **Taban oran (Q-3):** aynı coinde, referans andan önceki 30 günün (720 mum) her mumunun kapanışı sinyal sayılarak,
  aynı yön ve aynı kuralla elde edilen isabet oranı. Değerlendirme penceresi referans anı aşan mumlar sayılmaz. Bir
  olay türünün taban oranı, ölçülen örneklerinin taban oranlarının ortalamasıdır.
- **Model kesim tarihi (Q-6):** ayarda yazılı bir tarih. Bu tarihten önceki olaylar, LLM'in eğitim verisinde
  sonucuyla birlikte bulunabilir.

## Requirements
- R-1 — **Etiketleme.** Her duyuruya etiket kurallarıyla bir olay türü ve başlıkta geçen coinler atanır. Bir coin
  başlıkta açıkça bir sembolle ya da çiftle (ör. `(XYZ)`, `XYZ/USDT`, `XYZUSDT`) adlandırılırsa geçer. Ağ adları
  (ör. `BEP20`, `ERC20`), stabil coinler (ör. `USDT`, `USDC`) ve tarihler sabit bir dışlama listesiyle coin sayılmaz.
  Coinin "Binance'te USDT spot çifti var" sayılmasına Binance'in genel borsa bilgisindeki çiftlere, kapanmış ya da
  kaldırılmış olanlar dahil, bakılarak karar verilir (G-3). Kurallar, dışlama listesi ve tür
  listesi bu spec'te sabittir ve ölçüm sonucuna bakılarak değiştirilmez. Kural setinin parmak izi rapora yazılır.
  Kurallarda yapılacak bir değişiklik yeni spec ister (Q-2).
- R-2 — **Kütüphanenin kaynakları (Q-5).** Kütüphane 0047 arşivinin bütün kayıtlarını ve 0046 ileriye dönük kaydının
  `binance-duyuru` türü kaynaklardan gelen kayıtlarını okur; RSS kayıtlarını okumaz. Aynı Binance duyuru kimliği iki
  kaynakta da varsa tek duyuru sayılır. O duyurunun satırı iki kaynağı da gösterir ve ileriye dönük kayıttaki ilk görme
  anını taşır. Kaynak kayıtlar yalnız okunur, hiçbiri değiştirilmez. Toplayıcı ya da arşiv komutu çalışırken de okuma
  yapılabilir.
- R-3 — **Fiyat verisi (Q-4).** Her ölçülebilir örnek için coinin USDT spot çiftinin 1h mumları, Binance'in genel
  piyasa verisinden ayrı bir indirme adımıyla alınır. Alınan aralık, taban oran ve ATR ısınması için referans andan
  önceki 30 günü ve giriş mumundan sonraki 24 mumu kapsar. Normal piyasa verisi bir çiftin mumlarını vermezse (ör.
  listeden çıkarılmış çift), Binance'in herkese açık geçmiş veri arşivi ikinci kaynak olarak kullanılır (G-1). Aynı
  coinin üst üste binen aralıkları bir kez indirilir; indirmenin süre sınırı yoktur, toplam süre kaydedilir (G-6).
  İndirme API anahtarı kullanmaz. İndirme adımı 0047 R-5'in
  nazik istek kurallarına uyar: aynı anda tek istek, iki istek arası en az ayardaki süre (vars. 1 s, en az 1 s), istek
  başına en çok 30 s, genel istemci adı. Kaynak hata verirse adım hatanın adıyla durur ve indirilmiş olanlar kalır.
  Yeniden çalıştırma yalnız eksikleri indirir. Ölçüm adımı ağa çıkmaz.
- R-4 — **Ölçülemeyen örnekler.** Şu örnekler kütüphanede durur ama ölçülmez; her birinin nedeni yazılır ve sayısı
  raporlanır: yayın anı "bilinmiyor"; coin yok; coinin Binance'te USDT spot çifti yok; giriş mumu yok ya da açılışı
  referans andan 1 saatten daha sonra (ör. listeleme duyurusu işlem başlamadan yayınlanır); ATR ya da taban oran için
  mum yetmiyor; giriş mumundan sonraki 24 mum veri sonunu aşıyor.
- R-5 — **Ölçüm.** Her ölçülebilir örnek için hem yükseliş hem düşüş isabeti ve ikisinin taban oranı ölçülür. Olay
  türünün beklenen yönü olumluysa yükseliş, olumsuzsa düşüş **ana sonuç**tur; öteki yön ayrı tabloda raporlanır. Nötr
  türlerde iki yön de ayrı tablolarda raporlanır, ana sonuç yoktur. Aynı coinde 24 mumluk pencereleri üst üste binen
  örnekler ayrı sayılır ve ayıklanmaz; tablo her satırda başka bir örnekle penceresi çakışan örnek sayısını gösterir
  (G-7).
- R-6 — **Kalibrasyon tablosu (Q-6).** Rapor her olay türü × yön × dönem için şunları gösterir: duyuru sayısı, örnek
  sayısı, ölçülen örnek sayısı, penceresi çakışan örnek sayısı, isabet oranı, taban oran ve farkı (puan). Dönemler model kesim tarihine göre ikidir:
  kesimden önce ve kesimden sonra (sınırdaki an "sonra" sayılır); ayrıca ikisinin toplamı. Ölçülen örneği 30'dan az olan
  satır "yetersiz örnek" diye işaretlenir. Tablo betimleyicidir: hiçbir satır "kullanılabilir", "geçti" ya da benzeri
  bir hüküm taşımaz. Tablo hiçbir aşama kapısının, stratejinin ya da filtrenin girdisi değildir.
- R-7 — **Kütüphane dosyası (Q-7).** Rapordan ayrı, makinece okunur bir kütüphane dosyası her örnek için şunları taşır:
  Binance duyuru kimliği, kaynak işareti (arşiv / ileriye dönük / ikisi), katalog, başlık, yayın anı, ilk görme anı
  (varsa), olay türü, beklenen yön, coin, dönem, giriş anı ve fiyatı, yükseliş ve düşüş isabeti, iki taban oran ve
  ölçülemediyse nedeni. Başlık güvenilmeyen girdidir: olduğu gibi yazılır, hiçbir biçimde çalıştırılmaz ve
  yorumlanmaz.
- R-8 — **Etiket denetimi.** Rapor, sahibin kuralları gözle denetleyebilmesi için her olay türünden en çok 20 başlığı,
  sabit bir seçim kuralıyla örnek olarak yazar. Ayrıca "diğer" türüne düşen duyuru sayısını ve "diğer"de en sık geçen
  ilk 20 başlık kalıbını yazar.
- R-9 — **Yeniden üretilebilirlik.** Aynı kaynak kayıtları, aynı fiyat verisi ve aynı ayarla iki ölçüm koşusu, üretim
  anı satırı dışında bayt bayt aynı rapor ve kütüphane dosyası üretir. Rapor; girdilerin (arşiv, ileriye dönük kayıt,
  fiyat verisi) okunduğu anı, kayıt sayılarını, kural seti parmak izini ve model kesim tarihini yazar.
- R-10 — **Ayarlar ve dosyalar.** Kaynak kayıtların yerleri, fiyat verisinin yeri, çıktı yerleri, istek aralığı ve model
  kesim tarihi ayardadır. Model kesim tarihinin varsayılanı yoktur, yazılması zorunludur; değerini sahip, LLM spec'inde
  seçilecek modelin yayıncısının bildirdiği eğitim kesimine göre koşudan önce yazar (G-8). Aynı çıktı yerine ikinci bir
  indirme ya da ölçüm koşusu açılmak istenirse anlaşılır bir mesajla reddedilir (G-5). Çıktılar deponun dışında
  durur ve git'e girmez. Bir çıktı yeri kaynak kayıtlardan, bot deposundan ya da bir kayıt dosyasından biriyse komut
  başlamayı reddeder. Arşiv yoksa komut başlamayı adıyla reddeder. İleriye dönük kayıt yoksa bunu raporda yazar ve
  yalnız arşivle sürer.
- R-11 — **İşlem davranışı değişmez.** Paper, live, backtest, kalibrasyon (0045), aşama kapısı, risk limitleri, haber
  toplayıcı ve arşiv komutu bugünkü gibi çalışır. Çalışan `crytobot.toml` ve `crytobot-news.toml` değişmez.

## User experience
none — no user interface. Etkileşim CLI komutları, ayar, rapor ve kütüphane dosyasıdır; pano ve Telegram değişmez.

## Constraints & out of scope
- Sensitive area: yok. Emir, risk, sır, mod, defter ve bot deposuyla ilgisi yoktur; kaynak kayıtlar yalnız okunur.
- Yeni çalışma bağımlılığı eklenmez; onaylı tek çalışma bağımlılığı `ccxt` kalır (spec 0018).
- `scripts/check` ağa çıkmaz; kaynak kayıtlar ve fiyat yanıtları kayıtlı örneklerle sınanır (`docs/testing.md`).
- Gerçek veri koşusunun ön koşulu, sahibin 0047 arşivini (`news archive`) doldurmasıdır. 2026-11-16 itibarıyla arşiv
  deposu yoktur.
- Binance'in genel piyasa verisi listeden çıkarılmış çiftlerin geçmişini vermeyebilir; bu yüzden herkese açık geçmiş
  veri arşivi ikinci kaynaktır (G-1). İkisi de vermezse örnek "fiyat verisi yok" sayılır ve sayısı görünür; sessiz
  boşluk oluşmaz. İki kaynağın da biçimi değişirse kaynak hatası olur.
- Split: proposed 0048 (etiketleme ve kütüphane) + 0049 (fiyat indirme, ölçüm, tablo); kept as one — Galip Badem,
  2026-11-16, etiketleme tek başına sonuç üretmez, tablo ondan çıkar (G-9).
- Out of scope: LLM çağrısı, LLM skoru ve skor → isabet kalibrasyonu (LLM spec'i, bu tabloya skor sütununu o ekler);
  RSS haberleri ve serbest metinden coin/tür çıkarma; duyuru sayfası ya da metni; olağandışı mum işaretleri (0045 R-8);
  1h dışındaki aralıklar; tablodan hüküm ya da eşik; strateji filtresi ve gölge mod; kütüphanenin otomatik ya da
  zamanlanmış yenilenmesi; kaynak kayıtların değiştirilmesi.

## Acceptance criteria
- [ ] AC-1 — Etiketleme: her olay türü için en az bir kayıtlı başlık doğru türü alır. Hiçbir kurala uymayan başlık
  "diğer" olur. İki türe uyan başlık tablodaki sıraya göre ilk türü alır. Üç coin geçen duyuru üç örnek verir. Coin
  geçmeyen duyuru tek "coin yok" örneğidir. `(BEP20)`, `(USDT)` ve tarih gibi dışlama listesindeki parantezler coin
  sayılmaz. Kaldırılmış ama borsa bilgisinde bulunan çiftin coini "çift var" sayılır; hiç USDT spot çifti olmayan coin
  "çift yok" nedeniyle ölçülmez. Kural seti parmak izi rapordadır (R-1, R-4).
- [ ] AC-2 — Kaynaklar: arşivde ve ileriye dönük kayıtta aynı kimlikle bulunan duyuru tek duyuru sayılır, kaynak
  işareti "ikisi"dir ve ilk görme anını taşır. RSS kayıtları kütüphaneye girmez. Koşudan önce ve sonra kaynak
  kayıtların içeriği aynıdır. Toplayıcı kaydı açıkken okuma çalışır. İleriye dönük kayıt yoksa rapor bunu yazar ve
  arşivle sürer (R-2, R-10).
- [ ] AC-3 — Giriş ve isabet: giriş mumu, açılışı referans andan kesin sonra olan ilk mumdur. Açılışı tam referans
  anında olan mum giriş değildir. Açılışı referans andan tam 1 saat sonra olan mum giriştir, 1 saatten sonra olan
  ölçülmez. Hedefe 24. mumda ulaşan isabetlidir, 25. mumda ulaşan değildir. Stopa önce değen ve aynı mumda iki sınıra
  değen isabetli değildir. 2×ATR maliyetten küçükse hedef maliyet mesafesidir. Yükseliş ve düşüş kuralları
  simetriktir. Yayın anı bilinmeyen ama ilk görme anı olan örnek ilk görme anıyla ölçülür ve "ilk görme anı
  kullanıldı" işaretini taşır; ikisi de yoksa "yayın anı bilinmiyor" nedeniyle ölçülmez. Hedef mesafesindeki maliyet
  ayardaki ücret, slippage ve spread'den hesaplanır ve rapordadır (R-5, G-2, G-4).
- [ ] AC-4 — Ana sonuç: olumlu türde ana sonuç yükseliş, olumsuz türde düşüştür. Öteki yön ayrı tabloda raporlanır.
  Nötr türde iki yön de ayrı raporlanır, ana sonuç yoktur. Üst üste binen pencereler ayrı sayılır, ayıklanmaz ve
  tablo satırında penceresi çakışan örnek sayısı görünür (R-5, R-6).
- [ ] AC-5 — Taban oran: referans andan önceki 720 mumun her kapanışı sinyal sayılarak aynı kural ve yönle hesaplanır.
  Penceresi referans anı aşan mum sayılmaz. 720 mumdan azı varsa örnek "mum yetmiyor" nedeniyle ölçülmez. Türün taban
  oranı örnek taban oranlarının ortalamasıdır (R-4).
- [ ] AC-6 — Ölçülemeyen örnekler: yayın anı bilinmiyor, coin yok, çift yok, giriş mumu yok ya da geç, mum yetmiyor ve
  pencere veri sonunu aşıyor durumlarının her biri kütüphanede nedeniyle durur, ölçülmez ve raporda ayrı sayılır
  (R-4).
- [ ] AC-7 — Tablo: her olay türü × yön × dönem satırı duyuru, örnek ve ölçülen örnek sayısını, isabet oranını, taban
  oranı ve farkını taşır. Tam kesim anındaki olay "sonra" dönemindedir. 29 ölçülen örnekli satır "yetersiz örnek"
  işaretlidir, 30 örnekli değildir. Hiçbir satır hüküm taşımaz. Rapor tür başına en çok 20 örnek başlığı ve "diğer"in
  sayısı ile en sık 20 kalıbını yazar (R-6, R-8).
- [ ] AC-8 — Kütüphane dosyası R-7'nin bütün alanlarını taşır. Kod ya da biçim karakteri içeren başlık olduğu gibi
  yazılır ve hiçbir şeyi tetiklemez. Aynı girdilerle iki ölçüm koşusu, üretim anı satırı dışında bayt bayt aynı rapor
  ve kütüphane dosyası üretir. Ölçüm adımı ağa istek göndermez (R-7, R-9).
- [ ] AC-9 — İndirme adımı: iki istek arasında en az ayardaki süre geçer ve aynı anda tek istek vardır. Takılan istek
  en çok 30 saniyede (ölçüm payıyla) hata olur. Ağ hatası, HTTP hata cevabı, hız sınırı (429) ya da beklenmeyen
  yanıtta adım hatanın adını veren satırla, çıkış 1 ile durur ve aynı isteği yinelemez. İndirilmiş olanlar kalır.
  Yeniden çalıştırma yalnız eksikleri ister. İstekler API anahtarı ya da kişisel bilgi taşımaz. Çifti olmayan coin için
  "fiyat verisi yok" yazılır ve adım sürer. Normal piyasa verisi bir çiftin mumunu vermezse herkese açık geçmiş veri
  arşivi denenir; ikisi de vermezse örnek "fiyat verisi yok" olur. Aynı coinin çakışan aralıkları bir kez istenir.
  Toplam süre kaydedilir (R-3, G-1, G-6).
- [ ] AC-10 — Geçersiz ayarda komut ağa çıkmadan ve hiçbir dosya yazmadan, hatanın adını veren bir mesajla, çıkış 1 ile
  başlamayı reddeder. Geçersiz ayar şunlardır: model kesim tarihi yok ya da okunamıyor; arşiv yok; bir çıktı yeri
  kaynak kayıtlardan, bot deposundan ya da bir kayıt dosyasından biri; istek aralığı 1 saniyeden küçük. Aynı çıktı
  yerine ikinci bir koşu açılmak istenirse anlaşılır bir mesajla reddedilir (R-10, G-5).
- [ ] AC-11 — İşlem davranışı değişmez: koşudan önce ve sonra `crytobot.toml`, `crytobot-news.toml`, kaynak kayıtlar ve
  bot deposu aynıdır (sha256). Paper, backtest, kalibrasyon, aşama kapısı ve haber testleri değişmeden geçer (R-11).
- [ ] AC-12 — Gerçek veriyle koşu yapılır ve kayda geçer: sahibin doldurduğu arşivle ve ileriye dönük kayıtla indirme
  ve ölçüm koşulur. Girdilerin kayıt sayıları ve okunma anı, fiyat verisinin indirme anı, kural seti parmak izi, model
  kesim tarihi, tür başına ölçülen örnek sayısı ve ana sonuç farkı, ölçülemeyenlerin nedene göre sayısı, rapor parmak
  izi ve toplam süre planın `## Build evidence` bölümüne yazılır (R-6, R-9).

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
