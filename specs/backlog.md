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
- **B-9** — Uç tarihli, zaman dilimi taşıyan zaman (`datetime.min` + `+01:00`, `datetime.max` + `-01:00`)
  `observe`'ta ve `approve_trade`'de `astimezone(UTC)` içinde yakalanmayan `OverflowError` fırlatıyor (fail-closed,
  durum değişmez, onay yok) — Source: spec 0004, review round 3 F-10 (`src/crytobot/risk/_tracking.py:66`,
  `src/crytobot/risk/_approval.py:144`) — Severity: Low — Recommendation: UTC'ye çevrilemeyen zaman R-6/R-7
  kapsamında adlandırılmış ret; iki örnek test — Deferred by: Galip Badem, 2026-10-31, zaman sistem saatinden
  geliyor; zamanı dış kaynaktan alan ilk spec'te kapanır.
- **B-11** — `risk` tarafı: ölçek sınırı içindeki uç girdiler sınırlı ama yavaş — `_size` ~2,4 s ve ~1 MB'lık onay
  mesajı (giriş `1E+999999`, adım `1E-999999`); ~1M basamaklı `int` girdinin `Decimal`'e çevrilmesi ~27 s. Execution
  tarafı spec 0006 ile kapandı (emir miktarı ve fiyat ≤ 28 anlamlı basamak, 28 basamaklı sınırlı hesap, kısa mesaj)
  — Source: spec 0005, review round 1 F-4 (`src/crytobot/risk/_approval.py:302-314`) — Severity: Info —
  Recommendation: `risk`'te de execution'daki gibi sınırlı bağlam ve basamak sayısıyla yazılan mesaj — Deferred by:
  Galip Badem, 2026-11-01, yalnız gerçekçi olmayan girdiler; R-7 tutuyor (istisna yok, süre sonlu); spec 0006'da
  risk tarafına daraltıldı.
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
- **B-20** — Miktarsız onayda çok küçük fiyatla (`1E-999999`) sıfır komisyon ölçek dışı kalır; ret nedeni "onaysız öneri"den
  "geçersiz girdi"ye döner. Emir oluşmaz — Source: spec 0010, review round 1 F-8 (`src/crytobot/execution/_orders.py`) —
  Severity: Low, backlog-only — Recommendation: ölçek denetimini onay adımından sonraya almak — Deferred by: Galip Badem,
  2026-11-02, gerçek borsa böyle fiyat üretmez, para kaybı ve yanlış kayıt yok.
- **B-21** — `notional` ve `fee` sınır vakaları kendi hesabını tek başına kanıtlamıyor: `execution`'da yalnız o hesap sınır dışına
  alınınca testler yeşil kalıyor, çünkü sonraki hesap aynı isteği reddediyor — Source: spec 0010, VERIFY F-2
  (`src/crytobot/execution/_close.py`, `_orders.py`) — Severity: Low, backlog-only — Recommendation: `BOUND`'a gelirin sığıp
  komisyonun sığmadığı bir vaka — Deferred by: Galip Badem, 2026-11-03, kod doğru reddediyor; ayırt eden değer 61 basamaklı
  bir komisyon oranı.
- **B-22** — `save_store` tamsayı olmayan `base.revision`'da istisna fırlatıyor: `base.revision + 1` `try` dışında; `revision=None` ya da
  `"1"` → `TypeError` (R-10 "istisna fırlatmaz" sözünün dar ihlali). Depo değişmez — Source: spec 0011, review round 1 F-6
  (`src/crytobot/persistence/_store.py`) — Severity: Low, backlog-only — Recommendation: `type(base.revision) is int` denetimi ve
  `INVALID_INPUT` — Deferred by: Galip Badem, 2026-11-03, `base` yalnız `create_store`, `load_store`, `save_store` sonucundan gelir;
  bu değeri ancak kasıtlı elle kurulmuş bir `StoredState` üretir. Not (spec 0011, review round 3 L-1): `base.ledger` da aynı sınıfta;
  `replace(state, ledger=None)` → `AttributeError` (`_store.py`, `encode_summary(base.ledger)`). Aynı düzeltmeye `isinstance(base.ledger, Ledger)` denetimi ve
  `INVALID_INPUT` eklenir.
