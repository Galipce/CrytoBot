# Conventions

> Bootstrap: 2026-10-29. Buradaki her kural ya araçla zorlanır ya da review'da kontrol edilir.

## Language
- Chat language (interviews, sessions): Turkish (`tr`)
- Document language (docs/, specs, plans, ADRs, review and verify reports): Turkish (`tr`)
- Always English (protocol, not prose): ANEW core files, template headings and field labels,
  `Status:` values (Draft / Approved / In progress / Shipped), `Approved by / on:`, `Source:`.
- Code identifiers, branch names, commit messages: English
- Agent messages (handoff summaries, refusals, `Next:` lines): chat language; command names, file
  paths and protocol fields verbatim.

## Language & framework versions
- Python 3.12; ortam ve bağımlılıklar `uv` ile, sürümler `uv.lock` ile sabit.
- Ana kütüphaneler (sürümleri ilk iskelet spec'inde sabitlenir): `ccxt`, `anthropic`,
  `python-telegram-bot` (veya eşdeğeri), `pydantic`, `pytest`, `hypothesis`, `ruff`, `mypy`, `import-linter`.
  `pandas` yok: `analysis` yalnız standart kütüphaneyle hesaplar (spec 0014, plan Risk 1).

## Naming
- Paket düzeni: `src/crytobot/<module>/` — modül adları `docs/architecture.md` tablosundaki gibi.
- Dosya/fonksiyon/değişken `snake_case`, sınıflar `PascalCase`, sabitler `UPPER_SNAKE`.
- Testler: `tests/<module>/test_<konu>.py`; test adı davranışı söyler: `test_rejects_intent_without_stop_loss`.
- İş kuralına bağlı testler adında veya docstring'inde BR numarasını taşır (`BR-4`).

## Error handling
- Her modül kendi tipli hatalarını tanımlar (`<Module>Error` tabanından); çıplak `except:` / `except Exception: pass` yasak.
- **Fail-safe:** belirsiz durumda (emir durumu bilinmiyor, bakiye tutmuyor, veri bayat, LLM şema hatası)
  yeni işlem açılmaz, durum loglanır ve bildirim gider (BR-11). Tahmin yürütülmez.
- Emir gönderimi körlemesine retry edilmez; her emir idempotent `clientOrderId` taşır, retry önce durum sorgular.
- Hata mesajları ve loglar asla sır (API anahtarı, TOTP sırrı, token) içermez.

## Data rules
- Para, fiyat, miktar, oran (emir/risk/defter tarafı): **`decimal.Decimal`**, asla `float`.
  `float` yalnızca `analysis` içinde (indikatör hesabı) kullanılır; `strategy → risk` sınırında
  `Decimal`'e çevrilir ve borsanın adım/tick hassasiyetine yuvarlanır.
- Yüzdeler oran olarak saklanır (`Decimal("0.01")` = %1).
- Zaman damgaları **UTC, timezone-aware** (`datetime` + `tzinfo=UTC`); mumlar açılış zamanına (ms) göre anahtarlanır. "Gün" = UTC günü.
- Saat enjekte edilir (`Clock` arayüzü); iş kodu doğrudan `datetime.now()` çağırmaz.
- Defter append-only; kayıt silinmez/güncellenmez.

## Known traps
- Backtest'te look-ahead bias (kapanmamış mumun verisini veya gelecek veriyi kullanmak) — sinyal yalnızca kapanmış mumlardan hesaplanır, emir bir sonraki mumda dolar — from bootstrap
- ccxt hassasiyet ve minimum emir (`amount_to_precision`, `price_to_precision`, `minNotional`) — her onaylı emir yuvarlanır ve min. tutar kontrolünden geçer — from bootstrap
- Borsa rate limit'leri — ccxt `enableRateLimit=True`; döngüler backoff'lu — from bootstrap
- LLM uydurması (hallucination) — araştırma/haber skoru kaynak alıntısı içermeli ve şema ile doğrulanmalı; alıntısız skor yok sayılır — from bootstrap
- `subprocess.run(..., timeout=)` zaman aşımında yalnızca doğrudan çocuğu öldürür; `sh -c` sarmalayıcısı altındaki
  süreçler (Windows/MSYS'te her durumda) arkada kalır — alt süreci kendi süreç grubunda başlat, zaman aşımında ağacı
  sonlandır — from spec 0001, review round 1 L-4 (backlog B-1)
- Windows'ta `core.filemode=false`: yeni çalıştırılabilir dosya (betik, hook) git'e `100644` girer ve POSIX'te
  çalışmaz — `git update-index --chmod=+x <yol>`, modu `git ls-files -s` ile doğrula; pathspec'li commit
  (`git commit -- <yol>`) index'teki mod değişikliğini görmez, yalnız o dosya staged iken index'ten commit'le
  — from bug-001, review round 1 L-1
- Windows'ta `NUL` (`/dev/null`) bir karakter aygıtıdır ve `isatty()` `True` döner: rich kullanan araçlar
  (import-linter) çıktı atılınca terminal sanıp spinner/emoji çizer, cp1254 ile yazamaz (`UnicodeEncodeError`)
  ve adım yanlış kırmızı olur — bu tür adımlara `PYTHONUTF8=1` — from B-7 (spec 0003, review round 4 F-9)
- Tam decimal bağlamı (`MAX_PREC` + `Inexact` trap) üs aralığını genişletmez: varsayılan `Emax`'ı aşan sonlu bir
  değer `Overflow` fırlatır — riskteki her tam hesap ya `MAX_EMAX`/`MIN_EMIN` ayarlar ya da `DecimalException`'ı
  adlandırılmış rede çevirir — from spec 0004, review round 1 F-1
- Üs aralığını genişletmek tam toplama/çıkarmayı güvenli kılmaz: `1E+N - 1` ~N basamak üretir, büyük N'de
  `MemoryError` (yakalanmaz; onay yok ama adlandırılmış ret de yok) — değerin ölçeği girişte sınırlanır: riskte
  kasalar, onayın her sayısal girdisi ve kâr/maliyet katı (`_in_scale`, ±999999); yalnız çarpımda kullanılan oran
  limitleri ölçeksizdir — from spec 0004, review round 2 F-6, round 3 F-7; spec 0005
- Python 3.12 `int`→`str` dönüşümü 4300 basamakla sınırlı: ret mesajında ham `int` ya da onu içeren bir `repr`
  (`Fraction`, tuple, list) basmak ve tomllib'in uzun tam sayıyı okuması `ValueError` fırlatır — mesajda ham
  girdi her zaman `_show` ile, config'te `ValueError` → `RiskConfigError` — from spec 0005, review round 1 F-1,
  round 2 F-1
- Ölçek içindeki değerler de toplamda dev sonuç üretir: `1 + oran` (oran `1E-999999`) ~1M basamaklıdır, `miktar %
  adım` üs farkı büyükse dev bölüm ister — `execution` ve `portfolio`'da hesap 60 basamaklı (girdi 28; spec 0010), sonucu yuvarlamak yerine fırlatan
  bağlamda (`BOUNDED`) yapılır, sığmayan sonuç "ölçek hesaplanamıyor" retti; mesajdaki uzun sayı basamak
  sayısıyla yazılır — from spec 0006, plan Risk 3
- Sayı yardımcıları (`_number`, `_in_scale`, `_significant`, `_brief`, `_show`, `BOUNDED`) üç modülde kopya:
  `risk` (`_limits.py`, `_approval.py`; `BOUNDED` yok), `execution/_numbers.py`, `portfolio/_numbers.py` —
  başka modülün iç alt modülü import edilemez (R-3d); kurallardan biri değişirse üçü birlikte değişir; `risk`'in
  `_show`'u uzun sayıyı kısaltmaz, kısa mesaj gereken yerde `_brief` kullanılır — from spec 0007, plan Risk 2;
  spec 0009, plan Risk 2

- İki modülün aynı basamak sınırı aynı hesabı sınamaz: `execution` emri doldururken defterin sonraki hesabı (gelir, maliyet,
  bakiye) sığmayabilir; 8 ondalıklı olağan değerlerde 28 basamak yetmedi. `execution` çıktısı defterin kapısından geçmeli,
  bakiyeye bağlı kalan ret `app`'te BR-11 sayılır — from spec 0009, review round 4 F-1; spec 0010
- SQLite'ın `timeout`'u gerçek süre değildir: nominal uykuları toplar, Windows'ta `timeout=4` 6 saniye sürdü. Süre sözü varsa
  `timeout=0` ve monotonik saatle bekleme döngüsü — from spec 0011, build (`tests/persistence/test_errors.py`)
- `sqlite3.connect` sonrası ilk PRAGMA da kilit ya da bozuk dosya hatası verir; `closing` onu kapsamalı, yoksa bağlantı GC'ye
  kadar açık kalır ve Windows'ta dosya kilitlenir — from spec 0011, review round 1 F-2
- Hassas modül klasörüne eklenen `slow` test araç testlerinin proje kopyasına da girer: `test_check_profiles.py`'deki "1 deselected" düşer, "slow test yok" durumu kaybolur.
  `tests/tooling/conftest.py` dışlama listesine eklenir; süre ölçen test `--cov` altında ürün dışı süre de ölçer, ayrı süreçte koşar — from spec 0011, ship PR #24, review round 4 I-3
- `mode=ro` ile açılan SQLite deposu, öldürülmüş sürecin sıcak günlüğünü geri alamaz; salt okuma da `mode=rw` açar — from spec
  0011, plan Risk 3
- `Decimal("1.10") == Decimal("1.1")`: birebirlik (geçmiş, geri yükleme) değerle değil metinle karşılaştırılır — from spec 0011
- Alımı kesen kapı ile kapanış aynı değere bakmalı: kapanış stop'u güncel fiyatla, dolum kapısı slippage'lı dolumla
  karşılaştırırsa `fiyat <= stop < dolum` bandındaki alım sonraki turda kesin zararla kapanır — stop tarafı fiyatla
  denetlenir — from spec 0016, review round 2 F-1
- Hazır indikatör kütüphaneleri spec'in tanımlarını vermez: TA-Lib düz piyasada RSI 0 verir, MACD'de hızlı EMA'yı yavaşa
  hizalar, ATR'de ilk mumu atlar; pandas `ewm` varsayılanı SMA ile başlamaz. Referans olarak ChartSchool ve InvestExcel
  tabloları kullanılır (`tests/analysis/references.py`), tablodaki girdiler tam basamaklarıyla yazılır (`44.34` değil `44.3389`) —
  from spec 0014, plan Risk 1, 2
- `portfolio/_replay.py`, `record_fill` ve `close_position`'ın hesabının kopyasıdır: motoru tekrar çalıştırmak O(n²); hesap
  değişirse ikisi birlikte değişir, `tests/portfolio/test_replay.py` farkı yakalar — from spec 0011, ADR 0001
- Fiyatı tick'e yuvarlamak için `quantize` yetmez: tick `0.5` ya da `3` olabilir, 10'un kuvveti değildir; `(değer // tick) * tick` kullanılır, `//` sıfıra doğru
  keser, negatif değer yuvarlamaya sokulmaz. `float`'tan gelen değer `Decimal(repr(x))` ile çevrilir. Hesap `BOUNDED` ile sınırlanamaz: Wilder ATR düz seride `3e-323`'e
  kadar söner, gerçek bir değerdir; tam bağlam kullanılır, boyutu `k`, `r` ve tick'in ölçek kapısı sınırlar — from spec 0015, plan Risk 3
- `risk` slippage'lı girişle boyutlar (spec 0020 R-1), `execution` güncel fiyat ve slippage'la doldurur: bakiyeyle sınırlı onay slippage'la defterden döner (dolu emir + kalıcı mutabakat), fiyat girişten uzaksa dolumdaki risk config limitini ya da sabit üst sınırı aşar (ölçüm: %5.93), dolum stop'un altına ya da hedefin üstüne düşebilir (sonraki turda kesin zararla kapanış), BR-8 katı güncel fiyatta bozulabilir. `app` emirden önce beş kapıyla keser: bakiye → sabit üst sınır → stop/hedef → config limiti → BR-8; kapılar miktarı değiştirmez. Kayıp formülü `risk._size`'ın kopyasıdır (giriş yerine güncel fiyatla), biri değişirse ikisi değişir; BR-8 formülü kopyalanmaz, `risk.edge_clears` onayla aynı iç hesabı 60 basamaklı, fırlatan bağlamda yapar — from spec 0016, plan Risk 1, 2, A-1; spec 0020, plan Risk 2, 3
- Defter, `now`'ı pozisyonun açılışından eski dolumu reddeder ama `execution` emri önce doldurur: geri giden saatte dolu emir + kalıcı çelişki kalır, aynı kimlik yeniden denenemez. Emirden önce `now` karşılaştırılır — from spec 0016, plan Risk 3
- `tests/tooling` kopya projesi yalnız hassas modül testlerini taşır: `tests/app`, `tests/analysis` ya da `tests/strategy`'den import edemez, yoksa kapı testleri toplama hatasıyla kırmızı olur — from spec 0016, plan Risk 16
- `ccxt`'nin birleşik çağrıları bozuk yanıtı gizler: `fetch_ohlcv` yanıtı sıralar (`[3000, 1000, 1000]` `[1000, 1000, 3000]` olur), varsayılan sayı `float`'tır, istenenden başka sembol dönse de geçer. Mum ve fiyatta ham uçlar (`publicGetKlines`, `publicGetTicker24hr`), piyasalarda `number=str`; yanıttaki `symbol` istenenle karşılaştırılır — from spec 0017, plan Risk 3
- Okuma boyunca saat tek değer olamaz: başta alınan `now` sonra gelen fiyat damgasını "gelecek" gösterir ve 0016 tüm alımları keser; sonda alınan `now` okuma sırasında kapanan mumu kapanmış sayar. Mum süzgeci istekten önce, kayma denetimi yanıttan sonra okur; `run_turn`'ün `now`'ı `read.read_at`'tir — from spec 0017, plan Risk 4
- Binance `klines` istenen sayıya açık mumu da katar: `limit=1` hiç kapanmış mum bırakmaz, `limit+1` de 1000'de 999 döndürür. İstekte `endTime` = son kapanmış mumun kapanışı − 1 ms. `limit=1001` hata vermez, 1000 döner: üst sınırı kod korur — from spec 0017, plan Risk 5
- `ccxt`'nin `timeout`'u soket süresidir, toplam değil: yavaş akan yanıt onu aşar. Her çağrı daemon iş parçacığında, bekleme `min(çağrı süresi, kalan bütçe)`; `ThreadPoolExecutor` çıkışta takılan işi bekler, kullanılmaz — from spec 0017, plan Risk 6
- `Retry-After` çağrıya değil istemciye aittir; yeniden deneme döngüsünde uygulamak sonraki çağrıları korumaz. — from spec 0017, review round 1 F-1
- `ccxt` `OperationFailed`, `NetworkError` değildir; Binance'in `-1000/-1001/-1006` kodları `NetworkError` süzgecinden kaçar. — from spec 0017, review round 1 F-2
- Python sinyal işleyicisi ana iş parçacığı Python'a dönünce koşar: Windows'ta okumanın `join`'i sırasında gelen Ctrl+C en çok
  `call_timeout` kadar gecikir. Bekleme ≤1 s'lik parçalarla yapılır (`make_wait`); ilk istek yalnız işaret koyar, ikincisi
  `ForcedStop(BaseException)` fırlatır — `except Exception` onu yutmaz, depo yazımı atomiktir. Ctrl+Break yalnız kendi süreç grubu
  olan sürece ulaşır (`CREATE_NEW_PROCESS_GROUP`) — from spec 0022, plan Risk 6
- `app`'in import izin listesinde `typing` yok ve `.now()`/`.time()`/`.monotonic()` adlı her öznitelik çağrısı saat çağrısı
  sayılır (kendi yönteminiz de): `collections.abc.Callable` ve dataclass kullanılır, `Protocol` kullanılmaz; saat `LoopParts`
  ile gelir. Dosya, ortam ve sinyal işi `__main__`'dedir — from spec 0022, plan Risk 1, 11
- Yönlendirilmiş (pipe) konsol Windows'ta yerel kod sayfasındadır (cp1254), UTF-8 değildir: alt sürecin çıktısını test eden
  kayıt dosyasına (UTF-8) bakar; konsol `errors="replace"` ile yazar — from spec 0022, build (`tests/main/test_lock_process.py`)
- mypy yalnız koştuğu makinenin platformunu denetler: Windows'ta yeşil olan kod CI'da (ubuntu) kırmızı olabilir. Platforma
  özgü ad (`signal.SIGBREAK`, `msvcrt`, `fcntl`) koşullu ifadede değil, `if sys.platform == "win32":` bloğunda kullanılır; yerelde
  `mypy --platform linux src tests tools` ile denenir — from spec 0022, ship PR CI (`tests/main/test_entry.py`, A-3)
- Canlı borsa çağrısını saran `except Exception` `BannedError`'ı (HTTP 418) yutar ve döngü banı uzatarak çağırmayı sürdürür;
  ayrıca dolan emir borsaya ikinci çağrıdan önce kaydedilmezse istisna kaydı kaybettirir — yeni `except` bloğu banı
  `TurnRun.raise_if_banned` ile yeniden fırlatır, dolumu önce `save` eder — from spec 0034, review round 1 F-4 (A-4)
- `urlopen(timeout=)` ad çözümlemeyi kapsamaz: DNS takılınca Telegram isteği soket süresini aşar. İstek daemon iş parçacığında,
  bekleme turun kalan Telegram bütçesiyle sınırlı (`TelegramClient.attempt`); terk edilen istek sürerken yenisi gönderilmez — from spec 0039, plan Risk 1, 4, A-1
- ccxt binance emir doğrulama reddinin çoğunu `InvalidOrder` değil `BadRequest` olarak fırlatır: `-1013`
  (`Filter failure: NOTIONAL`/`MIN_NOTIONAL`), `-1100…-1106`, `-1111`, `-1114…-1121` (`-1121`: `BadSymbol`);
  yalnız `LOT_SIZE`/`PRICE_FILTER` gibi birkaçı `InvalidOrder` olur — kesin ret yanıt gövdesindeki koddan
  okunur, hata sınıfı testleri elle kurulmuş istisnayla değil ccxt'nin gerçek `handle_errors` eşlemesinden
  üretilir — from spec 0036, review round 1 F-1

## Enforced by tooling
- `ruff check` + `ruff format --check` — lint ve format.
- `mypy --strict` — tip kontrolü (tüm `src/`).
- `import-linter` — `docs/architecture.md` "Forbidden dependencies" (`pyproject.toml` `[tool.importlinter]`;
  yalnızca doğrudan importlar). "İç alt modül" kuralı özel sözleşme tipiyle: `tools/import_contracts.py`.
- `pytest --cov` + `coverage report` — `risk`, `execution`, `portfolio`, `persistence`, `app`: her biri için ayrı %90 branch coverage eşiği
  (full-only `coverage` adımı, modül başına `coverage report --include`; `pyproject.toml` `[tool.coverage.*]`).
- Türkçe metin: ruff `allowed-confusables = ["ı"]` — docstring/yorumlarda noktasız ı serbest.
