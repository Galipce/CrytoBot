# Spec 0044 — 2022 verisi ve son değerlendirme

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0044-plan.md`
- Self-critique: done
- Source: spec 0043 split (K-1, Galip Badem, 2026-11-12)
- Design: —

## Intent
Botun sahibi, canlıya geçmeden önce 0043'ün sabit aday kümesinin (S0…S3) maliyetler düşüldükten sonra kârlı olup olmadığını öğrenmek istiyor. Adaylar 2022'den bugüne beş likit çiftte (BTC, ETH, BNB, SOL, XRP / USDT), 1h ve 4h'te, 0042'nin üç dönemli düzeniyle bir kez ve dürüstçe sınanır. Başarı: tek bir paper adayı ya da "aday yok" sonucunun yeniden üretilebilir kanıtla (veri parmak izi, rapor parmak izi, tarih, süre) kayda geçmesi; ikisi de başarıdır. Uzun dönemde veri boşlukları kaçınılmaz olduğundan rapor onları açıkça gösterir; bir çiftin bir dönemde hiç verisi yoksa değerlendirme rapor üretmez. Yeni aday, ızgara ya da eşik; sonuca bakarak tarih ya da çift değiştirmek; kaldıraç, açığa satış, risk limitleri, beyaz listenin kendiliğinden değişmesi ve canlı ya da testnet koşusu kapsam dışıdır. Kararlar: 0042 C-6, G-5; 0043 Q-1, Q-2, Q-6, K-5, K-6; 0044 clarify Q-1…Q-7 ve self-critique K-1…K-7 — Galip Badem, 2026-11-12. Spec onayı: Galip Badem, 2026-11-12.

Terimler (0042, 0043'e ek):
- **Veri boşluğu:** Bir çiftin, bir aralığın dosyasında dönem içinde (başlangıç dahil, bitiş hariç) beklenen açılış anında mumu olmaması. Ardışık eksik mumlar tek boşluktur. Isınma mumlarındaki (dönem başından önce) eksikler boşluk sayılmaz; tanım indirme özetindeki `boşluk=` ile aynıdır (K-2).
- **Değerlendirme ayarı:** Son değerlendirmenin koştuğu, deponun dışında tutulan ayar kopyası (Q-1). Çalışan bot ayarı değildir.

## Requirements
- R-1 — **Veri (C-6, G-5).** 2022-01-01'den bugüne BTC, ETH, BNB, SOL, XRP / USDT; 1h ve 4h. Örneklem içi 2022-01-01 → 2025-06-30, örneklem dışı 2025-07-01 → 2026-08-31, saklı dönem 2026-09-01 → indirme günü 00:00 UTC'den önceki son kapanmış mum (K-5 [0043], K-1; rapor bu anı yazar). İki aralığın dosyası aynı bitişle (indirme günü 00:00 UTC, bitiş hariç) indirilir; saklı dönem iki aralıkta aynı anda biter. Maliyetler değerlendirme ayarındadır; spread bütün çiftler için tek değerdir, `0.0005` (Q-7).
- R-2 — **Boşluklar görünür (Q-2, Q-6).** Mum boşlukları koşuyu durdurmaz ve doldurulmaz. Son değerlendirme raporu her aralıkta her çiftin her boşluğunu ilk ve son eksik mumuyla ve eksik mum sayısıyla, zaman sırasıyla yazar; boşluk yoksa bunu da yazar. Varsayılan `backtest` raporu değişmez.
- R-3 — **Verisiz dönem reddi (Q-3).** Son değerlendirmede bir çiftin bir aralıkta örneklem içi, örneklem dışı ya da saklı dönemde hiç kapanmış mumu yoksa değerlendirme hiçbir tur atmadan ve rapor yazmadan, çifti, aralığı ve dönemi adlandırarak reddeder. Dönemin bir kısmında mum olması reddedilmez; eksik kısım boşluktur.
- R-4 — **Kanıt çalışan beyaz listeyle aynı (Q-1, Q-2 [0043], K-2).** Rapordaki çift listesi ile çalışan beyaz liste arasındaki bugünkü kapı karşılaştırması korunur. Değerlendirme, değerlendirme ayarıyla koşar; çalışan ayar dosyası değişmez. Beyaz listenin beş çifte çıkması sahibin paper aşama onayıyla birlikte yaptığı ayar değişikliğidir; bu spec beyaz listeyi değiştirmez.
- R-5 — **Süre (Q-4 [0043], Q-4, 0042 R-8).** 1h verisinde beş çift ve bütün veri döneminde en ağır kombinasyonun (ısınması en uzun aday S3, en küçük k; K-4) varsayılan backtest koşusu 60 dakikada biter (duvar saati, VERIFY'ın makinesi). Toplam değerlendirme süresine sınır yoktur; süre kaydedilir.
- R-6 — **Son değerlendirme ve kayıt (Q-5, Q-6).** Son değerlendirme R-1 verisiyle koşulur. Kayda geçenler: iki veri dosyasının sha256'sı, indirme anı, saklı dönemin son mumu, sonuç (paper adayı ya da "aday yok") ve her adayın hükmü, boşluk listesi, rapor parmak izi, tarih, toplam süre. Bağımsız bir tekrar aynı veriyle aynı sonucu verir; fark çıkarsa bulgudur, kriter gevşemez (K-6). "Bir kez", sonuca bakılarak hiçbir girdinin (tarih, çift, aday, ızgara, eşik, maliyet, veri, risk limitleri, açılış bakiyesi, ücretler — değerlendirme ayarının bütün koşulları) değiştirilmemesidir. Değerlendirme ayarının koşulları çalışan ayarınkilerle aynıdır; yalnız beyaz liste, veri yolları, dönem tarihleri ve rapor yolu farklıdır (K-5); aynı girdilerle tekrar serbesttir. Geçen aday varsa paper için yeni aşama onayı sahibindedir.

## User experience
none — no user interface. Etkileşim CLI çıktısı, değerlendirme ayarı ve son değerlendirme rapor dosyasıdır; pano ve Telegram değişmez.

## Constraints & out of scope
- Sensitive area: none — risk limitleri, emir gönderimi, kimlik, kalıcı durum ve aşama kapısı değişmez (R-4 yalnız mevcut davranışı korur).
- Split: önerilmedi — tek yetenek, 7 kriter (K-7).
- K-6 [0043]: R-5 tutmazsa 60 dakikalık sınır gevşetilmez, 1h de düşürülmez; R-08 ile spec'e dönülür.
- Veri dosyaları git'e girmez; deponun dışında ya da kökte yok sayılan yeni adla durur. Kökteki `crytobot-history-2026*.jsonl`, `crytobot-backtest-2026*.txt` ve çalışan `crytobot.toml` değişmez (Q-6).
- Kapsam dışı: yeni aday, ızgara ya da eşik (0042, 0043 sabitler); çift başına spread ya da ücret; boşluk doldurma; varsayılan `backtest` raporunun değişmesi; kaldıraç, açığa satış (BR-2); risk limitleri; LLM ya da dış sinyal; beyaz listenin değişmesi ve paper'a geçiş; son değerlendirmenin yeniden koşulmasına teknik kilit; canlı ya da testnet koşusu.

## Acceptance criteria
- [ ] AC-1 — Son değerlendirme raporu her aralık (1h, 4h) ve çift için her boşluğu `<çift> <ilk eksik mum> → <son eksik mum> (<n> mum)` olarak zaman sırasıyla yazar; tek eksik mum `n = 1` ile, ardışık eksikler tek satırla görünür; boşluğu olmayan aralık `veri boşluğu: yok` yazar. Bir çiftin bir aralıktaki boşluk satırı sayısı aynı dosyanın indirme özetindeki `boşluk=` değerine eşittir (K-3). Boşluk koşuyu durdurmaz ve mum eklenmez. Varsayılan `backtest` raporu bayt bayt aynı kalır.
- [ ] AC-2 — Son değerlendirmede bir çiftin bir aralıkta bir dönemde hiç kapanmış mumu yoksa `veri eksik: <çift> <aralık> <dönem>` ile reddedilir (dönem: `örneklem içi | örneklem dışı | saklı dönem`); tur atılmaz, rapor yazılmaz, çıkış 1. Dönemde tek kapanmış mum varsa ret yoktur, eksik kısım AC-1'deki gibi boşluktur.
- [ ] AC-3 — Rapordaki çift listesi çalışan beyaz listeden farklıysa (eksik, fazla ya da farklı çift) `start` ve `start --live` `ayar uyuşmazlığı: whitelist` ile reddeder; aynı liste (sıra farkı dahil) geçer (korunan davranış).
- [ ] AC-4 — 1h, beş çift, R-1'in bütün dönemiyle en ağır kombinasyonun (S3, k=1.5; K-4) varsayılan `backtest` koşusu 60 dakikada biter (VERIFY gözlemi: komut, süre).
- [ ] AC-5 — R-1 verisiyle son değerlendirme koşulur ve R-6'nın bütün kalemleri (veri sha256'ları, indirme anı, saklı dönemin son mumu, sonuç, aday hükümleri, boşluk listesi, rapor parmak izi, tarih, toplam süre) planın `## Build evidence` bölümüne yazılır.
- [ ] AC-6 — VERIFY aynı veri dosyalarıyla (sha256 eşit) son değerlendirmeyi bağımsız tekrarlar; `paper adayı:` satırı, her `sonuç:` satırı ve boşluk listesi AC-5'teki kayıtla birebir aynıdır.
- [ ] AC-7 — Değerlendirme boyunca çalışan `crytobot.toml` ve kökteki `crytobot-history-2026*.jsonl`, `crytobot-backtest-2026*.txt` dosyaları değişmez (öncesi/sonrası sha256) ve yeni veri dosyaları git'e girmez.

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
