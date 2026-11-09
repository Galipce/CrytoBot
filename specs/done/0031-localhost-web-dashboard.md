# Spec 0031 — Localhost salt-okunur web panosu (dashboard)

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0031-plan.md`
- Self-critique: done

## Intent
Sistemin sahibi, CrytoBot'un anlık durumunu, kasasını, serbest bakiyesini, drawdown oranını, açık pozisyonlarını ve son turlarını konsol terminali açmadan veya Telegram mesajlarına bağımlı kalmadan, modern, okunabilir, responsive ve güzel tasarımlı bir web arayüzünden (`127.0.0.1`) tek bakışta izlemek istiyor. Bu iş, ADR 0002 Faz 2 kapsamındaki salt okunur web izleme panosunu tamamlar ve sahibine bot üzerinde şeffaf, görsel bir denetim sağlar. Başarı: `crytobot dashboard` komutuyla yerel HTTP sunucusunun ayağa kalkması; tarayıcıdan girildiğinde depodaki (`bot.db`) güncel verilerin şık kartlar, durum rozetleri, responsive tablolar ve otomatik yenileme (polling) ile temiz biçimde sunulması; sayfa açıkken botun çalışmasını veya SQLite kilitlerini asla aksatmaması; DNS rebinding saldırılarına karşı Host denetimi yapmasıdır. Bilerek yapılmayanlar: Pano üzerinden emir verme, limit gevşetme/değiştirme, kill switch veya stop gibi kontrol komutları (kontrol yalnızca CLI ve Telegram'da kalır — ADR 0002); internete açılma (`0.0.0.0`); oturum açma/şifreleme (güvenlik localhost kısıtı ve Host denetimiyle sağlanır); harici derleme adımları (npm/node build tool).

## Requirements
Terimler:
- **Pano (Dashboard):** Yalnızca `127.0.0.1` adresinde çalışan, depoyu salt-okunur inceleyen, modern ve responsive web arayüzü.
- **Sunucu (Server):** Pano arayüzünü ve durum verilerini HTTP GET istekleriyle istemciye sunan hafif yerel web servisi.
- **Durum API'si (Status API):** Deponun o anki özet durumunu (kasa, serbest bakiye, drawdown, pozisyonlar, süreç durumu, durdurmalar) JSON biçiminde dönen salt-okunur veri kapısı (`/api/status`).
- **Host Denetimi (Host Validation):** Gelen HTTP isteklerindeki `Host` başlığının yalnızca izin verilen yerel adreslere (`localhost`, `127.0.0.1`) ait olduğunu doğrulayan güvenlik kuralı (DNS rebinding koruması).
- **Otomatik Yenileme (Auto Refresh):** Tarayıcıdaki arayüzün sayfayı baştan yüklemeden, belirli aralıklarla (ör. 5 saniye) arka plandan veri çekerek kartları güncellemesi.

Davranış:
- R-1: **Bağımsız çalıştırma (`dashboard`).** `dashboard` komutu verildiğinde yerel web sunucusu belirlenen portta (`[dashboard] port = 8080`, varsayılan 8080) ayağa kalkar, konsola erişim adresini (`http://127.0.0.1:8080`) yazar ve Ctrl+C (veya sinyal) gelene kadar çalışır. Bot döngüsünün çalışıp çalışmamasından bağımsızdır (`durdu` durumundayken de depoyu açar ve inceler).
- R-2: **Salt okunur depo erişimi.** Sunucu depoyu yalnızca salt okunur (`mode=ro`) açar; depoda hiçbir değişiklik yapmaz, kilit almaz veya yazan bot sürecini engellemez. SQLite meşgul olursa standart bekleme süresince (4.0 s) dener.
- R-3: **Host başlığı ve ağ güvenliği (ADR 0002).** Sunucu yalnızca `127.0.0.1` IPv4 adresine bağlanır (`0.0.0.0` bağlanmaz). Gelen her HTTP isteğinin `Host` başlığı denetlenir; `localhost` veya `127.0.0.1` (ve portu) dışındaki istekler (DNS rebinding girişimleri) HTTP 403 Forbidden ile reddedilir.
- R-4: **Durum verisi sunumu (JSON).** Sunucu, depodaki güncel durumu JSON formatında dönen bir salt-okunur yol (`/api/status`) sunar. Döndürülen veri; süreç durumu (çalışıyor/durdu), mod (`paper`), toplam kasa, serbest bakiye, zirve kasa, drawdown oranı (%), günün gerçekleşen ve açık kâr/zararı, aktif durdurmalar (yok / kill-switch / drawdown), açık pozisyonların detaylı listesi ve son turun özetini içerir.
- R-5: **Modern, responsive ve güzel tasarımlı web arayüzü.** Kök adrese (`/`) gelen isteklerde; modern, koyu temalı (dark mode), okunabilir tipografiye sahip, mobil ve masaüstü uyumlu (responsive) tek sayfalık HTML/CSS/JS arayüzü sunulur. Harici CDN veya internet bağlantısı gerektirmez (çevrimdışı/ağsız çalışır).
  - Ekran alanları:
    1. Sistem Durum Başlığı: Süreç durumu rozeti (yeşil "Çalışıyor" / gri "Durdu"), Çalışma Modu rozeti (`paper`), Aktif Durdurma rozeti (kırmızı "Kill Switch Devrede" / turuncu "Drawdown Durdurması" / yeşil "Normal"), son tur zamanı.
    2. Metrik Kartları: Toplam Kasa (USDT), Serbest Bakiye (USDT), Günlük Kâr/Zarar (USDT ve %), Zirve Kasa, Drawdown Çubuğu/Oranı (%).
    3. Açık Pozisyonlar Tablosu: Varsa her pozisyon için çift adı, yön (ALIM), miktar, giriş fiyatı, güncel fiyat, stop-loss, hedef fiyat ve anlık kâr/zarar. Pozisyon yoksa temiz boş durum mesajı.
    4. Son Tur ve Olay Özeti: Son turun sonucu, zamanı ve son kontrol kayıtları.
    5. Otomatik Yenileme ve Canlı Sayaç: Sayfa her 5 saniyede bir durumu arka plandan sorgular ve kartları yeniler; ayrıca elle "Yenile" butonu bulunur.
