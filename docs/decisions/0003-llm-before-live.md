# ADR 0003 — LLM sinyalleri live'dan önce; abonelikle, filtre olarak, ileriye dönük ölçümle

- Status: Accepted
- Date: 2026-11-15

## Context
ADR 0002 ürünü üç faza böldü: Faz 1 gözetimsiz paper ve backtest, Faz 2 salt okunur pano ve ardından küçük sermayeyle
live, Faz 3 `llm`, `news`, `research` ve sinyallerin `strategy`'de birleşmesi. Gerekçe, live'a iki yeni riskin
(LLM harcaması, güvenilmeyen girdi) aynı anda girmemesiydi. ADR 0002'nin bir yeniden açma koşulu "teknik sinyal tek
başına yetersiz kalırsa Faz 3'ün bir kısmı live'dan önceye alınabilir, ayrı karar olarak" idi. Bu koşul gerçekleşti:

- Spec 0044: sekiz teknik aday stratejinin (S0…S3, 1h ve 4h) hiçbiri maliyetlerden sonra kâr etmedi; son değerlendirme
  "aday yok" dedi. BR-10'a göre aday olmadan live açılamaz.
- Spec 0045: sekiz indikatör, beş aralıkta, kriptoya ayarlanmış ayarlarıyla ölçüldü; görülmemiş dönemde
  (2025-07 → 2026-11) hiçbiri "kullanılabilir" çıkmadı (0/40). Ayarlamada öne çıkan altı ayarın avantajı en çok
  +2,5 puandı (eşik +5) ve 15m Supertrend ile 4h Donchian'da olağandışı mumlar (büyük, çoğu olay kaynaklı hareketler)
  çıkarılınca taban oranın altına düştü: fiyattan türeyen sinyallerin küçük avantajı olaylardan geliyor gibi.
- Sahip kararı (2026-11-15): "LLM devreye girmeden bu sistemi canlıya alamayız."
- Faz 2'nin altyapısı (pano, live adaptörü, anahtar yönetimi, testnet; spec 0031–0041) hazırdır; bekleyen, gerçek
  parayla live başlatmadır.

Ek kısıtlar (sahip, 2026-11-15): LLM için ayrı, ücretli bir API alınmaz; LLM mevcut Claude aboneliğiyle çalışır.
Geçmiş haberler modelin skorlamasını iyileştirmek için kullanılmak istenir. Projede onaylı tek çalışma bağımlılığı
`ccxt`'tir (spec 0018). Güvenlik kuralları (`docs/security.md`): haber ve LLM yanıtı güvenilmeyen girdidir, LLM çıktısı
yalnız şemalı ve alıntılı bir skordur, hiçbir aksiyonu doğrudan tetiklemez, harcama günlük limitlidir.

