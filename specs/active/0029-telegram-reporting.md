# Spec 0029 — Telegram Bildirimleri ve Raporlama

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0029-plan.md`
- Self-critique: done

## Intent
Botun sahibi, bilgisayar başında olmadığı zamanlarda CrytoBot'un çalışma durumunu, karşılaşılan risk ve güvenlik durdurmalarını, gerçekleşen alım-satım işlemlerini ve günlük kâr/zarar performansını uzaktan Telegram üzerinden güvenilir bir şekilde takip etmek istemektedir. Bu iş; kritik sistem durumlarında (bayat veri, mutabakat uyumsuzluğu, kasa durdurması vb.), işlem dolumlarında ve gün dönümünde net, sır içermeyen bildirim ve özet raporların Telegram'a iletilmesini sağlar. Başarı; Telegram üzerinden gönderilen bildirimlerin eksiksiz, mükerrer spam üretmeden ve sır sızdırmadan kullanıcıya ulaşması; olası Telegram API veya ağ kesintilerinin botun ana işlem döngüsünü kesinlikle aksatmamasıdır. Bilerek yapılmayanlar: Telegram üzerinden bota komut gönderme, limit değiştirme veya acil durdurma (kill switch) gibi çift yönlü etkileşimler (`control` modülü yetki alanıdır ve bu spec kapsamı dışındadır); canlı işlem (live) adaptörü; grafikleri/görselleri render edip göndermek.

## Requirements
Terimler:
- **Bildirim gönderimi (notification):** `reporting` modülünün, botun karşılaştığı durumları ve işlemleri tek yönlü olarak Telegram kanalına/sohbetine mesaj olarak iletmesi.
- **Sistem ve durum bildirimleri:** `app` döngüsünde üretilen ve `TurnNotice` ile temsil edilen süren durumlar (bayat veri, mutabakat hatası, depo erişilemezliği, güvenli mod vb.) için üretilen giriş ve çıkış bildirimleri.
- **Risk durdurma bildirimleri (B-42):** Kasanın drawdown limitini aşması (`HALTED`) veya o günkü gerçekleşen+açık zararın günlük zarar limitini aşması durumlarında üretilen acil durum bildirimleri.
- **İşlem olay bildirimleri:** Onaylanan bir alım emrinin borsada dolması veya bir pozisyonun stop-loss ya da kâr hedefi ile kapatılması anında üretilen detaylı işlem bildirimleri.
- **Günlük özet raporu:** Her UTC gün dönümünde (00:00 UTC) üretilen, gün başı/sonu kasa, net PnL ve BR-1 kâr metriğini içeren periyodik özet rapor.
- **Bellek kuyruğu (retry queue):** Telegram API kesintisi veya rate limit durumunda iletilemeyen mesajların bot döngüsünü engellemeden geçici olarak hafızada tutulduğu sınırlı kuyruk.

Davranış:
- R-1: **Yapılandırma ve isteğe bağlılık (Opt-in).** Telegram bildirimleri isteğe bağlıdır. Telegram Bot Token işletim sistemi ortam değişkeninden veya `.env` dosyasından (`TELEGRAM_BOT_TOKEN`), Telegram Chat ID ve ayarlar ise `crytobot.toml` konfigürasyon dosyasından (`[reporting.telegram]` altında `enabled = true|false`, `chat_id = "..."`) okunur. Token ya da `chat_id` eksikse ya da `enabled = false` ise Telegram gönderimi devre dışı kalır; bot hata vermeden başlar, bildirimler standart konsol/log çıktısına yazılır.
- R-2: **Sır güvenliği ve redaksiyon (`docs/security.md`).** Bot token, borsa API anahtarları veya herhangi bir kimlik doğrulama sırrı loglara, hata kayıtlarına, konsol çıktısına ve Telegram mesajlarına hiçbir koşulda yazılmaz. Hata ve istisna yakalama bloklarında hata metni sır içermeyecek şekilde adlandırılır.
- R-3: **Sistem durum bildirimleri ve biçimlendirme güvenliği.** `app` döngüsünün ürettiği `TurnNotice` bildirimleri Telegram'a iletilir. Süren bir durum başladığında tek bir giriş bildirimi (ör. 🔴 `[DURUM BAŞLADI]`), durum düzeldiğinde tek bir çıkış bildirimi (ör. 🟢 `[DURUM DÜZELDİ]`) gönderilir. Durum devam ettiği sürece ara turlarda mükerrer bildirim gönderilmez. Mesajlar katı bir kaçış (escaping) filtresiyle biçimlendirilir; Telegram API'den ayrıştırma hatası (HTTP 400 Bad Request vb.) alınırsa mesaj otomatik olarak düz metne (plain text) düşürülerek iletilir (G-2).
- R-4: **Risk ve kasa durdurma bildirimleri (B-42).** Drawdown durdurması (`HALTED`) veya günlük zarar limitinin aşılması durumunda, öneri olup olmamasına bakılmaksızın ilk turda derhal bildirim iletilir. Günlük zarar durumu `risk` modülünün public arayüzü üzerinden okunur (G-3); formül `app`'e kopyalanmaz. Günlük zarar limiti yeni UTC gününde sıfırlandığında çıkış bildirimi gönderilir.
- R-5: **İşlem olay bildirimleri.** Bir alım emri başarıyla dolduğunda çift, miktar, dolum fiyatı ve belirlenen stop seviyesi; bir pozisyon kapandığında ise çift, kapanış gerekçesi (stop-loss veya kâr hedefi) ve net kâr/zarar tutarı ile yüzdesi Telegram'a anlık iletilir.
- R-6: **Günlük özet raporu (BR-1).** Her yeni UTC gününün ilk tamamlanan turunda bir önceki UTC gününün performansını özetleyen tek bir günlük rapor hazırlanıp Telegram'a iletilir (G-1). Rapor şunları içerir:
  - Gün başı kasa ve gün sonu kasa (USDT).
  - Günlük gerçekleşen net kâr/zarar tutarı ve yüzdesi.
  - BR-1 günlük kâr hedefi metriği (%20–25 hedef kıyaslaması, BR-1 uyarınca karar kuralı değil salt raporlanan metrik olarak).
  - Açık pozisyon sayısı ve gün içinde tamamlanan işlem adedi.
  Süreç belleğinde son raporlanan UTC tarihi tutulur; aynı UTC günü için mükerrer günlük rapor gönderilmez.
- R-7: **Ağ hatası izolasyonu ve kuyruk yönetimi (B-45, Fail-safe).** Telegram API çağrısında oluşan ağ kesintisi, zaman aşımı veya HTTP hataları botun ana döngüsünü, alım-satım işlemlerini veya defter kayıtlarını **asla aksatmaz / durdurmaz**. İletilemeyen bildirimler en fazla 10 mesajlık bellek içi bir kuyrukta saklanır ve sonraki turlarda yeniden denenir. Kuyruk taşarsa en eski mesaj atılır; oluşan hata tur sonucuna (`notice_errors`) ve loga adıyla yansıtılır. Süreç yeniden başlatıldığında bellek kuyruğu sıfırlanır, süren durumlar `TurnMemory` ile ilk turda yeniden bildirilir (G-4). İlk ağ çağrısında geçersiz kimlik (HTTP 401/400) görülürse Telegram devre dışı bırakılır ve döngü konsol çıktılarıyla sürdürülür (G-5).
- R-8: **Mimari sınırlar ve import kuralları (`docs/architecture.md`).** Bildirim ve rapor gönderimi yalnızca `reporting` modülünün sorumluluğundadır. Diğer modüller (`app`, `risk`, `execution`, `portfolio` vb.) doğrudan Telegram API'sine veya HTTP kütüphanesine bağlanamaz; `scripts/check` sözleşmeleri korunur.

## User experience
none — no user interface. Kullanıcı Telegram istemcisinde bota abone olan chat ID üzerinden tek yönlü metin mesajları alır.
- Flow:
  - Bot başladığında ve Telegram aktif olduğunda sessizce hazır duruma geçer.
  - Kritik bir durum (bayat veri, durdurma vb.) oluştuğunda anında uyarı bildirimi düşer.
  - Alım veya satım gerçekleştiğinde detaylı işlem özeti iletilir.
  - Her yeni UTC gününün ilk tamamlanan turunda günün performans özeti gelir.
  - Ağ kesilirse bot sessizce çalışmaya devam eder; ağ geri geldiğinde kuyruktaki mesajlar iletilir.
- States:
  - Telegram devre dışı (ayar kapalı veya token yok): Telegram'a hiçbir istek atılmaz, konsola yazılır.
  - Telegram devrede / normal: Mesajlar anında iletilir.
  - Telegram devrede / ağ hatası: Hata loglanır, mesaj kuyrukta tutulur, bot çalışmayı sürdürür.
- Design reference: none — the flow above is the design.
- Accessibility: none — standart Telegram istemci erişilebilirliği.

## Constraints & out of scope
- Sensitive area: `Telegram komut yetkilendirmesi / sırlar` (`docs/domain.md`, `docs/security.md`).
- Çift yönlü Telegram komutları (`/durum`, `/durdur`, limit değiştirme, TOTP doğrulama vb.) bu spec'te YOKTUR; bu işlevler `control` modülüne aittir.
- Canlı (live) emir gönderimi veya gerçek borsa API anahtarları kapsam dışıdır (mod `paper`'dır).
- Grafik/görsel oluşturma ve resim olarak gönderme kapsam dışıdır; tüm bildirimler düz metin formatındadır.
- Webhook sunucusu açma veya gelen mesajları dinleme (polling) yoktur; yalnızca dışa doğru HTTPS POST çağrıları yapılır.
- Split değerlendirmesi: Anlık bildirimler ve günlük raporlama tek bir `reporting` yeteneğinde birleştirilmiştir (~8 kriter).
- Self-critique kararları G-1–G-5 (Galip Badem, 2026-11-08) R-3, R-4, R-6, R-7 ve AC-3, AC-4, AC-6, AC-7'ye işlendi.

## Acceptance criteria
- [ ] AC-1 — Yapılandırma ve devre dışı başlangıç (R-1): `enabled = false` veya token / chat ID eksik olduğunda bot hata vermeden başlar; Telegram'a hiçbir ağ çağrısı yapılmaz; bildirimler konsol ve log çıktısına yönlendirilir.
- [ ] AC-2 — Sır güvenliği ve redaksiyon (R-2): Telegram token'ı veya diğer sırlar loglara, hata kayıtlarına veya gönderilen bildirim mesajlarına sızmaz; redaksiyon testle kanıtlanır.
- [ ] AC-3 — Sistem durum bildirimleri ve kaçış güvenliği (R-3): `TurnNotice` olayları için durum başladığında tek bir giriş bildirimi, durum bittiğinde tek bir çıkış bildirimi iletilir; durum süresince mükerrer bildirim gitmez; ayrıştırma hatasında düz metin iletimi güvencesi sağlanır.
- [ ] AC-4 — Kasa ve risk durdurma bildirimleri (B-42, R-4): Kasa drawdown limitine ulaştığında (`HALTED`) ve günlük zarar limiti aşıldığında öneri olup olmamasına bakılmaksızın derhal bildirim iletilir; durum `risk` modülünün public sorgusuyla okunur; günlük zarar limiti sıfırlandığında çıkış bildirimi gider.
- [ ] AC-5 — İşlem olay bildirimleri (R-5): Onaylı alım emri dolduğunda çift, miktar, fiyat ve stop seviyesi; pozisyon kapandığında ise çift, kapanış türü (stop/hedef) ve net gerçekleşen kâr/zarar tutar ve oranıyla bildirim iletilir.
- [ ] AC-6 — Günlük özet raporu (R-6): Yeni UTC gününün ilk tamamlanan turunda gün başı/sonu kasa, net PnL, BR-1 günlük kâr metriği (%20–25 hedef kıyaslaması), açık pozisyon sayısı ve işlem adedini içeren tek bir özet rapor iletilir; aynı gün mükerrer rapor üretilmez.
- [ ] AC-7 — Ağ hatası izolasyonu ve kuyruk dayanıklılığı (B-45, R-7): Telegram API çağrısı zaman aşımına uğradığında veya hata verdiğinde ana döngü kesintiye uğramaz; iletilemeyen mesajlar en fazla 10 mesajlık kuyrukta saklanıp sonraki turlarda denenir; kuyruk taşarsa en eski mesaj atılır; hatalı kimlikte Telegram devre dışı bırakılır.
- [ ] AC-8 — Modül sınırları ve import kuralı (R-8): Telegram gönderimini yalnızca `reporting` modülü yönetir; diğer modüller doğrudan Telegram veya HTTP çağrısı yapamaz; `scripts/check` import-linter sözleşmeleri yeşil kalır.

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
