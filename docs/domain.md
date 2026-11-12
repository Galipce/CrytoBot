# Domain

> Bootstrap: 2026-10-29. Ortak dil — kodda, spec'lerde ve sohbette aynı kelime aynı anlama gelir.

## Ubiquitous language

| Term | Meaning | Notes / not to be confused with |
|---|---|---|
| Kasa (equity) | Hesaptaki toplam değer: USDT bakiyesi + açık pozisyonların piyasa değeri | Serbest bakiye değil |
| Serbest bakiye | Yeni emir için kullanılabilir USDT | Kasa değil |
| Çift (pair) | `BASE/USDT` sembolü, ör. `BTC/USDT` | Yalnızca beyaz listedekiler işlem görür |
| Beyaz liste | Config'teki, işlem yapılabilir likit USDT çiftleri (ilk 20–30) | Değişikliği insan onaylar |
| Sinyal | Bir kaynağın (teknik, haber, whitepaper) ürettiği yön + güç skoru | Emir değil |
| Araştırma skoru | `research`'ün whitepaper/proje için ürettiği, kaynak alıntılı, şemalı skor | Asla doğrudan emir üretmez |
| Haber skoru | `news`'in bir haber için ürettiği etki/yön skoru | Güvenilmeyen girdiden türetilir |
| İşlem önerisi (trade intent) | `strategy`'nin sinyallerden ürettiği "şunu, şu stop ile al/sat" önerisi | Risk onayı olmadan emir değildir |
| Onaylı emir | `risk`'in onayladığı, hassasiyete yuvarlanmış emir | Yalnızca `execution` gönderir |
| Stop-loss | Pozisyonun zararla kapanacağı fiyat | Her pozisyonda zorunlu |
| İşlem riski | Stop'a gelinirse kaybedilecek tutar ÷ kasa | Pozisyon büyüklüğü değil |
| Günlük zarar limiti | Gün içinde (UTC) gerçekleşen + açık zarar ÷ gün başı kasa | Aşılınca o gün yeni işlem yok |
| Drawdown | Kasanın en yüksek değerden düşüşü (%) | Limit aşılınca bot durur, insan açar |
| Efektif maliyet | Komisyon + spread + tahmini slippage | Yalnızca komisyon değil |
| Mod | `backtest` · `paper` · `live` — aynı strateji kodu, farklı `execution` adaptörü | Varsayılan `paper` |
| Aşama (stage) | backtest → paper → live (küçük sermaye) → live; her geçiş insan onaylı | |
| Kill switch | Tüm yeni işlemleri durduran acil anahtar | CLI veya Telegram |
| Günlük hedef | Günlük kâr % (hedef %20–25) — **ölçülen metrik, karar kuralı değil** | Bkz. BR-1 |

## Business rules

