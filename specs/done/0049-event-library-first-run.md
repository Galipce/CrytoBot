# Spec 0049 — Olay örnek kütüphanesinin ilk gerçek koşusunun kaydı (mini)

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0049-plan.md`
- Self-critique: done
- Source: B-91 (`specs/backlog.md`; spec 0048'in ship kapısında R-08 ile çıkarılan AC-12)
- Design: —
- Supersedes: —

## Intent
Spec 0048'in kodu sentetik veriyle kanıtlandı; arşivle gerçek koşu o gün yapılamadığı için B-91'e
taşındı. Koşu 2026-11-17'de yapıldı (girdiler ve çıktılar `E:/CrytoBot/data`, ayarlar
`E:/CrytoBot/events-run`). Sahip, koşunun kanıtının repoda denetlenebilir biçimde durmasını, B-91'in
kapanmasını ve koşunun gösterdiği iki sorunun ayrı kayıtlar olarak izlenmesini istiyor; LLM spec'i bu
kayda dayanacak. Kod, kural seti, ölçüm kuralı ve eşikler değişmez; koşu yeniden yapılmaz.

## Changed behavior
- [x] CB-1 — Planın `## Build evidence` bölümü 2026-11-17 koşusunun B-91'in istediği her kalemini taşır: kaynak kayıtların sayıları ve okunma anı (arşiv, ileriye dönük kayıt); fiyat verisinin borsa bilgisi anı, indirme ilk/son anı, toplam indirme süresi ve kayıt sayıları (USDT çifti, mumlu çift, mum, aralık, boş aralık); kural seti parmak izi; model kesim anı (2026-07-01); duyuru, örnek ve ölçülen toplamları; her olay türü × yön için ölçülen örnek sayısı ve fark (kesimden önce, kesimden sonra, toplam; "yetersiz örnek" işaretiyle); ölçülemeyenlerin nedene göre sayısı; kütüphane ve rapor parmak izleri; ölçümün süresi. Her değer `E:/CrytoBot/data/events-report.txt` ya da `events measure` çıktısının kaydı `E:/CrytoBot/data/events-measure.out` ile birebir aynıdır. İki değer türetilmiştir ve kayıtta öyle yazılır: indirme süresi raporun `toplam süre=` değeridir (kesintili indirme koşularının toplamı); ölçümün süresi komut çıktısında yoktur, raporun okunma anından (kaynak kayıtlar) üretim anına kadar geçen süredir.
- [x] CB-2 — Kayıttaki kütüphane ve rapor parmak izlerinin `E:/CrytoBot/data/events-library.jsonl` ve `E:/CrytoBot/data/events-report.txt` dosyalarının sha256'sına eşit olduğu, BUILD anında alınmış komut çıktısıyla kanıtta gösterilir. Eşit değilse kayıt yazılmaz, R-10 ile durulur.
- [x] CB-3 — Kayıt, tablonun betimleyici olduğunu (ADR 0003 ilke 3; hiçbir kapının, stratejinin ya da filtrenin girdisi değil) ve kesimden önceki sonuçların modelin eğitim verisinde sonucuyla bulunabileceğini açıkça söyler; sonuçtan hiçbir hüküm, eşik ya da öneri türetmez.
- [x] CB-4 — `specs/backlog.md`'de B-91 kaydı silinir (backlog kuralı: kapatan işin commit'inde) ve iki yeni kayıt eklenir, ikisi de Severity: Info, Source: spec 0049: **B-92** — spot listeleme ölçülemiyor (311 örnekten 0 ölçüldü; 222'si "giriş mumu yok ya da geç": duyuru işlem açılışından önce yayımlanıyor, ayrıca yeni coin'de taban oran için 720 geçmiş mum yok; çözüm ölçüm kuralında bir karar ister). **B-93** — etiket gürültüsü: kredi/staking/VIP Loan "delist" duyuruları "listeden çıkarma"ya düşüyor; kampanya, sistem ve kredi duyuruları "vadeli / marjin listeleme"ye düşüyor; "diğer"de 57 "Binance Lists X" ve "Binance Adds X/Y Trading Pairs" kaçağı var (raporun etiket denetimi bölümünden örnek başlıklarla). B-93 sıradaki iş olarak işaretlenir.

## Preserved behavior
- [x] PB-1 — `src/`, `tests/`, `tools/`, `scripts/`, `docs/` ve kök ayar örnekleri değişmez: dal diff'i yalnız `specs/` altındaki dosyaları içerir (spec, plan, backlog; ship'te spec'in `specs/done/`'a taşınması).
- [x] PB-2 — `E:/CrytoBot/data` ve `E:/CrytoBot/events-run` altındaki dosyalar BUILD boyunca değişmez: CB-2'deki sha256'lar, fiyat deposunun ve arşiv deposunun sha256'sı BUILD'in başında ve sonunda aynıdır. `C:/Github/CrytoBot/news-data` altındaki ileriye dönük depo bu ölçütün dışındadır: toplayıcı ona yazmaya devam eder; koşudaki kayıt sayısı (154) rapordan alınır.
- [x] PB-3 — `scripts/check` yeşil (yalnız belge değişikliği; doctor `--strict` spec/plan durumlarını kabul eder).

## Out of scope
- Koşuyu yeniden yapmak (`events download` / `events measure`); rapor dosyasını repoya kopyalamak (çıktılar bilerek repo dışında, 0048).
- B-92 ve B-93'ün kendisi: kural seti, ölçüm kuralı, etiket düzeltmeleri — ayrı spec'ler.
- ADR 0003'ü ya da `docs/` altını sonuçla güncellemek; LLM spec'i.
- Sonuca bakarak model_cutoff, maliyet, eşik ya da tür tanımı değiştirmek.
- Sensitive area: yok — para, emir, risk, kimlik bilgisi ya da live moda dokunmaz.

## Definition of Done
- [x] `scripts/check` green
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Criterion ↔ evidence table complete for CB-* **and** PB-*
- [x] Spec moved to `specs/done/` (immutable there)
