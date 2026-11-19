# ADR 0004 — İleriye dönük paper koşusu: S0, 90 gün, ön kayıtlı, gölge filtre açık

- Status: Accepted
- Date: 2026-11-19

## Context
Spec 0044'te sekiz teknik aday (S0…S3, 1h ve 4h) maliyetlerden sonra kâr etmedi; spec 0045'te 40 indikatör ayarından
hiçbiri görülmemiş dönemde rastgele girişi eşik kadar geçmedi (en iyisi +2,47 puan, eşik +5). Sahip 2026-11-15'te aynı
veride yeniden ayar ya da aday aramayı veri gözetleme olarak reddetti; ADR 0003 ile LLM fazı live'dan önceye alındı.
LLM hattı 2026-11-19'da ileriye dönük çalışmaya başladı (0046 toplayıcı, 0051 skorlayıcı, 0053 ölçüm, 0056 resmi
Binance duyuru akışı), ama 0052'nin gölge filtre kaydı yalnız paper bot turlarında tutulur ve paper bot hiç
başlatılmadı. Geçmiş veride yeni bir şey denemek gözetleme olacağından teknik taraftaki tek temiz bilgi kaynağı
ileriye dönük, görülmemiş veridir. Aşama onayı (`[stage]`, Galip Badem, 2026-11-12) S0'ın bugünkü ayarı için vardır.

## Decision
Bugünkü S0 (EMA 12/26, RSI 14 eşik 70, ATR 14, k 2, r 2; 4h mum ve tur; BTC/USDT ve ETH/USDT; bugünkü risk ayarları;
100 USDT paper bakiye) paper modda, kanıtlı başlatmayla (`start`) ve gölge filtre kaydı (`[shadow]`) açık olarak
2026-11-19'dan en az 2027-02-17'ye kadar (90 gün) koşar; bu sürede strateji ve ayar değişmez, sonuç 90 günün sonunda
rapor olarak yazılır ve live kararı vermez.

Ön kayıt kuralları:
1. Aday ve ayarlar yukarıdaki gibidir; seçim geçmiş veriye bakılarak değiştirilmez. Botun durup yeniden başlaması
   serbesttir; durduğu süre raporda gösterilir, süre uzatılmaz ya da kısaltılmaz.
2. Gölge filtre (spec 0052) skorları ve haberleri sahip makinesindeki ileriye dönük kayıtlardan okur; skorlar hiçbir
   kararın girdisi değildir (ADR 0003 ilke 5).
3. 90 gün sonunda yazılacak rapor: işlem sayısı ve sonuçları (kâr faktörü, drawdown, maliyetler), teknik "al"ların
   gölge filtre durumu (bastırılırdı / bastırılmazdı / eksik bilgi / filtre yok) ve bastırılanların sonraki seyri
   (0053 R-7). Rapor bir hüküm değil, kayıttır.
4. Paper'dan live'a geçiş bu ADR'nin konusu değildir: BR-10'un kendi kapısı, ADR 0003'ün LLM ölçüm hükmü ve sahibin
   onayı gerekir.

## Consequences
- Kazanılan: görülmemiş veride S0'ın gerçek davranışı; 0053 raporunun gölge bölümü dolar (her teknik "al" için haberin
  ne diyeceği); paper hattı (turlar, Telegram bildirimleri, kill switch) uçtan uca, gerçek zamanda sınanır.
- Bedeli: 4h S0 90 günde yaklaşık 15 işlem yapar (2026 örneklem içinde 6 ayda 29); kârlılık hakkında istatistiksel
  olarak zayıf bir sonuçtur. S0 geçmişte zararlıydı; paper olduğu için para riski yoktur. Bot sahip makinesinde koşar;
  bilgisayar uyurken turlar kaçar.
- Koşu sırasında strateji iyileştirmesi yapılamaz; yeni bir aday ancak bu koşu bittikten sonra ve ayrı bir ön kayıtla
  denenebilir.

## Alternatives considered
- **Hiçbir şey başlatmamak, yalnız haber hattının birikmesini beklemek:** gölge filtre kaydı hiç dolmaz; 0053'ün R-7
  bölümü boş kalır ve S0'ın ileriye dönük davranışı görülmez.
- **S1/S2/S3'ten "en iyi görüneni" seçmek:** seçim 0044/0045'in geçmiş verisine bakarak yapılmış olur (gözetleme);
  ayrıca aşama onayı yalnız S0 için var.
- **Birden çok adayı aynı anda paper'da koşmak:** bot tek strateji ve tek depoyla çalışır; çoklu koşu yeni kod ister ve
  çoklu karşılaştırma sorununu (en iyi görüneni sonradan seçmek) geri getirir.
- **`start --trial` ile başlatmak:** BR-10 kapısını atlar; mevcut aşama onayı S0 için geçerli olduğundan kanıtlı
  başlatma kullanılabilir.

## Revisit triggers
- Bot 90 gün dolmadan sürekli çalışamıyorsa (makine, uyku): koşunun bir sunucuya taşınması ayrı karar olarak açılır.
- S0'ın drawdown durdurması (%15) tetiklenirse: koşu kayda geçer ve durur; yeniden başlatma ayrı karar.
- LLM ölçümü (0053) olumlu hükme varırsa ya da teknik tarafta yeni bir ön kayıtlı aday önerilirse.
