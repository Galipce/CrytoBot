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
- Ana kütüphaneler (sürümleri ilk iskelet spec'inde sabitlenir): `ccxt`, `pandas`, `anthropic`,
  `python-telegram-bot` (veya eşdeğeri), `pydantic`, `pytest`, `hypothesis`, `ruff`, `mypy`, `import-linter`.

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
  `float` yalnızca `analysis` içinde (pandas/indikatör) kullanılır; `strategy → risk` sınırında
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
  `MemoryError` (yakalanmaz, fail-closed değil) — değerin ölçeği girişte sınırlanır (riskte `_in_scale`, ±999999)
  — from spec 0004, review round 2 F-6

## Enforced by tooling
- `ruff check` + `ruff format --check` — lint ve format.
- `mypy --strict` — tip kontrolü (tüm `src/`).
- `import-linter` — `docs/architecture.md` "Forbidden dependencies" (`pyproject.toml` `[tool.importlinter]`;
  yalnızca doğrudan importlar). "İç alt modül" kuralı özel sözleşme tipiyle: `tools/import_contracts.py`.
- `pytest --cov` + `coverage report` — `risk`, `execution`, `portfolio`: her biri için ayrı %90 branch coverage eşiği
  (full-only `coverage` adımı, modül başına `coverage report --include`; `pyproject.toml` `[tool.coverage.*]`).
- Türkçe metin: ruff `allowed-confusables = ["ı"]` — docstring/yorumlarda noktasız ı serbest.
