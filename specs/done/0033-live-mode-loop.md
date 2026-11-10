# Spec 0033 — Canlı Mod Döngüsü ve Bakiye Mutabakatı

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0033-plan.md`
- Self-critique: done

## Intent
Sistemin sahibi, Spec 0032 ile hazırlanan Binance spot canlı borsa adaptörünü (`LiveExchange`) ve API kimlik denetimlerini kullanarak botun gerçek piyasada küçük sermayeyle çalışmasını (`app` canlı mod döngüsü) ve işlemlerini borsa serbest bakiyesiyle mutabakat içinde yürütmesini istiyor. Başarı; botun `crytobot.toml`'daki `mode = "live"` ayarı ve açık `--live` komut satırı bayrağıyla başlatılabilmesi, `python -m crytobot prepare --live` komutunun Binance serbest USDT bakiyesini doğrudan borsadan sorgulayarak defteri bu bakiye ile canlı modda açması, `[stage]` altındaki BR-10 canlı aşama onay alanlarını (`live_approved_by`, `live_approved_at`) doğrulaması, her tur başında borsa serbest USDT bakiyesi ile yerel defter bakiyesini mutabakat (reconciliation) ederek toleransı (≤ 0.05 USDT) aşan farklarda veya bakiye sorgusu hatalarında BR-11 uyarınca yeni alımları durdurması (`RECONCILIATION_HALT`), risk onaylı emirleri `LiveExchange` üzerinden `LIVE` mod ile gerçek borsaya iletmesi, borsa hata ve yasaklarında fail-closed davranması ve paper/live depolarının birbirine karışmasını (`mode_mismatch`) engellemesidir. Bilerek yapılmayanlar: Para çekme (withdrawal) veya transfer yeteneği (asla hiçbir kod yolunda olmayacaktır); borsada koşullu stop emri (Exchange stop-loss, B-51 — sonraki iş); Telegram üzerinden canlı mod başlatma veya canlı/paper anahtarlama (yalnızca yerel CLI kontrolü); kaldıraçlı/marjin işlem (yalnızca spot); LLM tabanlı haber/whitepaper sinyalleri (Faz 3).

## Requirements
Terimler:
- **Canlı Mod Döngüsü (`live loop`):** `app` seviyesinde, gerçek borsa adaptörü (`LiveExchange`) ile çalışan, `mode="live"` olarak işaretlenmiş turları aralık sınırlarında atan döngü.
- **Canlı Depo (`live store`):** SQLite üzerinde modu `LIVE` olarak kaydedilmiş, defter ve emir geçmişi canlı işlemleri temsil eden kalıcı depo.
- **Bakiye Mutabakatı (`balance reconciliation`):** Yerel defterdeki serbest USDT bakiyesi ile Binance Spot hesabındaki kullanılabilir (free) USDT bakiyesinin karşılaştırılması.
- **Mutabakat Toleransı (`reconciliation tolerance`):** Küçük komisyon/yuvarlama farkları nedeniyle defter ile borsa arasında izin verilen maksimum sapma eşiği (≤ 0.05 USDT).
- **Mutabakat Engeli (`RECONCILIATION_HALT`):** Borsa bakiyesi ile yerel bakiye arasındaki farkın toleransı aşması veya bakiye sorgusunun başarısız/belirsiz olması durumunda yeni alımları engelleyen BR-11 güvenli mod durumu.
- **BR-10 Canlı Aşama Kapısı:** Canlı moda geçiş için `[stage]` ayarlarında yer alan insan onayı ve tarih doğrulaması (`live_approved_by`, `live_approved_at`).

Davranış:
- R-1: **Çift Kilitli Canlı Başlatma (Dual-Lock Start).** Canlı mod döngüsü yalnızca `crytobot.toml` dosyasında `[bot] mode = "live"` (varsayılan "paper") ayarı mevcutken VE CLI başlatma komutuna `--live` bayrağı (`python -m crytobot start --live`) birlikte verildiğinde başlatılır. İkisinden biri eksik veya birbiriyle çelişkili ise (ör. config "live" iken bayrak yoksa veya bayrak varken config "paper" ise) bot başlamaz; `MODE_MISMATCH` veya `LIVE_FLAG_REQUIRED` ile adıyla reddeder.
- R-2: **Canlı Depo Hazırlığı (`prepare --live`).** `python -m crytobot prepare --live` komutu, borsa kimlik bilgilerini yükler (`load_credentials`), yetkilerini doğrular (`verify_permissions`), Binance serbest USDT bakiyesini sorgular ve bu bakiye ile depoyu `LIVE` modunda oluşturup defteri açar. Depo zaten varsa veya borsa bakiyesi pozitif sayı değilse işlem reddedilir ve depoya dokunulmaz. Canlı hazırlıkta config'teki `opening_balance` aranmaz/kullanılmaz; borsa bakiyesi esastır. `prepare` komutuna `--live` verilmediğinde mevcut paper hazırlık davranışı aynen korunur.
- R-3: **Depo ve Mod Doğrulaması (Fail-Closed).** Canlı mod başlatıldığında hedef SQLite deposunun modu `LIVE` olmak zorundadır. Depo `PAPER` modunda ise veya depo yoksa bot başlamaz, `MODE_MISMATCH` adıyla reddeder. Tersine, paper mod başlatıldığında depo `LIVE` ise paper başlatma da reddedilir.
- R-4: **BR-10 Canlı Aşama Kapısı Doğrulaması.** Canlı başlatma sırasında `[stage]` bölümünde `live_approved_by` ve `live_approved_at` ayarları aranır. Herhangi biri eksik, boş veya geçersiz ISO-8601 UTC tarih ise bot başlamaz, ilgili ayar adıyla reddeder (`stage.live_approved_by` / `stage.live_approved_at`).
- R-5: **Borsa Kimlik ve Yetki Kapısı.** Canlı başlatma sırasında API anahtarları `.env` / ortam değişkenlerinden yüklenir (`load_credentials`). `verify_permissions` ile para çekme yetkisi olmadığı (`WITHDRAWAL_PERMISSION_FORBIDDEN`) ve spot işlem yetkisinin açık olduğu doğrulanır. `[exchange] testnet = true` ayarlandığında canlı döngü Binance Spot Testnet uç noktalarına bağlanır, `BINANCE_TESTNET_API_KEY`/`SECRET` kullanılır ve konsol/kayıt çıktısında testnet olduğu açıkça bildirilir. Herhangi bir yetki sorunu veya eksik kimlik bilgisi başlatmayı fail-closed durdurur.
- R-6: **Tur Başı Bakiye Mutabakatı (Reconciliation).** Canlı modda her tur başlamadan önce Binance serbest USDT bakiyesi sorgulanır. Defter serbest bakiyesi ile borsa serbest bakiyesi karşılaştırılır:
  - Bakiye farkı mutlak değerce ≤ 0.05 USDT ise: Mutabakat başarılı sayılır; defter bakiye geçmişinin değişmezliği (Domain invariant) korunarak deftere suni düzeltme kaydı atılmaz; fark loga not edilerek tura devam edilir.
  - Bakiye farkı > 0.05 USDT ise: BR-11 uyarınca güvenli moda geçilir (`RECONCILIATION_HALT`). Yeni alımlar derhal durdurulur, durum konsola ve kayda yazılır, bildirim üretilir. Mevcut açık pozisyonların izlenmesi ve stop/kapanış yönetimi devam eder.
  - Bakiye sorgusu ağ hatası veya borsa 5xx nedeniyle başarısız olursa: BR-11 uyarınca yeni alımlar engellenir (`BALANCE_CHECK_FAILED` / güvenli mod).
  - Yeniden başlatmada (`start --live`): İlk tur öncesi depodan durum yüklendiğinde, önce durumu `UNKNOWN` olan emirler `query_order` ile borsada çözülmeye çalışılır, ardından bakiye mutabakatı işletilir.
- R-7: **Canlı Emir İletimi ve LiveExchange Entegrasyonu.** Canlı mod turlarında `app` bileşenleri (`run_turn`, `_buys`, `_closes`), `LiveExchange` adaptörünü kullanır ve emir isteklerine (`OrderRequest`, `CloseOrderRequest`) `mode = LIVE` parametresini iletir. Emir dolumları borsadan gelen `OrderStatus.FILLED`, retler `REJECTED`, belirsizlikler `UNKNOWN` olarak işlenir.
- R-8: **Bilinmeyen Emir ve Güvenli Mod.** İletilen veya sorgulanan bir canlı emir `UNKNOWN` durumda kalırsa, bot güvenli moda geçer ve emir `query_order` ile borsada çözümlenene kadar yeni alım açmaz. Çözülemeyen bilinmeyen emir varken bakiye mutabakatı da güvenli tarafta kalarak yeni alımları engeller.
- R-9: **Borsa Hata ve Yasak Koruması (BR-11, Rate Limit & Banned).** Canlı okuma ve emir adımlarında borsa 429 yanıtı verirse `Retry-After` süresi boyunca beklenir. 418 (Banned) hatası alınırsa bot fail-closed olarak temiz durdurmaya geçer (`BannedError`).
- R-10: **Temiz Durdurma ve Süreç Kilidi.** Canlı bot Ctrl+C veya SIGINT/SIGTERM ile temiz durdurulur (mevcut tur biter, depoya durum yazılır, kilit serbest bırakılır). Canlı depoya ait kilit (`.lock`) ve durdurma bayrağı (`.stop`) bağımsız çalışır.

## User experience
none — no user interface. Kullanıcı konsol komutlarını ve metin loglarını görür.
- Flow:
  - Hazırlık: `.env` dosyası hazırlanır → `python -m crytobot prepare --live` ile borsa bakiyesi sorgulanıp canlı depo açılır.
  - Başlatma: `crytobot.toml` dosyasında `[bot] mode = "live"` ve `[stage]` canlı onayları yazılır → `python -m crytobot start --live` ile bot başlatılır.
  - Çalışma: Bot her tur başında bakiye mutabakatı yapar → taze piyasa verisiyle analiz ve risk denetimi yürütür → onaylı emirleri `LiveExchange` ile borsaya gönderir.
  - Durdurma: Ctrl+C ile tur bitiminde güvenle durdurulur.
- States:
  - Başlatma reddedildi: bayrak/config mod uyumsuzluğu (`MODE_MISMATCH` / `LIVE_FLAG_REQUIRED`).
  - Başlatma reddedildi: canlı aşama kapısı onaysız (`stage.live_approved_by` / `stage.live_approved_at`).
  - Başlatma reddedildi: API anahtarı eksik veya para çekme yetkisi açık (`WITHDRAWAL_PERMISSION_FORBIDDEN`).
  - Başlatma reddedildi: depo modu uyuşmuyor (`store is paper, expected live`).
  - Başarılı canlı başlangıç ve bakiye mutabakatı.
  - Mutabakat engeli / güvenli mod (`RECONCILIATION_HALT`).
  - Bakiye sorgusu hatası / güvenli mod (`BALANCE_CHECK_FAILED`).
  - Başarılı canlı emir dolumu (`FILLED`).
  - Belirsiz emir / güvenli mod (`UNKNOWN`).
  - Borsa yasağı / durma (418 Banned).
- Design reference: none — the flow above is the design.
- Accessibility: yalnız klavye; renk bilgi taşımaz.

## Constraints & out of scope
- Sensitive area: `Paper ↔ live mod anahtarı`, `Emir gönderimi (execution)`, `API anahtarları / sırlar`, `Portföy / defter (portfolio)`, `Kalıcı durum (persistence)` — `docs/domain.md`.
- Out of scope:
  - Açık pozisyon kripto varlık (coin) bakiye mutabakatı (dust/küsurat ve borsa dışı transfer karmaşıklığı nedeniyle V1 kapsamı dışıdır; serbest USDT mutabakatı esastır — B-60).
  - Borsada şartlı stop emri (Exchange stop-loss, B-51) — sonraki iş.
  - Para çekme (withdrawal — hiçbir zaman desteklenmez).
  - Telegram üzerinden canlı mod başlatma veya canlı/paper anahtarlama (yalnızca CLI).
  - Web panosundan canlı işlem komutu (web panosu salt okunurdur, ADR 0002).
  - Çoklu borsa veya birden fazla hesap desteği.
- Boyut: 8 kabul kriteri. Propose split: Gerek yok; canlı mod başlatma, bakiye mutabakatı ve `LiveExchange` entegrasyonu tek bir kullanıcı yeteneğini ("botun canlı modda çalışması") oluşturur.

## Acceptance criteria
- [x] AC-1 — Çift kilitli canlı başlatma (R-1, R-3): `mode = "live"` ayarı ve `--live` bayrağı birlikte verilmediğinde (yalnız biri verildiğinde veya hiçbiri verilmediğinde) bot canlı modda başlamaz; `MODE_MISMATCH` veya `LIVE_FLAG_REQUIRED` ile adıyla reddeder. Paper depoyla canlı başlatma, canlı depoyla paper başlatma reddedilir.
- [x] AC-2 — Canlı depo hazırlığı (R-2): `python -m crytobot prepare --live`, `.env`'den anahtarları yükler, borsa serbest USDT bakiyesini sorgular, defteri bu bakiye ile açar ve depoyu `mode="live"` olarak kaydeder. Depo zaten varken hiçbir şey yazmadan reddeder. `--live` bayrağı olmadan eski paper hazırlık davranışı bozulmaz.
- [x] AC-3 — BR-10 canlı aşama kapısı denetimi (R-4): Canlı başlatma sırasında `[stage]` içinde `live_approved_by` veya `live_approved_at` eksik veya geçersizse bot başlamaz, ilk sorunlu ayar adıyla söylenir.
- [x] AC-4 — Kimlik ve yetki güvenlik kapıları (R-5): Canlı başlatmada API anahtarı eksikse (`CREDENTIALS_MISSING`), para çekme yetkisi açıksa (`WITHDRAWAL_PERMISSION_FORBIDDEN`) veya spot işlem yetkisi kapalıysa bot fail-closed olarak başlamayı reddeder.
- [x] AC-5 — Tur başı bakiye mutabakatı (R-6): Canlı mod turunda borsa serbest USDT bakiyesi ile yerel defter serbest bakiyesi karşılaştırılır. Fark ≤ 0.05 USDT ise tur normal devam eder; fark > 0.05 USDT ise bot `RECONCILIATION_HALT` ile güvenli moda geçer, yeni alımları durdurur ve bildirim üretir. Borsa bakiye sorgusu başarısız olduğunda da yeni alımlar engellenir.
- [x] AC-6 — Canlı emir iletimi ve döngü entegrasyonu (R-7, R-8): Canlı mod turlarında `run_turn`, `_buys` ve `_closes` `LiveExchange` adaptörünü kullanır; emirler `mode=LIVE` ile iletilir; `FILLED` emirler deftere ve pozisyonlara doğru işlenir; `UNKNOWN` kalan emirlerde bot güvenli moda geçer ve `query_order` çözene kadar yeni işlem açmaz.
- [x] AC-7 — Borsa rate limit ve ban yönetimi (R-9): Canlı döngüde borsa 429 verdiğinde `Retry-After` süresince bekler; borsa 418 (`BannedError`) verdiğinde bot fail-closed temiz durmaya geçer.
- [x] AC-8 — Canlı temiz durdurma ve süreç kilidi (R-10): Canlı modda çalışan bot Ctrl+C veya durdurma isteği aldığında mevcut turu tamamlar, durumu kaydeder, `.lock` kilidini çözer ve temiz çıkar. İkinci durdurma isteğinde `ForcedStop` ile anında çıkar.

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
| Fix rounds | 2 (fix-1: F-1..F-3, fix-2: F-4) |
| Review findings: real / noise / deferred | 3 / 0 / 0 (Round 1: 3 real [fix-1]) |
| Regressions introduced | 1 (F-4: Fix-1 F-3 kağıt modu ipucu regresyonu; fix-2 ile çözüldü) |
| Bugs escaped to production | 0 (henüz üretim yok) |

DoD'nin `scripts/check` kutusu koşullu işaretlendi (`doctor`, `specs/done/`'da işaretsiz kriteri reddediyor); koşul bu PR'ın `check` ve `doctor` işleridir, yeşil olmadan merge yapılmaz (`docs/testing.md`, Two speeds, rule 10). VERIFY @`4f07b79`: adı geçen testler hızlı profilde yeşil, 8 kasıtlı bozmanın 8'i kırmızı; full kanıt bu PR'ın CI koşusudur.
