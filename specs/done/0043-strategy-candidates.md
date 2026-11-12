# Spec 0043 — Aday stratejiler

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0043-plan.md`
- Self-critique: done
- Source: spec 0042 split (G-7, Galip Badem, 2026-11-12); 0042 VERIFY V-3
- Design: —
- Supersedes: 0042 R-3/AC-4'ün "geçmedi" satır biçimi (satır tutmayan değeri ve eşiği de yazar, R-6); 0042'nin son değerlendirmede tek yapılandırma sınırı (bir değerlendirme 1h ve 4h'yi birlikte sınar, R-5). Galip Badem, 2026-11-12 (Q-7, K-2).

## Intent
Botun sahibi, canlıya geçmeden önce maliyetler düşüldükten sonra kârlı bir strateji arıyor. Bugünkü strateji (S0) son değerlendirmeden "aday yok" sonucuyla çıktı: örneklem içinde 29 işlem var, eşik 30. Bu spec, 0042'nin değerlendirme düzeninin sınayacağı önceden sabitlenmiş, sınırlı bir aday kümesini (S0…S3) ve ayar ızgaralarını getirir. Sahip ayardan hangi stratejinin koşacağını seçer; seçilen strateji backtest, paper ve live'da aynı kodla çalışır. Başarı: dört aday bir son değerlendirmede 1h ve 4h ile sınanabilir, aşama kapısı seçilen adayın strateji adını, bütün parametrelerini ve aralığını çalışan ayarla karşılaştırır. 2022'den itibaren veri, beş çift, süre ölçümü ve gerçek son değerlendirme spec 0044'tedir. Kaldıraç, açığa satış, risk limitlerinin değişmesi, LLM sinyalleri, aşama kapılarının gevşemesi ve birden fazla stratejinin aynı anda koşması bilerek kapsam dışıdır. Kararlar: 0042 C-1…C-7, G-2, G-5; 0043 clarify Q-1…Q-7 ve self-critique K-1…K-7 — Galip Badem, 2026-11-12.

Terimler (0042'ye ek):
- **Trend ortalaması:** Son L kapanmış mumun kapanışlarının basit ortalaması (K-7).
- **Kırılma penceresi:** Son kapanmış mumdan önceki N kapanmış mum. Pencerenin en yüksek değeri: pencere mumlarının en yüksek fiyatı (`high`) — plan 0043 Risk 2, Galip Badem, 2026-11-12.

## Requirements
- R-1 — **Strateji seçimi (C-5, K-3).** Sahip ayarda S0, S1, S2 ya da S3'ü seçer. Seçim yoksa S0 ve bugünkü davranış aynen sürer. Bilinmeyen strateji adı ya da seçilen stratejinin eksik veya geçersiz ayarı başlatmayı reddeder. Seçilen strateji backtest, paper ve live'da aynı mumlardan aynı öneriyi üretir. Aşama kapısı seçilen stratejinin bütün parametrelerini onaylı raporla karşılaştırır.
- R-2 — **Aday kümesi sabit (C-5, Q-4).** Bütün adaylar yalnız spot alım önerir. Her öneri k×ATR stop ve r×risk hedefi taşır (BR-3), `risk` onayından geçer (BR-4…BR-9). Adaylar yalnız giriş koşuluyla ayrılır:
  - S0 — bugünkü strateji (EMA kesişimi, RSI eşiğinin altında).
  - S1 — S0'ın giriş koşulu, ek olarak son kapanış trend ortalamasının üzerinde.
  - S2 — son kapanış, kırılma penceresinin en yüksek değerini aşıyor (eşitlik aşmaz).
  - S3 — son kapanış 200 mumluk trend ortalamasının üzerinde ve RSI aşırı satım eşiğinin altında.
- R-3 — **Ayar ızgarası (G-2, Q-3).** Ortak sabitler: RSI süresi 14, ATR süresi 14, r = 2. Her aday için stop çarpanı k ∈ {1.5, 2, 3}. Izgaralar spec'te sabittir ve ayarla değişmez:
  - S0: (fast, slow) ∈ {(9,21), (12,26), (20,50)}, RSI eşiği 70.
  - S1: fast 12, slow 26, RSI eşiği 70, trend ortalaması L ∈ {100, 150, 200}.
  - S2: kırılma penceresi N ∈ {20, 55, 100}.
  - S3: trend ortalaması 200, RSI aşırı satım eşiği ∈ {30, 35, 40}.
  Her aday 9 kombinasyondur; 1h ve 4h ile son değerlendirme 72 kombinasyon sınar.
- R-4 — **Isınma mumu (Q-5).** Ayardaki mum sayısı seçilen adayın en uzun göstergesinin gerektirdiğinden azsa ayar reddedilir. Son değerlendirmede bütün adaylar aynı mum sayısıyla koşar ve bu sayı en uzun ızgara göstergesine yeter.
- R-5 — **Tek değerlendirmede iki aralık (K-2).** Bir son değerlendirme 1h ve 4h verisini birlikte sınar ve tek rapor yazar; 0042 R-4'ün tek paper adayı bütün aday ve aralıklar arasından seçilir. Aşama kapısı paper adayının aralığını çalışan mum aralığıyla karşılaştırır. Çift listesinin beyaz listeyle karşılaştırılması bugünkü gibi sürer.
- R-6 — **Hükmün rakamı (Q-7, V-3).** Her "geçmedi" satırı tutmayan değeri ve eşiği birlikte yazar.

## User experience
none — no user interface. Etkileşim CLI çıktısı, ayar dosyası ve backtest rapor dosyasıdır; pano ve Telegram değişmez.

## Constraints & out of scope
- Sensitive area: none — risk limitleri, emir gönderimi, kimlik ve kalıcı durum değişmez. Aşama kapısı yalnız yeni parametreleri ve adayın aralığını da karşılaştırır (R-1, R-5); kapının hassas alan sınıfı B-84'te açıktır, plan kapıyı 0042'deki gibi hassas sayar.
- Eşikler, seçim kuralı ve dönemleme 0042'deki gibidir; bu spec onları değiştirmez (yalnız R-6'daki satır biçimi).
- Sonuca bakılarak aday, ızgara ya da eşik değiştirmek yasaktır; gerekirse yeni spec açılır.
- Kapsam dışı: R-2 dışında aday ya da R-3 dışında ayar; 2022'den itibaren veri, beş çift, eksik veri reddi, 1h süre ölçümü ve gerçek veriyle son değerlendirme (spec 0044); kaldıraç, açığa satış (BR-2); risk limitleri ve BR-8 katı; LLM ya da dış sinyal; birden fazla stratejinin aynı anda koşması; beyaz listenin değişmesi; aşama, rapor ve paper kanıtı kapılarının gevşemesi; canlı ya da testnet koşusu.
- Split: önerilen 0043 (aday stratejiler) → 0044 (2022 verisi ve son değerlendirme); kabul edildi — Galip Badem, 2026-11-12 (K-1). Gerekçe: adaylar sentetik mumlarla tek başına doğrulanır; veri ve süre riski ayrı işte kalır.

## Acceptance criteria
- [ ] AC-1 — Ayarda strateji seçimi yoksa backtest ve paper bugünkü S0 ile aynı işlemleri ve aynı metrikleri üretir (K-4). Bilinmeyen strateji adı `ayar geçersiz: strategy.<alan>`, seçilen stratejinin eksik anahtarı `ayar eksik: strategy.<alan>` ile reddedilir; depo yazılmaz, borsaya istek gitmez, çıkış 1.
- [ ] AC-2 — Aynı mumlar ve aynı ayarla seçilen strateji backtest ve paper turunda aynı öneriyi (giriş, stop, hedef) üretir; S0…S3'ün her biri için.
- [ ] AC-3 — S1: S0 alım üreten mumlarda son kapanış trend ortalamasının üzerindeyse alım önerir; eşit ya da altındaysa önermez.
- [ ] AC-4 — S2: son kapanış kırılma penceresinin en yükseğini aşarsa alım önerir; tam eşitse ya da altındaysa önermez; pencere son kapanmış mumu içermez.
- [ ] AC-5 — S3: son kapanış 200 mumluk ortalamanın üzerinde ve RSI eşiğin altındaysa alım önerir; RSI tam eşikteyse ya da kapanış ortalamaya eşit ya da altındaysa önermez.
- [ ] AC-6 — S0…S3'ün her önerisi alımdır, stop k×ATR, hedef r×risk ile hesaplanır ve `risk` onayından geçer; hiçbir aday stop'suz ya da satış önerisi üretmez.
- [ ] AC-7 — Son değerlendirme her aday ve aralıkta R-3 ızgarasını tam olarak sınar (eksik ya da fazla kombinasyon yok); 1h + 4h ile rapor `sınanan kombinasyon: 72` yazar ve tek paper adayını (ya da "aday yok") bütün aday ve aralıklar arasından adlandırır. Ayardaki strateji parametreleri ızgarayı değiştirmez.
- [ ] AC-8 — Mum sayısı seçilen adayın en uzun göstergesine yetmiyorsa `ayar geçersiz: market.candle_count` ile reddedilir; tam yeten değer kabul edilir.
- [ ] AC-9 — Aşama kapısı: onaylı rapordaki seçilen adayın herhangi bir parametresi (L, N, aşırı satım eşiği, k dahil) çalışan ayardan farklıysa `ayar uyuşmazlığı: <parametre>`, adayın aralığı çalışan mum aralığından farklıysa `ayar uyuşmazlığı: candle_interval`, çift listesi beyaz listeden farklıysa bugünkü `ayar uyuşmazlığı: whitelist` ile `start` ve `start --live` reddeder (depo yazılmaz, borsaya istek gitmez, çıkış 1). Hepsi aynıysa geçer.
- [ ] AC-10 — Her "geçmedi" satırı tutmayan değeri ve eşiği yazar, ör. `geçmedi: örneklem içi işlem yetersiz (29 < 30)`, `geçmedi: örneklem dışı kâr faktörü (1.1500 < 1.2)`.

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
