# Spec 0059 — LLM karar turu: teknik özet, Claude kararı, karar kaydı (paper öncesi)

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0059-plan.md`
- Self-critique: done
- Source: ADR 0005 (LLM karar modu, paper); sahip isteği 2026-11-20

## Intent
Sahip, Claude'un belirlenmiş on coinlik listede teknik özet ve haber skorlarını birlikte değerlendirip "al" kararı ve
fiyat seviyeleri (giriş bölgesi, stop, hedef) vermesini istiyor (ADR 0005). Bu spec o kararın üretilmesini ve
kaydedilmesini kurar: saatte bir, listedeki her coin için teknik özet çıkarılır, tek bir Claude çağrısında karar alınır,
karar doğrulanır ve kayda yazılır; sahibe "al" kararları bildirilir. Başarı: birkaç gün içinde kararların biçimi,
tutarlılığı ve sıklığı görülür. Bilerek yapılmayan: kararlar bu spec'te uygulanmaz (paper defteri ve ölçüm 0060), Claude
pozisyondan çıkış kararı vermez, kararlar hiçbir mevcut botun ya da defterin girdisi değildir.

Clarify kararları (Galip Badem, 2026-11-20, "onaylıyorum"):
- **S-1:** İki spec: 0059 karar turu ve kaydı; 0060 LLM paper defteri, karşılaştırma ve ön kayıtlı hüküm.
- **S-2:** Teknik özet coin başına: son 48 adet 1h mum (açılış, en yüksek, en düşük, kapanış, hacim), son 30 adet 4h mumun
  özeti, EMA 20/50/200, RSI 14, ATR 14 (1h), 24 saatlik ve 7 günlük değişim, son 48 1h mumun en yüksek ve en düşüğü,
  son 24 saatteki olay skorları (0051 skor kaydından); piyasa bağlamı olarak BTC özeti. İndikatörler projenin analiz
  modülüyle hesaplanır; Claude hesap yapmaz.
- **S-3:** Ayrı komut (`decide`), kendi zamanlanmış görevi; her 1h mum kapanışından birkaç dakika sonra. ADR 0004'ün S0
  botuna dokunulmaz.
- **S-4:** Karar coin başına: `al` / `bekle`; `al` için giriş bölgesi (alt, üst), stop, hedef, geçerlilik (en çok 4 saat),
  güven (1–5), en çok 3 maddelik gerekçe (her madde verilen veriye atıf). Tutarsız karar atılır.
- **S-5:** Claude çıkış kararı vermez; çıkış (0060'ta) yalnız stop, hedef ya da süreyle.
- **S-6:** Günde en çok 24 çağrı; çağrı başarısız ya da yanıt şema dışıysa tur kararsız (her coin `bekle`), neden kayıtlı;
  yalıtım 0051/0057 aynen.
- **S-7:** Tur kaydı: girdi özetinin parmak izi, ham karar, doğrulama sonucu, atılma nedeni; `decide status`; Telegram'a
  yalnız `al` kararları, "paper öncesi, uygulanmıyor" işaretiyle.

Self-critique kararları (Galip Badem, 2026-11-20, "tamam" — önerildiği gibi):
- **G-1:** Model `claude-sonnet-5-5` (ayarda); değişirse ölçüm (0060) yeniden başlar.
- **G-2:** İstem ~30–40 KB; fiyatlar coin hassasiyetine yuvarlanır; 64 KB'ı aşarsa önce 4h özeti kısalır.
- **G-3:** İstem ve model parmak izi tur kaydında; 0060'ın ölçümü değişince yeniden sayar.
- **G-4:** Tur 1h mum kapanışından 5 dakika sonra (ayar, vars. 5).
- **G-5:** Geçerlilik tur anından başlar.
- **G-6:** Yeniden sorma ya da "en iyisini seçme" yok; tek yanıt kayda geçer.
- **G-7:** Saatte ~20 herkese açık mum isteği; okunamayan coin yalnız o coin için "veri yok".
- **G-8:** 9 kriter, tek yetenek; bölünmez.

## Tanımlar
- **Liste:** ADR 0005 kural 1'in on coini, USDT spot: BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK, TON.
- **Karar turu:** bir 1h mum kapanışından sonraki tek değerlendirme: özet → tek çağrı → doğrulama → kayıt.
- **Geçerli `al` kararı:** şemaya uyan ve tutarlılık kurallarını geçen `al`.

## Requirements
1. Liste, model, tur zamanı (mum kapanışından sonraki dakika), günlük çağrı sınırı ve kayıt yolları ayardan gelir; liste
   ADR 0005'teki ön kayıtlı listeyle aynıdır (farklıysa ret).
2. Her turda her coin için teknik özet son kapanmış mumlardan çıkarılır (kapanmamış mum kullanılmaz). Bir coinin verisi
   eksik, bayat ya da okunamıyorsa o coin "veri yok" olarak işaretlenir ve Claude'a o coin için karar istenmez.
3. Tur başına tek Claude çağrısı; istem, her coinin özetini ve son 24 saatin olay skorlarını veri olarak (talimat değil)
   taşır, verilen veri dışında bilgiye dayanmamasını ister. Yalıtım, zaman aşımı, kota beklemesi 0051 R-5 ile aynıdır.
4. Yanıt güvenilmeyen girdidir: şemaya uymayan yanıt bütünüyle atılır; şemaya uyan yanıtta her coinin kararı ayrı
   doğrulanır. `al` için: giriş alt ≤ giriş üst; stop < giriş alt; hedef > giriş üst; fiyatlar son 48 1h mumun en
   düşüğünün %20 altı ile en yükseğinin %20 üstü arasında; geçerlilik 1–4 saat; güven 1–5; 1–3 gerekçe maddesi.
   Kuraldan biri bozulursa o coinin kararı "tutarsız" olarak atılır (nedeni kayıtlı), diğer coinler etkilenmez.
5. Tur kaydı yalnız eklenir: tur anı, model ve istem parmak izi, girdi özetinin parmak izi, çağrı sonucu sınıfı, coin
   başına karar (ham alanlar, doğrulama sonucu, atılma nedeni). Ham yanıt metni ve haber metni kayda yazılmaz.
6. Geçerli her `al` kararı için Telegram'a tek mesaj gider (coin, giriş bölgesi, stop, hedef, geçerlilik, güven, gerekçe
   özeti) ve "paper öncesi — uygulanmıyor" işareti taşır; Telegram kapalıysa yalnız satır.
7. `decide status` ağa ve LLM'e çıkmadan son turları, coin başına son kararı, bugünkü çağrı sayısını ve tutarsız/şema
   dışı sayılarını gösterir.
8. Kararlar hiçbir defterin, botun ya da filtrenin girdisi değildir; bot (`app`) karar kaydını okumaz.

## User experience
none — no user interface (komut satırı ve Telegram mesajı; satır biçimleri kriterlerde).

## Constraints & out of scope
- ADR 0005 kural 2–7; ADR 0003 live için aynen.
- Kapsam dışı: kararların uygulanması, paper defteri, karşılaştırma ve hüküm (0060); Claude'un çıkış kararı; listeyi ya
  da sıklığı değiştirmek (yeni ön kayıt); coin başına ayrı çağrı.
- Bot kararları ve ADR 0004 koşusu değişmez.

## Acceptance criteria
- [x] AC-1 — Ayar: liste ADR 0005'teki on coinden farklıysa, model ya da yollar eksikse ya da yollar başka kayıtlarla
  çakışıyorsa `decide` hiçbir çağrı yapmadan alan adıyla reddeder.
- [x] AC-2 — Özet: her coin için özet yalnız kapanmış mumlardan çıkar; 48 adet 1h ve 30 adet 4h mum, EMA 20/50/200,
  RSI 14, ATR 14, 24 saat ve 7 gün değişim, 48 mumun en yüksek/en düşüğü, son 24 saatin olay skorları ve BTC bağlamı
  içerir; verisi eksik ya da bayat coin "veri yok" olur ve karar istenmez.
- [x] AC-3 — Çağrı: tur başına tek çağrı; istem her coinin özetini veri bölümünde taşır; yalıtım ve zaman aşımı 0051 ile
  aynı; günlük sınır dolmuşsa çağrı yapılmaz, tur "sınır" olarak kaydedilir.
- [x] AC-4 — Doğrulama: şemaya uymayan yanıt bütünüyle atılır (her coin `bekle`, neden `şema dışı`); şemaya uyan yanıtta
  R-4'ün her tutarlılık kuralının bozulduğu durum yalnız o coini `tutarsız` yapar, nedeni adıyla.
- [x] AC-5 — Kayıt: her tur yalnız eklenen kayda yazılır (tur anı, parmak izleri, sonuç sınıfı, coin başına karar ve
  doğrulama); ham yanıt ve haber metni kayıtta yoktur; aynı tur iki kez yazılmaz.
- [x] AC-6 — Bildirim: geçerli her `al` için tek Telegram mesajı, "paper öncesi — uygulanmıyor" işaretiyle; `bekle`,
  tutarsız ve şema dışı kararlar bildirilmez.
- [x] AC-7 — Durum: `decide status` ağsız ve LLM'siz son turları, coin başına son kararı, bugünkü çağrı sayısını ve
  tutarsız/şema dışı sayılarını gösterir; kayıt yoksa "henüz tur yok".
- [x] AC-8 — Zamanlama ve durdurma: tur, 1h mum kapanışından ayardaki dakika sonra koşar; Ctrl+C temiz durdurur (çıkış 0),
  ikinci Ctrl+C zorla (130); yarım tur kaydı kalmaz.
- [x] AC-9 — Yalıtım sınırı: bot ve paper defterleri karar kaydını okumaz; `decide` bot deposuna yazmaz (import kuralıyla
  ve testle).

## Definition of Done
- [x] Every acceptance criterion mapped to proof (test or reproducible observation)
- [x] `scripts/check` green
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Docs / ADRs updated if behavior or architecture changed (`docs/commands.md`, `docs/architecture.md`, `docs/security.md`, `docs/domain.md` paper istisnası, örnek ayar)
- [x] Spec moved to `specs/done/` (it becomes immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | 0 (liste ADR 0006 ile değişti: plan A-7) |
| Fix rounds | 2 (review turu 1; VERIFY sonrası TRX ve F-2 testi) |
| Review findings: real / noise / deferred | 7 / 5 / 2 (B-103, B-104) |
| Regressions introduced | 0 |
| Bugs escaped to production | 0 (ship anında) |

## Handoff
Shipped — Galip Badem, 2026-11-20. Liste ADR 0006 ile (TON yerine TRX); ertelenenler B-103, B-104. Sırada 0060
(LLM paper defteri, karşılaştırma, ön kayıtlı hüküm; Claude'un `bekle`si `action='bekle'` ile ayrılır).
