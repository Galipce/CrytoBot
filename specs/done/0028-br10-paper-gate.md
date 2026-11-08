# Spec 0028 — BR-10 paper başlatma kapısı ve aşama onayı

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0028-plan.md`
- Self-critique: done

## Intent
Botun sahibi, teknik stratejinin geçmiş veride (komisyon ve slippage dahil, örneklem dışı / out-of-sample) kârlı olduğu kanıtlanmadan ve kendisi açık onay vermeden paper botunun kanıtlı modda çalışmasını engellemek istiyor (BR-10, ADR 0002 Faz 1). Bu iş, backtest üçlüsünün son parçası olarak backtest raporundaki metrikleri denetleyen, insan onayını bağlayan ve paper başlatmayı buna tabi kılan BR-10 kapısını kurar. Başarı şöyle görünür: geçerli ve metrik eşiklerini karşılayan bir backtest raporu ile kayıtlı insan onayı olmadan paper botu kanıtlı olarak başlamaz; onay sağlandığında başlatma ve tur kayıtlarından deneme işareti (`TRIAL_MARK`) kalkar; ayar veya strateji uyuşmazlığında kapı botu başlatmayı adıyla reddeder. Bilerek yapılmayanlar: Live mod adaptörü ve live aşama geçişi (ADR 0002 Faz 2'ye aittir); yeni backtest koşusu veya parametre optimizasyonu; web panosu veya Telegram üzerinden onay arayüzü.

## Requirements
Terimler:
- **BR-10 kapısı:** paper botunun başlatılmasını geçerli bir backtest kanıtına ve insan onayına bağlayan güvenlik denetimi.
- **Aşama onayı (stage approval):** insanın ayar dosyasında beyan ettiği, belirli bir backtest raporuna atıfta bulunan, onaylayan adı ve tarihini taşıyan onay kaydı.
- **Kanıtlı koşu:** geçerli backtest raporu ve aşama onayı ile çalışan, deneme işareti taşımayan paper koşusu.
- **Deneme koşusu:** `--trial` bayrağı ile açıkça başlatılan, backtest onayı aramayan, deneme işareti (`TRIAL_MARK`) taşıyan paper koşusu.
- **Rapor kanıtı:** spec 0025'in ürettiği, örneklem dışı parçasında "BR-10 kanıtı adayı" işareti taşıyan, bayt bayt doğrulanabilen backtest rapor dosyası.
- **Metrik eşikleri:** stratejinin paper'a geçebilmesi için örneklem dışı backtest sonuçlarının karşılamak zorunda olduğu asgari performans sınırları (net getiri > 0, drawdown ≤ limit, asgari işlem sayısı, varsa asgari kâr faktörü).
- **Ayar uyumu:** backtest raporunun üretildiği piyasa ve strateji ayarlarının botun güncel ayarlarıyla birebir aynı olması şartı.

Davranış:
- R-1: **Varsayılan başlatma kapısı.** `crytobot start` komutu (veya paper başlatma) varsayılan olarak aşama onayı ve geçerli rapor kanıtı arar. Aşama onayı bulunmayan, eksik olan, raporu geçersiz veya ayarları uyumsuz olan ayar dosyasıyla başlatma hiçbir tur atmadan, borsaya çıkmadan ve depoya dokunmadan adıyla reddedilir.
- R-2: **Aşama onayı ayarları.** Aşama onayı ayar dosyasında `[stage]` bölümünde tutulur. Bölüm şu alanları taşır: `report_path` (rapor dosyasının yolu), `approved_by` (onaylayan kişinin adı/kimliği), `approved_at` (onay anı, UTC ISO formatında). İsteğe bağlı eşik alanları: `min_trades` (pozitif tam sayı, belirtilmezse varsayılan 10) ve `min_profit_factor` (1'den büyük veya eşit oran/metin). Ayarlar dosya sırasıyla ve açık tip/değer denetimiyle doğrulanır; eksik, boş, geçersiz tipli ya da bozuk formatlı her alan ilk sorunlu alanın adıyla reddedilir.
- R-3: **Rapor dosyasının varlığı ve bütünlüğü.** Belirtilen `report_path` yolundaki dosya okunabilir olmak zorundadır. Dosya yoksa, okunamıyorsa, boşsa, tamamlanmamışsa ya da spec 0025 rapor formatına uymuyorsa başlatma adıyla reddedilir. Raporda "örneklem dışı — BR-10 kanıtı adayı" başlıklı bölüm bulunmak zorundadır; bu bölüm yoksa veya aday işareti eksikse başlatma "rapor aday işareti taşımıyor" nedeniyle reddedilir.
- R-4: **Metrik eşiklerinin denetimi.** Kapı, rapordaki örneklem dışı ("BR-10 kanıtı adayı") bölümünün metriklerini denetler:
  - Örneklem dışı net kâr/zarar sıfırdan büyük olmak zorundadır (net getiri > 0). Zararda veya sıfır olan sonuç reddedilir.
  - Örneklem dışı en büyük drawdown, botun `risk.max_drawdown` ayarından (ve kod içi BR-6 tavanı %25'ten) büyük olamaz.
  - Örneklem dışı kapanmış işlem sayısı `stage.min_trades` (varsayılan 10) eşiğinden az olamaz. İşlem yoksa ("tanımsız" oranlar) reddedilir.
  - Eğer `stage.min_profit_factor` tanımlanmışsa, örneklem dışı kâr faktörü "tanımsız" olamaz ve bu değerden küçük olamaz.
  Herhangi bir eşik ihlalinde bot başlatılmaz ve karşılanmayan eşik adıyla söylenir.
- R-5: **Ayar ve evren uyumu.** Raporun başlığındaki koşu bilgileri ile botun güncel ayarları karşılaştırılır:
  - Beyaz liste (`whitelist`) çift kümesi birebir aynı olmak zorundadır (eksik, fazla veya farklı çift olamaz).
  - Mum aralığı (`candle_interval`) ve tur aralığı (`turn_interval`) rapordakiyle aynı olmak zorundadır.
  - Spread değeri (`spread`) rapordakiyle aynı olmak zorundadır.
  - Strateji parametreleri (RSI periyodu ve eşiği, SMA periyotları vb.) rapordakiyle birebir aynı olmak zorundadır.
  Herhangi bir uyuşmazlıkta başlatma "ayar uyuşmazlığı: <ayar_adı>" ile reddedilir.
- R-6: **Deneme modu (`--trial`).** Kullanıcı `crytobot start --trial` komutunu açıkça verdiğinde BR-10 aşama kapısı atlanır. Aşama onayı bulunmayan veya geçersiz olan sistem başlatılır; ancak bu durumda başlatma çıktısı, kayıt dosyasındaki başlatma satırı ve her tur özeti `TRIAL_MARK` ("BR-10 öncesi deneme, strateji kanıtı değil") taşımaya devam eder. Kanıtlı koşuda ise `TRIAL_MARK` kalkar.
- R-7: **Çıktı ve kayıt satırları.**
  - Kanıtlı koşuda başlatma satırı ve kaydı onay kanıtını taşır: `başladı: mod=paper ... onaylı: onaylayan=<ad> rapor=<dosya>`. Tur özetlerinde `— TRIAL_MARK` yer almaz.
  - Deneme koşusunda (`--trial`) başlatma satırı ve tur özetleri bugünkü gibi `— BR-10 öncesi deneme, strateji kanıtı değil` metnini taşır.
- R-8: **Güvenli ret (Fail-closed).** R-1–R-5 kapsamında reddedilen hiçbir durumda paper deposu açılmaz, defter kilitlenmez, borsaya ağ isteği gönderilmez. Ret nedeni konsola açıkça yazılır ve çıkış kodu ret kodu (1) olur.

## User experience
none — no user interface. Kullanıcı yalnız konsol komutunu, konsol çıktısını ve kayıt dosyasını görür. Metinler Türkçedir.
- Flow:
  - Kanıtlı başlatma: backtest koşusu yap → rapor dosyasını incele → ayar dosyasına `[stage]` bölümünü yaz (rapor yolu, onaylayan, tarih) → `crytobot start` → bot onay denetiminden geçer, kanıtlı modda turlarını atar.
  - Deneme başlatma: `crytobot start --trial` → bot BR-10 kapısını atlar, deneme işaretiyle turlarını atar.
- States:
  - Başlatma reddedildi (onay eksik/yok, onay ayarı geçersiz, rapor dosyası yok/bozuk/adayı değil, metrik eşiği yetersiz, ayar uyuşmazlığı).
  - Başlatma başarılı (kanıtlı mod, onay bilgisiyle).
  - Başlatma başarılı (deneme modu, `--trial` ile ve deneme işaretiyle).
- Design reference: none — the flow above is the design.
- Accessibility: yalnız klavye; renk bilgi taşımaz.

## Constraints & out of scope
- Sensitive area: Paper ↔ live mod anahtarı / aşama geçişi (`docs/domain.md`). Mod paper'dır, live'a geçilmez; ancak aşama geçişi (backtest → paper) bu spec ile ilk kez kurala bağlanır.
- `crytobot prepare` (hazırlık) komutu BR-10 kapısına tabi değildir; hazırlık yalnızca boş depoyu açar ve bakiyeyi yazar, tur atmaz ve borsaya çıkmaz (Spec 0022 R-3).
- Live mod, live adaptörü, API anahtarı kullanımı ve paper → live geçiş kapısı kapsam dışıdır (ADR 0002 Faz 2).
- Backtest çalıştırma veya veri indirme bu komuta dahil değildir (0023 ve 0025 komutları kullanılır).
- Web panosu veya Telegram üzerinden onay verme kapsam dışıdır (CLI / ayar dosyası).
- Shipped testlerin beklentileri korunur; botun diğer ayar kuralları (`[history]`, `[backtest]` dahil) bozulmaz.
- SQLite depo şeması değişmez; onay bilgisi depoda değil ayar ve rapor dosyalarında tutulur. Yeniden başlamada her başlatma onay denetimini baştan yapar.
- Coverage: değişen her modül için modül başına %90 branch eşiği geçerlidir (`docs/testing.md`).
- Split: proposed 0028a (onay yükleyicisi ve rapor doğrulama) → 0028b (başlatma kapısı ve --trial); kept as one — Galip Badem, tek kullanıcı yeteneğidir (BR-10 paper başlatma kapısı), rapor doğrulama başlatma kapısından bağımsız kullanılamaz, 8 kriter tek spec sınırındadır.
- Self-critique kararları G-1–G-5 (Galip Badem, 2026-11-08) R-3, R-5, R-6, Constraints ve AC-3, AC-5, AC-7'ye yazıldı.

## Acceptance criteria
- [x] AC-1 — Mutlu yol (Kanıtlı başlatma) (R-1, R-2, R-3, R-4, R-5, R-7): Geçerli bir backtest raporu yolu, onaylayan adı, geçerli onay tarihi ve eşikleri karşılayan metriklerle `[stage]` bölümü tanımlanmış ayar dosyasıyla başlatma başarılı olur. İlk tur hemen atılır. Başlatma çıktısı ve kayıt dosyası onaylayan adını ve rapor yolunu taşır. Tur özetinde "BR-10 öncesi deneme, strateji kanıtı değil" metni yer almaz.
- [x] AC-2 — Varsayılan başlatmada onaysız ret (R-1): `[stage]` bölümü bulunmayan ya da `report_path`, `approved_by`, `approved_at` alanlarından biri eksik olan ayar dosyasıyla varsayılan `crytobot start` çalıştırıldığında başlatma tur atmadan, borsaya çıkmadan ve depoya dokunmadan reddedilir. İlk eksik/sorunlu alan adıyla söylenir.
- [x] AC-3 — Deneme modu (`--trial`) (R-6, R-7): `[stage]` onayı bulunmayan veya geçersiz olan bir ayar dosyasıyla `crytobot start --trial` çalıştırıldığında bot başlar, ilk turu atar. Başlatma satırı ve tur özetleri "BR-10 öncesi deneme, strateji kanıtı değil" (`TRIAL_MARK`) işaretini taşır.
- [x] AC-4 — Onay ayarları geçerliliği (R-2): `approved_by` boş metin veya metin dışı tip; `approved_at` ISO formatında değil, zaman dilimsiz veya geçersiz; `report_path` metin değil; `min_trades` sıfır, negatif veya tam sayı değil; `min_profit_factor` 1'den küçük veya sayıya çevrilemeyen metin/tip olduğunda başlatma reddedilir, ilk sorunlu ayar adıyla söylenir.
- [x] AC-5 — Rapor dosyası varlığı ve aday işareti (R-3): `report_path` yolundaki dosya yoksa, okunamıyorsa, boşsa, bozuksa veya raporda "örneklem dışı — BR-10 kanıtı adayı" başlığı/işareti bulunmuyorsa başlatma tur atmadan reddedilir, neden adıyla söylenir.
- [x] AC-6 — Metrik eşikleri yetersizliği (R-4): Raporun örneklem dışı bölümünde: (a) net kâr sıfır veya negatif (getiri ≤ 0); (b) en büyük drawdown botun `risk.max_drawdown` ayarından yüksek; (c) işlem sayısı `min_trades` eşiğinden az veya sıfır (oranlar tanımsız); (d) tanımlanmışsa kâr faktörü `min_profit_factor`'den düşük veya tanımsız olduğunda başlatma adıyla reddedilir.
- [x] AC-7 — Ayar ve evren uyuşmazlığı (R-5): Raporun koşu ayarlarında yer alan beyaz liste çift kümesi, mum aralığı, tur aralığı, spread veya strateji parametrelerinden herhangi biri botun güncel ayarlarından farklıysa başlatma "ayar uyuşmazlığı: <ayar_adı>" ile reddedilir.
- [x] AC-8 — Depo ve ağ dokunmasızlığı (R-8): R-1–R-5 kapsamında reddedilen hiçbir durumda paper SQLite deposu oluşturulmaz, açılmaz, kilitlenmez, borsaya ağ isteği gitmez. Hata durumunda çıkış kodu ret kodu (1) olur.

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
| Fix rounds | 0 (review clean, fix turu açılmadı) |
| Review findings: real / noise / deferred | 0 / 2 / 1 (F-01 noise, F-02 deferred B-56, F-03 noise) |
| Regressions introduced | 0 (kanıt bu PR'ın full CI koşusu) |
| Bugs escaped to production | 0 (henüz üretim yok) |

DoD'nin `scripts/check` kutusu koşullu işaretlendi (`doctor`, `specs/done/`'da işaretsiz kriteri reddediyor); koşul bu PR'ın `check` ve `doctor` işleridir, yeşil olmadan merge yapılmaz (`docs/testing.md`, Two speeds, rule 10). VERIFY @`f9b26fe`: adı geçen testler hızlı profilde yeşil, 8 kasıtlı bozmanın 8'i kırmızı; full kanıt bu PR'ın CI koşusudur.
