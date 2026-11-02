# Backlog — deferred findings

Findings a human triaged as **defer**: real, but fixed later by decision (`workflows/feature-development.md`,
step 7). Nothing lands here without that decision; noise is rejected in the triage record, not parked here.

- A criterion moved out at the ship gate (R-08, `→ moved to B-<n>`) lands here too, by the
  human's ship decision; the entry names the spec and criterion.
- One entry per finding, newest last. Delete the entry in the commit of the work that closes it.
- An entry that grows into new behavior becomes a spec (`specs/active/`), not a fix.

<!-- Format (labels stay English):
- **B-<n>** — <finding, one line> — Source: spec <NNNN>, review round <n> (<file:line>) — Severity: <…>
  — Recommendation: <the reviewer's action> — Deferred by: <name>, <YYYY-MM-DD>, <why>
  A decision deferred at bootstrap (its REPORT) uses Source: bootstrap <YYYY-MM-DD>.
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
  kapatmak yerine sorun sınıfını oracle kapatır. Not (spec 0005, review round 1 F-6): `decide_change` `current`'ı
  doğrulamıyor — elle kurulmuş `NaN` limit `InvalidOperation`, `str` limit `TypeError`; aynı spec'te `current`
  için `_limit_problems` ön kontrolü. Not (spec 0005, review round 3 F-1, F-2): Telegram ret mesajı `current`'ı
  `Decimal(...)` ile yazar (`_limits.py:251,261`) — elle kurulmuş `Fraction` limit `TypeError`, `float` limit uzun
  ikili açılım yazar; artırma dalının (`:261`) dev `int` `current` testi yok (aynası: `test_telegram_cannot_lower_a_
  huge_int_multiple`); ön kontrol ikisini de kapatır.
- **B-6** — `approve_trade` hash'lenemeyen bir çift (ör. liste) alırsa `TypeError` fırlatıyor; R-1'in "sonuç ya
  miktar ya adlandırılmış ret" sözü bu uçta karşılanmıyor (fail-closed, `pair: str` tipi mypy ile korunuyor) —
  Source: spec 0003, VERIFY round 1 G-3 (`src/crytobot/risk/_approval.py:124`) — Severity: Low — Recommendation:
  `isinstance(intent.pair, str)` değilse `NOT_WHITELISTED` ve örnek test — Deferred by: Galip Badem, 2026-10-31,
  çağıran yok; `approve_trade`'i `strategy`'ye bağlayan spec'te kapanır (B-5 spec 0005'te kapandı).
- **B-9** — Uç tarihli, zaman dilimi taşıyan zaman (`datetime.min` + `+01:00`, `datetime.max` + `-01:00`)
  `observe`'ta ve `approve_trade`'de `astimezone(UTC)` içinde yakalanmayan `OverflowError` fırlatıyor (fail-closed,
  durum değişmez, onay yok) — Source: spec 0004, review round 3 F-10 (`src/crytobot/risk/_tracking.py:66`,
  `src/crytobot/risk/_approval.py:144`) — Severity: Low — Recommendation: UTC'ye çevrilemeyen zaman R-6/R-7
  kapsamında adlandırılmış ret; iki örnek test — Deferred by: Galip Badem, 2026-10-31, zaman sistem saatinden
  geliyor; zamanı dış kaynaktan alan ilk spec'te kapanır.
- **B-10** — `_state_problems`'taki `e.is_finite()` koşulunu hiçbir test sınamıyor (koşul kaldırılınca 0 test
  kırılıyor; elle kurulmuş `NaN` zirveli durum o zaman `_reached`'te yakalanmayan `InvalidOperation`, `Infinity`
  zirve `DRAWDOWN_HALT` verir); ayrıca "gün başı, zirve ya da son kasa eksik" mesajı `NaN`/`Infinity`/`int` kasa
  için de dönüyor — bunlar eksik değil geçersiz. Bugünkü kod doğru (`INVALID_INPUT`); yalnız `observe`'un
  üretemeyeceği elle kurulmuş durumlar — Source: spec 0004, review round 4 N-1, N-2
  (`src/crytobot/risk/_approval.py:137`) — Severity: Low — Recommendation: HAND_BUILT'e `nan_peak` (ve `inf_peak`)
  vakası, beklenen mesaj "eksik ya da geçersiz"; mesaj metni buna göre — Deferred by: Galip Badem, 2026-10-31, fix
  turu kalmadı (R-06 orantısız); `RiskState`'i kalıcı depoya yazan/okuyan ilk spec'te kapanır. Not (spec 0005,
  review round 2 F-2): elle kurulmuş `day=10**4300` durumu `_approval.py:168`'deki mesajda `ValueError`
  fırlatır — aynı sınıf, aynı yerde kapanır.
