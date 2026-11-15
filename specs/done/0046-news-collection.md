# Spec 0046 — Haber toplama (ileriye dönük)

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0046-plan.md`
- Self-critique: done
- Source: ADR 0003 (sıranın ilk işi: haber toplama)

## Intent
Botun sahibi, LLM'in olay skoru üretebilmesi ve bu skorun ileride dürüstçe ölçülebilmesi için önce zaman damgalı bir
haber kaydı istiyor (ADR 0003). Bot, config'te tanımlı kaynaklardan (Binance duyuruları ve birkaç büyük kripto haber
sitesinin RSS akışı) haberleri, işlem döngüsünden ayrı çalışan bir komutla düzenli aralıklarla toplar. Her kayıt
kaynağını, kaynağın verdiği yayın anını ve botun haberi ilk gördüğü anı taşır; sonraki ölçümler "bot bunu o anda
bilebilir miydi" sorusunu ilk görme anıyla yanıtlar. Başarı: toplama aylarca gözetimsiz çalışır, aynı haber iki kez
yazılmaz, çöken bir kaynak diğerlerini ve işlem döngüsünü durdurmaz, uzun süren bir kesinti görünür olur.
Bilerek yapılmayanlar: geçmiş arşivin doldurulması (spec 0047), LLM skoru, coin eşlemesi, olay türü ve habere dayalı
hiçbir işlem kararı. Clarify kararları S1–S7 ve self-critique kararları G-1…G-8 Galip Badem, 2026-11-15 tarihinde
onayladı.

Terimler:
- **Kaynak:** config'te adı, türü (`binance-duyuru` ya da `rss`), `https` adresi ve açık/kapalı bilgisi olan bir haber
  akışı. `rss` türü RSS 2.0 ve Atom akışlarını kabul eder; `binance-duyuru` JSON yanıt bekler (G-5).
- **Haber kaydı:** bir kaynaktan alınmış tek haber: kaynak adı, kaynağın haber kimliği (yoksa bağlantısı), başlık,
  metin (akışın verdiği özet ya da gövde), bağlantı, yayın anı, ilk görme anı.
- **Yayın anı:** kaynağın haber için bildirdiği zaman, UTC'ye çevrilmiş. Güvenilmez; yalnız bilgi amaçlıdır.
- **İlk görme anı:** haberi ilk kez getiren kaynak yanıtının alındığı an (UTC; turun başlangıcı değil, G-2). Sonraki
  bütün ölçümlerin kullandığı zaman.
- **Toplama turu:** açık kaynakların her birinin bir kez sorgulandığı çalışma.
- **Kaynak hatası:** bir kaynağın o turda kayıt üretememesi: ağ hatası, zaman aşımı, HTTP hata cevabı, sınırı aşan ya
  da beklenmeyen türde yanıt, ayrıştırılamayan ya da reddedilen içerik.

## Requirements
- R-1 — Ayrı bir CLI komutu, durdurulana kadar `interval_minutes` aralıkla (vars. 15) toplama turları çalıştırır. Bu
  komut işlem döngüsünden bağımsızdır: bot durumunu, defteri, emirleri, riski ve paper/live deposunu okumaz ve
  değiştirmez. Bot çalışırken de çalışabilir.
- R-2 — Her turda her açık kaynak bir kez sorgulanır. Yeni haberler, R-3'teki alanlarla ve kayıtlar yalnız eklenerek
  haber kaydına yazılır. Mevcut kayıt silinmez ve değiştirilmez.
- R-3 — Bir haber, aynı kaynak adı ve aynı kaynak kimliği (kimlik yoksa aynı bağlantı) taşıyorsa tekrardır ve yazılmaz.
  Haber değişmiş olsa da (başlık ya da metin) ilk yazılan sürüm kalır. Bu kural turlar ve yeniden başlatmalar
  boyunca geçerlidir.
- R-4 — Yayın anı yoksa, okunamıyorsa ya da ilk görme anından 5 dakikadan daha ileri bir zamanı gösteriyorsa kayıt yine
  yazılır, ama yayın anı "bilinmiyor" olarak işaretlenir. İlk görme anı hiçbir durumda yayın anından türetilmez.
- R-5 — Haber metni güvenilmeyen girdidir. Bir kaynağın yanıtı en çok `max_response_kb` (vars. 2048) büyüklükte olabilir
  ve beklenen türde olmalıdır. Kayıt başına metin en çok 20 KB'tır; fazlası kesilir ve kayıt "kesildi" işaretini
  taşır. 20 KB UTF-8 bayttır; kesme çok baytlı bir karakterin ortasına düşmez (G-4). Metin olduğu gibi
  saklanır, HTML etiketleri temizlenmez; düz metne çevirme LLM spec'inin işidir (G-6). Yalnız `https` adresler
  kullanılır; en çok 3 yönlendirme izlenir, `http`'ye düşen ya da 3'ü aşan yönlendirme kaynak hatasıdır (G-7). XML dış varlık ya da varlık genişletmesi içeriyorsa reddedilir. Bağlantılar izlenmez (haber sayfası
  indirilmez). İçerik hiçbir biçimde çalıştırılmaz ve yorumlanmaz. Başlığı da metni de boş olan haber yazılmaz,
  geçersiz sayılır.
- R-6 — Bir kaynak hatası yalnız o kaynağı o tur için etkiler. Diğer kaynaklar aynı turda toplanır, sonraki turda
  hatalı kaynak yeniden denenir. Bir kaynağa bir turda en çok 30 saniye ayrılır; ad çözümleme dahil hiçbir ağ durumu
  bu süreyi aşamaz. Hata adı ve anı kaydedilir. Kayıt içinde yetkilendirme bilgisi ya da sır bulunmaz.
- R-7 — Her tur, kaynak başına bir özet satırı yazar (konsol ve log): yeni, tekrar ve geçersiz kayıt sayıları ya da hata
  adı. Binance duyurularında okunan sayfanın bütün öğeleri yeniyse satır "olası kaçırma" uyarısı taşır (G-3).
- R-8 — Ayrı bir durum komutu, config'teki her kaynak için son başarılı toplama anını, son hatayı (adı ve anı) ve toplam
  kayıt sayısını, ayrıca haber kaydının toplam boyutunu gösterir (G-8). Hiç başarılı olmamış kaynak "hiç başarılı olmadı" diye görünür. Kayıt boşken komut bunu
  söyler ve hata vermez. Durum komutu ağa çıkmaz.
- R-9 — Bir kaynak `source_alert_hours` süresinden (vars. 6) uzun süre aralıksız hata verirse, `reporting` üzerinden
  tek bir Telegram bildirimi gider. Kaynak yeniden başarılı olunca tek bir çıkış bildirimi gider. Süren kesinti için
  tekrar bildirim gitmez. Kesintinin başlangıcı ve bildirimin gönderildiği bilgisi kayıttan okunur: komutun yeniden
  başlatılması sayacı sıfırlamaz ve aynı kesinti için ikinci bildirim üretmez (G-1). Telegram kapalıysa durum yalnız konsola ve loga yazılır.
- R-10 — Kaynaklar ve ayarlar config'tedir; kaynak eklemek ya da çıkarmak kod değişikliği gerektirmez. Config'ten
  çıkarılan kaynağın eski kayıtları kalır.

## User experience
none — no user interface (yalnız CLI komutları ve konsol/log satırları; Telegram bildirimi R-9).

## Constraints & out of scope
- Yeni çalışma bağımlılığı eklenmez; onaylı tek çalışma bağımlılığı `ccxt` kalır (spec 0018).
- `scripts/check` ağa çıkmaz; kaynak yanıtları kayıtlı örneklerle sınanır (`docs/testing.md`).
- Kaynaklara nazik davranılır: kaynak başına turda bir istek (Binance duyurularında yalnız ilk sayfa), aralığın alt
  sınırı 5 dakika. İstekler kişisel bilgi taşımayan genel bir istemci adıyla gider.
- Binance duyuru uç noktası belgelenmiş değildir ve değişebilir. Değişirse kaynak hatası olur (R-6, R-9); sessiz boşluk
  oluşmaz.
- Sensitive area: yok. Emir, risk, sır, mod ve defterle ilgisi yoktur; haber kaydı `news`'in kendi deposudur. Telegram
  yalnız giden bildirimdir, komut yetkilendirmesine dokunulmaz.
- Out of scope: geçmiş arşivin doldurulması (spec 0047); LLM çağrısı ve haber skoru; coin eşlemesi ve olay türü; strateji
  filtresi; haber sayfası kazıma; sosyal medya, on-chain ve ücretli toplayıcılar; panoda (0031) haber gösterimi;
  kayıtların silinmesi ya da saklama süresi (G-8: sınır yok, boyut durum komutunda görünür).
- Split: 0046 ileriye dönük toplama, 0047 geçmiş arşiv (Binance duyuruları) — Galip Badem, 2026-11-15 (S1).

## Acceptance criteria
- [x] AC-1 — Üç açık kaynaktan (bir `binance-duyuru`, bir RSS 2.0, bir Atom) gelen yeni haberler tek turda yazılır. Her
  kayıtta kaynak adı, kimlik ya da bağlantı, başlık, metin (HTML'si olduğu gibi), bağlantı, UTC yayın anı ve o kaynağın
  yanıtının alındığı UTC ilk görme anı bulunur. Kapalı kaynak sorgulanmaz. Kaynak başına özet satırı doğru
  yeni/tekrar/geçersiz sayılarını gösterir. Binance sayfasının bütün öğeleri yeniyse satır "olası kaçırma" uyarısı
  taşır, en az bir öğe tekrarsa taşımaz (R-2, R-7).
- [x] AC-2 — Aynı haber sonraki turda ve komut yeniden başlatıldıktan sonra yeniden görülünce yazılmaz. İlk görme anı
  ve ilk sürümün başlığı ve metni değişmez. Kimliği olmayan RSS öğesinde tekrar bağlantıyla anlaşılır. Aynı kimlik iki
  farklı kaynakta görülürse iki ayrı kayıt olur (R-3).
- [x] AC-3 — Yayın anı eksik, okunamaz ya da ilk görme anından 5 dakikadan daha ileri olan haber "yayın anı bilinmiyor"
  işaretiyle yazılır. Tam 5 dakika ileri olan haber işaretlenmez. İlk görme anı her üç durumda da kaynak yanıtının
  alındığı andır (R-4).
- [x] AC-4 — Metni 20 KB'ı aşan haber 20 KB'a kesilir ve "kesildi" işaretini taşır; tam 20 KB işaretlenmez; çok baytlı karakter sınıra denk gelirse karakter bölünmez. Başlığı ve
  metni boş olan haber yazılmaz, geçersiz sayılır. `max_response_kb`'ı aşan ya da beklenmeyen türdeki yanıt, dış varlık
  ya da varlık genişletmesi içeren XML bozuk XML/JSON, `http`'ye düşen ya da 3'ten fazla yönlendirme, o kaynak için kaynak hatası olur ve o kaynaktan o tur hiçbir
  kayıt yazılmaz. Haber bağlantılarına istek gitmez (R-5).
- [x] AC-5 — Bir kaynak ağ hatası, zaman aşımı, HTTP hata cevabı ya da takılan ad çözümleme yaşarken diğer kaynağın
  haberleri aynı turda yazılır. Takılan kaynak turu en çok 30 saniye (ölçüm payıyla) geciktirir. Hata adı ve anı
  kaydedilir. Kayıtta ve log satırlarında sır ya da yetki bilgisi yoktur. Hatalı kaynak sonraki turda yeniden denenir
  (R-6).
- [x] AC-6 — Durum komutu her kaynak için son başarılı anı, son hatayı ve toplam kayıt sayısını, ayrıca kaydın toplam
  boyutunu gösterir. Hiç başarılı olmamış kaynak "hiç başarılı olmadı" diye görünür. Boş kayıtta bunu söyler ve 0 koduyla çıkar. Ağa istek göndermez
  (R-8).
- [x] AC-7 — `source_alert_hours`'tan uzun süre aralıksız hata veren kaynak için tek bir Telegram bildirimi gider;
  eşiğe kadar gitmez, süren kesintide tekrar gitmez. Bildirim gittikten sonra komut yeniden başlatılırsa aynı kesinti için ikinci
  bildirim gitmez; eşiğe yaklaşmış bir kesintide yeniden başlatma sayacı sıfırlamaz. İlk başarıda tek bir çıkış
  bildirimi gider. Telegram kapalıyken
  bildirim yalnız konsol ve log satırı olur. Bildirim kaynak adını ve kesintinin başlangıç anını taşır (R-9).
- [x] AC-8 — Komut `interval_minutes` aralıkla turları sürdürür. Durdurma (Ctrl+C) turun ortasında gelse de yarım kayıt
  bırakmadan çıkar. Aynı haber kaydına ikinci bir toplama komutu açılmak istenirse anlaşılır bir mesajla reddedilir.
  Komut çalışırken paper botunun bir turu, komut hiç yokmuş gibi aynı sonucu verir. Komut bot deposuna yazmaz (R-1).
- [x] AC-9 — Geçersiz config'te (kaynak yok, bilinmeyen tür, aynı ad iki kez, adres yok ya da `https` değil, `interval_minutes` < 5,
  sınırların sıfır ya da negatif olması) komut ağa çıkmadan, hatanın adını veren bir mesajla başlamayı reddeder. Config'ten
  çıkarılan kaynağın eski kayıtları kalır (R-10).

## Definition of Done
- [x] Every acceptance criterion mapped to proof (test or reproducible observation)
- [x] `scripts/check` green
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Docs / ADRs updated if behavior or architecture changed (`docs/architecture.md`, `docs/commands.md`, `docs/security.md`, `crytobot-news.example.toml`, ADR 0003)
- [x] Spec moved to `specs/done/` (it becomes immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | 0 (Approved metin, onaydan sonra değişmedi; plan A-1…A-4) |
| Fix rounds | 1 (fix-1: F-1 Medium, F-2, F-3, F-4; review round 2 clean) |
| Review findings: real / noise / deferred | 4 (F-1…F-4) / 8 (round 1 I-1, I-2, I-3, I-6; round 2 Info-1…Info-4) / 0; I-4 → A-4, I-5 kapandı (9c0d132), round 2 Info-5 işlem yok; VERIFY F-1 Info (AC-6 çıkış kodu `tests/main/test_news_entry.py::test_status_empty_store_exit_0`'da) |
| Regressions introduced | 0 |
| Bugs escaped to production | 0 |
