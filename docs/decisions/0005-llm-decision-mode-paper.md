# ADR 0005 — LLM karar modu: paper'da Claude'un al kararı ve fiyat seviyeleri, ön kayıtlı ölçümle

- Status: Accepted — kural 1'in listesi Superseded by ADR-0006 (TON yerine TRX) ve ADR-0007 (20 coin)
- Date: 2026-11-20

## Context
ADR 0003 LLM'i yalnız filtre olarak tanımladı: olumsuz olay skoru teknik "al"ı bastırır; LLM tek başına "al" demez
(ilke 2) ve çıktısı hiçbir aksiyonu doğrudan tetiklemez (ilke 5). O günden beri teknik taraf ilerlemedi: 0044'te sekiz
aday maliyetlerden sonra kâr etmedi, 0045'te 40 indikatör ayarından hiçbiri görülmemiş dönemde eşiği geçmedi; ADR 0004
ile BTC/ETH 4h S0 ileriye dönük paper'da koşuyor ama kârlı olması beklenmiyor. Ayrıca gölge filtre (0052) BTC/ETH'de
nadiren tetiklenir: Binance'in olumsuz duyuruları çoğunlukla küçük altcoinlerle ilgilidir.

Sahip (2026-11-20) yön değişikliği istedi: belirlenmiş, güvenilir bir coin listesinde kısa aralıklarla teknik analiz
modülünün özeti ve haber skorları Claude'a verilsin; Claude inceledikten sonra "al" diyorsa ve giriş, stop, hedef
seviyelerini belirliyorsa bu dikkate alınsın. Sahibin gerekçesi: LLM'in birden çok bilgiyi birlikte değerlendirme
yeteneği tek tek indikatör sinyalinden daha değerli olabilir. Bu bir hipotezdir; LLM'in kısa vadeli fiyat tahmininde
indikatörlerden iyi olduğu bilinmiyor ve ikna edici gerekçe isabet demek değildir.

## Decision
ADR 0003'ün ilke 2 ve 5'i **yalnız paper aşamasında** gevşer: Claude, sabit bir coin listesinde saatte bir, teknik
özet ve haber skorlarıyla şemalı bir karar verir (her coin için `al` / `bekle`, giriş bölgesi, stop, hedef, geçerlilik
süresi, verilere dayanan gerekçe); ayrı bir paper defteri bu kararları risk modülünün onayından geçirerek uygular ve
sonuç, önceden yazılmış ölçütlerle S0 ve rastgele girişle karşılaştırılır. Live'da ADR 0003'ün ilkeleri aynen
geçerlidir; LLM kararının live'a geçmesi bu ölçümün olumlu sonucunu, BR-10'u ve ayrı bir ADR'yi ister.

Kurallar:
1. **Liste ve sıklık (ön kayıt):** BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK, TON (USDT spot); saatte bir tur, 1h
   mum. Liste ve sıklık ölçüm süresince değişmez; değişiklik yeni ön kayıttır.
2. **Tek çağrı:** Bir turda bütün liste tek Claude çağrısında değerlendirilir (günde 24 çağrı; 0051'in günlük sınırı ve
   yalıtımı aynen).
3. **Veriye dayanma:** Gerekçe yalnız verilen teknik özet ve haber skorlarına dayanır; seviyeler verilen fiyat
   aralığında olmalı, şemaya uymayan ya da tutarsız karar (stop girişin üstünde, hedef altında gibi) atılır.
4. **Risk modülü değişmez:** Her LLM kararı bugünkü risk kurallarından (işlem başına risk, günlük zarar, drawdown,
   maliyet katı, açık pozisyon sınırı) geçer; LLM limitleri, modu ya da beyaz listeyi değiştiremez.
5. **Ayrı defter:** LLM kararları kendi paper deposunda; ADR 0004'ün S0 koşusu ayrı kalır ve kıyas çizgisi olur.
6. **Ölçüm (ön kayıt, spec'te sayılarla):** başarı ölçütü (süre, en az işlem sayısı, maliyetlerden sonra kâr, kâr
   faktörü, drawdown, rastgele girişe karşı fark) ölçüm başlamadan spec'e yazılır ve sonradan gevşetilmez.
7. **Bilgi kesimi:** Claude'un eğitim kesiminden önceki dönemle yapılan ölçüm hüküm sayılmaz (ADR 0003 ilke 3);
   ölçüm ileriye dönüktür.

## Consequences
- Kazanılan: sahibin hipotezi (LLM'in bütüncül değerlendirmesi) gerçek, görülmemiş veride ve para riski olmadan
  sınanır; seviye tabanlı (giriş/stop/hedef) karar yapısı kurulur; 10 likit coin gölge filtreden daha çok sinyal üretir.
- Bedeli: iki yeni spec (teknik özet + karar çağrısı; LLM defteri + karşılaştırma raporu) ve bakım; günde 24 çağrılık
  kota (etkileşimli kullanımla ortak); LLM kararları belirlenimli değildir (aynı girdiye farklı karar) — ölçüm bunu
  kapsamalıdır. LLM'in yanlış ama ikna edici kararları paper'da zarar üretebilir; amaç tam olarak bunu ölçmektir.
- ADR 0003'ün ilke 2 ve 5'i paper'da artık geçerli değildir; `docs/domain.md`'deki "LLM çıktısı hiçbir zaman doğrudan
  emir tetiklemez" kuralı live için kalır, paper istisnası yazılır.

## Alternatives considered
- **ADR 0003'ü korumak, yalnız 0053'ün ileriye dönük ölçümünü beklemek:** LLM yalnız fren olarak ölçülür; sahibin
  hipotezi (LLM al kararı) hiç sınanmaz ve live'a giden yol teknik bir adaya bağlı kalır, o da yok.
- **LLM kararını doğrudan live'da denemek:** kanıtsız para riski; BR-10 ve ADR 0003 ilke 3 ile çelişir.
- **Coin başına ayrı çağrı, yarım saatte bir:** günde 480 çağrı, sınırın (200) ve aboneliğin üstünde; tek çağrıda
  liste aynı bilgiyi verir.
- **Teknik indikatör ayarlarını yeniden aramak:** 0045 sonrası sahip kararıyla reddedildi (gözetleme).

## Revisit triggers
- Ölçüm süresi dolduğunda (spec'teki ön kayıtlı hüküm): olumluysa live için ayrı ADR; olumsuzsa LLM karar modu durur.
- Kota ya da abonelik kullanılamaz hale gelirse; Claude modeli değişirse (yeni üçlü, ölçüm yeniden başlar — 0053 gibi).
- LLM kararlarının şema dışı ya da tutarsız oranı yüksekse (spec'te eşik).