- **B-11** — `risk` tarafı: ölçek sınırı içindeki uç girdiler sınırlı ama yavaş — `_size` ~2,4 s ve ~1 MB'lık onay
  mesajı (giriş `1E+999999`, adım `1E-999999`); ~1M basamaklı `int` girdinin `Decimal`'e çevrilmesi ~27 s. Execution
  tarafı spec 0006 ile kapandı (emir miktarı ve fiyat ≤ 28 anlamlı basamak, 28 basamaklı sınırlı hesap, kısa mesaj)
  — Source: spec 0005, review round 1 F-4 (`src/crytobot/risk/_approval.py:302-314`) — Severity: Info —
  Recommendation: `risk`'te de execution'daki gibi sınırlı bağlam ve basamak sayısıyla yazılan mesaj — Deferred by:
  Galip Badem, 2026-11-01, yalnız gerçekçi olmayan girdiler; R-7 tutuyor (istisna yok, süre sonlu); spec 0006'da
  risk tarafına daraltıldı.
- **B-12** — `./scripts/residue` kalan süreçleri check'e ebeveyn ağacıyla bağlamıyor: boşta olmayan makinede sistem
  süreçleri (svchost, SearchProtocolHost/SearchFilterHost, WmiPrvSE, tarayıcı) her koşuda `RESIDUE FOUND`, rc=1 verir
  ve her spec'te elle değerlendirilir — Source: spec 0005, VERIFY (`scripts/residue`) — Severity: Info —
  Recommendation: survivor'ları check'in başlattığı süreç ağacına (ebeveyn PID) göre süz; ağaç dışındakileri ayrı,
  bilgi satırı olarak yaz — Deferred by: Galip Badem, 2026-11-01, spec'i bloklamıyor; araç değişikliği kendi
  bug/change akışında.
- **B-13** — `query_order`, durumu `bilinmiyor` olup `quotes` girdisi olmayan elle kurulmuş bir `ExecutionState`'te
  `KeyError` fırlatır (`src/crytobot/execution/_orders.py:436`); bugün durum yalnız `place_order`'dan geldiği için
  ulaşılamaz — Source: spec 0006, review round 1 F-6 — Severity: Info — Recommendation: kalıcılık spec'inde quote
  `Order` üzerinde taşınsın ya da emirle birlikte yazılsın; ya da `.get` + "geçersiz girdi" — Deferred by: Galip
  Badem, 2026-11-01, bu spec'te ulaşılamaz; davranışı kalıcılık spec'i tanımlar.
- **B-14** — `_judged_differently`'deki "çift/yön metin değil" guard'ını (`src/crytobot/execution/_orders.py:269-270`)
  hiçbir test korumuyor: `None` çiftli vaka guard olmadan da reddediliyor. Guard silinirse elle kurulmuş bir onayda
  `__eq__`'i istisna fırlatan çift `TypeError` (R-12), hep True dönen çift emir oluşturur (R-2) — Source: spec 0006,
  VERIFY ikinci geçiş F-1 — Severity: Low — Recommendation: AC-2'ye `__eq__`'i hep True dönen ve istisna fırlatan çift
  nesneli iki vaka, beklenen "onaysız öneri" — Deferred by: Galip Badem, 2026-11-02, fix turu kalmadı (R-06
  orantısız); bugün davranış doğru, yalnız elle kurulmuş onayda; execution'a dokunan sonraki spec'te kapanır. Not (spec 0009,
  review round 3 F-4): `__str__`/`__eq__`/`__ne__`'i ezilmiş bir `str` alt sınıfı yön, `place_order`'ın alım denetimini aşar;
  alım tarafında `type(side) is str` bu sınıfla birlikte kapanır.
