# Spec 0043 — Aday stratejiler, veri ve son değerlendirme

- Status: Draft
- Mode: strict
- Plan: `specs/plans/0043-plan.md`
- Self-critique: pending (after 0042 ships)
- Source: spec 0042 split (G-7, Galip Badem, 2026-11-12)
- Design: —

## Intent
Spec 0042'nin sabitlediği değerlendirme düzeniyle sınırlı bir aday strateji kümesini dürüstçe sınamak. Sahip ayarda stratejiyi seçer; seçilen strateji backtest, paper ve live'da aynı kodla koşar. Değerlendirme 2022'den bugüne birkaç likit çiftte, 1h ve 4h'te yapılır; sonuç bir paper adayı ya da "aday yok"tur ve ikisi de başarıdır. Kaldıraç, açığa satış, risk limitlerinin değişmesi ve LLM sinyalleri kapsam dışıdır. Clarify kararları C-1…C-7 ve 0042 self-critique kararları G-2, G-5 Galip Badem, 2026-11-12 tarihinde onayladı. Bu taslak 0042 ship edilince ANALYZE'da tamamlanır.

## Requirements
- R-1 — **Strateji seçimi (C-5).** Ayarda strateji seçimi; seçim yoksa bugünkü strateji (S0) ve bugünkü davranış.
- R-2 — **Aday kümesi sabit (C-5):** S0 bugünkü strateji; S1 trend filtreli S0 (fiyat uzun dönem ortalamasının üzerindeyken alım); S2 kırılma (son N mumun en yükseği kapanışla aşılınca alım, ATR stop); S3 trend içinde geri çekilme (uzun dönem trend yukarıyken kısa dönem aşırı satımda alım, ATR stop). Yalnız spot alım, her öneride stop (BR-3), `risk` onayı (BR-4…BR-9).
- R-3 — **Ayar ızgarası (G-2):** her aday için spec'te sabit, en çok 9 kombinasyonluk ızgara (self-critique'te sabitlenecek).
- R-4 — **Veri (C-6, G-5):** 2022-01-01'den bugüne BTC, ETH, BNB, SOL, XRP / USDT; 1h ve 4h. Örneklem içi 2022-01-01 → 2025-06-30, örneklem dışı 2025-07-01 → 2026-08-31, saklı dönem 2026-09-01 → veri sonu. Eksik veri çift adıyla ve aralığıyla raporlanır.
- R-5 — **Son değerlendirme:** 0042 düzeniyle bir kez koşulur; sonuç, parmak izi ve tarih kaydedilir. Geçen aday varsa paper için yeni aşama onayı sahibindir.

## User experience
none — no user interface.

## Constraints & out of scope
- Sensitive area: none — risk limitleri, emir gönderimi, kimlik ve kalıcı durum değişmez.
- Kapsam dışı: R-2 dışında aday; kaldıraç, açığa satış (BR-2); risk limitleri; LLM ya da dış sinyal; birden fazla stratejinin aynı anda koşması.
- Not (0042 VERIFY V-3, Galip Badem, 2026-11-12): "aday yok" raporu nedenin rakamını (ör. örneklem içi işlem sayısı 29) göstermiyor; ANALYZE'da değerlendirilir.

## Acceptance criteria
<!-- 0042 ship edildikten sonra ANALYZE'da yazılır (Self-critique: pending). -->

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