- **B-24** — `tests/persistence/test_unreadable.py`'de gerçek tahminsiz emir satırı sınanmıyor: `unknown_without_quote` ve `unknown_without_quote_fee` tek alanı boşalttığı için
  kural yerine çözücüde reddediliyor; `quote_on_a_filled_order` da tek alan yazıyor — Source: spec 0011, VERIFY Q-1 — Severity: Low — Recommendation: iki alanı birden boşaltan vaka — Deferred by: Galip Badem, 2026-11-03, gerilemeyi `execution` ve `test_errors.py` testleri yakalıyor.
- **B-25** — `test_other_process_restores_exactly`'nin dünyalarında bilinmeyen emir yok; dolum tahmini ayrı süreçte sınanmıyor (VERIFY'da gözlemle doğrulandı) — Source: spec 0011,
  VERIFY Q-2 — Severity: Low — Recommendation: parametreye `full_world` — Deferred by: Galip Badem, 2026-11-03, aynı süreçteki test tahmini sınıyor.
- **B-26** — `test_day_start_and_peak_are_not_reset_on_the_same_day` zirve son kasaya eşitken kaydediyor, zirve sıfırlamasını görmüyor — Source: spec 0011, VERIFY Q-3 — Severity: Low —
  Recommendation: senaryo 11000, 10500 olarak kaydedilsin, sonra yeniden başlatılsın — Deferred by: Galip Badem, 2026-11-03, gerilemeyi `test_history.py -k halt_starts` ve property testi yakalıyor.
- **B-27** — `test_atomic_write.py`'nin kill testleri üretim `_save` işlemini kanıtlamıyor: biri `_write`'ı kendi `BEGIN`'iyle çağırıyor, diğerinde öldürme anı şansa bağlı. Kill yarısı
  işlemsizliğe kör, bu yarı testsiz kalıyor — Source: spec 0011, VERIFY Q-4 — Severity: Low — Recommendation: öldürmeyi üretim `_save` işleminin içinde belirli bir ana bağlamak — Deferred by: Galip Badem, 2026-11-03, işlemsiz yazımı enjekte hata testleri yakalıyor.
- **B-29** — AC-12'nin süre testi duvar saatine bağlı ve bu makinede sınır çevresinde kalabiliyor: yükleme bazı koşullarda 0,95-1,12 s (aynı kod başka zaman 0,62-0,68 s; pilde çalışma olası neden, sınanmadı);
  yerelde 6 koşunun 2'si kırmızı, flaky riski (R-03) — Source: spec 0011, ship PR #24 (`tests/persistence/test_volume.py`) — Severity: Low — Recommendation: yükleme yolunu hızlandırmak ya da R-11'in sınırını
  `app` spec'inden önce yeniden değerlendirmek; sınır burada gevşetilmez — Deferred by: Galip Badem, 2026-11-03, kapı CI koşusu; regresyon yok (`d27d3d2` ile aynı). Not (review round 4 L-2): gerçek süre ölçen testte R-03 yerine getirilemez, rampa R-12; sınır değişirse R-08; karar `app` spec'inden önce, botun çalışacağı makine adlandırılarak. Not (spec 0016): karar, makine adlandırılarak giriş noktası spec'ine taşındı; 0016 giriş noktası vermiyor.