Bir ölçüm tuzağı karara yön verir: modelin eğitim verisi geçmiş olayların fiyat sonuçlarını içerebilir. Eğitim
kesiminden önceki haberlerle yapılan ölçümde "doğru tahmin" aslında hatırlamadır (LLM'deki look-ahead).

## Decision
LLM fazı live'dan önce gelir: sıra Faz 1 ve pano (tamam) → haber toplama → geçmiş olaylardan örnek kütüphanesi ve
kalibrasyon → `llm` ve gölge mod → ileriye dönük ölçüm → ancak sonra live; live, BR-10'u geçen bir adayla birlikte LLM
ölçümünün olumlu hükmünü de şart koşar. LLM şu ilkelerle çalışır:

1. Mevcut Claude aboneliğiyle çalışır; ayrı ücretli API ve API anahtarı kullanılmaz (uygulama yolu spec'te seçilir).
2. İlk rolü filtredir: ilgili coin için olumsuz bir olay skoru varken teknik "al" bastırılır. LLM'in tek başına "al"
   sinyali üretmesi ayrı bir karardır.
3. Başarı yalnız ileriye dönük gölge modla (bot skorları kaydeder, karara karışmaz) ya da modelin eğitim kesiminden
   sonraki haberlerle ölçülür; ölçüm 0045'in isabet kuralı ve taban oranıyla yapılır.
4. Geçmiş haberler modelin ağırlıklarını eğitmek için değil, örnek kütüphanesi (benzer olay ve gerçek sonucu) ve
   kalibrasyon tablosu (olay türü ve skor → ölçülmüş isabet) için kullanılır; hüküm onlarla verilmez.
5. LLM çıktısı hiçbir aksiyonu (emir, limit, mod, beyaz liste) doğrudan tetiklemez; abonelik kullanılamazsa ya da
   limit dolarsa LLM devre dışı kalır, bot teknik sinyalle devam eder.
6. Yerel, açık kaynak sınıflandırıcılar (ör. CryptoBERT, FinBERT) yedek ya da ön eleme seçeneği olarak açık kalır;
   aynı ölçümden geçmeden kullanılmaz.

ADR 0002'nin geri kalanı geçerlidir: Faz 1'in tanımı, salt okunur ve yalnız localhost pano, kontrolün CLI ve TOTP
onaylı Telegram'da kalması, B-51'in live stop emri spec'ine bağlı olması.

## Consequences
- Live için bekleme uzar: gölge mod ölçümü aylar sürer (öneri: en az 3 ay ve en az 30 skorlanmış olay; spec'te
  sabitlenir). Bedeli: hazır live altyapısı bu süre boyunca kullanılmaz; testnet ve paper dışında gerçek işlem olmaz.
  Kazancı: kanıtsız bir stratejiyle gerçek para riske girmez.
- LLM'in değeri, işlem kararına karışmadan ölçülür: gölge mod paper sonuçlarını değiştirmez, hangi sinyalin işe
  yaradığı ayrılabilir. ADR 0002'nin "iki risk aynı anda girmesin" kaygısı bu yolla karşılanır: LLM riski live'dan
  önce, para riski olmadan oturur.
- Abonelik kullanımı ek ücret getirmez ve yeni SDK bağımlılığı gerektirmeyebilir. Bedeli: kota (zaman pencereli
  kullanım sınırları) ve aboneliğin otomatik, sürekli kullanıma izin verip vermediği belirsizdir; bu, ilk LLM
  spec'inin çözmesi gereken açık sorudur ve sahibin güncel kullanım koşullarından doğrulaması gerekir. Kota dolduğunda
  ya da oturum düştüğünde skor üretilmez; gölge modda veri boşluğu, sonra filtrede "filtre yok" durumu oluşur.
- İleriye dönük ölçüm dürüsttür ama yavaştır; geçmiş veriyle hızlı bir "kanıt" üretmek bilerek reddedilir. Bedeli:
  prompt ve kalibrasyon iyileştirmesinin etkisi de ancak ileriye dönük görülür.
- Zaman damgalı geçmiş haber bulmak zordur (RSS geçmiş tutmaz, toplayıcı arşivleri çoğunlukla ücretlidir); örnek
  kütüphanesinin kapsamı ulaşılabilen arşivle sınırlı kalır (en güçlü aday Binance duyuru arşivi).
- Filtre rolü dar başlar: LLM yalnız alımı bastırabilir, açtıramaz. Bedeli: LLM olumlu olayda fırsatı yakalasa bile
  bu ilk aşamada kullanılmaz.
- `news`, `llm` ve `strategy`'de birleşme spec'leri art arda gelir; harcama limiti, şema, alıntı ve prompt
  injection kuralları her birinde testle kanıtlanır.

## Alternatives considered
- **Yalnız faz sırasını değiştirmek, ilkeleri spec'lere bırakmak:** ADR kısa ve tek konulu olurdu; ama abonelik
  kısıtı ve "geçmiş veriyle hüküm yok" disiplini spec'lere dağılır ve her LLM spec'inde yeniden tartışılırdı.
- **ADR 0002'yi aynen sürdürmek (live önce, yalnız teknik sinyal):** yazılı plan buydu; ama kanıtlı aday yok, BR-10
  live'ı zaten kapatıyor ve sahip LLM'siz live'ı reddetti. Pratikte belirsiz süre beklemek demekti.
- **LLM'i bırakıp teknik araştırmaya devam etmek (kendi indikatörümüz, zaman serisi modelleri):** LLM'in riskleri
  hiç girmezdi; ama 0044 ve 0045 fiyattan türeyen sinyallerde avantajın zayıf olduğunu ve kalan küçük avantajın
  olaylı hareketlerde olduğunu gösterdi. Kendi indikatörümüz ileride ayrı bir karar olarak açık kalır.
- **Ücretli Claude API:** kota ve koşullar açık, otomatik kullanım net biçimde izinli, harcama limitle sınırlı
  olurdu; sahip ek ücreti reddetti. Abonelik yolu kapanırsa ilk alternatif budur.
- **Yalnız yerel açık kaynak model:** ücret ve kota yoktur; ama olay türü, coin eşlemesi ve alıntı gibi ayrımları
  Claude kadar yapamaz ve PyTorch gibi ağır bir bağımlılık getirir. Yedek olarak açık kalır.

## Revisit triggers
- Aboneliğin kullanım koşulları otomatik, sürekli kullanıma izin vermiyorsa ya da kota gölge mod için yetmiyorsa:
  ücretli API ya da yerel model yeniden tartışılır.
- Gölge mod, spec'te sabitlenen süre ve olay sayısı sonunda taban oranı geçemezse: LLM filtresi bırakılır; live'ın
  şartı ve projenin yönü yeniden kararlaştırılır.
- Yerel bir model aynı ölçümde Claude'a denk çıkarsa: kota ve koşul riskini azaltmak için yerine geçmesi tartışılır.
- Teknik tarafta BR-10'u geçen bir aday çıkar ve sahip LLM'siz live isterse: sıra yeniden açılır.
- LLM'e alım açtırma, emir üretme ya da limitlere dokunma yetkisi istenirse: yeni ADR (güvenlik kurallarıyla
  çatışır).
