# Backlog — deferred findings

Findings a human triaged as **defer**: real, but fixed later by decision (`workflows/feature-development.md`,
step 7). Nothing lands here without that decision; noise is rejected in the triage record, not parked here.

- One entry per finding, newest last. Delete the entry in the commit of the work that closes it.
- An entry that grows into new behavior becomes a spec (`specs/active/`), not a fix.

<!-- Format (labels stay English):
- **B-<n>** — <finding, one line> — Source: spec <NNNN>, review round <n> (<file:line>) — Severity: <…>
  — Recommendation: <the reviewer's action> — Deferred by: <name>, <YYYY-MM-DD>, <why>
-->

- **B-1** — Araç öz-testlerinde zaman aşımı yalnızca doğrudan çocuk `sh`'yi öldürüyor; iç içe `sh -c` altındaki
  pytest/mypy süreçleri (Windows'ta her durumda) arkada kalabilir — Source: spec 0001, review round 1
  (`tests/tooling/conftest.py:44-55`) — Severity: Low — Recommendation: alt süreci kendi süreç grubunda başlat,
  zaman aşımında ağacı sonlandır (POSIX `start_new_session=True` + `os.killpg`; Windows
  `CREATE_NEW_PROCESS_GROUP` + `taskkill /T /F`) — Deferred by: Galip Badem, 2026-10-29, yalnızca >180 s zaman
  aşımı yolunda tetikleniyor, hiçbir kriteri bozmuyor; platforma özgü süreç yönetimi ayrı ve dikkatli iş.
- **B-2** — Limitler arası tutarlılık kuralı yok: ör. işlem başına risk günlük zarar limitinden büyükse tek bir
  stop günlük limiti aşar — Source: spec 0002, ANALYZE self-critique G6 (`specs/done/0002-risk-limits.md`)
  — Severity: Low — Recommendation: önce `docs/domain.md`'ye iş kuralı olarak eklenip (insan kararı) sonraki bir
  spec'te zorlanması — Deferred by: Galip Badem, 2026-10-30, `docs/domain.md`'de böyle bir kural yok; spec'e
  eklemek kural uydurmak olurdu.
- **B-3** — `RiskLimits` yapıcısı doğrulama yapmıyor: `load_limits`/`decide_change` dışından kurulan limitler üst
  sınırları aşabilir — Source: spec 0002, review round 1 (`src/crytobot/risk/_limits.py:100-106`) — Severity: Low
  — Recommendation: `RiskLimits.__post_init__` içinde tür, alt sınır ve `HARD_CAPS` kontrolü (`HARD_CAPS`'in kendisi
  için ayrı sabit ya da istisna) — Deferred by: Galip Badem, 2026-10-30, bugün hiçbir kriteri bozmuyor; limitleri
  `load_limits` dışında ilk kuracak spec (0003 / `control`) doğru yer.
- **B-4** — Spec 0002 testleri üç davranışı regresyona karşı korumuyor (kod bugün doğru): (G-7) `decide_change`'de
  boşluklu kanal/limit adı (`" cli"`, `" per_trade_risk"`) → `UNKNOWN_CHANNEL`/`UNKNOWN_LIMIT`; `strip` eklenirse
  bilinmeyen kanaldan artırma kabul edilir. (G-8) config'te açıkça yazılmış, varsayılana eşit değer `defaulted`
  sayılmaz. (G-9) oran limitine verilen bool `INVALID_VALUE` ile reddedilir, `ABOVE_CAP` ile değil — Source: spec
  0002, VERIFY round 4 (`src/crytobot/risk/_limits.py:70,137,174,177`) — Severity: Low — Recommendation: üç örnek
  test (`channel_space`, `limit_space`, `ratio_bool` satırları; varsayılan değerleri açıkça yazan config) ve kök
  neden için AC-10 property testine beklenen-sonuç modeli (oracle); G-7, kanalları `decide_change`'e bağlayan
  spec'ten önce kapanmalı — Deferred by: Galip Badem, 2026-10-30, A-5 gereği yeni fix turu yok; tek tek mutant
  kapatmak yerine sorun sınıfını oracle kapatır.