- **B-32** — `test_store_properties.py`'de CB-5'in rastgele aşamasındaki kapsamı koruyan assert yok; seed test gövdesinin özetinden geldiği için bir yerel değişken adı değişince `NH>` ve `H=` durumları sessizce kaybolabiliyor, `EQUITIES` düzenlemesi de `H>` erişimini 2 örneğe düşürüp yeşil kalıyor — Source: spec 0012, review round 3 (`tests/persistence/test_store_properties.py:37`, `:40`, `:45-67`, `:308`) — Severity: Low — Recommendation: açık örneklerin durum ve yazım kümesini saf bir zincirle assert eden küçük bir test (rastgele aşamayı korumaz); istenirse `refuse` ve `resume` için birer `@example` — Deferred by: Galip Badem, 2026-11-04, seed yalnız test gövdesi düzenlenince değişiyor; açık örnekler bu durumları her koşuda çalıştırıyor; rastgele aşama için ek koşusuz ucuz koruma yok. Rastgele aşama tek başına her seed'de yetmiyor (QA, 12 seed, açık örnekler kaldırılmış: `NH>` 3 seed'de, `H=` 5 seed'de, meşru kapanış 2 seed'de sıfır; seed 1'de son kasa değişince zirve kuralını atlayan bozma yeşil).
- **B-33** — `risk_writes` ve adlı testler bazı yasak yazım bileşimlerini kurmuyor: durdurma aynı yazımda başlarken gün başı değişimi; kapanışta yalnız metin değişimi (`10000.00` → `1E+4`); yeni gözlemle yalnız metin değişimi; aynı UTC gününde daha geç anlı gün başı değişimi ve zirve düşüşü dizilerde yok, süren durdurmada gün başı değişiminin geç anlı biçimi adlı testlerde de yok. Gerçek `save_store` hepsini `HISTORY_IMMUTABLE` ile reddediyor — Source: spec 0012, VERIFY round 3 (`tests/persistence/test_store_properties.py`, `risk_writes`) — Severity: Low — Recommendation: `risk_writes`'a üç satır; bellekte denendi, üç bozma da kırmızıya döndü — Deferred by: Galip Badem, 2026-11-04, üretim hatası yok, gün kuralı `_risk_allows`'ta tek ve koşulsuz satır, fix turu sınırı doldu (R-06).
- **B-34** — `doctor`, `specs/done/0013-full-run-doc-alignment.md`'de kanıt yerine alıntılanmış `CHECK GREEN (fast, …)` ifadesini (CB-1 metni, `:19`) "fast output cited as evidence" sayıyor; shipped spec değişmediği için her `doctor` koşusu 1 warn veriyor, çıkış kodu 0 — Source: spec 0013, ship (`scripts/doctor:506`, `:508`) — Severity: Low — Recommendation: `fast_only`'nin eşleşmesini gerçek çıktıya daraltmak (`CHECK GREEN (fast, <sayı> steps`), üç noktalı alıntı eşleşmesin; `selftest`'e iki durum için birer vaka; ANEW yükseltmesi betiği ezebileceği için farkı yükseltmede kontrol etmek — Deferred by: Galip Badem, 2026-11-04, spec'in kriter metni ship anında değiştirilmedi; uyarı CI'ı ve çıkış kodunu bozmuyor.
- **B-35** — `NonFiniteResultError.position` "ilk ulaştığı konum" diyor, ama hesap sütun sütun ilerlediği için ilk taşan konum bildirilmeyebilir: `bollinger([1,2,30,1.7e308,…], period=3, k=1.7e308)` `position=4` verir, aynı bant taşması `[1,2,30]` ile `position=2`; RSI ve MACD de aynı yapıda — Source: spec 0014, review round 1 F-6 (`src/crytobot/analysis/_candles.py:64`, `_indicators.py`) — Severity: Low — Recommendation: docstring'i "hesabın ilk fark ettiği konum" yapmak — Deferred by: Galip Badem, 2026-11-04, `backlog-only`: `~1e308` fiyat ya da `k` gerekir, hata yine fırlar, kısmi sonuç ve yanlış kayıt yok.
- **B-37** — Mum taşımayan boş diziler `NOT_A_SERIES` yerine boş sonuç veriyor: `sma(range(0), period=2)`, boş `memoryview` ve boş `array` `()` döner; `sma(b'', period=2)` reddedilir, doluyken bu tipler `NOT_A_CANDLE` alır — Source: spec 0014, review round 2 F-12 (`src/crytobot/analysis/_candles.py`, `checked_prices`) — Severity: Low — Recommendation: gerçek bir çağıran böyle bir tip geçirirse kapıyı daraltmak; bugün değişiklik yok — Deferred by: Galip Badem, 2026-11-04, `backlog-only`: mum serisi diye bu tipleri geçiren çağıran yok, sonuç boş tuple; para kaybı, yanlış kayıt ve kısmi sonuç yok.
- **B-38** — Recovery ramp'leri rule 10 notunu taşımıyor: `prompts/recovery/flaky-test.md:15` ve `build-error.md`, `perf-miss.md`, `plan-drift.md`, `red-test.md`, `regression.md`, `rollback.md`, `spec-change.md` çıkışta full koşu istiyor; öncelik yalnız `docs/testing.md`'den anlaşılıyor (rule 10, rule 2'nin önüne geçer) — Source: spec 0014, VERIFY round 1 V-1 — Severity: Low — Recommendation: CHANGE lane'de ramp'lere kısa proje notu; ANEW yükseltmesi ramp'leri ezebileceği için farkı yükseltmede kontrol etmek — Deferred by: Galip Badem, 2026-11-04, doküman boşluğu, öncelik `docs/testing.md`'den çözülüyor; bu spec'in ship'ini bekletmez.
- **B-40** — `risk` bakiyeyle sınırlı miktarı slippage'sız boyutluyor; dolum slippage'lı olduğu için defter dolu emri reddederdi, `app` kapısı (`FILL_EXCEEDS_BALANCE`) bu alımı hiç oluşturmuyor: kalıcı durdurma önlendi ama alım kaybediliyor — Source: spec 0016, plan Risk 1 (`src/crytobot/risk/_approval.py`, `_size`) — Severity: Medium — Recommendation: `_size`'ın bakiye sınırına slippage'ı ekleyen ayrı spec; `risk` 0016'da değişemezdi — Deferred by: Galip Badem, 2026-11-05, plan onayı; önce bir tur sahte veriyle çalışıyor.
- **B-41** — Dolum fiyatı öneri girişinden uzaksa gerçek işlem riski config limitini aşabilir; `app` kapısı (`RISK_CAP_AT_FILL`) yalnız sabit üst sınırı korur, %1 ile %2 arası açık — Source: spec 0016, plan Risk 2 (`src/crytobot/app/_buys.py`, `_fill_gate`) — Severity: Medium — Recommendation: gerçek veri spec'inde fiyat sapmasına göre boyutlama ya da sapma sınırı kararı — Deferred by: Galip Badem, 2026-11-05, plan onayı; tur yalnız testlerde sahte veriyle koşuyor. Not (spec 0016, review round 1 F-1, A-1): dolumun stop ya da hedefi aşması `FILL_OUTSIDE_STOP_TARGET` ile kesildi; BR-8 katı hâlâ girişe göre denetleniyor (ör. fiyat 11.9, hedef 12: beklenen kâr maliyetin katını geçmese de alım olur), dolumla yeniden denetim de aynı kararda. Not (spec 0017): giriş noktası spec'inden önce çözülmeli; gerçek veriyle ilk kez koşacak tur bu açığı taşımamalı.
- **B-42** — Drawdown ve günlük zarar durdurması bildirim üretmiyor (R-9, AC-10), sahibi sessiz bir durdurmayla karşılaşabilir. `TurnResult.halts` yalnız kalıcı drawdown'ı gösterir; günlük zarar engeli yalnız öneri varsa çiftin `risk` reddinde görünür, öneri yoksa sonuçta iz bırakmaz (`risk`'in `_reached`'i public değil, formül `app`'e kopyalanmadı) — Source: spec 0016, plan Risk 12; review round 1 F-4 — Severity: Low — Recommendation: `reporting` spec'inde bu durumlar için bildirim ve görünürlük kararı — Deferred by: Galip Badem, 2026-11-05, plan onayı; spec bildirim üretmemeyi sabitliyor, gerçek gönderim henüz yok.
- **B-44** — Durumu bilinmeyen kapanışta sebep değişince sahibine yanlış `CLOSE_REFUSED` bildirimi gidiyor: stop sebebiyle `UNKNOWN` kalan emir, hedef kararında içerik karşılaştırmasına `reason` girdiği için `ALREADY_EXISTS` değil `ID_CONFLICT` döner, `app` bunu reddedilmiş sayar ve "kimlik çakışması" mesajı üretir. Kayıt, bakiye ve pozisyon doğru kalır, alım güvenli modda durur — Source: spec 0016, review round 4 F-2 (`src/crytobot/app/_closes.py:102-104`; `src/crytobot/execution/_close.py:189-200`) — Severity: Low — Recommendation: B-17 ile birlikte, live kapanış kimliği ele alınırken: `ID_CONFLICT` durumunda var olan `cx-` emri `REJECTED` değilse sessizce dön, adlı test ekle — Deferred by: Galip Badem, 2026-11-05, triage.
- **B-45** — Alıcı hatasında giriş bildirimi bir daha gönderilmiyor: `Notices` durumu göndermeden önce hafızaya yazıyor, hata o turun `notice_errors` alanında görünüyor ama durum sürse de sonraki turda bildirim gitmiyor. Gerçek alıcıda kısa bir kesintide başlayan süreli durdurma, yeniden başlatmaya kadar bildirilmez — Source: spec 0016, review round 4 F-4 (`src/crytobot/app/_notices.py:86-88`) — Severity: Low — Recommendation: Telegram/`reporting` spec'inde B-42 ile birlikte karar: başarısız giriş yeniden denensin mi — Deferred by: Galip Badem, 2026-11-05, triage; bugün gerçek gönderim yok.
- **B-46** — Coverage kapısının araç testi bu makinede kopyanın 180 s sınırını aşıyor: `test_well_tested_module_does_not_hide_untested_one` yerelde `test-unit` adımında `TimeoutExpired` veriyor ve assert'e ulaşmıyor (ölçüm, `--cov`, dört hassas modül: `tests/app`'siz 179 s, `tests/app`'li 198 s); CI'da aynı test yeşil (run 41996811628) — Source: spec 0016, review round 1 F-5 (`tests/tooling/test_coverage_gate.py`) — Severity: Low — Recommendation: bu makinedeki kırmızı yeni hata sayılmaz, kanıt CI koşusudur; sınır ve test gevşetilmez. Araç testlerini yerelde koşma ihtiyacı doğarsa süreyi yeniden ölçüp R-12 ile karar vermek (B-29 emsali) — Deferred by: Galip Badem, 2026-11-05, kapı CI'da yeşil; yalnız yerel koşu etkileniyor, üretim koduna ve paraya etkisi yok
- **B-47** — `test_app_imports_only_allowed_modules` `APP_DIR.glob("*.py")` kullanıyor, özyinelemeli değil; import ve saat denetimi `app`'in alt klasörlerine bakmıyor. Bugün alt klasör yok — Source: spec 0019, review round 1 L-1 (`tests/app/test_boundaries.py:132`) — Severity: Low — Recommendation: `glob` yerine `rglob` geçişi kendi mini işi olarak yapılır. Aynı desen `:127`'deki `.realized` testinde (`test_decisions_do_not_read_realized_profit`) de var; o test 0019'un PB-3'ü kapsamında donduruldu, geçiş ikisini birlikte ele alır — Deferred by: Galip Badem, 2026-11-05, triage; `app`'te bugün alt klasör yok, denetim bugünkü dosyaların hepsini görüyor. VERIFY F-1 (aynı karar, ship onayı): alt klasörde `from crytobot.market_data import *` ne import denetimine ne CB-3 taramasına takılır, yani 0019/CB-2 alt klasörde tam değildir; bu iş `app`'e ilk alt klasör eklenmeden önce kapatılır.
- **B-48** — Yasak ve `Retry-After` bilgisi okumanın dışına çıkmıyor, okuma durumsuz: sonraki okuma HTTP 418 sürerken yine istek atar. Bugün döngü yok — Source: spec 0017, review round 1 F-4 (`src/crytobot/market_data/_calls.py:67`, `src/crytobot/market_data/_types.py:146-155`) — Severity: Low — Recommendation: giriş noktası spec'inde ele alınır; `MarketRead`'e "şu ana kadar istek atma" alanı — Deferred by: Galip Badem, 2026-11-05, spec 0017 döngüyü kapsam dışı tutuyor
- **B-49** — Okuma 40 karakterlik fiyat geçiriyor, defter 28 anlamlı basamaktan uzununu reddediyor: pozisyon o turda açık kalır, alım durur, çelişki oluşmaz (`test_b43_price_only_the_ledger_refuses_leaves_no_conflict` sabitliyor) — Source: spec 0017, review round 1 F-6 (`src/crytobot/market_data/_numbers.py:12-13`) — Severity: Low, `backlog-only` — Recommendation: kayıtlı kalır, fix round açmaz — Deferred by: Galip Badem, 2026-11-05, 28'i aşmak için 18 ondalığa ek 11+ tam basamak gerekir; kayıtlı Binance değerleri 8 ondalıklı, para kaybı ve yanlış kayıt yok