- BR-1: Günlük kâr hedefi yalnızca raporlanan bir metriktir. Hedefe ulaşılmaması pozisyon büyüklüğünü, kaldıracı veya işlem sıklığını **asla** artırmaz. Opsiyonel: hedefe ulaşılınca gün kapatılabilir (config).
- BR-2: Yalnızca spot, kaldıraçsız işlem; yalnızca beyaz listedeki USDT çiftleri.
- BR-3: Her pozisyon açılırken bir stop-loss taşır; stop'suz işlem önerisi reddedilir.
- BR-4: İşlem başına risk ≤ %1 kasa (config; kodda sabit üst sınır %2).
- BR-5: Günlük zarar limiti %3 (config; sabit üst sınır %5). Aşılınca o UTC günü yeni pozisyon açılmaz.
- BR-6: Drawdown %15 (config; sabit üst sınır %25). Aşılınca bot tüm yeni işlemleri durdurur; yalnızca insan yeniden başlatır.
- BR-7: Aynı anda en fazla 5 açık pozisyon (config; sabit üst sınır 8).
- BR-8: Beklenen kâr, efektif maliyetin (komisyon + spread + slippage) config'teki katını geçmiyorsa işlem açılmaz (varsayılan kat 2; sabit alt sınır 1).
- BR-9: Her işlem önerisi `risk` onayından geçer; onaysız hiçbir emir borsaya gitmez.
- BR-10: Aşama geçişi (backtest→paper→live) metrik eşiği + insan onayı ister; strateji paper'a ancak komisyon/slippage dahil out-of-sample backtest sonucu ile geçer.
  Paper→live (spec 0038): `start --live`, `[stage] paper_store_path`'teki paper kanıt deposunu salt okunur denetler. Her paper başlatması depoya yalnız eklenen bir başlatma kaydı yazar (kanıtlı: onaylı raporun mutlak yolu; `--trial`: deneme). Kanıt sayılmaz: deneme kaydı olan, hiç kaydı olmayan (0038 öncesi açılmış), ilk kayıttan önce tur/emir/durum yazımı olan (ilk başlatmadan önce `kill-switch`/`resume` çalıştırılmış depo dahil — fail-closed) ya da başka bir rapora bağlı depo. Eşikler (ilk kanıtlı başlatmadan son tura, bayat veri turları dahil): (a) en az `paper_min_days` × 24 saat (vars. 14, alt sınır 7); (b) en az `paper_min_trades` tamamen kapanmış işlem (vars. 10, alt sınır 5); (c) komisyon dahil gerçekleşen net > 0; (d) gerçekleşen kasa eğrisinin en büyük düşüşü ≤ min(`risk.max_drawdown`, %25). Açık pozisyonun gerçekleşmemiş sonucu eşiğe girmez. Onay sırası: `stage.live_approved_at` son paper turundan sonra ve şimdiden önce (ya da eşit). Sıra: ayar ve rapor kapıları → paper kanıtı → depo ağı → kimlik/yetki; testnet'te aynıdır, ret borsaya istek göndermez.
  Testnet (spec 0041): yalnız live modda (`[exchange] testnet = true`; paper modda ayar reddi). Bir koşu tek ağdadır: okumalar (piyasa listesi, mum, son fiyat), bakiye ve emirler aynı ağdan; mainnet'e geri dönüş yoktur. Canlı depo açıldığı ağa bağlıdır (meta `network`); başka ağla açılmaz, ağ kaydı olmayan depo `mainnet`'tir. İstisna (plan 0041 A-2): depo kilitten önce salt okunur okunamazsa (ör. öldürülmüş sürecin sıcak günlüğü) ağ kilit altında, kimlik/yetkiden sonra ama ilk turdan ve depo yazımından önce denetlenir; o istek yalnız ayardaki ağa gider. Testnet hiçbir aşama, rapor ya da paper kanıtı kapısını atlatmaz; backtest ve geçmiş veri her zaman mainnet'tir.
  Rapor bütünlüğü (spec 0040): onay, raporun ham baytlarının SHA-256 parmak izine bağlıdır (`[stage] report_sha256`, `backtest` konsolundaki `rapor parmak izi:` satırı); rapor başlığı üretim anını ve koşulları (`fee`, `slippage`, `per_trade_risk`, `daily_loss_limit`, `max_drawdown`, `max_open_positions`, `profit_cost_multiple`, `opening_balance`) taşır. Kapı: tek bayt farkı reddedilir; `approved_at` üretim anından önce ya da şimdiden sonra olamaz; her koşul ve `[backtest] spread` çalışan ayarla sayısal değerce eşit olmalıdır; rapordaki ya da ayardaki eksik bilgi denetimi geçirmez, reddeder. Kanıtlı paper başlatma kaydı parmak izini taşır; parmak izi olmayan (eski) ya da farklı parmak izli kayıt canlı geçiş kanıtı değildir (`rapor uyuşmazlığı`). Ret depoya yazmaz, borsaya istek göndermez.
- BR-11: Durum belirsizse (emir durumu bilinmiyor, bakiye mutabakatı tutmuyor, veri bayat) bot yeni işlem açmaz, güvenli tarafa geçer ve bildirim gönderir.
- BR-12: Borsa seçimi efektif maliyet ölçümüyle yapılır; ücretler config'te tutulur, kodda değil.
- BR-13: Risk limitleri Telegram'dan yalnızca sıkılaştırılabilir; gevşetme yalnızca CLI'den yapılır (oran ve pozisyon limitlerinde sıkılaştırmak düşürmek, kâr/maliyet katında yükseltmektir).

