# Spec 0042 — Strateji değerlendirme düzeni

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0042-plan.md`
- Self-critique: done
- Source: ADR 0002 revisit trigger ("out-of-sample backtest maliyet sonrası kârsız → Faz 2'den önce strateji işi"); spec 0041 CB-6'nın beklediği kârlı paper kanıtı
- Design: —
- Supersedes: 0025 R-9/R-10'un varsayılan rapor kısmı (varsayılan rapor yalnız örneklem içini yazar; örneklem dışı, saklı dönem ve tüm koşu yalnız son değerlendirmede); 0028 R-3'ün kapı kısmı (kapı yalnız son değerlendirme raporunu kabul eder). Plan 0042 Risk 3 — Galip Badem, 2026-11-12.

## Intent
Botun sahibi, canlıya geçmeden önce maliyetler düşüldükten sonra kârlı bir strateji istiyor. Bugünkü strateji (EMA kesişimi + RSI + ATR stop) örneklem dışında zararda: 4h'te -%5.9, kâr faktörü 0.76, 26 işlem; 1h'te hiç işlem yok. Paper kanıtı bu yüzden geçemiyor ve canlı aşama (0041 CB-6 dahil) bekliyor. Bu spec yeni strateji getirmez; önce ölçüm düzenini sabitler: geçmiş veri üç döneme bölünür, ayarlar yalnız örneklem içinde seçilir, örneklem dışı ve saklı dönem son değerlendirmede bir kez açılır, eşikler kodda sabittir. Böylece sonraki spec'in (0043) adayları ölçüme göre şekillendirilemez. Başarı: aynı düzen S0 (bugünkü strateji) üzerinde çalışır ve her aday için dürüst bir "geçti / geçmedi" ve tek bir paper adayı ya da "aday yok" sonucu verir. Kaldıraç, açığa satış (BR-2), risk limitlerinin değişmesi, LLM sinyalleri, aşama kapılarının gevşemesi ve işlem sıklığı hedefi bilerek yapılmıyor. Clarify kararları C-1…C-7 ve self-critique kararları G-1…G-7 Galip Badem, 2026-11-12 tarihinde onayladı.

Terimler:
- **Aday:** Bir strateji, bir zaman dilimi (1h ya da 4h) ve bir ayar kombinasyonu. Bu spec'te yalnız S0 vardır; S1…S3 spec 0043'tedir.
- **Örneklem içi / örneklem dışı / saklı dönem:** Geçmiş verinin ardışık üç parçası; sınırları ayardaki iki tarihtir.
- **Son değerlendirme:** Örneklem dışı ve saklı dönem sonuçlarının hesaplandığı, sahibin açıkça istediği backtest koşusu.

## Requirements
- R-1 — **Üç dönem (C-2).** Backtest geçmiş veriyi ayardaki iki tarihle örneklem içi, örneklem dışı ve saklı döneme böler. Varsayılan koşu yalnız örneklem içi sonuçları hesaplar ve gösterir. Örneklem dışı ve saklı dönem sonuçları yalnız son değerlendirmede hesaplanır; son değerlendirme raporu bunu başlığında belirtir.
- R-2 — **Ayar seçimi yalnız örneklem içinde (G-2).** Bir strateji birden fazla ayar kombinasyonuyla sınanırsa her strateji ve zaman dilimi için tek kombinasyon örneklem içi sonuçla seçilir: örneklem içinde en az 30 kapanmış işlemi olanlar arasında en yüksek kâr faktörü. Örneklem içinde 30 işlemi olan kombinasyon yoksa o strateji ve zaman dilimi "geçmedi: örneklem içi işlem yetersiz" olur. Seçim örneklem dışı ya da saklı dönem sonucuna bakmaz.
- R-3 — **Eşik kararı (C-3, G-1).** Son değerlendirme raporu her seçilmiş aday için "geçti" ya da "geçmedi: <ilk tutmayan eşik>" yazar. Geçmek için, komisyon, slippage ve spread dahil:
  - örneklem dışında: net kâr > 0, kâr faktörü ≥ 1.2, en az 30 kapanmış işlem, en büyük drawdown < %15;
  - saklı dönemde: net kâr > 0 ve en büyük drawdown < %15 (işlem asgarisi yok).
  Eşikler kodda sabittir, ayarla gevşetilemez.
- R-4 — **Seçim kuralı (G-3).** Birden fazla aday geçerse paper adayı, örneklem içi ve örneklem dışı kâr faktörlerinin küçüğü en yüksek olandır; eşitlikte örneklem dışı net kârı yüksek olan. Hiçbiri geçmezse rapor "aday yok" yazar.
- R-5 — **Deneme sayısı görünür (G-4).** Son değerlendirme raporu toplam sınanan kombinasyon sayısını (strateji × zaman dilimi × ayar) yazar.
- R-6 — **Risk sabit (C-7).** Bir son değerlendirmedeki bütün adaylar aynı risk ve maliyet koşullarıyla koşar; rapor başlığındaki koşullar (spec 0040) adaylar arasında aynıdır. Değerlendirme risk ayarlarını değiştirmez.
- R-7 — **Aşama kapısı stratejiyi bilir.** Rapor başlığı stratejinin adını ve ayarlarını taşır. Onaylı rapordaki strateji ya da ayarları çalışan ayardakinden farklıysa paper ve canlı başlatma reddedilir (depo yazılmaz, borsaya istek gitmez, çıkış 1). Aşama kapısı yalnız son değerlendirme raporunu kabul eder.
- R-8 — **Süre (G-6).** Tek bir backtest koşusu R-14 sınırında (60 dakika) kalır; birden fazla koşudan oluşan değerlendirmenin toplam süresine sınır yoktur.

## User experience
none — no user interface. Etkileşim CLI çıktısı, ayar dosyası ve backtest rapor dosyasıdır; pano ve Telegram değişmez.

## Constraints & out of scope
- Sensitive area: none — risk limitleri, emir gönderimi, kimlik ve kalıcı durum değişmez (R-6). Aşama kapısı yalnız strateji adını ve ayarlarını da karşılaştırır (R-7).
- İşlem sıklığı hedef değildir (C-4); paper kanıtının süre/işlem eşikleri gerekirse yalnız ayarda uzatılır, bu spec'te değişmez.
- Kapsam dışı: yeni strateji türleri, strateji seçimi ayarı, 2022'den itibaren veri ve çift listesi (spec 0043); son değerlendirmenin gerçek verilerle koşulması (spec 0043'ün son kriteri); kaldıraç, açığa satış (BR-2); risk limitleri ve BR-8 katı; LLM ya da dış sinyal; aşama, rapor ve paper kanıtı kapılarının gevşemesi; canlı ya da testnet koşusu.
- Split: önerilen 0042 (değerlendirme düzeni) → 0043 (aday stratejiler, veri ve son değerlendirme); kabul edildi — Galip Badem, 2026-11-12 (G-7). Gerekçe: ölçüm düzeni adaylardan önce sabitlenir.
- Clarify kararları C-1…C-7 ve self-critique kararları G-1…G-7 (Galip Badem, 2026-11-12) Intent, R-1…R-8 ve bu bölüme işlendi; G-5 (çiftler, tarihler) spec 0043'tedir.

## Acceptance criteria
- [x] AC-1 — Varsayılan backtest koşusu yalnız örneklem içi sonuçları yazar; raporda ve konsolda örneklem dışı ya da saklı dönemden tek bir rakam yoktur. Son değerlendirme üç dönemi ayrı bölümlerde yazar ve başlığında son değerlendirme olduğunu belirtir.
- [x] AC-2 — Dönem tarihleri eksik, sırasız, veri aralığı dışında ya da bir dönemi boş bırakan değerdeyse backtest `ayar geçersiz: backtest.<alan>` ile reddeder ve rapor yazmaz. Eksik anahtar proje kuralıyla `ayar eksik: backtest.<alan>` olur (plan 0042 Risk 1, Galip Badem, 2026-11-12).
- [x] AC-3 — Birden fazla ayar kombinasyonunda seçilen kombinasyon, örneklem içinde en az 30 işlemi olanlar arasında en yüksek kâr faktörlüdür; örneklem dışı ve saklı dönem sonuçları değiştirildiğinde seçim değişmez. 30 işlemi olan kombinasyon yoksa sonuç "geçmedi: örneklem içi işlem yetersiz"dir.
- [x] AC-4 — Örneklem dışı eşik sınırları: kâr faktörü tam 1.2 ve tam 30 işlem geçer; 1.19 ya da 29 işlem geçmez; drawdown tam %15 geçmez; net kâr tam 0 geçmez. Zararlı işlemi olmayan (kâr faktörü tanımsız) ve diğer eşikleri geçen aday geçer. Her "geçmedi" satırı ilk tutmayan eşiği adlandırır.
- [x] AC-5 — Saklı dönem: örneklem dışında geçen aday saklı dönemde net kâr ≤ 0 ya da drawdown ≥ %15 ise "geçmedi: saklı dönem <eşik>" olur; saklı dönemde işlem sayısı karara girmez (0 işlem ve net kâr 0 → geçmedi).
- [x] AC-6 — Birden fazla aday geçerse rapor, örneklem içi ve örneklem dışı kâr faktörlerinin küçüğü en yüksek olanı tek paper adayı olarak adlandırır; eşitlikte örneklem dışı net kârı yüksek olanı. Hiçbiri geçmezse "aday yok" yazar. Rapor toplam sınanan kombinasyon sayısını yazar.
- [x] AC-7 — Bir son değerlendirmedeki bütün adayların rapor başlığındaki risk ve maliyet koşulları aynıdır; koşullar değerlendirme sırasında değişirse koşu rapor yazmadan reddeder.
- [x] AC-8 — Onaylı rapordaki strateji ya da ayarları çalışan ayardakinden farklıysa `start` ve `start --live` `ayar uyuşmazlığı: strateji` ile reddeder (depo yazılmaz, borsaya istek gitmez, çıkış 1). Son değerlendirme olmayan rapor aşama kapısında `rapor son değerlendirme değil` ile reddedilir. Strateji adı farklıysa metin `ayar uyuşmazlığı: strateji`; bir parametre farklıysa mevcut `ayar uyuşmazlığı: <parametre>` kalır (plan 0042 Risk 7, Galip Badem, 2026-11-12).
- [x] AC-9 — S0 üzerinde, bugünkü 4h verisi ve ayarlarıyla son değerlendirme koşulur, R-14 sınırında biter ve sonucu (beklenen: "aday yok") raporlar; koşu süresi ve rapor parmak izi VERIFY'a gözlem olarak girer.

## Definition of Done
- [x] Every acceptance criterion mapped to proof (test or reproducible observation)
- [x] `scripts/check` green
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Docs / ADRs updated if behavior or architecture changed (`docs/domain.md` BR-10 satırı, `docs/commands.md` backtest)
- [x] Spec moved to `specs/done/` (it becomes immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | 1 (Approved; plan Risk 1, 3, 7 açıklama satırları) |
| Fix rounds | 1 (fix-1, yalnız docstring) |
| Review findings: real / noise / deferred | 1 / 3 / 0 (review); VERIFY Info: 0 / 1 / 1 (B-84) |
| Regressions introduced | 0 |
| Bugs escaped to production | 0 |
