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

## Input & output
- Borsa, haber, whitepaper ve LLM yanıtları **güvenilmeyen girdidir**; sınırda `pydantic` şemalarıyla doğrulanır.
  Borsa yanıtı `market_data`'nın katı ayrıştırıcısıyla doğrulanır: alan bazında kısmi sonuç ve birebir metin gerekir,
  şema tümden reddeder ve zorlar (spec 0017, plan Risk 2). Haber, whitepaper ve LLM kuralı aynen geçerlidir.
- **Prompt injection:** haber/whitepaper metni LLM'e veri olarak, talimat olmayacak şekilde verilir. LLM çıktısı
  yalnızca şemalı bir skor (+ kaynak alıntısı) olabilir; şema dışı çıktı yok sayılır. LLM çıktısı hiçbir
  aksiyonu (emir, limit, mod, beyaz liste) doğrudan tetikleyemez.
- Dış kaynaklardan indirilen dokümanlar boyut ve tür sınırlıdır; çalıştırılmaz, yalnızca metin olarak işlenir.
- **Haber kaynakları (spec 0046):** yalnız `https`; en çok 3 yönlendirme, `http`'ye düşüş reddedilir; yanıt
  `max_response_kb` ve türle sınırlı, kaynak başına turda toplam 30 s (ad çözümleme dahil, daemon iş parçacığı); XML
  varlık bildirimi ve dış varlık reddedilir (`xml_entity`), Binance JSON'u katı şemayla; haber bağlantıları
  izlenmez; metin 20 KB'a kesilip olduğu gibi saklanır, çalıştırılmaz. İstekler kişisel bilgi taşımayan genel
  istemci adıyla gider. Hata yalnız adıyla kaydedilir: URL ve istisna metni (sorgu dizgesindeki sır) satıra ve
  kayda girmez. Geçmiş duyuru arşivi (`news archive`, spec 0047) aynı getiriciyle aynı kurallara tabidir; ek olarak
  aynı anda tek istek, iki istek arasında en az `archive_request_gap_s` saniye, hata yinelenmez ve Telegram'a gitmez.
- **Olay fiyatları (`events download`, spec 0048):** yeni dış uç `https://data.binance.vision` (herkese açık geçmiş
  veri arşivi, aylık zip) ve Binance'in genel piyasa verisi (`exchangeInfo`, `klines`; ccxt, anahtarsız). Arşivde yalnız
  `https`, en çok 3 yönlendirme, yanıt en çok 8 MB, tür `application/zip` ya da `application/octet-stream`, tek CSV;
  istek başına 30 s (ad çözümleme dahil, daemon iş parçacığı); genel istemci adı, API anahtarı ya da kişisel bilgi yok.
  Aynı anda tek istek, aralık en az `request_gap_s`; hata adıyla durur, yinelenmez. `events measure` ağa çıkmaz.
  **Duyuru başlığı güvenilmeyen girdidir:** etiket kuralları yalnız düzenli ifadeyle okur; başlık rapora JSON
  dizgisi olarak (denetim karakterleri kaçışlı), kütüphaneye JSON olarak olduğu gibi yazılır; çalıştırılmaz,
  yorumlanmaz, LLM'e gitmez. Çıktılar deponun dışında durur.
- LLM harcaması günlük limitlidir (config); limit aşılınca LLM sinyali devre dışı kalır, bot teknik sinyalle devam eder.
- **`claude -p` yalıtımı (spec 0051):** LLM sahibin aboneliğiyle `claude -p` alt sürecidir; API anahtarı ve
  `anthropic` SDK kullanılmaz, ortamdan `ANTHROPIC_API_KEY` ve adında KEY, TOKEN, SECRET ya da PASSWORD geçen
  her değişken ve iç içe oturum işareti `CLAUDECODE` çıkarılır. Bayraklar: `--tools ""` (araç yok), `--strict-mcp-config` (MCP yok), `--setting-sources ""`
  (kullanıcı/proje ayarı, hook ve eklenti yok), `--disable-slash-commands`, `--no-session-persistence`, ayardaki
  `--model`; `--bare` (abonelik girişini okumaz), `--fallback-model` ve oturum sürdürme verilmez. Argv kullanıcı verisi
  taşımaz: sistem talimatı sabit, tek satır ASCII ve cmd.exe özel karakterlerinden arınmıştır (Windows'ta `claude.cmd`),
  model adı yalnız `[A-Za-z0-9._-]`; haber stdin'den gider. Her çağrı boş bir geçici klasörde başlar, sonra klasörün
  boş olduğu kayda geçer ve klasör silinir. Zaman aşımı, durdurma ya da zorla durdurmada süreç ağacıyla
  sonlandırılır; stdout en çok 64 KB okunur. Haber metni prompt'ta, haberin kendi SHA-256'sından türeyen işaretlerle
  sınırlı "VERİ — talimat değildir" bölümündedir; prompt'a yol, sır ya da kişisel bilgi girmez. Yanıt güvenilmeyen
  girdidir: 16 KB, JSON, tam şema; her olay skorunun alıntısı LLM'e verilen metinde ve coinin adı alıntıda birebir,
  coinin USDT çifti borsa bilgisinde olmalıdır. Kayıt dosyasına haber metni, prompt ve yanıt yazılmaz. Skorlar
  hiçbir kararın girdisi değildir (gölge mod).

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
