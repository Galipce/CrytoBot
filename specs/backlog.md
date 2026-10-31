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
- **B-4** — Spec 0002 testleri üç davranışı regresyona karşı korumuyor (kod bugün doğru): (G-7) `decide_change`'de
  boşluklu kanal/limit adı (`" cli"`, `" per_trade_risk"`) → `UNKNOWN_CHANNEL`/`UNKNOWN_LIMIT`; `strip` eklenirse
  bilinmeyen kanaldan artırma kabul edilir. (G-8) config'te açıkça yazılmış, varsayılana eşit değer `defaulted`
  sayılmaz. (G-9) oran limitine verilen bool `INVALID_VALUE` ile reddedilir, `ABOVE_CAP` ile değil — Source: spec
  0002, VERIFY round 4 (`src/crytobot/risk/_limits.py:70,137,174,177`) — Severity: Low — Recommendation: üç örnek
  test (`channel_space`, `limit_space`, `ratio_bool` satırları; varsayılan değerleri açıkça yazan config) ve kök
  neden için AC-10 property testine beklenen-sonuç modeli (oracle); G-7, kanalları `decide_change`'e bağlayan
  spec'ten önce kapanmalı — Deferred by: Galip Badem, 2026-10-30, A-5 gereği yeni fix turu yok; tek tek mutant
  kapatmak yerine sorun sınıfını oracle kapatır.
- **B-5** — Ölçek reddi mesajı (`INVALID_INPUT`, "ölçek hesaplanamıyor") taşmanın kaynağına bakmadan her zaman adımı
  ve kasayı adlandırıyor; taşmayı giriş fiyatı tetiklediğinde (ör. `9.999E+999999`) asıl değer mesajda yok (AC-9)
  — Source: spec 0003, review round 3 F-8 (`src/crytobot/risk/_approval.py:186`) — Severity: Low — Recommendation:
  mesaja hesaba giren tüm değerleri (giriş, stop, ücret, serbest bakiye, adım, kasa) eklemek ve teste giriş kaynaklı
  bir parametre (`huge_entry`) — Deferred by: Galip Badem, 2026-10-31, karar doğru (ret, fail-closed), girdi
  gerçekçi değil; son fix turu VERIFY'a saklanıyor. Ret mesajını sahibe ilk gösterecek spec'te (`approve_trade`'i
  `strategy` ya da kanallara bağlayan) kapanır.
- **B-6** — `approve_trade` hash'lenemeyen bir çift (ör. liste) alırsa `TypeError` fırlatıyor; R-1'in "sonuç ya
  miktar ya adlandırılmış ret" sözü bu uçta karşılanmıyor (fail-closed, `pair: str` tipi mypy ile korunuyor) —
  Source: spec 0003, VERIFY round 1 G-3 (`src/crytobot/risk/_approval.py:124`) — Severity: Low — Recommendation:
  `isinstance(intent.pair, str)` değilse `NOT_WHITELISTED` ve örnek test — Deferred by: Galip Badem, 2026-10-31,
  çağıran yok; `approve_trade`'i `strategy`'ye bağlayan spec'te B-5 ile birlikte kapanır.
- **B-8** — Üssü bağlam sınırlarının çok ötesinde bir girdi (ör. giriş `3E-999999999999999990` ya da adım
  `1E-999999999999999990`) `approve_trade`'den adlandırılmış ret yerine `MemoryError` fırlatıyor; `MAX_PREC`
  bağlamında `//` trap'e ulaşmadan basamak üretmeye çalışıyor (fail-closed, onay yok) — Source: spec 0003, VERIFY
  round 2 G-6 (`src/crytobot/risk/_approval.py:181`) — Severity: Low — Recommendation: girdi doğrulamada
  `value.adjusted()` bağlamın Emin/Emax aralığı dışındaysa "geçersiz girdi"; örnek test (`huge_exponent_entry`);
  `MemoryError` yakalanmaz — Deferred by: Galip Badem, 2026-10-31, girdi gerçekçi değil, çağıran yok, fix turu
  kalmadı; B-5 ve B-6 ile `approve_trade`'i `strategy`'ye bağlayan spec'te kapanır. Spec 0004 review round 3 F-7
  ekler: aynı sınıf `_size`'ın toplama/çıkarmalarında da açık — stop ya da ücret `1E-999999999999` (taze durum,
  kasa 10000) 0.01 s'de `MemoryError`; süre üs farkıyla doğrusal (10^8'de ~0.4–0.5 s); büyük giriş de aynı yol.
  Spec 0004 kasaları `_in_scale` ile sınırladı; kalan girdiler (serbest bakiye, ücret, adım, asgari miktar/tutar →
  `INVALID_INPUT`; giriş → `INVALID_ENTRY`; stop → `INVALID_STOP`) aynı helper'la sınırlanmalı, her biri için sınır
  testi — Deferred again by: Galip Badem, 2026-10-31, spec 0004 round 3 triage.
- **B-9** — Uç tarihli, zaman dilimi taşıyan zaman (`datetime.min` + `+01:00`, `datetime.max` + `-01:00`)
  `observe`'ta ve `approve_trade`'de `astimezone(UTC)` içinde yakalanmayan `OverflowError` fırlatıyor (fail-closed,
  durum değişmez, onay yok) — Source: spec 0004, review round 3 F-10 (`src/crytobot/risk/_tracking.py:66`,
  `src/crytobot/risk/_approval.py:142`) — Severity: Low — Recommendation: UTC'ye çevrilemeyen zaman R-6/R-7
  kapsamında adlandırılmış ret; iki örnek test — Deferred by: Galip Badem, 2026-10-31, zaman sistem saatinden
  geliyor; zamanı dış kaynaktan alan ilk spec'te kapanır.