- R-6: **Depo yok / bozuk / defter açılmamış durumu.** Depo dosyası henüz oluşturulmamışsa veya bozuksa, sunucu çökmez; JSON API ve web arayüzü hatayı adıyla bildirir (ör. "Depo bulunamadı — önce 'prepare' çalıştırılmalı") ve temiz bir hata ekranı gösterir.
- R-7: **Port çakışması ve hata yönetimi.** İstenen port başka bir süreç tarafından kullanılıyorsa, sunucu çökmeden konsola anlaşılır bir Türkçe hata mesajı basar (`EXIT_REFUSED` / çıkış kodu 1).
- R-8: **Yasak eylemler (ADR 0002).** Pano hiçbir POST, PUT, DELETE metodu kabul etmez; hiçbir alım, satım, mod değiştirme, limit değiştirme veya kill-switch tetikleme yetkisi taşımaz. Yalnızca GET metodunu destekler; diğer metotlar HTTP 405 Method Not Allowed ile reddedilir.

## User experience
- Flow: Kullanıcı konsoldan `python -m crytobot dashboard` çalıştırır → konsolda `http://127.0.0.1:8080` linki basılır → kullanıcı tarayıcıda adresi açar → modern, koyu temalı pano yüklenir → metrik kartları ve açık pozisyonlar listelenir → sayfa her 5 saniyede bir otomatik güncellenir → kullanıcı Ctrl+C ile sunucuyu kapatır.
- States:
  - Yükleniyor (Loading)
  - Başarılı / Veri Var (Success - pozisyonlu ve pozisyonsuz)
  - Bot Durdu / Bot Çalışıyor durum rozetleri
  - Durdurma Aktif durumu (Kill switch veya drawdown uyarı rozeti)
  - Depo Yok / Bozuk (Error / Not found)
  - Yetkisiz Host Başlığı (Forbidden - 403)
- Design reference: none — the flow and visual layout above is the design.
- Accessibility: klavye ile odaklanabilir (Tab), semantik HTML, koyu tema yüksek kontrast (WCAG AA).