- **B-15** — Sayı kuralında büyüklük sınırı yok: `_significant` sondaki sıfırları saymadığından `10**4300` (ve
  `Decimal("1E+999999")`) tek anlamlı basamaklı, ölçek içi ve geçerli; defter 4301 basamaklı bakiyeyle açılır, stop
  ya da hedefi anlamsız pozisyon kaydedilir, değerler riske aynen gider. Aynı kural `risk` ve `execution`'da da
  geçerli — Source: spec 0007, review round 1 F-1 (`src/crytobot/portfolio/_numbers.py:28-31`,
  `_ledger.py:141-150`) — Severity: Medium — Recommendation: üç modülde birlikte, para ve fiyat alanlarına üst sınır
  ya da sondaki sıfırları da sayan basamak kuralı; kendi change akışında — Deferred by: Galip Badem, 2026-11-02, kural
  üç modülde kopya (docs/conventions.md); yalnız `portfolio`'da değiştirmek kopyaları ayırır, üçünü birden
  değiştirmek bu spec'in kapsamını aşar.
- **B-16** — `get`'i `KeyError` dışında bir istisna fırlatan elle yazılmış bir `Mapping` fiyat girdisi
  `exit_decisions`'tan (`src/crytobot/portfolio/_close.py`, `prices.get`) ve spec 0007'nin `account_state`'inden
  (`_ledger.py`) istisna olarak sızar ("hiçbir girdi istisna fırlatmaz") — Source: spec 0008, review round 1 F-3 —
  Severity: Info — Recommendation: iki fonksiyonda birlikte, fiyat okumasını adlandırılmış bir "geçersiz girdi"
  retine çeviren tek bir yardımcı ya da girdiyi `dict`'e kopyalamak — Deferred by: Galip Badem, 2026-11-02, gerçek
  çağıran (`app`) düz `dict` verir; düzeltme shipped spec 0007'nin koduna da dokunur; `app` spec'inde kapanır.
- **B-17** — Reddedilmiş bir kapanış emri yeniden denenemez: kapanış `clientOrderId`'si pozisyondan deterministik
  türediği için (`cb-` → `cx-`) aynı pozisyonun sonraki kapanış isteği, durumu `reddedildi` olan emri "zaten var" ile
  döndürür ve pozisyon açık kalır — Source: spec 0009, clarify S7 — Severity: Medium — Recommendation: live spec'inde
  borsanın aynı `clientOrderId`'yi final durumdan sonra yeniden kabul davranışıyla birlikte karar verilsin (ör. deneme
  sayısı taşıyan kimlik ya da reddedilmiş emrin yerine yeni emir) — Deferred by: Galip Badem, 2026-11-02, paper'da ret
  yalnız ayarlanmış simülatörde olur; karar borsa davranışına bağlı.
- **B-18** — Ret mesajı ham metin girdisini kısaltmaz: `risk`'in `_show`'u (ve onu kullanan `_short`) ile
  `execution`'daki `_show(pair)` sınırsız `repr` yazar; milyon karakterlik bir kimlik ya da neden ~2 MB'lık mesaj
  üretir ("mesaj kısa", spec 0009 R-13). Aynı kalıp spec 0006'nın öneri kimliği ve çift mesajlarında da var —
  Source: spec 0009, review round 1 F-3 (`src/crytobot/risk/_close.py`, `src/crytobot/execution/_close.py`) —
  Severity: Low — Recommendation: üç modüldeki `_show` kuralını birlikte değiştir (uzun metni karakter sayısıyla
  kısalt); B-11 ve B-15 ile aynı change akışında — Deferred by: Galip Badem, 2026-11-02, gerçekçi değil (talep
  defterin doğrulanmış alanlarından kurulur); düzeltme kopya kuralını üç modülde birlikte değiştirir. Not (spec 0009, review
  round 3 F-2b; Severity: Medium): `_show` yalnız `ValueError` yakalar; `__repr__`'i fırlatan nesne ve aşırı derin iç içe
  değer (`RecursionError`) ret mesajı yazılırken istisna fırlatır; spec 0009 R-13 bu sınıfı güvence dışı sayar. Alım ve
  `query_order` da aynı. Not (spec 0009, review round 4 F-3): özel `tzinfo` ile `place_order` ve
  `query_order`'daki `now.utcoffset()` da korumasız (`src/crytobot/execution/_orders.py`).
- ~~**B-19**~~ — Kapandı: spec 0010 (hesap sınırı 60 basamak, `execution` çıktısı defterin kapısından geçer). Kalan: bakiyeye
  bağlı defter reddi `app` spec'inde BR-11 sayılır (spec 0010, Constraints).