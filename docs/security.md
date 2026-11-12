# Security

> **Template — filled during bootstrap.** Baseline rules agents must honor in every plan and review.

## Secrets
- Secrets never enter the repo, specs, prompts, or chat. `.env` is gitignored; provide `.env.example`.
- Agents never print secret values, even when debugging.

- Sırlar `.env` (gitignore'da) veya işletim sistemi keyring'inde; `.env.example` yalnızca anahtar adlarını içerir.
- Sırlar loglara, raporlara, Telegram mesajlarına, LLM prompt'larına ve hata mesajlarına asla yazılmaz
  (log redaksiyonu testle kanıtlanır).
- **Borsa API anahtarı:** yalnızca okuma + spot işlem yetkisi; **para çekme (withdrawal) yetkisi kapalı**;
  borsa destekliyorsa IP kısıtlaması açık. Bot başlarken anahtar yetkilerini doğrulayabiliyorsa withdrawal
  yetkisi görürse çalışmayı reddeder.
- Testnet, paper ve live için **ayrı anahtarlar**; live anahtarı paper modda yüklenmez.
- **Testnet yetki istisnası (spec 0041 CB-2):** Binance Spot Testnet anahtar kısıtı ucunu sunmaz. Yalnız
  `[exchange] testnet = true` iken (o koşuda yalnız `BINANCE_TESTNET_API_KEY`/`SECRET` yüklenir, istemci sandbox
  modundadır) kısıt sorgusunun yerine testnet anahtarıyla imzalı bakiye sorgusu yapılır; başarısızsa
  `PERMISSION_CHECK_FAILED` ile fail-closed. Mainnet'te yetki denetimi atlanamaz: testnet bayrağı dışında hiçbir
  ayar, argüman ya da ortam değişkeni onu değiştirmez.

## Input & output
- Borsa, haber, whitepaper ve LLM yanıtları **güvenilmeyen girdidir**; sınırda `pydantic` şemalarıyla doğrulanır.
  Borsa yanıtı `market_data`'nın katı ayrıştırıcısıyla doğrulanır: alan bazında kısmi sonuç ve birebir metin gerekir,
  şema tümden reddeder ve zorlar (spec 0017, plan Risk 2). Haber, whitepaper ve LLM kuralı aynen geçerlidir.
- **Prompt injection:** haber/whitepaper metni LLM'e veri olarak, talimat olmayacak şekilde verilir. LLM çıktısı
  yalnızca şemalı bir skor (+ kaynak alıntısı) olabilir; şema dışı çıktı yok sayılır. LLM çıktısı hiçbir
  aksiyonu (emir, limit, mod, beyaz liste) doğrudan tetikleyemez.
- Dış kaynaklardan indirilen dokümanlar boyut ve tür sınırlıdır; çalıştırılmaz, yalnızca metin olarak işlenir.
- LLM harcaması günlük limitlidir (config); limit aşılınca LLM sinyali devre dışı kalır, bot teknik sinyalle devam eder.

## AuthN / AuthZ
- Tek kullanıcı. **Varsayılan: reddet.**
- **Varsayılan mod `paper`.** `live` için config bayrağı **ve** açık onay (CLI'de ya da Telegram'da TOTP + teyit) gerekir.
- **Telegram:** yalnızca config'teki chat ID'den gelen komutlar kabul edilir, diğerleri sessizce reddedilir ve loglanır.
  - Zararsız komutlar (durum, rapor, **kill switch / durdurma**): chat ID yeterli.
  - **Hassas komutlar** (paper↔live mod değişikliği, aşama onayı, strateji aç/kapa, beyaz liste değişikliği):
    chat ID + **TOTP kodu** + "evet/hayır" teyit adımı.
  - Risk limitleri Telegram'dan **yalnızca sıkılaştırılabilir** (dört limitte düşürme, kâr/maliyet katında
    yükseltme); gevşetme yalnızca CLI'den (BR-13).
  - Para çekme ve API anahtarı işlemleri hiçbir kanaldan yoktur.
- Her CLI/Telegram komutu `control` audit log'una yazılır (kim, ne, ne zaman, sonuç) — sır içermeden.
- Kodda sabit risk üst sınırları hiçbir kanaldan aşılamaz.

## Dependencies
- Sürümler `uv.lock` ile sabit; yeni bağımlılık **insan onayı** ister (spec/plan'da gerekçesiyle):
  lisans (MIT/BSD/Apache uyumlu), bakım durumu, bilinen CVE kontrol edilir.
- İstisna: dolaylı bağımlılıkta MPL-2.0, kod değiştirilmeden kullanım kabul (spec 0018).
- `pip-audit` ağ gerektirdiği için `scripts/check` içinde değil, CI'da ayrı adım olarak çalışır.
- Kripto/borsa ile ilgili az bilinen paketler (typosquatting riski) özellikle incelenir.

## Review lens
Security is a mandatory dimension of every independent review (see `prompts/review.md`), not a
separate afterthought phase.
