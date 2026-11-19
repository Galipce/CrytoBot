# Spec 0055 — Haber kaynağında AI kullanım izni (mini)

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0055-plan.md`
- Self-critique: done
- Source: B-100 (`specs/backlog.md`; spec 0054 ANALYZE kaynak araştırması)
- Design: none — no user interface
- Supersedes: 0046/AC-9 (kaynak ayarının doğrulaması genişler: CB-1); 0051/AC-1 ve AC-6 (skorlanacak haber ve prompt
  örnekleri izin kaydına bağlanır: CB-2, CB-3); 0053/AC-1 ve AC-4 (izin kaydı olmayan kaynaktan gelen örnek hükme
  girmez, ayrı sayılır: CB-4). `specs/done/` dosyaları değişmez.

## Intent
İleriye dönük haber hattı (0046 toplayıcı, 0051 skorlayıcı, 0053 rapor) yalnız koşulları içeriğin AI tarafından
işlenmesine izin veren kaynakları kullanır; bu izin sahip tarafından kaynak başına, tarih ve dayanakla kayda geçirilir.
Kaydı olmayan kaynak toplanmaz, haberi ve örnekleri Claude'a gitmez, ölçüm hükmüne girmez. Neden şimdi:
Cointelegraph koşulları içeriğin AI sistemlerinde kullanımını yazılı izin olmadan yasaklıyor, CoinDesk `robots.txt`'i
AI ajanlarını engelliyor (2026-11-19 doğrulandı) — iki kaynak şu an hem toplanıyor hem Claude'a veriliyor.
Clarify kararları S-1…S-6 (Galip Badem, 2026-11-19): izin kaydı kaynak ayarında (S-1); toplama da durur (S-2);
Binance istisna değil (S-3); kayıtlar silinmez, skorlayıcı tekrar çağırmaz, rapor hüküm dışı sayar (S-4); yeni kaynak
bu spec'te seçilmez (S-5); sahibin ayarı işletim adımıyla (S-6).

## Tanımlar
- **İzin kaydı:** bir kaynağın ayarında, sahibin o kaynağın koşullarını AI ile işlemeye izin verir bulduğunu yazan
  üç bilgi: doğrulayan (ad), tarih (`YYYY-MM-DD`), dayanak (koşul belgesi ve maddesi; boş olamaz). Kod izin kararı
  vermez, alan adı listesi tutmaz; yalnız kaydın varlığını ve biçimini denetler.
- **İzinli kaynak:** ayarda açık (`enabled = true`) ve geçerli izin kaydı olan kaynak. Ayarda kapalı, kayıtsız ya da
  ayardan çıkarılmış kaynak izinli değildir.

## Changed behavior
- [x] CB-1 — Ayar: açık bir kaynağın izin kaydı yoksa ya da eksik/geçersizse (doğrulayan boş, tarih `YYYY-MM-DD`
  değil ya da gelecekte, dayanak boş) toplayıcı, durum komutu ve skorlayıcı başlamaz; mesaj kaynağın sırasını ve
  alanın adını söyler (0046 AC-9 biçimi), ham değeri yazmaz. Kapalı kaynakta izin kaydı zorunlu değildir; varsa da
  biçimi denetlenir.
- [x] CB-2 — Skorlama: kaynağı izinli olmayan haber için `claude -p` çağrılmaz; haber "izinsiz kaynak" olarak kaynak
  adına göre sayılır, skor kaydına skor yazılmaz ve sonraki turlarda yeniden denenmez (kaynak sonradan izinli olsa da
  — başlangıç anı kuralı, 0051 AC-2, değişmez). Bu kural haber kaydında zaten var olan satırlara da uygulanır. Durum
  komutu kaynak başına "izinsiz kaynak" sayısını ağa ve LLM'e çıkmadan gösterir.
- [x] CB-3 — Prompt örnekleri: örnek kütüphanesi Binance duyurularından oluşur (0048); ayarda `binance-duyuru` türünden
  en az bir izinli kaynak yoksa prompta örnek girmez ve prompt bunu "örnek yok" olarak yazar (0051 AC-6'nın boş
  bağlam hali). İzinli `binance-duyuru` kaynağı varken örnek seçimi 0051 AC-6 ile aynıdır.
- [x] CB-4 — Rapor: ileriye dönük rapor (0053) kaynağı izinli olmayan haberden gelen olumsuz olay skorunu örnek
  saymaz; hiçbir orana, sayıya, hüküm şartına (90 gün / 30 örnek) girmez; raporda kaynak adına göre "izinsiz kaynak,
  hüküm dışı" satırında sayılır. İzinli kaynağın örneklerinde 0053'ün bütün kuralları aynıdır.
- [x] CB-5 — Örnek ayar (`crytobot-news.example.toml`): `coindesk` ve `cointelegraph` kaynakları yoktur; izin kaydı
  doğrulanmamış hiçbir kaynak açık değildir; izin kaydının üç alanı ve anlamı yorumda açıklanır; açıklamalı, kapalı
  (yorum satırında) bir `rss` kaynak örneği adres içermeden durur. Örnek ayar dosyası CB-1 doğrulamasından geçer.

## Preserved behavior
- [x] PB-1 — İzinli kaynak: izinli bir `binance-duyuru` ve izinli bir `rss` kaynağıyla toplama (0046 AC-1, tek tur)
  ve skorlama (0051 AC-1, bir `binance-duyuru` ve bir `rss` haberi skorlanır) bugünkü gibi çalışır; skor kaydının
  biçimi değişmez.
- [x] PB-2 — Kayıtlar değişmez: haber kaydındaki satırlar (CoinDesk ve Cointelegraph dahil) silinmez ve değişmez;
  skor kaydındaki geçmiş skorlar silinmez ve değişmez; kayıt biçim sürümleri aynıdır. Yeni kural yalnız okurken
  uygulanır.
- [x] PB-3 — Diğer ayar ret kuralları (0046 AC-9, 0051 AC-8, 0053 AC-10) aynı mesajlarla çalışır; izin kaydı alanları
  dışındaki bilinmeyen anahtar yine reddedilir.
- [x] PB-4 — Sınırlar: durum komutları ve rapor ağa ve LLM'e çıkmaz, kilit almaz (0051 AC-9, 0053 AC-9); gölge mod
  (0051 AC-7) aynıdır: bot, `calibrate`, `events`, toplayıcı ve arşiv komutu skor kaydını okumaz.

## Constraints & out of scope
- Sensitive area: yok (para, emir, live dokunulmaz). Uyum riski: yüksek (B-100).
- **İşletim adımı (repo dışı, sahip):** sahibin makinesindeki `crytobot-news.toml`'da `coindesk` ve `cointelegraph`
  hemen `enabled = false` yapılır (ship beklenmez). **Binance kararı (A; Galip Badem, 2026-11-19):**
  `binance.com/robots.txt` `*/bapi/` yolunu AI tarayıcıları dahil bütün ajanlara kapatıyor, bölgesel koşullar
  bot/crawler ile erişimi yasaklıyor; AI kullanımına izin veren dayanak bulunmadı. `binance-duyuru` için izin kaydı
  yazılmaz, kaynak da kapatılır. Sonuç bilerek kabul edildi: ship sonrası izinli kaynak yoktur, skorlayıcı çağrı
  yapmaz, prompt örneksizdir, 0053 ölçümü izinli kaynak eklenene kadar ilerlemez. Aday kaynak (SEC, CFTC basın
  akışları) araştırması ayrı nottur. Ship sonrası her açık kaynak izin kaydı ister; kaydı yazılmamış
  açık kaynak toplayıcıyı durdurur (CB-1) — bu bilinçli: sessizce izinsiz toplamaktansa durmak.
- **Out of scope:** yeni kaynak seçimi ve eklenmesi (aday araştırması ayrı not; ekleme sahibin ayar kararıdır);
  0047 arşiv komutu ve 0048 örnek kütüphanesinin kendisi (Claude'a gitmezler; prompta girişleri CB-3 ile kesilir);
  0054 (kendi dışlama listesi var); haber kaydından satır silme; geçmiş skorların yeniden üretilmesi; bot ve strateji.
- Hüküm şartları gevşetilmez (0051 S-1, ADR 0003): CB-4 örneği daraltır, şart sayıları aynıdır; daralma raporda
  görünür.
- Self-critique kararları (2026-11-19): bütün kaynaklar kapalıyken toplayıcının boş tur davranışı (`kaynak=0/N`)
  olduğu gibi kalır, kriter olmaz; raporun haber ayarını okuması yeni girdidir, 0053 yol çakışması kurallarının ona
  uygulanması PLAN'da Risk olarak çözülür; "gelecek tarih" UTC bugüne göre denetlenir, PLAN'da yazılır.
- Size: 5 CB + 4 PB = 9 kriter, tek kullanıcı yeteneği ("izinli kaynak" kuralı); bölünme önerilmez.

## Definition of Done
- [x] `scripts/check` green
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Criterion ↔ evidence table complete for CB-* **and** PB-* (UI: before/after screenshots, agent-captured, judged at SHIP)
- [x] Spec moved to `specs/done/` (immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | 0 |
| Fix rounds | 2 (fix-1: review M-1, L-1, I-1; fix-2: VERIFY F-1, yalnız test) |
| Review findings: real / noise / deferred | 4 / 1 / 0 (review 1. tur: M-1, L-1, I-1 real, I-2 noise; 2. ve 3. tur clean; VERIFY: F-1 real) |
| Regressions introduced | 0 |
| Bugs escaped to production | 0 (ship anında) |

## Handoff
Shipped — Galip Badem, 2026-11-19 ("devam et"). İşletim adımı (S-6): sahip makinesindeki `crytobot-news.toml`'da
izinsiz kaynaklar kapatılır; yoksa yeni sürümde toplayıcı açılışta reddeder.