## Key domain invariants

- Hiçbir kod yolu kodda sabitlenmiş risk üst sınırlarını aşamaz (config ne derse desin).
- LLM çıktısı (haber/whitepaper) hiçbir zaman doğrudan emir, limit veya mod değişikliği tetiklemez.
- Strateji kodu backtest, paper ve live'da aynıdır; yalnızca `execution` adaptörü değişir.
- Defter (ledger) kayıtları silinmez/değiştirilmez; düzeltme yeni kayıtla yapılır.
- Para çekme (withdrawal) hiçbir kod yolunda yoktur.
- **Borsa şartlı stop emri (live, spec 0034):** Canlı modda bir alım dolunca borsaya `cs-<alım id>` kimlikli şartlı stop emri verilir. Kapanıştan önce borsa stopunun iptali teyit edilir; tur başında borsada dolmuş stop deftere işlenerek senkronize edilir. Koruma her canlı turda durumdan türer: borsada hiç olmayan stop yeniden verilir; iptal edilmiş, reddedilmiş, durumu belirsiz ya da kısmen dolmuş stop yeni alımı durdurur (fail-closed, `BuyHalt.STOP_ORDER_FAILED`) ve pozisyona özgü `STOP_ORDER_FAILED` bildirimi üretir (güvenli mod `SAFE_MODE` bildiriminden ayrı).
- **Canlı dolum (live, spec 0036):** Canlı defter paper tahminini değil borsanın gerçek dolumunu yazar: maliyet/satış fiyatı = ödenen USDT / dolan miktar (28 basamağa, alımda aşağı, satışta yukarı), ücret = defterin bakiyeden düştüğü ya da eklediği tutar borsadakiyle birebir aynı olacak fark. Komisyon alınan coinden kesildiyse pozisyon **net miktardır** (dolan − coin komisyonu, miktar adımına aşağı); adımın altındaki **toz** yalnız emir kaydında durur, satılmaz, kasaya katılmaz. Satış ve borsa stopu net miktarla verilir; net miktar asgarinin altındaysa pozisyon kaydedilir ama alım durur (`POSITION_BELOW_MINIMUM`). İki varlıktan ya da satışta coinden kesilen komisyon, komisyondan sonra net miktarı sıfır olan dolum ve komisyonu, ortalama fiyatı ya da dolan miktarı bildirilmeyen dolum deftere yazılmaz: emir `UNKNOWN` kalır (BR-11; desteklenmeyen dolumda `UNSUPPORTED_FILL` bildirimi). Kısmi dolum ve üçüncü varlıktan komisyon spec 0037'den beri yazılır (aşağıda); 0036'nın bunlar için geçici güvenli modu kalktı. Yalnız kesin ret (yetersiz bakiye, geçersiz emir/filtre, yetki) `REJECTED` sayılır; ağ, zaman aşımı, bakım, hız sınırı ve tanınmayan hata `UNKNOWN`'dır. Borsanın "böyle emir yok" yanıtı alım/kapanışı yalnız verilişten 5 dakika sonra ve önceki turda da aynı yanıt alındıysa reddeder (gözlem süreç belleğinde; yeniden başlatma sayımı sıfırlar; `cs-` stoplar bu kurala girmez). D-1: durumu bilinmeyen canlı emir netleşince gerçek dolum yazılır (paper'da kayıtlı tahmin, spec 0011 R-8). Gerçek dolum bilgisi taşımayan eski canlı depo adıyla reddedilir (`prepare --live` ile yeniden açılır).
- **Kısmi dolum ve kısmi kapanış (live, spec 0037, D-2):** Kalanı borsada sona eren (ya da iptal edilen) emrin dolan kısmı gerçek dolumdur; "doldu" denen emirde dolan < emir tutarsızlıktır (`UNKNOWN`). Kısmen dolan alımın net miktarı pozisyon olur, borsa stopu bu miktarla verilir, `PARTIAL_FILL` bildirimi bir kez gider; net miktar asgari miktarın ya da asgari tutarın altındaysa alım aynı turda durur (`POSITION_BELOW_MINIMUM`; tam asgari değer durdurmaz). Kısmen dolan kapanış satışı yalnız canlıda **kısmi kapanış**tır: spec 0008 R-4'ün "yalnız tam kapanış" kuralı paper ve backtest'te sürer. Kapanan kısmın maliyeti miktarla **orantılıdır**: kısım / miktar × (miktar × maliyet fiyatı + alım ücreti); ücret payı, kısmın tutarı ile ücretin büyüğünün en büyük basamağından itibaren 28 basamağa ROUND_HALF_EVEN yuvarlanır, kalan pozisyonun ücreti `ücret − pay`'dır. Böylece parçaların maliyet toplamı tam kapanışın maliyetine birebir eşittir; maliyet fiyatı değişmez. Kalan pozisyon aynı kimlikle açık kalır, borsa stopu kalan miktarla hemen yeniden verilir ve sonraki turda yeniden değerlendirilir. Kapanış ve stop kimliğinin **nesli** pozisyonun kısmi kapanış sayısıdır: 0 → `cx-`/`cs-`, n → `cx{n+1}-`/`cs{n+1}-` (36 karakter sınırı yüzünden en çok `cx9-`); nesil kalmazsa kapanış reddedilir, stop verilemez, alım durur, "elle bakılmalı" bildirimi gider. Borsa stopunun kısmi dolumu bu spec'te desteklenmez (`stop_failed`, B-73).
- **Üçüncü varlıktan komisyon (live, spec 0037, D-4):** Komisyon USDT ya da alınan coin dışında bir varlıktan (ör. BNB) kesildiyse pozisyon miktarı dolan miktardır; komisyon kendi varlığıyla emir kaydında durur. USDT değeri o turda ek olarak okunan `<varlık>/USDT` son fiyatıyla (beyaz liste dışında da) hesaplanır ve ücrete girer; fiyat okunamazsa ya da çift borsada yoksa dolan × fiyat × ayardaki ücret oranıyla **tahmin** edilir, emir "tahmini" işaretini taşır, `ESTIMATED_FEE` bildirimi bir kez gider; güvenli mod devreye girmez. Defter bu değeri USDT bakiyesinden düşer, borsa ise o varlıktan keser: USDT mutabakatı beklenen bakiyeyi defter + dolan emirlerdeki üçüncü varlık komisyonlarının USDT değeri olarak alır (tolerans 0,05 USDT, spec 0033).
- **Coin mutabakatı (live, spec 0037 R-5, A-15):** Canlı tur başında, açık pozisyonu olan her coinde borsadaki toplam coin (serbest + borsa emrinde bekleyen) o coindeki bütün açık pozisyonların net toplamından bir miktar adımından fazla azsa yeni alım durur (`COIN_SHORTFALL`), kapanışlar sürer, çift adıyla bildirim gider; koşul düzelince durdurma kalkar ve çıkış bildirimi gider. Fazla coin (sahibin bottan bağımsız varlığı, toz) yok sayılır. Coin sorgusu USDT sorgusundan sonra, yalnız açık pozisyon varken yapılır; başarısızsa güvenli mod (`BALANCE_CHECK_FAILED`, G-8).

## Sensitive areas

- **Emir gönderimi** (`execution`) — yanlış emir = doğrudan para kaybı.
- **Risk limitleri** (`risk`) — limit hatası = kontrolsüz kayıp.
- **API anahtarları / sırlar** — sızıntı = hesap ele geçirme.
- **Paper ↔ live mod anahtarı** — yanlış mod = sanal sanılan gerçek işlem.
- **Telegram komut yetkilendirmesi** (chat ID, TOTP, teyit) — yetkisiz kontrol.
- **Portföy / defter** (`portfolio`) — yanlış bakiye/kâr-zarar = yanlış risk hesabı.
- **Kalıcı durum** (`persistence`) — kaybolan ya da bozuk okunan durum = silinmiş durdurma, yanlış bakiye.
