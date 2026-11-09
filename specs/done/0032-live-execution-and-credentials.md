# Spec 0032 — Borsa API anahtar yönetimi ve ccxt Binance spot live execution adaptörü

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0032-plan.md`
- Self-critique: done

## Intent
Sistemin sahibi, CrytoBot'un bugüne kadar yalnızca simüle ortamda (`paper`) çalışan onaylı emir iletim mekanizmasını (`execution`), ADR 0002 Faz 2 yol haritası uyarınca gerçek Binance spot piyasasında küçük sermayeyle çalıştırabilmek ve borsa API anahtarlarını güvenli biçimde yönetmek istiyor. Başarı; canlı mod (`live`) için gerekli Binance API anahtarı ve gizli anahtarının (secret) repoya, loglara veya hata mesajlarına sızmadan güvenli yerel ortam değişkenlerinden (`.env`) okunabilmesi; bot başlarken anahtar yetkilerinin doğrulanması (para çekme / withdrawal yetkisi tespit edilirse sistemin derhal fail-closed olarak çalışmayı reddetmesi); `execution` modülü altında `ccxt` tabanlı bir canlı borsa adaptörü (`LiveExchange`) ile risk onaylı emirlerin (`clientOrderId` korunarak) gerçek Binance spot piyasasına iletilmesi ve durumunun (`FILLED`, `REJECTED`, `UNKNOWN`) güvenli şekilde sorgulanabilmesidir. Bilerek yapılmayanlar: Para çekme (withdrawal) veya transfer yeteneği (asla hiçbir kod yolunda olmayacaktır); bot döngüsünün canlı modda başlatılması ve bakiye mutabakatı (bu mekanizma BR-10 aşama kapısı ile Spec 0033'ün konusudur); kaldıraçlı/marjin işlem (yalnızca spot); web panosu veya Telegram üzerinden API anahtarı düzenleme veya girme.

## Requirements
Terimler:
- **Borsa Kimlik Bilgileri (Exchange Credentials):** Canlı borsa API'sine erişim için gerekli API Key ve API Secret ikilisi. Yalnızca ortam değişkenlerinden veya `.env` dosyasından okunur; asla repoya, config dosyasına veya loglara yazılmaz.
- **Canlı Borsa Adaptörü (`LiveExchange`):** `execution` modülü altında, onaylı emir isteklerini gerçek Binance Spot API'sine ileten ve emir durumunu sorgulayan bileşen.
- **Para Çekme Koruması (Withdrawal Guard):** Botun API anahtarının para çekme (`withdraw`) yetkisi taşıyıp taşımadığını doğrulayan, bu yetki varsa veya doğrulanamıyorsa çalışmayı derhal reddeden güvenlik kuralı.
- **Deterministik Borsa Kimliği (`clientOrderId`):** Emirlerin mükerrer iletilmesini borsa seviyesinde önlemek amacıyla botun ürettiği tekil kimlik (`cb-<id>` alım için, `cx-<id>` kapanış için).
- **Belirsiz Emir Durumu (`UNKNOWN`):** Ağ kesintisi, zaman aşımı veya borsa 5xx hatalarında emrin borsada oluşup oluşmadığının bilinmemesi durumu; güvenli modu tetikler (BR-11).
- **Maskeleme (Redaction):** API anahtarlarının ve sırlarının herhangi bir string dönüşümünde (`str`, `repr`), logda veya hata mesajında `***REDACTED***` olarak gizlenmesi.

Davranış:
- R-1: **Kimlik Bilgilerinin Güvenli Yüklenmesi (Credentials Loading).** Canlı mod (`live`) istendiğinde API anahtarı ve gizli anahtar (secret) yalnızca ortam değişkenlerinden (`BINANCE_API_KEY`, `BINANCE_API_SECRET`) veya kökteki `.env` dosyasından okunur. `crytobot.toml` config dosyasında anahtar aranamaz veya kabul edilemez. Anahtarlar eksik veya boşsa canlı adaptör başlatılamaz, anlaşılır hata ile reddedilir (`CREDENTIALS_MISSING`).
- R-2: **Para Çekme (Withdrawal) Yetki Guard'ı (Fail-Closed).** Canlı borsa adaptörü başlatılırken (veya ilk bağlantıda) borsa API'sinden anahtar yetkileri sorgulanır. Anahtarın para çekme (`withdraw` / `enableWithdrawals`) yetkisi etkinse VEYA borsa yetkileri doğrulanamıyorsa (belirsiz yanıt, API hatası), adaptör başlatılmaz ve bot fail-closed olarak `WITHDRAWAL_PERMISSION_FORBIDDEN` (veya `PERMISSION_CHECK_FAILED`) ile çalışmayı durdurur.
- R-3: **Spot Piyasa ve Yetki Kısıtlaması.** Anahtarın spot işlem yetkisinin açık olduğu doğrulanmalıdır; spot yetkisi kapalıysa adaptör `SPOT_TRADING_DISABLED` ile reddeder.
- R-4: **Log ve Hata Redaksiyonu (Masking).** API Key ve Secret değerleri hiçbir log satırında, traceback'te, hata mesajında veya nesne `__repr__` / `__str__` çıktısında açık metin olarak yer alamaz. Ekrana veya loga basılması gereken durumlarda değerler maskelenir (`***REDACTED***`).
- R-5: **Canlı Piyasa Alım Emri (`place_order`).** `execution`'a gelen onaylı alım isteği (`OrderRequest`), canlı borsa adaptörü üzerinden Binance Spot piyasasına piyasa alım emri (`MARKET BUY`) olarak iletilir. İletimde `newClientOrderId` olarak botun `cb-<id>` formatındaki tekil kimliği kullanılır. Borsa emri kabul edip doldurursa `FILLED`, borsa filtreleri (yetersiz bakiye, geçersiz miktar vb.) nedeniyle reddederse `REJECTED`, ağ hatası/zaman aşımı olursa `UNKNOWN` döner.
- R-6: **Canlı Piyasa Kapanış/Satış Emri (`place_close_order`).** `execution`'a gelen onaylı kapanış isteği (`CloseOrderRequest`), canlı borsa adaptörü üzerinden Binance Spot piyasasına piyasa satış emri (`MARKET SELL`) olarak iletilir. `newClientOrderId` olarak `cx-<id>` kullanılır. Dolum, ret ve belirsizlik durumları alım emriyle aynı kurallarla ele alınır.
- R-7: **Emir Durumu Sorgulama (`query_order`).** Durumu `UNKNOWN` olan bir emrin akıbeti, `query_order` ile borsadan `origClientOrderId` kullanılarak sorgulanır. Borsa emri `FILLED` veya `CANCELED`/`EXPIRED` olarak döndürürse durum netleştirilir; borsa "böyle bir emir yok" (`Order does not exist` / -2013) derse ve emir zaman aşımına uğramışsa `REJECTED` sayılır; ağ hatası sürüyorsa `UNKNOWN` olarak kalır ve güvenli mod (BR-11) korunur.
- R-8: **Testnet ve Canlı Ayrımı.** Config'te `[exchange] testnet = true` ayarlandığında canlı adaptör Binance Spot Testnet uç noktalarına bağlanır; testnet açıkken anahtarlar `BINANCE_TESTNET_API_KEY` ve `BINANCE_TESTNET_API_SECRET` ortam değişkenlerinden okunur; canlı anahtarlar testnet modunda kesinlikle kullanılmaz (`docs/security.md`).

## User experience
none — no user interface. Kullanıcı konsol komutlarını ve metin loglarını görür.
- Flow:
  - Ortam hazırlığı: Kullanıcı `.env` dosyasına anahtarları yazar (`BINANCE_API_KEY`, `BINANCE_API_SECRET`).
  - Başlatma: Bot canlı modda çalıştırıldığında kimlik bilgileri yüklenir → anahtar yetkileri borsa üzerinden doğrulanır (withdrawal kapalı, spot açık) → adaptör hazır hale gelir.
  - Emir iletimi: Risk onaylı öneri geldiğinde gerçek borsaya `cb-` kimliğiyle spot piyasa emri iletilir → borsa anında dolum (`FILLED`) veya ret (`REJECTED`) döner.
  - Belirsizlik (Ağ kopması): Zaman aşımında emir `UNKNOWN` kalır → bot güvenli moda geçer → `query_order` ile durum borsa tarafında çözülünceye kadar yeni alımlar durur.
- States:
  - Başarılı kimlik yükleme ve yetki doğrulama.
  - Eksik kimlik bilgisi (anahtar yok — `CREDENTIALS_MISSING`).
  - Yasak yetki (para çekme açık — `WITHDRAWAL_PERMISSION_FORBIDDEN`).
  - Spot yetkisi kapalı (`SPOT_TRADING_DISABLED`).
  - Başarılı borsa emri (`FILLED`).
  - Borsa tarafından reddedilen emir (`REJECTED`).
  - Ağ zaman aşımı / belirsiz emir (`UNKNOWN` / safe mode).
  - Başarılı emir durumu çözümleme (`query_order`).
- Design reference: none — the flow above is the design.
- Accessibility: yalnız klavye; renk bilgi taşımaz.

## Constraints & out of scope
- Sensitive area: `Emir gönderimi (execution)`, `API anahtarları / sırlar`, `Paper ↔ live mod anahtarı` — `docs/domain.md`.
- Out of scope:
  - Bot döngüsünün (`app`) canlı modda başlatılması, bakiye mutabakatı (reconciliation) ve paper->live TOTP aşama geçişi (Spec 0033).
  - Borsada şartlı stop emri (Exchange stop-loss, B-51) — sonraki iş.
  - Para çekme (withdrawal — hiçbir zaman desteklenmez).
  - ccxt haricinde harici kütüphane eklenmesi (ccxt tek runtime bağımlılığıdır).
  - Birim testlerde gerçek ağ çağrısı (tüm birim testler sahte/mock istemcilerle ağsız çalışır).
- Boyut: 8 kabul kriteri. Propose split: Gerek yok; kimlik doğrulaması ve adaptör borsa emir iletiminin ayrılmaz parçalarıdır.

## Acceptance criteria
- [x] AC-1 — Kimlik bilgilerinin güvenli yüklenmesi (R-1, R-8): Canlı modda API anahtarı ve secret yalnızca ortam değişkenlerinden / `.env`'den yüklenir; config dosyasında anahtar aranmaz; eksik veya boş anahtarlarda adaptör `CREDENTIALS_MISSING` ile temiz biçimde reddeder. Testnet ayarlandığında canlı anahtarlar yüklenmez, testnet anahtarları aranır.
- [x] AC-2 — Para çekme (Withdrawal) yetkisi koruması (R-2): API anahtarında para çekme yetkisi tespit edilirse adaptör derhal fail-closed olarak `WITHDRAWAL_PERMISSION_FORBIDDEN` ile başlatılmayı reddeder; yetki sorgusu başarısız veya belirsiz olduğunda da çalışmayı durdurur.
- [x] AC-3 — Spot yetki doğrulaması (R-3): API anahtarında spot işlem yetkisi kapalı ise adaptör `SPOT_TRADING_DISABLED` ile başlatılmayı reddeder.
- [x] AC-4 — Log ve metin redaksiyonu (R-4): API Key ve Secret nesneleri `repr` ve `str` çıktılarında maskelenir (`***REDACTED***`); loglarda ve traceback'lerde açık metin anahtar/secret basılmadığı negatif testle kanıtlanır.
- [x] AC-5 — Canlı piyasa alım emri iletimi (R-5): Onaylı alım isteği (`OrderRequest`) `LiveExchange` üzerinden Binance spot API'sine `newClientOrderId=cb-<id>` ile iletilir; borsa kabul edip doldurduğunda `FILLED`, borsa filtreleri (yetersiz bakiye vb.) nedeniyle reddettiğinde `REJECTED` döner (güvenli moda sokmaz).
- [x] AC-6 — Canlı piyasa kapanış emri iletimi (R-6): Onaylı kapanış isteği (`CloseOrderRequest`) `LiveExchange` üzerinden Binance spot API'sine `newClientOrderId=cx-<id>` ile iletilir; borsa dolum ve ret yanıtları doğru `CloseOrderResult` durumuna eşlenir.
- [x] AC-7 — Ağ hatası ve belirsiz emir (BR-11) (R-5, R-6, R-7): Emir iletimi sırasında borsa zaman aşımı veya ağ hatası verirse emir sonucu `UNKNOWN` döner, bot güvenli moda geçer ve durumu netleşene kadar yeni alımlar engellenir. Borsa 429 (Rate limit) durumunda `Retry-After` süresi korunur; 418 (Banned) durumunda bot fail-closed durur.
- [x] AC-8 — Canlı emir sorgulama (R-7): `query_order`, `UNKNOWN` durumundaki emri borsadan `origClientOrderId` ile sorgular; borsa dolumu teyit ederse `FILLED`, emir borsada hiç oluşmamışsa `REJECTED` döner ve güvenli moddan çıkış bildirimini üretir; ağ hatası sürüyorsa `UNKNOWN` kalır.

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
| Fix rounds | 2 (fix-1: F-1..F-6, fix-2: F-7..F-9) |
| Review findings: real / noise / deferred | 9 / 0 / 0 (Round 1: 6 real [fix-1], Round 2: 3 real [fix-2]) |
| Regressions introduced | 0 (kanıt bu PR'ın full CI koşusu) |
| Bugs escaped to production | 0 (henüz üretim yok) |

DoD'nin `scripts/check` kutusu koşullu işaretlendi (`doctor`, `specs/done/`'da işaretsiz kriteri reddediyor); koşul bu PR'ın `check` ve `doctor` işleridir, yeşil olmadan merge yapılmaz (`docs/testing.md`, Two speeds, rule 10). VERIFY @`c9b78f6`: adı geçen testler hızlı profilde yeşil, 8 kasıtlı bozmanın 8'i kırmızı; full kanıt bu PR'ın CI koşusudur.
