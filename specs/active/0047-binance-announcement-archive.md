# Spec 0047 — Binance duyuru arşivi (geçmiş)

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0047-plan.md`
- Self-critique: done
- Source: ADR 0003 (sıranın ikinci işi: geçmiş olaylardan örnek kütüphanesi ve kalibrasyon); spec 0046 S1 (0046
  ileriye dönük toplama, 0047 geçmiş arşiv)

## Intent
Botun sahibi, LLM'in olay skorunu ileride kalibre edebilmek için geçmiş Binance duyurularının zaman damgalı bir
arşivini istiyor (ADR 0003 ilke 4: listeleme, listeden çıkarma, bakım, haber gibi olaylar; sonradan gerçek fiyat
sonucuyla eşleşecek benzer örnekler). Arşiv, Binance'in duyuru listesinin bütün kataloglarında ulaşılabilen en eski
duyuruya kadar doldurulur; yeniden çalıştırılınca yalnız eksikleri ekler, yarıda kalırsa kaldığı yerden sürer.
Başarı: her geçmiş duyuru kaynağı, kategorisi ve kaynağın bildirdiği yayın anıyla bir kez kayıtlıdır; arşivin ne
kadarının dolu olduğu görünürdür; arşiv kayıtları ileriye dönük toplamadan (0046) açıkça ayrıdır ve hiçbir ölçüm
onları "o anda biliniyordu" diye kullanamaz. Bilerek yapılmayanlar: diğer sitelerin geçmişi, duyuru metninin
indirilmesi (yalnız başlık, canlı toplamayla aynı girdi biçimi), coin eşlemesi, olay türü, fiyat sonucuyla eşleştirme
(örnek kütüphanesi ve kalibrasyon tablosu sonraki spec), LLM ve habere dayalı her türlü işlem kararı. Clarify
kararları Q1–Q7 ve self-critique kararları G-1…G-8 Galip Badem, 2026-11-15 tarihinde onayladı.

Terimler:
- **Arşiv:** geçmiş duyuruların, ileriye dönük haber kaydından (0046) ayrı tutulan kaydı.
- **Katalog:** Binance duyuru listesinin bir kategorisi (ör. yeni listeleme, listeden çıkarma, son haberler, bakım);
  Binance her kataloğun adını ve toplam duyuru sayısını bildirir.
- **Arşiv kaydı:** tek duyuru: kaynak (Binance duyuruları), katalog adı, Binance duyuru kimliği, bağlantı, başlık,
  yayın anı (UTC) ve arşive alındığı an (UTC). İlk görme anı taşımaz.
- **Arşive alınma anı:** duyuruyu taşıyan yanıtın alındığı an. Duyurunun bilindiği anı değil, arşivin indirildiği
  anı gösterir.
- **Katalog tamam:** kataloğun en eski sayfasına hatasız ulaşılmıştır. Binance'in bildirdiği toplam yalnız bilgidir:
  bir duyuru birden çok katalogda görünebilir ya da Binance duyuru silebilir; arşivdeki sayıyla fark gösterilir, koşul
  değildir (G-1).

## Requirements
- R-1 — Ayrı bir CLI komutu arşivi doldurur: her katalog için en yeni duyurudan en eskiye doğru okur ve arşivde
  olmayan duyuruları yazar. Komut işlem döngüsünden ve ileriye dönük toplayıcıdan bağımsızdır: bot durumunu, defteri,
  emirleri, riski, paper/live deposunu ve ileriye dönük haber kaydını değiştirmez; ikisi çalışırken de çalışabilir.
- R-2 — Her arşiv kaydı Terimler'deki alanları taşır ve "arşivden" işaretlidir. Yayın anı yoksa ya da okunamıyorsa
  kayıt yine yazılır, yayın anı "bilinmiyor" olur; arşive alınma anından 5 dakikadan daha ileri bir yayın anı da
  "bilinmiyor" sayılır (0046 R-4'ün kuralı, G-4). Arşiv kaydı hiçbir durumda ilk görme anı taşımaz; arşive alınma
  anı ilk görme anı yerine kullanılamaz.
- R-3 — Aynı Binance duyuru kimliği arşivde bir kez bulunur; tekrar gelirse (başka bir katalogda da) yazılmaz ve
  ilk yazılan sürüm, kataloğuyla birlikte kalır (G-1).
  Arşiv yalnız eklenerek büyür: mevcut kayıt silinmez ve değiştirilmez. Bu kural yeniden çalıştırmalar boyunca
  geçerlidir.
- R-4 — Komut durdurulursa (Ctrl+C) ya da bir hatayla kesilirse yazılmış kayıtlar kalır, yarım kayıt kalmaz; sonraki
  çalıştırma tamamlanmamış kataloglarda kaldığı yerden sürer ve baştan başlamaz. Okuma sürerken gelen yeni duyurular
  sayfa sınırlarını kaydırabilir; bu yalnız tekrara yol açar, kayba yol açmaz (G-2). Tamam olan katalog yeniden
  çalıştırmada en yeniden geriye okunur ve arşivde zaten bulunan bir kimliğe ulaşınca durur.
- R-5 — Kaynağa nazik davranılır: aynı anda tek istek, iki istek arasında en az `archive_request_gap_s` saniye
  (vars. 1, en az 1), kişisel bilgi taşımayan genel bir istemci adı. Bir istek en çok 30 saniye sürebilir (ad
  çözümleme dahil). Kaynak hata verirse (ağ hatası, zaman aşımı, HTTP hata cevabı, hız sınırı, beklenmeyen yanıt)
  komut o hatayla durur, yazılmışlar kalır; kaynağa ısrarla tekrar istek gönderilmez.
- R-6 — Yanıtlar güvenilmeyen girdidir; 0046 R-5'in kuralları aynen geçerlidir: yalnız `https`, yanıt boyutu ve türü
  sınırlı, şemaya uymayan yanıt hatadır, bağlantılar izlenmez (duyuru sayfası indirilmez), başlık olduğu gibi
  saklanır ve hiçbir biçimde çalıştırılmaz. Başlık 20 KB UTF-8 bayttan uzunsa 0046'nın kuralıyla kesilir ve kayıt
  "kesildi" işaretini taşır (G-6). Başlığı boş ya da kimliği olmayan duyuru yazılmaz, geçersiz sayılır.
- R-7 — Komut her katalog için bir özet satırı yazar (konsol ve log): yeni, tekrar, geçersiz sayısı, ulaşılan en eski
  yayın anı ve kataloğun tamam olup olmadığı; en sonda tüm arşiv için tamam ya da eksik satırı. Hatayla durulursa
  satır hatanın adını taşır. Kayıtta ve satırlarda sır ya da yetki bilgisi yoktur. Çıkış kodu: 0 arşiv tamam, 4
  durdurma isteğiyle (Ctrl+C) durdu, 1 ret ya da kaynak hatası, 130 zorla durma (ikinci Ctrl+C) (G-3). Telegram
  bildirimi gitmez (G-8).
- R-8 — Ayrı bir durum komutu ağa çıkmadan, her katalog için kayıt sayısını, Binance'in son çalıştırmada bildirdiği
  toplamı ve arşivdeki sayıyla farkını, en eski ve en yeni yayın anını, tamam/eksik bilgisini ve son çalıştırmanın
  anını gösterir; ayrıca arşivin toplam boyutunu ve ileriye dönük haber kaydında da bulunan arşiv duyurusu sayısını
  (örtüşme: aynı Binance kimliği ileriye dönük kayıtta `binance-duyuru` türündeki herhangi bir kaynakta; ileriye dönük
  kayıt yoksa "ileriye dönük kayıt yok", G-5). Arşiv boşken bunu söyler ve hata vermez.
- R-9 — Ayarlar config'tedir (haber ayar dosyası); kaynağın adresi ayardadır, katalog listesi ayarda ya da kodda
  sabit değildir, yanıttan okunur: sonradan eklenen bir katalog kendiliğinden okunur (G-7). Arşiv kaydı ileriye dönük haber kaydından, bot deposundan ve
  kayıt dosyalarından ayrı bir yerdedir, bunlardan biri olarak ayarlanırsa komut başlamayı reddeder.

## User experience
none — no user interface (yalnız CLI komutları ve konsol/log satırları).

## Constraints & out of scope
- Yeni çalışma bağımlılığı eklenmez; onaylı tek çalışma bağımlılığı `ccxt` kalır (spec 0018).
- `scripts/check` ağa çıkmaz; kaynak yanıtları kayıtlı örneklerle sınanır (`docs/testing.md`).
- Binance duyuru listesinin ucu belgelenmiş değildir ve değişebilir; değişirse kaynak hatası olur, sessiz boşluk
  oluşmaz. Bugünkü gözlem (2026-11-15): yedi katalog, toplam yaklaşık 11.200 duyuru, en eskisi 2017-07.
- Sensitive area: yok. Emir, risk, sır, mod ve defterle ilgisi yoktur; arşiv kendi kaydıdır.
- Out of scope: Telegram bildirimi (G-8); diğer kaynakların geçmişi (RSS geçmiş tutmaz, ücretli arşivler); duyuru metni ya da sayfası; coin
  eşlemesi ve olay türü; fiyat sonucuyla eşleştirme, örnek kütüphanesi ve kalibrasyon tablosu (sonraki spec);
  LLM çağrısı; ileriye dönük haber kaydının değiştirilmesi ya da arşivle birleştirilmesi; arşivin otomatik ya da
  zamanlanmış yenilenmesi; kayıtların silinmesi ya da saklama süresi.

## Acceptance criteria
- [ ] AC-1 — İki ya da daha fazla katalogdan, birkaç sayfa süren kayıtlı yanıtlarla tam bir çalıştırma her duyuruyu
  bir kez yazar; her kayıtta kaynak, katalog adı, kimlik, bağlantı, başlık, UTC yayın anı, UTC arşive alınma anı ve
  "arşivden" işareti bulunur, ilk görme anı bulunmaz. Kataloglar yanıttan okunur, her biri en eski sayfaya kadar
  okunur ve tamam olarak işaretlenir; çıkış 0 (R-1, R-2, R-9).
- [ ] AC-2 — Yayın anı eksik, okunamayan ya da arşive alınma anından 5 dakikadan daha ileri olan duyuru "yayın anı
  bilinmiyor" işaretiyle yazılır; tam 5 dakika ileri işaretlenmez. Başlığı boş ya da kimliği olmayan duyuru yazılmaz,
  geçersiz sayılır. 20 KB'ı aşan başlık kesilir ve "kesildi" işaretini taşır (R-2, R-6).
- [ ] AC-3 — Aynı kimlik ikinci kez (aynı çalıştırmada başka sayfada ya da katalogda, ya da sonraki çalıştırmada)
  gelirse yazılmaz;
  ilk sürümün başlığı, kataloğu ve arşive alınma anı değişmez. Arşivde kayıt değiştirme ve silme reddedilir (R-3).
- [ ] AC-4 — Çalıştırma bir sayfanın ortasında durdurulursa (Ctrl+C) ya da kaynak hatasıyla kesilirse yazılmış
  kayıtlar kalır, yarım kayıt kalmaz; sonraki çalıştırma kaldığı sayfadan sürer, önceden okunan sayfaları yeniden
  istemez; Ctrl+C ile durmada çıkış 4, ikinci Ctrl+C'de 130. Okuma sırasında başa yeni duyuru eklenmesi (sayfa
  kayması) hiçbir duyuruyu atlatmaz. Tamam kataloglu yeniden çalıştırma en yeniden başlar, arşivde bulunan bir kimliğe
  ulaşınca o kataloğu bırakır ve yalnız yeni duyuruları yazar (R-4).
- [ ] AC-5 — İki istek arasında en az `archive_request_gap_s` saniye geçer ve aynı anda tek istek vardır; takılan bir
  istek (ad çözümleme dahil) en çok 30 saniyede (ölçüm payıyla) hata olur. Ağ hatası, zaman aşımı, HTTP hata cevabı,
  hız sınırı (429) ya da şemaya uymayan yanıtta komut hatanın adını veren satırla, çıkış 1 ile durur, aynı isteği
  yinelemez. Telegram bildirimi gitmez (R-5, R-7).
- [ ] AC-6 — 0046 R-5'in kaynak kuralları geçerlidir: `http`'ye düşen ya da 3'ten fazla yönlendirme, sınırı aşan ya da
  beklenmeyen türdeki yanıt, bozuk JSON kaynak hatasıdır; duyuru bağlantılarına istek gitmez; başlık olduğu gibi
  saklanır (R-6).
- [ ] AC-7 — Özet satırları her katalog için doğru yeni/tekrar/geçersiz sayısını, en eski yayın anını ve tamam/eksik
  bilgisini, en sonda tüm arşivin tamam ya da eksik olduğunu gösterir; kayıtta ve satırlarda sır yoktur (R-7).
- [ ] AC-8 — Durum komutu ağa istek göndermeden her katalog için kayıt sayısını, son bildirilen toplamı ve farkı, en
  eski ve en yeni yayın anını, tamam/eksik bilgisini ve son çalıştırma anını; arşivin toplam boyutunu ve ileriye dönük
  haber kaydıyla örtüşen duyuru sayısını (ileriye dönük kayıt yoksa bunu) gösterir. Boş arşivde bunu söyler ve 0
  koduyla çıkar (R-8).
- [ ] AC-9 — Komut çalışırken paper botunun bir turu ve ileriye dönük toplayıcının bir turu, komut hiç yokmuş gibi
  aynı sonucu verir; komut bot deposuna ve ileriye dönük haber kaydına yazmaz. Aynı arşive ikinci bir arşiv komutu
  açılmak istenirse anlaşılır bir mesajla reddedilir (R-1).
- [ ] AC-10 — Geçersiz ayarda (arşiv kaydının yeri yok ya da ileriye dönük haber kaydı, bot deposu veya bir kayıt
  dosyasıyla aynı; `archive_request_gap_s` 1'den küçük; adres yok ya da `https` değil) komut ağa çıkmadan, hatanın
  adını veren bir mesajla başlamayı reddeder (R-9).

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
