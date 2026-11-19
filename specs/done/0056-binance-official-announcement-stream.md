# Spec 0056 — Binance duyurularının resmi duyuru akışından toplanması

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0056-plan.md`
- Self-critique: done
- Source: spec 0055 (Binance kararı A: `bapi` yolu kapalı, izinli kaynak kalmadı; ileriye dönük ölçüm durdu);
  kaynak araştırması 2026-11-19 (Binance resmi duyuru WebSocket API'si; SEC basın RSS)
- Sensitive area: API anahtarları / sırlar (`docs/domain.md`)
- Supersedes: 0018/CB-1, CB-2, CB-3 (tek runtime bağımlılığı `ccxt` idi; `websocket-client` ikinci onaylı bağımlılık
  olur: AC-12) — R-08, Galip Badem, 2026-11-19 ("a"). `specs/done/` dosyaları değişmez.

## Intent
Sahip, ileriye dönük haber hattının (0046 toplayıcı → 0051 Claude skoru → 0053 ölçüm) yeniden çalışmasını istiyor.
Binance duyuruları, sitenin kapalı yolu yerine Binance'in geliştiricilere resmi olarak sunduğu duyuru akışından,
sahibin hesabına bağlı, yalnız okuma yetkili bir anahtarla alınacak. Bu, örnek kütüphanesinin (0048) ve hüküm
ölçümünün dayandığı kaynağın kendisi. Başarı: sahip izin kaydını yazıp kaynağı açınca yeni İngilizce duyurular
haber kaydına düşer, skorlayıcı onları Claude'a örnekli promptla verir ve 0053 ölçümü yeni üçlüyle saymaya başlar.
Bilerek yapılmayanlar: geçmiş duyuruları toplamak (0054), kodun izin kararı vermesi, anahtara işlem ya da para çekme
yetkisi istenmesi, SEC ya da başka bir RSS kaynağının kodla eklenmesi.

Clarify kararları (Galip Badem, 2026-11-19):
- **S-1:** Binance koşullarının duyuru içeriğinin AI ile işlenmesine izin verip vermediğini sahip doğrular; spec bu
  karardan bağımsızdır (kaynak yalnız izin kaydıyla açılır, 0055). Doğrulama PLAN'dan önce yapılır; izin
  çıkmazsa spec PLAN'a geçmeden geri çekilir. (Araştırma: AU sürümü 22, 26.1(h), 26.1(k) maddeleri; açık AI
  yasağı yok, açık izin de yok.)
- **S-2:** SEC basın RSS bu spec'in kriteri değildir: bugünkü `rss` türüyle okunur; sahip kendi ayarına kendi izin
  kaydıyla ekler (işletim adımı). Örnek ayarda açık kaynak olmaz (0055 CB-5).
- **S-3:** Haber için ayrı anahtar, yalnız okuma yetkili; işlem ve para çekme yetkisi görülürse toplayıcı başlamaz.
  Anahtar yalnız ortamdan okunur; hiçbir çıktıya yazılmaz.
- **S-4:** Bağlantı kopukken yayınlanan duyuru kaçabilir; kayıp kabul edilir ama kopukluk kayda ve duruma yazılır,
  uzun kesintide bugünkü kesinti bildirimi çalışır. Kapalı yolla tamamlama yapılmaz.
- **S-5:** Yeni kaynak "Binance duyurusu" sayılır (prompt örnekleri, arşiv örtüşmesi); eski kayıtlarla kimlik
  eşleşmesi şart değildir.
- **S-6:** Yalnız İngilizce duyurular, bütün kataloglar; katalog süzülmez.
- **S-1 kararı:** Galip Badem, 2026-11-19 — "binance için onay veriyorum": sahip Binance koşullarının bu kullanıma izin verdiğini kabul etti; dayanağı kendi ayarındaki izin kaydına (`ai_permission_basis`) sahip yazar. PLAN açılabilir.
- **Spec onayı:** Galip Badem, 2026-11-19 — self-critique G-1…G-9 önerildiği gibi.
- **S-7:** Örnekli prompt bağlam parmak izini değiştirir; 0053'te yeni üçlü başlar, 90 gün onun ilk sonucundan sayılır
  (beklenen etki, kriter değil).

## Tanımlar
- **Resmi duyuru akışı:** Binance'in geliştirici belgelerinde duyurular için sunduğu, anahtarla imzalanarak bağlanılan
  sürekli akış. Duyuru yayınlandıkça gelir; geçmişi vermez.
- **Akış kaynağı:** haber ayarında bu akışı okuyan kaynak türü. Bugünkü `binance-duyuru` (site yolu) ve `rss` türleri
  yanında yeni bir türdür.
- **Kopukluk:** akış kaynağı açıkken bağlantının olmadığı süre (ilk bağlantıdan önce, koptuktan sonra yeniden
  bağlanana kadar).

## Requirements
1. Haber ayarında yeni bir kaynak türü vardır: akış kaynağı. Diğer kaynaklar gibi adı, açık/kapalı durumu ve 0055
   izin kaydı vardır; açıkken izin kaydı zorunludur (0055 CB-1 aynen).
2. Açık akış kaynağı toplayıcı çalıştığı sürece akışa bağlı kalır; gelen her İngilizce duyuru haber kaydına bir kez,
   kaynağın adıyla, başlığı, metni (varsa), yayın anı ve ilk görülme anıyla yazılır. Aynı duyuru ikinci kez gelirse
   tekrar sayılır, yazılmaz. Bütün kataloglar alınır. İlk görülme anı iletinin alındığı andır; yayın anı yoksa,
   okunamıyorsa ya da alınma anından 5 dakikadan ilerideyse bilinmiyor (0046 kuralı). Başlık ve metin sınırları ve
   kesme kuralı 0046'nınkidir (G-3, G-7).
3. Akış kaynağının duyurusu, toplayıcının diğer kaynaklarıyla aynı tur satırı biçiminde sayılır (yeni, tekrar,
   geçersiz); turun aralığı bugünkü gibidir. Diğer kaynakların sorgulanması akış yüzünden gecikmez.
4. Anahtar ve gizli anahtar yalnız ortamdan (`.env` ya da işletim sistemi ortamı) okunur; ayarda yalnız ortam
   değişkenlerinin adları durur, varsayılanları `BINANCE_NEWS_API_KEY` ve `BINANCE_NEWS_API_SECRET` (bot
   anahtarlarından ayrı; G-8). Değerler hiçbir kayıt satırına, durum satırına, hata mesajına, bildirime, haber
   kaydına ve LLM promptuna girmez.
5. Toplayıcı akış kaynağı açıksa, her bağlantıdan önce (başlangıçta ve her yeniden bağlanmada; G-4) anahtarın
   yetkilerini Binance'ten okur. Okuma dışında bir yetki (spot/vadeli işlem, para çekme, transfer) açıksa toplayıcı
   hiçbir kaynağı sorgulamadan reddeder (kesin ret). Yetki okunamazsa (ağ, zaman aşımı, yanıt hatası) akış kaynağı
   bağlanmaz: bu kopukluk sayılır ve denetim yeniden bağlanma beklemesiyle yeniden denenir; diğer kaynaklar
   çalışmayı sürdürür (G-5). Her iki durumda da yetkisi doğrulanmamış anahtarla bağlantı kurulmaz.
6. Bağlantı koparsa, süresi dolarsa ya da kurulamazsa toplayıcı bekleyip yeniden bağlanır. Bekleme ardışık hatalarda
   5 saniyeden başlar, her ardışık hatada iki katına çıkar, en çok 15 dakikadır ve başarılı bağlantıda sıfırlanır
   (G-1); sağlayıcının bağlantı kurallarını (ileti hızı, canlılık iletisi) aşmaz. Her
   kopukluk bittiğinde süresi kayda yazılır.
7. Akış kaynağının kesintisi bugünkü kesinti kuralına (0046: `source_alert_hours`, tek bildirim, ilk başarıda çıkış
   bildirimi) bağlıdır: kopukluk ya da yetki dışı ret kesintidir.
8. Şemaya uymayan ya da sınırı aşan ileti yazılmaz; geçersiz sayılır; toplayıcı durmaz. Dil, abone olunan İngilizce
   duyuru konusuyla belirlenir; ileti ayrıca bir dil işareti taşıyorsa ve İngilizce değilse o da geçersizdir (G-2;
   BUILD yoklaması iletinin dil işareti taşıyıp taşımadığını gösterir).
9. Bağlantı durumu ve kopukluklar haber kaydındaki kaynak durumuna yazılır; `news status` akış kaynağı için bugünkü
   satıra ek olarak oradan bağlantı durumunu, son bağlantı anını, süren kopukluğun başladığı anı ve kayıt boyunca
   toplam kopukluk süresini gösterir; ağa çıkmaz (G-6).
10. Akış kaynağı "Binance duyurusu" sayılır: izinli bir akış kaynağı varsa skorlayıcının prompt örnekleri gelir
    (0055 CB-3'ün koşulu bu türü de kapsar); arşiv durumunun örtüşme sayımı bu türün kayıtlarını da tarar.
11. Örnek ayarda akış kaynağı kapalı ve izin kaydısız durur; yorumda anahtar ortam değişkenlerinin adları, "yalnız
    okuma yetkisi" kuralı ve izin kaydının sahibe ait olduğu açıklanır.

## User experience
none — no user interface (komut satırı; satır biçimleri Requirements ve kriterlerde).

## Constraints & out of scope
- Sensitive area: API anahtarları / sırlar — her kriter VERIFY'da kasıtlı kırmayla kanıtlanır (`prompts/verify.md`).
- İzin kararı kodda yoktur (0055). Bu spec, Binance koşullarının izin verdiğini varsaymaz; varsayılan örnek ayarda
  kaynak kapalıdır.
- Kapsam dışı: geçmiş duyurular ve kopukluk süresindeki duyuruların tamamlanması (S-4); site yolu (`binance-duyuru`
  türü) değişmez, kapalı kalır; SEC ve başka RSS kaynakları (S-2); İngilizce dışı duyurular (S-6); hesap, bakiye,
  emir ve kullanıcı verisi akışları; anahtarın oluşturulması ve IP kısıtlaması (sahibin Binance ayarı).
- 0053 hüküm kuralları değişmez (ADR 0003); yeni üçlü beklenen etkidir (S-7).
- Bot (`app`) akış kaynağını, anahtarını ve haber kaydını okumaz; toplayıcı bot deposuna yazmaz (0046 sınırı).
- Split: 11 AC + 2 PB, sınırın üstünde; tek yetenek (tek kaynak türü) — anahtar/yetki denetimi toplamadan ayrılırsa
  hiçbir parça tek başına kullanılamaz. Tek spec olarak tutuldu — Galip Badem, 2026-11-19 (G-9).
- BUILD'in ilk adımı bir yoklamadır: akışın gerçek ileti biçimi (alanlar, kimlik, dil işareti) belgelerle
  karşılaştırılır; belgeyle uyuşmazsa R-10.

## Acceptance criteria
- [x] AC-1 — Ayar: akış kaynağı açıksa izin kaydı ve iki anahtar değişkeninin adı zorunludur; eksik ya da geçersizse
  ret, alan adıyla (`news.sources[<sıra>].<alan>`). Ortamda değişken yoksa ya da boşsa toplayıcı hiçbir kaynağa
  istek göndermeden `ortam değişkeni yok: <ad>` ile reddeder (değer yazılmaz). Kapalı akış kaynağı anahtar istemez
  ve bağlantı kurulmaz.
- [x] AC-2 — Yetki denetimi: yalnız okuma yetkili anahtarla akış kaynağı bağlanır. İşlem, para çekme ya da transfer
  yetkisinden biri açıksa toplayıcı `reddedildi: anahtar yetkisi fazla: <yetki adları>` ile hiçbir kaynak
  sorgulanmadan durur (çıkış 1); bu denetim yeniden bağlanmada da yapılır ve fazla yetki görülürse toplayıcı aynı
  retle durur. Yetki okunamazsa `kaynak=<ad> hata=anahtar yetkisi doğrulanamadı` yazılır, akış kaynağı bağlanmaz,
  denetim AC-5 beklemesiyle yeniden denenir ve diğer kaynakların turları sürer.
- [x] AC-3 — Toplama: bağlıyken gelen İngilizce duyuru haber kaydına bir kez yazılır (kaynak adı, başlık, metin,
  yayın anı, ilk görülme anı); aynı duyuru yeniden gelirse `tekrar`; tur satırı `kaynak=<ad> yeni=<n> tekrar=<n>
  geçersiz=<n>` biçimindedir; bir turda hiç ileti gelmemesi hata değildir (`yeni=0`).
- [x] AC-4 — Geçersiz ileti: şemaya uymayan, sınırı aşan ya da İngilizce olmadığını belirten ileti yazılmaz,
  `geçersiz` sayılır; yayın anı geçersizse duyuru yazılır, yayın anı bilinmiyor olur;
  sonraki geçerli ileti yazılır; toplayıcı çalışmayı sürdürür.
- [x] AC-5 — Kopukluk: bağlantı koptuğunda, süresi dolduğunda ya da kurulamadığında toplayıcı yeniden bağlanır;
  bekleme 5 sn, 10 sn, 20 sn… diye iki katına çıkar, 15 dakikada sabitlenir ve başarılı bağlantıda 5 sn'ye döner; her kopukluk bitince kayda
  `kaynak=<ad> kopukluk=<süre>` yazılır; diğer kaynakların turları bu sırada gecikmez.
- [x] AC-6 — Kesinti bildirimi: kopukluk `source_alert_hours`'tan uzun sürerse tek Telegram bildirimi, ilk başarılı
  bağlantıda tek çıkış bildirimi gider (0046 kuralı aynen); kapalıysa yalnız satır.
- [x] AC-7 — Sır sızmaz: anahtar ve gizli anahtar değerleri hiçbir kayıt satırında, durum çıktısında, hata
  mesajında (bağlantı hatası ve ret dahil), bildirimde, haber kaydında ve LLM promptunda geçmez (değerleri bilinen
  sahte anahtarla taranarak kanıtlanır).
- [x] AC-8 — Durum: `news status` akış kaynağı için bugünkü satırı ve haber kaydındaki kaynak durumundan
  `bağlantı=<bağlı|kopuk|hiç bağlanmadı> son_bağlantı=<an|yok> kopukluk_başı=<an|yok> kopukluk_toplam=<süre>`
  bilgisini gösterir; ağa çıkmaz, anahtar okumaz, kilit almaz; kayıt yoksa bugünkü `haber kaydı boş` davranışı.
- [x] AC-9 — Binance duyurusu sayılır: izinli bir akış kaynağı varken skorlayıcının gerçek promptunda kütüphane
  örnekleri bulunur; akış kaynağı kapalıyken (ve izinli `binance-duyuru` yokken) prompt örneksizdir (0055 CB-3);
  `news archive status` örtüşme sayımı akış kaynağının kayıtlarını da sayar.
- [x] AC-10 — Durdurma: Ctrl+C bağlantıyı kapatır ve toplayıcı temiz durur (çıkış 0); ikinci Ctrl+C zorla durdurur
  (çıkış 130); yarım kayıt kalmaz.
- [x] AC-11 — Örnek ayar: akış kaynağı kapalı ve izin kaydısız; yorumda iki ortam değişkeninin adı, yalnız okuma
  yetkisi kuralı ve izin kaydının sahibe ait olduğu yazar; örnek ayar yükleyiciden geçer; `.env.example` iki
  değişkenin yalnız adını taşır.
- [x] AC-12 — Bağımlılık (R-08, 2026-11-19): projenin doğrudan runtime bağımlılıkları tam olarak `ccxt` ve
  `websocket-client`'tır (`pyproject.toml` ve `uv.lock`); izin listesi yine kesin ad listesidir — başka bir ad
  eklenince ya da biri çıkınca test kırmızıdır; ikisi de kilitte sürüm ve hash ile sabittir; CI `pip-audit`
  (`--strict`) ikisini ve dolaylılarını denetler (kanıt: ship PR'ının `audit` işi).

## Preserved behavior
- [x] PB-1 — `rss` ve `binance-duyuru` türleri, tur satırları, kesinti kuralı ve haber kaydı biçimi değişmez (0046);
  akış kaynağı olmayan ayarla toplayıcı bugünkü gibi çalışır, Binance'e bağlanmaz ve anahtar istemez.
- [x] PB-2 — 0055 kuralları aynen: izinsiz kaynak toplanmaz, Claude'a gitmez, hükme girmez; gelecek tarihli izin
  reddedilir.

## Definition of Done
- [x] Every acceptance criterion mapped to proof (test or reproducible observation)
- [x] `scripts/check` green
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Docs / ADRs updated if behavior or architecture changed (`docs/commands.md`, `docs/security.md`, `docs/architecture.md`, örnek ayar, `.env.example`)
- [x] Spec moved to `specs/done/` (it becomes immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | 2 (S-1 kararı satırı; R-08: AC-12 ve Supersedes 0018/CB-1…CB-3) |
| Fix rounds | 5 (fix-1…fix-3 review; R-06 → A-7 re-plan, fix-4; fix-5 yalnız belge) |
| Review findings: real / noise / deferred | 22 / 4 / 1 (review 5 tur + VERIFY 2 tur; B-101; 2 investigate canlı koşuyla kapandı) |
| Regressions introduced | 1 (fix-1'in kararsız testi, fix-2/fix-3'te kapandı) |
| Bugs escaped to production | 0 (ship anında) |

## Handoff
Shipped — Galip Badem, 2026-11-19. İşletim: `news-runner` yeni koda güncellenmeden akış kaynağı orada çalışmaz; kaynak açılırken izin kaydını sahip yazar.