## Constraints & out of scope
- Sensitive area: `Kalıcı durum (persistence)` — `docs/domain.md`. Depo asla değiştirilemez, salt okunur açılır.
- Out of scope: Pano üzerinden emir veya kontrol komutu verme (ADR 0002); internete açılma (`0.0.0.0`); kullanıcı adı / şifre / JWT oturum yönetimi; WebSocket (polling yeterlidir); harici Node.js/Vite derleme araçları.
- Boyut: 8 kabul kriteri. Propose split: Gerek yok, tek spec olarak teslim edilebilir.

## Acceptance criteria
- [x] AC-1 — Sunucu başlatma ve kapatma (R-1): `dashboard` komutu sunucuyu `127.0.0.1` ve ayardaki portta (`8080`) başlatır, konsola erişim adresini basar; Ctrl+C (veya sinyal) ile temiz biçimde kapanır.
- [x] AC-2 — Host denetimi ve HTTP metot kısıtı (R-3, R-8): `Host` başlığı `127.0.0.1` veya `localhost` dışındaki istekler HTTP 403 Forbidden ile reddedilir; GET dışındaki metotlar (POST, PUT, DELETE vb.) HTTP 405 Method Not Allowed ile reddedilir.
- [x] AC-3 — Salt okunur durum API'si (R-2, R-4): `/api/status` uç noktası HTTP GET ile çağrıldığında depodaki en güncel durumu (süreç durumu, mod, toplam kasa, serbest bakiye, zirve, drawdown %, açık pozisyonlar, aktif durdurmalar, son tur) JSON olarak döner; depoyu değiştirmez ve kilit almaz.
- [x] AC-4 — Modern ve responsive web arayüzü (R-5): Kök adrese (`/`) GET isteği yapıldığında modern, koyu temalı, responsive HTML arayüzü döner; sistem durum rozetini, finansal metrik kartlarını, açık pozisyonlar tablosunu ve son tur özetini doğru gösterir; harici CDN veya ağ bağlantısı gerektirmez.
- [x] AC-5 — Otomatik yenileme ve dinamik veri akışı (R-5): Web arayüzü JavaScript ile `/api/status` üzerinden her 5 saniyede bir sayfayı yeniden yüklemeden kartları ve tabloları günceller; ayrıca elle "Yenile" butonuyla anında tetiklenebilir.
- [x] AC-6 — Açık pozisyonlu ve pozisyonsuz durumlar (R-5): Açık pozisyon varken tüm pozisyon detayları (çift, miktar, giriş, stop, hedef) tabloda listelenir; açık pozisyon yokken anlaşılır boş durum mesajı ("Açık pozisyon yok") gösterilir.
- [x] AC-7 — Depo yok veya bozukken hata yönetimi (R-6): Depo dosyası henüz oluşturulmamışken (`prepare` öncesi) veya bozukken sunucu çökmez; `/api/status` ve web arayüzü anlaşılır hata durumu döner ve kullanıcıya durumu adıyla bildirir.
- [x] AC-8 — Port meşgulken ret (R-7): İstenen port başka bir süreç tarafından dinleniyorsa `dashboard` komutu çökmeden adıyla hata mesajı basar ve `EXIT_REFUSED` ile çıkar.

## Definition of Done
- [x] Every acceptance criterion mapped to proof (test or reproducible observation)
- [x] `scripts/check` green
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Docs / ADRs updated if behavior or architecture changed
- [x] Spec moved to `specs/done/` (it becomes immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | 0 |
| Fix rounds | 1 (fix-1: Finding 1, Finding 2) |
| Review findings: real / noise / deferred | 2 / 0 / 0 (Finding 1 real [fix-1], Finding 2 real [fix-1]) |
| Regressions introduced | 0 (kanıt bu PR'ın full CI koşusu) |
| Bugs escaped to production | 0 (henüz üretim yok) |

DoD'nin `scripts/check` kutusu koşullu işaretlendi (`doctor`, `specs/done/`'da işaretsiz kriteri reddediyor); koşul bu PR'ın `check` ve `doctor` işleridir, yeşil olmadan merge yapılmaz (`docs/testing.md`, Two speeds, rule 10). VERIFY @`8195264`: adı geçen testler hızlı profilde yeşil, 5 kasıtlı bozmanın 5'i kırmızı, 7 UI ekran görüntüsü galeri olarak doğrulandı; full kanıt bu PR'ın CI koşusudur.
